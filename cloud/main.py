"""Ledger web/API entry point: uvicorn cloud.main:app --port 8080."""
import asyncio
import copy
import csv
import io
import json
import os
import re
import uuid
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI, Depends, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict
from app.domain import Invoice
from .repository import ROOT, repository, now, encode, procurement_master
from .reader import inspect_file
from .auth import user, User, serializer, same_origin, verify_worker
from . import auth as accounts_auth
from .accounts import SQLiteAccounts, FirestoreAccounts
from .engine import Dispatcher, Conflict, process, new_record, decision, event, audit

@asynccontextmanager
async def lifespan(app):
    # Fail closed if a cloud deployment accidentally selects ephemeral local storage.
    if os.getenv('K_SERVICE') and os.getenv('LEDGER_STORAGE') != 'cloud':
        raise RuntimeError('Cloud Run requires LEDGER_STORAGE=cloud.')
    serializer()
    app.state.repo = repository()
    store = app.state.repo
    app.state.accounts = (FirestoreAccounts(store.db, store.fs) if os.getenv('LEDGER_STORAGE') == 'cloud'
                          else SQLiteAccounts(store.directory))
    app.state.dispatcher = Dispatcher(app.state.repo)
    yield
    pending = list(app.state.dispatcher.tasks)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending,return_exceptions=True)

app = FastAPI(title='Ledger',version='2.0',lifespan=lifespan,docs_url=None,redoc_url=None)

@app.middleware('http')
async def headers(request, call_next):
    length=request.headers.get('content-length','0')
    if request.url.path.startswith('/api/') and (not length.isdigit() or int(length)>12*1024*1024):
        return JSONResponse({'detail':'This request is too large. Upload documents separately, each up to 10 MB.'},status_code=413)
    if request.method not in {'GET','HEAD','OPTIONS'}:
        try:
            same_origin(request)
            if request.url.path.startswith('/api/'):
                accounts_auth.check_csrf(request)
        except HTTPException as exc:
            return JSONResponse({'detail':exc.detail},status_code=exc.status_code)
    try:
        response = await call_next(request)
    except Exception:
        # Log stack traces via ASGI server without exposing credentials or internals.
        import logging
        logging.getLogger('ledger').exception('Request failed: %s',request.url.path)
        response = JSONResponse({'detail':'Something interrupted this request. Your saved invoices are safe; refresh and retry.'},status_code=500)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'same-origin'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; connect-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; frame-src 'self' blob:; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
    response.headers['Cache-Control'] = 'no-store' if request.url.path.startswith('/api') else 'no-cache'
    return response

@app.exception_handler(KeyError)
async def missing(request, exc):
    return JSONResponse({'detail':'This session or invoice was not found in your account.'},status_code=404)

@app.exception_handler(Conflict)
async def conflict(request, exc):
    return JSONResponse({'detail':str(exc)},status_code=409)

def repo(request:Request):
    return request.app.state.repo

def valid_id(value):
    if not re.fullmatch('[a-f0-9]{32}', value):
        raise HTTPException(404,'Not found.')
    return value

def get_session(store, who, sid):
    sid=valid_id(sid)
    meta,rows=store.snapshot(who.uid,sid)
    # Upgrade only untouched, empty procurement lists. Recheck inside the same
    # transaction so concurrent edits/approvals cannot be overwritten.
    if (not meta.get('procurement_version') and not meta['master']['vendors']
            and not meta['master']['pos'] and not any(row['accepted'] for row in rows)):
        def initialize(meta,rows):
            if (meta.get('procurement_version') or meta['master']['vendors'] or meta['master']['pos']
                    or any(row['accepted'] for row in rows.values())):
                return
            meta['master']=procurement_master()
            meta['procurement_version']=1
            for row in rows.values():
                if row.get('data') and row['execution']=='completed':
                    decision(meta,rows,row)
                    audit(row,'procurement_initialized',who.username,{'source':'Repository vendor and PO list'})
        store.atomic(who.uid,sid,initialize)
        meta,rows=store.snapshot(who.uid,sid)
    return meta,rows

def get_row(store, who, sid, iid):
    meta, rows = get_session(store,who,sid)
    row = next((x for x in rows if x['id'] == valid_id(iid)),None)
    if row is None:
        raise KeyError(iid)
    return meta, row

def editable(row, expected_run):
    if row['accepted']:
        raise Conflict('Approved invoices are read-only.')
    if row['execution'] in {'queued','running'}:
        raise Conflict('Wait for processing to finish, or retry an interrupted run.')
    if row['run'] != expected_run:
        raise Conflict('This invoice changed. Refresh it before saving.')

@app.get('/healthz')
def health():
    return {'status':'ok','version':'2.0'}

@app.get('/api/config')
def config():
    return {'accounts_enabled':True,'gemini_configured':bool(os.getenv('GEMINI_API_KEY','').strip()),
            'max_batch':250,'max_file_mb':10,'max_pages':30,'demo_limit':15,'cloud':os.getenv('LEDGER_STORAGE')=='cloud'}

@app.get('/api/csrf')
def csrf():
    import secrets
    token = serializer().dumps(secrets.token_urlsafe(32), salt='ledger-csrf-v1')
    response = JSONResponse({'token':token})
    response.set_cookie(accounts_auth.CSRF_COOKIE, token, max_age=86400, httponly=True,
                        secure=accounts_auth.secure_cookies(), samesite='lax', path='/')
    return response

class Credentials(BaseModel):
    model_config=ConfigDict(extra='forbid')
    username:str=Field(max_length=128)
    password:str=Field(max_length=1024)

@app.post('/api/register')
def register(body:Credentials, request:Request):
    return accounts_auth.register(request, body.username, body.password)

@app.post('/api/login')
def login(body:Credentials, request:Request):
    return accounts_auth.login(request, body.username, body.password)

@app.post('/api/demo')
def demo(request:Request, store=Depends(repo)):
    # A fresh demo is private to this browser; never a shared public login.
    accounts_auth.revoke_login(request)
    uid = 'demo_' + uuid.uuid4().hex
    meta = store.create(uid,'Demo review',True)
    response = JSONResponse({'session':meta['id']})
    response.set_cookie('ledger_demo',serializer().dumps(uid),max_age=86400,httponly=True,
                        secure=accounts_auth.secure_cookies(),samesite='lax')
    response.delete_cookie(accounts_auth.LOGIN_COOKIE, secure=accounts_auth.secure_cookies(), httponly=True, samesite='lax')
    return response

@app.post('/api/logout')
def logout(request:Request):
    accounts_auth.revoke_login(request)
    response = JSONResponse({'ok':True})
    for cookie in (accounts_auth.LOGIN_COOKIE, 'ledger_demo'):
        response.delete_cookie(cookie, secure=accounts_auth.secure_cookies(), httponly=True, samesite='lax')
    return response

@app.get('/api/me')
def me(who:User=Depends(user)):
    return {'demo':who.demo,'username':who.username}

class SessionInput(BaseModel):
    name:str = Field(min_length=1,max_length=80)

@app.get('/api/sessions')
def sessions(who:User=Depends(user),store=Depends(repo)):
    return sorted([{k:v for k,v in x.items() if k!='master'} for x in store.sessions(who.uid)],key=lambda x:x['created'],reverse=True)

def owner_invoice_rows(store, who, folder='all'):
    folders = store.sessions(who.uid) if folder == 'all' else [get_session(store,who,folder)[0]]
    rows = []
    for meta in folders:
        meta, invoices = get_session(store,who,meta['id'])
        for row in invoices:
            summary = {k:v for k,v in row.items() if k not in {'original','audit','events','lease_token'}}
            rows.append({**summary,'folder_id':meta['id'],'folder_name':meta['name']})
    return rows

@app.get('/api/invoices')
def all_invoices(folder:str='all', who:User=Depends(user), store=Depends(repo)):
    return {'invoices':sorted(owner_invoice_rows(store,who,folder),key=lambda row:row['created'],reverse=True)}

@app.get('/api/invoices/export.xlsx')
def excel_export(folder:str='all', outcome:str='', dated:str='all', search:str='', group_by:str='none',
                 as_of:str|None=None, who:User=Depends(user),store=Depends(repo)):
    from datetime import date
    from .excel import filtered_rows, workbook
    if group_by not in {'none','date','month','year','vendor','invoice_no','po','status','folder'}:
        raise HTTPException(400,'Unknown grouping.')
    if dated not in {'all','7','30','90','month','year'}:
        raise HTTPException(400,'Unknown date filter.')
    try:
        today = date.fromisoformat(as_of) if as_of else None
    except ValueError:
        raise HTTPException(400,'Invalid filter date.') from None
    rows = filtered_rows(owner_invoice_rows(store,who,folder),outcome,dated,search,today)
    return Response(workbook(rows,group_by),media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    headers={'Content-Disposition':'attachment; filename="ledger-invoices.xlsx"'})

@app.post('/api/sessions')
def create_session(body:SessionInput,who:User=Depends(user),store=Depends(repo)):
    if who.demo and len(store.sessions(who.uid)) >= 3:
        raise HTTPException(403,'The demo includes three sessions. Create an account for your own workspace.')
    return store.create(who.uid,body.name.strip() or 'New session',who.demo)

@app.get('/api/sessions/{sid}')
def session(sid:str,who:User=Depends(user),store=Depends(repo)):
    meta, rows = get_session(store,who,sid)
    summaries = [{k:v for k,v in row.items() if k not in {'original','audit','events','lease_token'}} for row in rows]
    return {'session':meta,'invoices':sorted(summaries,key=lambda x:x['created'],reverse=True)}

@app.post('/api/sessions/{sid}/invoices')
async def upload(sid:str,request:Request,file:UploadFile=File(...),batch:str=Form(''),local_only:bool=Form(False),who:User=Depends(user),store=Depends(repo)):
    valid_id(sid)
    # Stream one document per request, avoiding Cloud Run's 32 MB HTTP/1 request cap.
    raw = await file.read(10*1024*1024+1)
    try:
        mime, pages = await asyncio.to_thread(inspect_file,raw)
    except Exception as exc:
        raise HTTPException(400,str(exc)[:180]) from None
    filename = Path((file.filename or 'invoice.pdf').replace('\\','/')).name[:160]
    row = new_record(filename,raw,mime,pages,batch[:64])
    # Verify ownership before persisting document bytes.
    await asyncio.to_thread(get_session,store,who,sid)
    await asyncio.to_thread(store.put_file,who.uid,sid,row['id'],raw,mime)
    def insert(meta, rows):
        limit = 15 if who.demo else 400
        if len(rows) >= limit:
            raise Conflict(f'This session supports {limit} invoices. Start a new session to preserve this history.')
        rows[row['id']] = row
    await asyncio.to_thread(store.atomic,who.uid,sid,insert)
    try:
        await request.app.state.dispatcher.enqueue(who.uid,sid,row['id'],1,local_only)
    except Exception:
        def failed(meta,rows):
            rows[row['id']]['execution']='failed'
            rows[row['id']]['error']='The file was saved, but the worker could not be queued. Retry this invoice.'
            event(rows[row['id']],'Uploaded','failed',rows[row['id']]['error'])
        await asyncio.to_thread(store.atomic,who.uid,sid,failed)
    return {'id':row['id']}

@app.get('/api/sessions/{sid}/invoices/{iid}')
def invoice(sid:str,iid:str,who:User=Depends(user),store=Depends(repo)):
    return get_row(store,who,sid,iid)[1]

@app.get('/api/sessions/{sid}/invoices/{iid}/file')
def source(sid:str,iid:str,who:User=Depends(user),store=Depends(repo)):
    _,row = get_row(store,who,sid,iid)
    raw = store.get_file(who.uid,sid,iid)
    mime = 'application/pdf' if raw.startswith(b'%PDF-') else row['mime']
    # TIFF and BMP use a normalized PNG preview but keep the source downloadable.
    if mime != 'application/pdf':
        from PIL import Image, ImageOps
        with Image.open(io.BytesIO(raw)) as image:
            image = ImageOps.exif_transpose(image).convert('RGB'); image.thumbnail((2000,2800))
            out=io.BytesIO(); image.save(out,format='PNG'); raw=out.getvalue(); mime='image/png'
    return Response(raw,media_type=mime)

@app.get('/api/sessions/{sid}/invoices/{iid}/original')
def original_file(sid:str,iid:str,who:User=Depends(user),store=Depends(repo)):
    _,row=get_row(store,who,sid,iid)
    return Response(store.get_file(who.uid,sid,iid),media_type='application/octet-stream',headers={'Content-Disposition':f'attachment; filename="invoice-{iid}.bin"'})

class Revision(BaseModel):
    data:Invoice
    expected_run:int = Field(ge=1)
    confirmed_fields:list[str] = Field(default_factory=list,max_length=20)
    compared_with_source:bool = False
    po:str|None = Field(default=None,max_length=100)

@app.post('/api/sessions/{sid}/invoices/{iid}/review')
def review(sid:str,iid:str,body:Revision,who:User=Depends(user),store=Depends(repo)):
    valid_id(sid);valid_id(iid)
    data = body.data.model_dump(mode='json')
    if len(encode(data).encode()) > 450_000 or len(body.data.lines)>300:
        raise HTTPException(400,'Use at most 300 line items and keep evidence concise.')
    if body.data.tax_rate is not None and not 0 <= body.data.tax_rate <= 100:
        raise HTTPException(400,'Tax rate must be between 0 and 100 percentage points.')
    def update(meta, rows):
        row = rows[iid]; editable(row,body.expected_run)
        before = copy.deepcopy(row['data'])
        # Preserve source evidence. Client cannot forge a verification or erase uncertainty.
        data['evidence'] = copy.deepcopy((before or {}).get('evidence',{}))
        uncertain = set((before or {}).get('uncertain_fields',[]))
        for key in Invoice.model_fields:
            if key in {'evidence','uncertain_fields'}:
                continue
            if (before or {}).get(key) != data.get(key):
                uncertain.add(key)
        if body.confirmed_fields and not body.compared_with_source:
            raise Conflict('Confirm that you compared these fields with the source document.')
        for key in body.confirmed_fields:
            if key not in Invoice.model_fields or key in {'evidence','uncertain_fields'} or data.get(key) in (None,'',[]):
                raise Conflict('Only present invoice fields can be confirmed. Fill missing values first.')
            ev=data['evidence'].setdefault(key,{})
            ev['reviewer_verification']={'at':now(),'reviewer':who.username,'method':'Compared with original document','value':data[key]}
            uncertain.discard(key)
        data['uncertain_fields']=sorted(uncertain)
        row.update(data=data,selected_po=body.po or None,run=row['run']+1,execution='completed')
        audit(row,'corrected_and_checked',who.username,{'before':before,'after':data,'confirmed_fields':body.confirmed_fields,'selected_po':body.po})
        decision(meta,rows,row)
        event(row,'Decision ready',message='Reviewer changes saved and all policy checks rerun.')
        return row
    return store.atomic(who.uid,sid,update)

class RunInput(BaseModel):
    expected_run:int = Field(ge=1)

@app.post('/api/sessions/{sid}/invoices/{iid}/approve')
def approve(sid:str,iid:str,body:RunInput,who:User=Depends(user),store=Depends(repo)):
    valid_id(sid);valid_id(iid)
    def update(meta, rows):
        row=rows[iid]
        if row['accepted']:
            return {'accepted':True}
        editable(row,body.expected_run)
        if row['execution']!='completed' or not row['data']:
            raise Conflict('Complete extraction and review before approval.')
        result=decision(meta,rows,row)
        if result['status']!='Ready for approval':
            raise Conflict('Current checks prevent approval. Refresh the invoice and resolve its findings.')
        row['allocations']=[{'po_line':m['po_line'],'qty':row['data']['lines'][m['index']]['qty']} for m in result['mappings']]
        row['accepted']=True
        audit(row,'approved',who.username,{'allocations':row['allocations'],'policy':'ledger-v2'})
        event(row,'Decision ready',message='Approved by a reviewer. PO balance updated. No payment was made.')
        # Re-evaluate every completed unapproved invoice in the same atomic commit.
        # This prevents stale Ready labels after PO consumption or master changes.
        for other in rows.values():
            if not other['accepted'] and other.get('data') and other['execution']=='completed':
                decision(meta,rows,other)
        return {'accepted':True}
    return store.atomic(who.uid,sid,update)

@app.post('/api/sessions/{sid}/invoices/{iid}/retry')
async def retry(sid:str,iid:str,body:RunInput,request:Request,who:User=Depends(user),store=Depends(repo)):
    valid_id(sid);valid_id(iid)
    def update(meta,rows):
        import time
        row=rows[iid]
        if row['accepted'] or row['run']!=body.expected_run:
            raise Conflict('Refresh the invoice before retrying.')
        if row['execution']=='running' and row.get('lease_until',0)>time.time():
            raise Conflict('The worker is still processing this invoice.')
        row.update(run=row['run']+1,execution='queued',error=None,lease_until=0)
        event(row,'Uploaded',message='Queued for a fresh extraction.')
        audit(row,'retry',who.username)
        return row['run']
    run=await asyncio.to_thread(store.atomic,who.uid,sid,update)
    try:
        await request.app.state.dispatcher.enqueue(who.uid,sid,iid,run)
    except Exception:
        def failed(meta,rows):
            rows[iid].update(execution='failed',error='Worker is unavailable. Check deployment configuration and retry.')
        await asyncio.to_thread(store.atomic,who.uid,sid,failed)
        raise HTTPException(503,'Your invoice is saved, but the worker could not start. Please retry.')
    return {'id':iid,'run':run}

class Vendor(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id:str=Field(min_length=1,max_length=80)
    name:str=Field(min_length=1,max_length=150)
    gstin:str=Field(max_length=30)
    aliases:list[str]=Field(default_factory=list,max_length=30)
    status:str=Field(pattern='^(approved|blocked)$')
    vendor_reference:str|None=None

class POLine(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    id:str=Field(min_length=1,max_length=100)
    item:str=Field(min_length=1,max_length=150)
    aliases:list[str]=Field(default_factory=list,max_length=30)
    qty:Decimal=Field(gt=0,le=10**12)
    price:Decimal=Field(ge=0,le=10**12)
    tax_basis:str=Field(pattern='^(exclusive|inclusive)$')
    tax_rate:Decimal=Field(ge=0,le=100)
    unit:str=Field(min_length=1,max_length=30)

class PO(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    number:str=Field(min_length=1,max_length=100)
    vendor_id:str
    status:str=Field(pattern='^(open|closed)$')
    currency:str=Field(pattern='^[A-Z]{3}$')
    date:str|None=None
    tax_basis:str=Field(pattern='^(exclusive|inclusive)$')
    tax_rate:Decimal=Field(ge=0,le=100)
    total:Decimal=Field(gt=0,le=10**15)
    lines:list[POLine]=Field(min_length=1,max_length=100)

class Master(BaseModel):
    model_config=ConfigDict(extra='forbid')
    vendors:list[Vendor]=Field(max_length=100)
    pos:list[PO]=Field(max_length=100)

@app.put('/api/sessions/{sid}/master')
def master(sid:str,body:Master,who:User=Depends(user),store=Depends(repo)):
    valid_id(sid)
    master=body.model_dump(mode='json')
    vids=[v.id for v in body.vendors]; pids=[p.number for p in body.pos]
    lids=[l.id for p in body.pos for l in p.lines]
    if len(set(vids))!=len(vids) or len(set(pids))!=len(pids) or len(set(lids))!=len(lids):
        raise HTTPException(400,'Vendor IDs, PO numbers and PO line IDs must be unique.')
    if any(p.vendor_id not in vids for p in body.pos):
        raise HTTPException(400,'Every PO must reference a vendor in this master.')
    if len(encode(master).encode())>400_000:
        raise HTTPException(400,'Master data is too large for a session.')
    def update(meta,rows):
        # Approved records consume the approved master; prohibit destructive replacement.
        if any(r['accepted'] for r in rows.values()):
            raise Conflict('This session has approvals. Start a new session before replacing its procurement master.')
        meta['master']=master
        meta['procurement_version']=1
        for row in rows.values():
            if row.get('data') and row['execution']=='completed':
                decision(meta,rows,row)
                audit(row,'master_updated',who.username)
        return {'ok':True}
    return store.atomic(who.uid,sid,update)

@app.get('/api/master-template')
def template(who:User=Depends(user)):
    return json.loads((ROOT/'samples/master.json').read_text())

@app.get('/api/samples')
def samples(who:User=Depends(user)):
    return [{'name':p.name,'label':p.stem.replace('_',' ')} for p in sorted((ROOT/'samples').glob('*.pdf'))]

@app.get('/api/samples/{name}')
def sample(name:str,who:User=Depends(user)):
    if name!=Path(name).name or not name.endswith('.pdf'):
        raise HTTPException(404)
    path=ROOT/'samples'/name
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path,media_type='application/pdf')

def csv_safe(value):
    value=str(value if value is not None else '')
    return "'"+value if value.startswith(('=','+','-','@','\t','\r')) else value

@app.get('/api/sessions/{sid}/export')
def export(sid:str,format:str='csv',who:User=Depends(user),store=Depends(repo)):
    meta,rows=get_session(store,who,sid)
    if format=='json':
        return Response(encode({'session':meta,'invoices':rows}),media_type='application/json',headers={'Content-Disposition':'attachment; filename="ledger-audit.json"'})
    out=io.StringIO(); writer=csv.writer(out)
    writer.writerow(['File','Invoice number','Vendor','Date','Currency','Total','Status','PO','Reader','Updated'])
    for row in rows:
        d=row.get('data') or {}
        status='Approved' if row['accepted'] else (row.get('result') or {}).get('status',row['execution'])
        writer.writerow([csv_safe(v) for v in [row['filename'],d.get('invoice_no'),d.get('vendor'),d.get('date'),d.get('currency'),d.get('total'),status,row.get('po'),row.get('extraction',{}).get('source'),row['updated']]])
    return Response('\ufeff'+out.getvalue(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="ledger-invoices.csv"'})

class TaskInput(BaseModel):
    uid:str=Field(pattern=r'^[A-Za-z0-9_-]{1,128}$')
    sid:str=Field(pattern=r'^[a-f0-9]{32}$')
    iid:str=Field(pattern=r'^[a-f0-9]{32}$')
    run:int=Field(ge=1)
    local_only:bool=False

@app.post('/internal/process',dependencies=[Depends(verify_worker)])
async def worker(body:TaskInput,store=Depends(repo)):
    try:
        await process(store,body.uid,body.sid,body.iid,body.run,body.local_only)
    except Conflict:
        # Non-2xx lets Cloud Tasks redeliver if another worker's lease expires.
        raise HTTPException(503,'Processing lease is active. Retry later.')
    return {'ok':True}

app.mount('/static',StaticFiles(directory=ROOT/'web'),name='static')
@app.get('/')
def index():
    return FileResponse(ROOT/'web/index.html')

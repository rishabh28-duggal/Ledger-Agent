import asyncio, hashlib, json, os, uuid, secrets
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, Depends
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from . import store as s
from .domain import Invoice, evaluate
from .extract import extract,read_pdf

@asynccontextmanager
async def lifespan(app):
    s.init(); yield
app=FastAPI(title='AP Review',lifespan=lifespan)
# A configured bearer token protects all app data on deployments; default localhost use needs none.
@app.middleware('http')
async def auth(request:Request,call_next):
    token=os.getenv('AP_ACCESS_TOKEN')
    if token and (request.url.path.startswith('/api/') or request.url.path in ['/docs','/openapi.json']):
        supplied=request.headers.get('authorization','').removeprefix('Bearer ')
        if not secrets.compare_digest(supplied,token): return JSONResponse({'detail':'Enter the deployment access token.'},status_code=401)
    return await call_next(request)

stages=['ingest','extract','completeness','vendor','po','checks','decision']
def resolve(db,row):
    return evaluate(Invoice.model_validate(row['data']),s.records(db,'vendors'),s.records(db,'pos'),s.all_invoices(db),row['id'],row['hash'],row['selected_po'])
async def process(id,rerun=False,on_event=None):
    try:
        with s.connection() as db:
            row=s.get(db,id);run=row['run'];db.execute("UPDATE invoices SET execution='running' WHERE id=?",(id,))
        for stage in stages:
            with s.connection() as db: s.event(db,id,run,stage,'running')
            if on_event: on_event(stage,'running',{})
            payload={}
            if stage=='ingest':
                payload={'filename':row['filename'],'sha256':row['hash']}
            elif stage=='extract':
                if rerun and row['data']:
                    inv=Invoice.model_validate(row['data']);source='Reviewer-corrected extraction'
                else:
                    inv,source=await extract((s.data_dir()/(id+'.pdf')).read_bytes(),row['mode'])
                payload={'source':source,'fields':json.loads(inv.model_dump_json())}
                with s.connection() as db:
                    db.execute('UPDATE invoices SET data=?, original=COALESCE(original,?) WHERE id=?',(inv.model_dump_json(),inv.model_dump_json(),id))
            else:
                with s.connection() as db:
                    row=s.get(db,id);result=resolve(db,row)
                codes={'completeness':lambda c:c['code'].startswith(('missing','uncertain')),'vendor':lambda c:c['code'] in ['vendor','gstin','vendor_name'],'po':lambda c:c['code'].startswith('po'),'checks':lambda c:True,'decision':lambda c:True}
                payload={'checks':[c for c in result['checks'] if codes[stage](c)]}
                if stage=='decision':
                    payload=result
                    with s.connection() as db:
                        db.execute("UPDATE invoices SET result=?,po=?,vendor_id=?,execution='completed' WHERE id=?",(s.dumps(result),result['po'],result['vendor_id'],id))
            with s.connection() as db: s.event(db,id,run,stage,'done',payload)
            if on_event: on_event(stage,'done',payload)
            await asyncio.sleep(0) # Yield to stream real events; never fake timed progress.
    except Exception as exc:
        if on_event: on_event(stage,'failed',{'error':str(exc)[:350]})
        with s.connection() as db:
            db.execute("UPDATE invoices SET execution='failed' WHERE id=?",(id,))
            s.event(db,id,run,stage,'failed',{'error':str(exc)[:350],'next_action':'Read the error above. Provider outages and quota limits require retrying later; missing credentials or unsupported files require configuration/input changes.'})

@app.get('/api/config')
def config(): return {'groq_configured':bool(os.getenv('GROQ_API_KEY')),'gemini_configured':bool(os.getenv('GEMINI_API_KEY')),'demo_reset':os.getenv('AP_DEMO_RESET')=='1','stages':stages}
@app.get('/api/dashboard')
def dashboard():
    with s.connection() as db:
        invoices=s.all_invoices(db);pos=s.records(db,'pos');vendors=s.records(db,'vendors')
        for p in pos:
            accepted=[x for x in invoices if x['accepted'] and x['po']==p['number']]
            p['used']=str(sum(__import__('decimal').Decimal(x['data']['total']) for x in accepted))
            for l in p['lines']:
                l['used']=str(sum(__import__('decimal').Decimal(a['qty']) for x in accepted for a in x['allocations'] if a['po_line']==l['id']))
        return {'invoices':invoices,'pos':pos,'vendors':vendors}
@app.post('/api/invoices')
async def upload(file:UploadFile=File(...),mode:str=Form('local')):
    if mode not in ['local','gemini','groq']: raise HTTPException(400,'Unsupported extraction mode.')
    raw=await file.read(10*1024*1024+1)
    if len(raw)>10*1024*1024: raise HTTPException(413,'Maximum PDF size is 10 MB.')
    if not raw.startswith(b'%PDF-'): raise HTTPException(400,'Upload a valid PDF.')
    try: read_pdf(raw)
    except Exception as exc: raise HTTPException(400,str(exc)[:200])
    id=uuid.uuid4().hex;digest=hashlib.sha256(raw).hexdigest()
    (s.data_dir()/(id+'.pdf')).write_bytes(raw)
    with s.connection() as db:
        db.execute('INSERT INTO invoices(id,filename,hash,mode,created,execution) VALUES(?,?,?,?,?,?)',(id,Path(file.filename or 'invoice.pdf').name,digest,mode,s.now(),'queued'))
    asyncio.create_task(process(id))
    return {'id':id}
@app.get('/api/invoices/{id}')
def detail(id:str):
    with s.connection() as db:
        row=s.get(db,id)
        if not row: raise HTTPException(404,'Invoice not found.')
        row['events']=[dict(r)|{'payload':json.loads(r['payload'])} for r in db.execute('SELECT * FROM events WHERE invoice_id=? ORDER BY seq',(id,))]
        row['reviews']=[dict(r)|{'details':json.loads(r['details'])} for r in db.execute('SELECT * FROM reviews WHERE invoice_id=? ORDER BY seq',(id,))]
        return row
@app.get('/api/invoices/{id}/pdf')
def pdf(id:str):
    with s.connection() as db:
        if not s.get(db,id): raise HTTPException(404)
    return FileResponse(s.data_dir()/(id+'.pdf'),media_type='application/pdf')
@app.get('/api/invoices/{id}/events')
async def events(id:str,after:int=0):
    with s.connection() as db:
        if not s.get(db,id): raise HTTPException(404)
    async def stream():
        cursor=after
        for _ in range(240):
            with s.connection() as db:
                rows=[dict(r) for r in db.execute('SELECT * FROM events WHERE invoice_id=? AND seq>? ORDER BY seq',(id,cursor))]
                row=s.get(db,id)
            for r in rows:
                cursor=r['seq'];r['payload']=json.loads(r['payload'])
                yield f'id: {cursor}\ndata: {json.dumps(r)}\n\n'
            if row['execution'] in ['completed','failed']:
                yield 'event: end\ndata: {}\n\n';return
            yield ': heartbeat\n\n'
            await asyncio.sleep(.2)
    return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})
class Edit(BaseModel):
    data: Invoice
class Selection(BaseModel):
    po: str=Field(min_length=1,max_length=100)

def editable(db,id):
    row=s.get(db,id)
    if not row: raise HTTPException(404,'Invoice not found.')
    if row['accepted']: raise HTTPException(409,'Accepted invoices are read-only.')
    if row['execution'] in ['running','queued']: raise HTTPException(409,'Wait for the active run to finish.')
    return row
@app.post('/api/invoices/{id}/correct')
async def correct(id:str,edit:Edit):
    with s.connection() as db:
        db.execute('BEGIN IMMEDIATE');row=editable(db,id)
        s.review(db,id,'correct',{'before':row['data'],'after':json.loads(edit.data.model_dump_json()),'reviewer':'Demo reviewer'})
        db.execute("UPDATE invoices SET data=?,run=run+1,execution='queued',result=NULL WHERE id=?",(edit.data.model_dump_json(),id))
    asyncio.create_task(process(id,True));return {'id':id}
@app.post('/api/invoices/{id}/select-po')
async def select_po(id:str,selection:Selection):
    with s.connection() as db:
        db.execute('BEGIN IMMEDIATE');row=editable(db,id)
        if not row['data']: raise HTTPException(409,'Extract the invoice first.')
        s.review(db,id,'select_po',{'before':row['selected_po'],'after':selection.po})
        db.execute("UPDATE invoices SET selected_po=?,run=run+1,execution='queued',result=NULL WHERE id=?",(selection.po,id))
    asyncio.create_task(process(id,True));return {'id':id}
@app.post('/api/invoices/{id}/retry')
async def retry(id:str):
    with s.connection() as db:
        db.execute('BEGIN IMMEDIATE');row=editable(db,id)
        db.execute("UPDATE invoices SET run=run+1,execution='queued',result=NULL WHERE id=?",(id,))
        s.review(db,id,'retry',{})
    asyncio.create_task(process(id,bool(row['data'])));return {'id':id}
@app.post('/api/invoices/{id}/approve')
def approve(id:str):
    with s.connection() as db:
        db.execute('BEGIN IMMEDIATE');row=s.get(db,id)
        if not row: raise HTTPException(404)
        if row['accepted']: return {'accepted':True,'already_accepted':True}
        if row['execution']!='completed': raise HTTPException(409,'Processing must finish before approval.')
        result=resolve(db,row)
        if result['status']!='Ready for approval':
            db.execute('UPDATE invoices SET result=? WHERE id=?',(s.dumps(result),id))
            return JSONResponse({'detail':'Latest checks prevent approval. Refresh the findings.','result':result},status_code=409)
        allocations=[{'po_line':m['po_line'],'qty':row['data']['lines'][m['index']]['qty']} for m in result['mappings']]
        db.execute('UPDATE invoices SET accepted=1,result=?,allocations=?,po=?,vendor_id=? WHERE id=?',(s.dumps(result),s.dumps(allocations),result['po'],result['vendor_id'],id))
        s.review(db,id,'accept',{'reviewer':'Demo reviewer','allocations':allocations,'policy':'v1'})
    return {'accepted':True}
@app.get('/api/samples')
def samples(): return [{'name':p.name,'url':'/api/samples/'+p.name} for p in sorted((s.ROOT/'samples').glob('*.pdf'))]
@app.get('/api/samples/{filename}')
def sample(filename:str):
    if filename!=Path(filename).name or not filename.endswith('.pdf'): raise HTTPException(404)
    p=s.ROOT/'samples'/filename
    if not p.is_file(): raise HTTPException(404)
    return FileResponse(p,media_type='application/pdf')
@app.post('/api/reset')
def reset():
    if os.getenv('AP_DEMO_RESET')!='1': raise HTTPException(403,'Demo reset is disabled.')
    with s.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute("SELECT 1 FROM invoices WHERE execution IN ('queued','running')").fetchone(): raise HTTPException(409,'Wait for all runs to finish.')
        db.execute('DELETE FROM events');db.execute('DELETE FROM reviews');db.execute('DELETE FROM invoices')
        for p in s.data_dir().glob('*.pdf'): p.unlink(missing_ok=True)
    return {'reset':True}
app.mount('/',StaticFiles(directory=s.ROOT/'app/static',html=True),name='ui')

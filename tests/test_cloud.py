"""End-to-end checks. No paid provider or cloud credentials required."""
import asyncio, copy
from concurrent.futures import ThreadPoolExecutor
from datetime import date
import pytest
from fastapi.testclient import TestClient
from cloud.main import app
from cloud import main
from cloud.auth import user, User, serializer
from cloud.repository import LocalRepository, ROOT
from cloud.engine import new_record, decision, process
from cloud.reader import parse_pages, read
from app.domain import Invoice

@pytest.fixture
def client(tmp_path,monkeypatch):
    store=LocalRepository(tmp_path)
    monkeypatch.setattr(main,'repository',lambda:store)
    monkeypatch.delenv('GEMINI_API_KEY',raising=False)
    monkeypatch.delenv('LEDGER_STORAGE',raising=False)
    with TestClient(app) as c:
        c.headers['X-CSRF-Token']=c.get('/api/csrf').json()['token']
        yield c,store

def demo(c):
    c.headers['X-CSRF-Token']=c.get('/api/csrf').json()['token']
    r=c.post('/api/demo');assert r.status_code==200,r.text
    return r.json()['session']

def uid(c):return serializer().loads(c.cookies.get('ledger_demo'))

def add_ready(store,owner,sid,name='TEST-001',qty=60):
    row=new_record(name+'.pdf',name.encode(),'application/pdf',1,'test')
    data=Invoice(vendor='Acme Furniture Private Limited',gstin='36ZZZCA0001A1Z8',invoice_no=name,date=date.today().isoformat(),po_ref='PO-1042',currency='INR',subtotal=str(qty*2000),tax=str(qty*360),tax_rate=18,total=str(qty*2360),tax_basis='exclusive',lines=[dict(item='Office chair',qty=qty,unit_price=2000,line_total=qty*2000,unit='each')]).model_dump(mode='json')
    row.update(data=data,original=copy.deepcopy(data),execution='completed')
    def insert(meta,rows):rows[row['id']]=row;decision(meta,rows,row)
    store.atomic(owner,sid,insert)
    return row['id']

def test_private_demo(client):
    c,store=client;assert c.get('/api/sessions').status_code==401
    sid=demo(c);assert c.get('/api/me').json()['demo']
    assert c.get('/api/sessions/'+sid).status_code==200
    cookie=c.cookies.get('ledger_demo');c.cookies.clear();demo(c)
    assert c.get('/api/sessions/'+sid).status_code==404
    c.cookies.clear();c.cookies.set('ledger_demo',cookie)
    assert c.get('/api/sessions/'+sid).status_code==200

def test_csrf_and_invalid_ids(client):
    c,_=client
    assert c.post('/api/demo',headers={'Origin':'https://attacker.example'}).status_code==403
    demo(c);assert c.get('/api/sessions/not-an-id').status_code==404

@pytest.mark.parametrize('name,total,lines',[('R01_acme_modern_happy.pdf',141600,1),('R04_orbit_two_page_invoice.pdf',236000,2)])
def test_real_layout_reader(name,total,lines):
    invoice,trace=asyncio.run(read((ROOT/'test_pack/invoices'/name).read_bytes(),'application/pdf',True))
    assert trace['fallback'];assert invoice.total==total;assert len(invoice.lines)==lines
    assert 'lines' in invoice.uncertain_fields;assert invoice.invoice_no

def test_scan_ocr():
    invoice,trace=asyncio.run(read((ROOT/'test_pack/invoices/R07_acme_scanned_invoice.pdf').read_bytes(),'application/pdf',True))
    assert any(p['method']=='Local OCR' for p in trace['pages'])
    assert invoice.total is not None;assert invoice.invoice_no is not None
    assert invoice.uncertain_fields

def test_missing_and_conflicting_fields():
    inv,_=parse_pages([(1,'Supplier: Acme Furniture\nCurrency: INR\nTax: 18\n','PDF text')])
    assert inv.total is None and inv.invoice_no is None and inv.date is None
    inv,_=parse_pages([(1,'Total: 100\nTotal: 200','PDF text')])
    assert inv.total is None and inv.evidence['total']['conflict']

def test_batch_continues_after_bad_file(client):
    c,_=client;sid=demo(c)
    assert c.post(f'/api/sessions/{sid}/invoices',files={'file':('bad.pdf',b'bad','application/pdf')}).status_code==400
    raw=(ROOT/'samples/01_happy_60_chairs.pdf').read_bytes()
    result=c.post(f'/api/sessions/{sid}/invoices',files={'file':('good.pdf',raw,'application/pdf')},data={'local_only':'true','batch':'b1'})
    assert result.status_code==200,result.text
    iid=result.json()['id']
    import time
    for _ in range(200):
        row=c.get(f'/api/sessions/{sid}/invoices/{iid}').json()
        if row['execution'] in {'completed','failed'}:break
        time.sleep(.02)
    assert row['execution']=='completed';assert row['result']['status']=='Needs review'

def test_confirm_does_not_bypass_policy(client):
    c,store=client;sid=demo(c);iid=add_ready(store,uid(c),sid)
    path=f'/api/sessions/{sid}/invoices/{iid}'
    row=c.get(path).json();data=row['data'];data['total']='1'
    r=c.post(path+'/review',json={'data':data,'expected_run':1,'confirmed_fields':['total'],'compared_with_source':True})
    assert r.status_code==200,r.text;assert r.json()['result']['status']=='Needs review'
    assert c.post(path+'/approve',json={'expected_run':2}).status_code==409

def test_atomic_approval_balance(client):
    c,store=client;sid=demo(c);owner=uid(c)
    ids=[add_ready(store,owner,sid,'INV-001',60),add_ready(store,owner,sid,'INV-002',50)]
    def approve(iid):return c.post(f'/api/sessions/{sid}/invoices/{iid}/approve',json={'expected_run':1}).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:codes=list(pool.map(approve,ids))
    assert sorted(codes)==[200,409]
    _,rows=store.snapshot(owner,sid);assert sum(r['accepted'] for r in rows)==1

def test_duplicate_scope(client):
    c,store=client;sid=demo(c);owner=uid(c)
    add_ready(store,owner,sid,'INV-001');second=add_ready(store,owner,sid,'INV-001')
    assert c.get(f'/api/sessions/{sid}/invoices/{second}').json()['result']['status']=='Blocked'
    other=c.post('/api/sessions',json={'name':'Independent run'}).json()['id'];third=add_ready(store,owner,other,'INV-001')
    assert c.get(f'/api/sessions/{other}/invoices/{third}').json()['result']['status']=='Ready for approval'

def test_revision_evidence_and_immutable_approval(client):
    c,store=client;sid=demo(c);iid=add_ready(store,uid(c),sid);path=f'/api/sessions/{sid}/invoices/{iid}'
    data=c.get(path).json()['data'];data['evidence']={'total':{'reviewer_verification':{'reviewer':'fake'}}}
    r=c.post(path+'/review',json={'data':data,'expected_run':1});assert r.status_code==200
    assert not r.json()['data']['evidence']
    assert c.post(path+'/review',json={'data':data,'expected_run':1}).status_code==409
    assert c.post(path+'/approve',json={'expected_run':2}).status_code==200
    row=c.get(path).json();assert row['audit'][-1]['action']=='approved'
    assert c.post(path+'/review',json={'data':row['data'],'expected_run':2}).status_code==409
    assert c.post(path+'/retry',json={'expected_run':2}).status_code==409
    assert c.put('/api/sessions/'+sid+'/master',json=c.get('/api/master-template').json()).status_code==409

def test_exports_and_source_are_private(client):
    c,store=client;sid=demo(c);iid=add_ready(store,uid(c),sid);demo(c)
    for suffix in [f'/invoices/{iid}',f'/invoices/{iid}/file','/export?format=json']:
        assert c.get(f'/api/sessions/{sid}'+suffix).status_code==404

def test_csv_formula_escaped(client):
    c,store=client;sid=demo(c);iid=add_ready(store,uid(c),sid)
    store.atomic(uid(c),sid,lambda m,rows:rows[iid].update(filename='=HYPERLINK("bad")'))
    assert "'=HYPERLINK" in c.get(f'/api/sessions/{sid}/export').text

def test_worker_denied(client):
    c,_=client
    assert c.post('/internal/process',json={'uid':'x','sid':'a'*32,'iid':'b'*32,'run':1}).status_code==404

def test_real_account_has_repository_procurement(client):
    c,store=client;app.dependency_overrides[user]=lambda:User('account_123',False,'analyst123')
    try:
        sid=c.post('/api/sessions',json={'name':'Real invoices'}).json()['id']
        assert c.get('/api/sessions/'+sid).json()['session']['master']==c.get('/api/master-template').json()
    finally:app.dependency_overrides.clear()

def test_120_document_batch(tmp_path):
    store=LocalRepository(tmp_path);owner='load_test';sid=store.create(owner,'120 invoice test',True)['id']
    raw=(ROOT/'samples/01_happy_60_chairs.pdf').read_bytes()
    rows=[new_record(f'invoice-{i}.pdf',raw,'application/pdf',1,'batch-120') for i in range(120)]
    for row in rows:store.put_file(owner,sid,row['id'],raw,'application/pdf')
    store.atomic(owner,sid,lambda meta,current:current.update({r['id']:r for r in rows}))
    async def run_all():
        semaphore=asyncio.Semaphore(3)
        async def one(row):
            async with semaphore:await process(store,owner,sid,row['id'],1,True)
        await asyncio.gather(*(one(row) for row in rows))
    asyncio.run(run_all());_,saved=store.snapshot(owner,sid)
    assert len(saved)==120 and all(r['execution']=='completed' for r in saved)
    assert all(r['data']['total']=='141600.00' for r in saved)
    assert sum(r['result']['status']=='Blocked' for r in saved)==119

@pytest.mark.parametrize('scenario',['invalid-key','rate-limit','timeout','invalid-json','success'])
def test_gemini_response_and_fallback(monkeypatch,scenario):
    import httpx,json
    from cloud import reader
    monkeypatch.setenv('GEMINI_API_KEY','test-key-never-sent')
    monkeypatch.setattr(reader,'_circuit_until',0)
    requests=[];original_client=httpx.AsyncClient
    def handler(request):
        requests.append(request)
        if scenario=='timeout':raise httpx.ReadTimeout('simulated',request=request)
        if scenario in {'invalid-key','rate-limit'}:
            return httpx.Response(403 if scenario=='invalid-key' else 429,json={'error':'simulated'})
        data=Invoice(vendor='Acme Furniture',invoice_no='API-001',currency='INR',total=100).model_dump(mode='json')
        for key in ['vendor','invoice_no','currency','total']:data['evidence'][key]={'page':1,'snippet':'printed value','confidence':'high'}
        text='bad json' if scenario=='invalid-json' else json.dumps(data)
        return httpx.Response(200,json={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':text}]}}]})
    def client_factory(*args,**kwargs):
        kwargs['transport']=httpx.MockTransport(handler);return original_client(*args,**kwargs)
    monkeypatch.setattr(httpx,'AsyncClient',client_factory)
    raw=(ROOT/'samples/01_happy_60_chairs.pdf').read_bytes()
    inv,trace=asyncio.run(reader.read(raw,'application/pdf'))
    if scenario=='success':
        assert trace['source']=='Gemini' and not trace['fallback'];assert inv.invoice_no=='API-001'
    else:
        assert trace['fallback'] and inv.total==141600
        assert inv.uncertain_fields
    assert len(requests)==(2 if scenario in {'rate-limit','timeout'} else 1)


def test_completed_task_redelivery_is_idempotent(tmp_path,monkeypatch):
    from cloud import engine
    store=LocalRepository(tmp_path);owner='worker_test';sid=store.create(owner,'Idempotent worker',True)['id']
    iid=add_ready(store,owner,sid)
    async def must_not_read(*args,**kwargs):raise AssertionError('Completed invoice was extracted twice')
    monkeypatch.setattr(engine,'read',must_not_read)
    asyncio.run(engine.process(store,owner,sid,iid,1))
    assert store.snapshot(owner,sid)[1][0]['execution']=='completed'


def test_local_restart_retains_invoice_and_exposes_retry(tmp_path):
    store=LocalRepository(tmp_path);owner='restart';sid=store.create(owner,'Before restart',True)['id']
    row=new_record('saved.pdf',b'file','application/pdf',1,'restart')
    store.put_file(owner,sid,row['id'],b'file','application/pdf')
    store.atomic(owner,sid,lambda meta,rows:rows.update({row['id']:row}))
    restarted=LocalRepository(tmp_path);saved=restarted.snapshot(owner,sid)[1][0]
    assert saved['execution']=='failed' and 'restarted' in saved['error']
    assert restarted.get_file(owner,sid,row['id'])==b'file'

import time, json, tempfile
from pathlib import Path
from fastapi.testclient import TestClient
from app import store as s
from app.main import app
from app.domain import Invoice,evaluate
import pytest

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(s,'DATA',tmp_path)
    monkeypatch.setattr(s,'DB',tmp_path/'test.sqlite3')
    monkeypatch.setenv('AP_DEMO_RESET','1')
    monkeypatch.delenv('AP_ACCESS_TOKEN',raising=False)
    with TestClient(app) as c: yield c

def wait(c,id):
    for _ in range(100):
        row=c.get('/api/invoices/'+id).json()
        if row['execution'] in ['completed','failed']:return row
        time.sleep(.01)
    raise AssertionError('Run did not complete')
def upload(c,name):
    with open(s.ROOT/'samples'/name,'rb') as f:r=c.post('/api/invoices',files={'file':(name,f,'application/pdf')},data={'mode':'local'})
    assert r.status_code==200,r.text
    return wait(c,r.json()['id'])
def test_happy_accept_split_and_idempotency(client):
    row=upload(client,'01_happy_60_chairs.pdf')
    assert row['result']['status']=='Ready for approval',row
    id=row['id']
    assert client.post('/api/invoices/'+id+'/retry').status_code==200
    row=wait(client,id)
    assert row['result']['status']=='Ready for approval' # Must not duplicate itself.
    assert client.post('/api/invoices/'+id+'/approve').status_code==200
    assert client.post('/api/invoices/'+id+'/approve').json()['already_accepted']
    p=next(p for p in client.get('/api/dashboard').json()['pos'] if p['number']=='PO-1042')
    assert p['lines'][0]['used']=='60'
    assert client.post('/api/invoices/'+id+'/correct',json={'data':row['data']}).status_code==409
    over=upload(client,'02_split_50_chairs.pdf')
    assert over['result']['status']=='Needs review'
    assert any(c['code'].startswith('quantity') and c['level']=='review' for c in over['result']['checks'])
    assert client.post('/api/invoices/'+over['id']+'/approve').status_code==409

def test_duplicates_and_rescan(client):
    original=upload(client,'03_original_duplicate.pdf')
    assert original['result']['status']=='Ready for approval',original
    repeat=upload(client,'03_original_duplicate.pdf')
    assert repeat['result']['status']=='Blocked'
    assert any(c['code']=='duplicate_file' for c in repeat['result']['checks'])
    near=upload(client,'04_near_duplicate.pdf')
    assert near['result']['status']=='Needs review'
    assert any(c['code']=='possible_duplicate' for c in near['result']['checks'])

def test_ambiguity_and_correction(client):
    row=upload(client,'06_ambiguous_po.pdf')
    assert row['result']['status']=='Needs review'
    assert len(row['result']['candidates'])==2
    assert client.post('/api/invoices/'+row['id']+'/select-po',json={'po':'PO-3001'}).status_code==200
    row=wait(client,row['id']);assert row['result']['status']=='Ready for approval'
    broken=upload(client,'07_arithmetic_error.pdf')
    assert broken['result']['status']=='Needs review'
    data=broken['data'];data['total']='23600'
    assert client.post('/api/invoices/'+broken['id']+'/correct',json={'data':data}).status_code==200
    corrected=wait(client,broken['id']);assert corrected['result']['status']=='Ready for approval'
    assert float(corrected['original']['total'])==99999
    assert corrected['reviews'][0]['action']=='correct'

def test_missing_scan_unknown_and_sse(client):
    row=upload(client,'05_missing_information.pdf');assert row['result']['status']=='Needs review'
    assert row['result']['email'] and row['data']['invoice_no'] is None
    scan=upload(client,'09_scan_requires_gemini.pdf');assert scan['execution']=='failed'
    assert scan['result'] is None
    unknown=upload(client,'08_unknown_vendor.pdf');assert unknown['result']['status']=='Needs review'
    events=client.get('/api/invoices/'+row['id']+'/events').text
    assert 'event: end' in events and '"stage": "decision"' in events
    assert client.get('/api/invoices/'+row['id']+'/pdf').content.startswith(b'%PDF')

def test_approval_rechecks_balance(client):
    first=upload(client,'01_happy_60_chairs.pdf')
    second=upload(client,'02_split_50_chairs.pdf')
    assert first['result']['status']==second['result']['status']=='Ready for approval'
    assert client.post('/api/invoices/'+first['id']+'/approve').status_code==200
    assert client.post('/api/invoices/'+second['id']+'/approve').status_code==409
    assert client.get('/api/invoices/'+second['id']).json()['result']['status']=='Needs review'

def test_auth_and_reset(client,monkeypatch):
    monkeypatch.setenv('AP_ACCESS_TOKEN','test-secret')
    assert client.get('/api/dashboard').status_code==401
    assert client.get('/api/dashboard',headers={'Authorization':'Bearer test-secret'}).status_code==200
    monkeypatch.delenv('AP_ACCESS_TOKEN')
    upload(client,'01_happy_60_chairs.pdf')
    assert client.post('/api/reset').status_code==200
    assert client.get('/api/dashboard').json()['invoices']==[]

def test_line_aggregation_and_identifier_conflicts(client):
    row=upload(client,'01_happy_60_chairs.pdf')
    data=row['data'];data['invoice_no']='OTHER';data['lines']=data['lines']*2
    data['subtotal']='240000';data['tax']='43200';data['total']='283200'
    with s.connection() as db:
        result=evaluate(Invoice.model_validate(data),s.records(db,'vendors'),s.records(db,'pos'),[],'other','other')
    assert result['status']=='Needs review'
    assert any(c['code'].startswith('quantity') and c['level']=='review' for c in result['checks'])
    data=row['data'];data['gstin']='WRONG'
    with s.connection() as db:r=evaluate(Invoice.model_validate(data),s.records(db,'vendors'),s.records(db,'pos'),[],'other','other')
    assert any(c['code']=='gstin' and c['level']=='review' for c in r['checks'])

def test_price_tolerance_and_po_limit_are_independent(client):
    row=upload(client,'01_happy_60_chairs.pdf');d=row['data']
    d['invoice_no']='PRICE-001';d['lines'][0].update(qty='10',unit_price='2036',line_total='20360')
    d.update(subtotal='20360',tax='3664.80',total='24024.80')
    with s.connection() as db:
        r=evaluate(Invoice.model_validate(d),s.records(db,'vendors'),s.records(db,'pos'),[],'other','other')
    assert r['status']=='Ready for approval'
    d['lines'][0].update(qty='100',line_total='203600')
    d.update(subtotal='203600',tax='36648',total='240248')
    with s.connection() as db:r=evaluate(Invoice.model_validate(d),s.records(db,'vendors'),s.records(db,'pos'),[],'other','other')
    assert next(c for c in r['checks'] if c['code']=='price_0')['level']=='pass'
    assert next(c for c in r['checks'] if c['code']=='balance')['level']=='review'

def test_wrong_po_cannot_be_forced_and_failed_retry(client):
    row=upload(client,'06_ambiguous_po.pdf')
    client.post('/api/invoices/'+row['id']+'/select-po',json={'po':'PO-1042'})
    row=wait(client,row['id']);assert row['result']['status']=='Needs review'
    assert row['po'] is None
    scan=upload(client,'09_scan_requires_gemini.pdf')
    client.post('/api/invoices/'+scan['id']+'/retry')
    scan=wait(client,scan['id']);assert scan['execution']=='failed'

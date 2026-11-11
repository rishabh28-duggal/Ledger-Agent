import copy
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from test_cloud import client, demo, uid, add_ready
from cloud.engine import decision
from cloud.reader import parse_pages
from app.controls import account, ifsc


def setup(c,store):
    sid=demo(c);owner=uid(c)
    def configure(m,rows):
        p=m['master']['pos'][0];p['lines'][0]['qty']='100';p['total']='236000'
    store.atomic(owner,sid,configure)
    meta=store.snapshot(owner,sid)[0];po=meta['master']['pos'][0]
    return sid,owner,po,meta['master']['vendors'][0]


def policy(c,sid,po,required=True):
    return c.post(f'/api/sessions/{sid}/receipt-policy',params={'po':po['number']},json={'required':required,'reason':'Goods purchase policy decision'})


def receipt(c,sid,po,qty,reference='GR-001',**changes):
    body=dict(id=uuid.uuid4().hex,reference=reference,po=po['number'],date=date.today().isoformat(),
              lines=[{'po_line':po['lines'][0]['id'],'qty':str(qty)}],reason='Warehouse delivery independently confirmed')
    body.update(changes)
    return c.post(f'/api/sessions/{sid}/receipts',json=body),body


def checks(c,sid,iid):
    return c.get(f'/api/sessions/{sid}/invoices/{iid}').json()['result']['checks']


def approve(c,sid,iid,run=1):
    return c.post(f'/api/sessions/{sid}/invoices/{iid}/approve',json={'expected_run':run})


def trusted(c,sid,v,number='000000123456',code='TEST0000001',version=0,verified=True):
    return c.put(f'/api/sessions/{sid}/vendors/{v["id"]}/bank',json=dict(beneficiary='Fictional Treasury',account=number,
        ifsc=code,verified=verified,expected_version=version,reason='Fictional established-contact verification reference'))


def invoice_bank(store,owner,sid,iid,number='000000123456',code='TEST0000001',uncertain=False):
    def update(m,rows):
        d=rows[iid]['data'];d.update(bank_account=number,bank_ifsc=code,bank_beneficiary='Fictional Treasury',bank_ambiguous=uncertain)
        d['evidence']['bank_account']={'page':1,'snippet':'Account number: '+number}
        if uncertain:d['uncertain_fields']=['bank_account']
        rows[iid]['original']=copy.deepcopy(d);decision(m,rows,rows[iid])
    store.atomic(owner,sid,update)


def test_missing_partial_multiple_receipts_and_consumption(client):
    c,store=client;sid,owner,po,v=setup(c,store);iid=add_ready(store,owner,sid,qty=100)
    assert any(x['code']=='receipt_optional' and x['level']=='info' for x in checks(c,sid,iid))
    assert policy(c,sid,po).status_code==200
    assert approve(c,sid,iid).status_code==409
    r,body=receipt(c,sid,po,60);assert r.status_code==200,r.text
    finding=next(x for x in checks(c,sid,iid) if x['code']=='receipt_'+po['lines'][0]['id'])
    assert finding['evidence']['available']=='60' and '40 require receipt confirmation' in finding['message']
    assert c.post(f'/api/sessions/{sid}/receipts',json=body).json()['revision']==1
    assert receipt(c,sid,po,60)[0].status_code==409
    assert receipt(c,sid,po,40,'GR-002')[0].status_code==200
    assert next(x for x in checks(c,sid,iid) if x['code']=='receipt_'+po['lines'][0]['id'])['level']=='pass'
    assert approve(c,sid,iid).status_code==200
    approved=store.snapshot(owner,sid)[1][0]
    body.update(expected_revision=1,reversed=True,reason='Erroneous receipt reversal attempt')
    assert c.post(f'/api/sessions/{sid}/receipts',json=body).status_code==409
    assert policy(c,sid,po,False).status_code==200
    assert store.snapshot(owner,sid)[1][0]==approved
    assert store.snapshot(owner,sid)[0]['control_audit'][-1]['action']=='receipt_policy_changed'


def test_aggregate_units_over_receipt_and_concurrent_approval(client):
    c,store=client;sid,owner,po,v=setup(c,store);policy(c,sid,po)
    receipt(c,sid,po,60)
    a=add_ready(store,owner,sid,'FIRST-1',40);b=add_ready(store,owner,sid,'SECOND-2',30)
    from cloud.main import approve as direct_approve,RunInput
    from cloud.auth import User
    from cloud.engine import Conflict
    def do(iid):
        try:return direct_approve(sid,iid,RunInput(expected_run=1),User(uid=owner,username='demo',demo=True),store)
        except Conflict:return {'accepted':False}
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(do,[a,b]))
    assert sum(x['accepted'] for x in results)==1
    remaining=next(r for r in store.snapshot(owner,sid)[1] if not r['accepted'])
    assert next(x for x in remaining['result']['checks'] if x['code']=='receipt_'+po['lines'][0]['id'])['level']=='review'
    # A sum of repeated mapped lines must be compared, not each line in isolation.
    def split(m,rows):
        row=rows[remaining['id']];line=copy.deepcopy(row['data']['lines'][0]);line['qty']='20'
        row['data']['lines']=[line,copy.deepcopy(line)];decision(m,rows,row)
    store.atomic(owner,sid,split)
    row=next(r for r in store.snapshot(owner,sid)[1] if not r['accepted'])
    assert next(x for x in row['result']['checks'] if x['code']=='receipt_'+po['lines'][0]['id'])['evidence']['billed']=='40'
    assert receipt(c,sid,po,50,'OVER-1')[0].status_code==200
    assert any(x['code'].startswith('receipt_over_') and x['level']=='review' for x in checks(c,sid,remaining['id']))
    def wrong_unit(m,rows):rows[remaining['id']]['data']['lines'][0]['unit']='kg';decision(m,rows,rows[remaining['id']])
    store.atomic(owner,sid,wrong_unit)
    assert any(x['code'].startswith('unit_') and x['level']=='review' for x in checks(c,sid,remaining['id']))


def test_receipt_ownership_corrections_and_policy_guard(client):
    c,store=client;sid,owner,po,v=setup(c,store)
    r,body=receipt(c,sid,po,20);body.update(expected_revision=1,lines=[{'po_line':po['lines'][0]['id'],'qty':'15'}],reason='Correct accepted count against delivery note')
    assert c.post(f'/api/sessions/{sid}/receipts',json=body).json()['revision']==2
    assert len(store.snapshot(owner,sid)[0]['receipts'][body['id']]['history'])==2
    policy(c,sid,po)
    master=c.get(f'/api/sessions/{sid}').json()['session']['master'];master['pos'][0]['require_receipts']=False
    assert c.put(f'/api/sessions/{sid}/master',json=master).status_code==409
    demo(c)
    assert c.post(f'/api/sessions/{sid}/receipts',json=body).status_code==404
    assert policy(c,sid,po).status_code==404


def test_bank_match_change_general_confirmation_and_external_verification(client):
    c,store=client;sid,owner,po,v=setup(c,store);iid=add_ready(store,owner,sid)
    assert trusted(c,sid,v,number='0000 0012-3456').status_code==200
    invoice_bank(store,owner,sid,iid,number='000000123456',code=' test 0000001 ')
    assert next(x for x in checks(c,sid,iid) if x['code']=='bank_match')['level']=='pass'
    invoice_bank(store,owner,sid,iid,number='000000654321')
    assert approve(c,sid,iid).status_code==409
    d=c.get(f'/api/sessions/{sid}/invoices/{iid}').json()['data']
    response=c.post(f'/api/sessions/{sid}/invoices/{iid}/review',json={'data':d,'expected_run':1,'confirmed_fields':['bank_account'],'compared_with_source':True})
    assert response.status_code==200,response.text
    assert any(x['code']=='bank_match' and x['level']=='review' for x in response.json()['result']['checks'])
    base=f'/api/sessions/{sid}/invoices/{iid}/bank'
    assert c.post(base+'/verify',json={'expected_run':2,'method':'Known procurement contact','reason':'Contact confirmed fictional reference 42'}).status_code==200
    row=c.get(f'/api/sessions/{sid}/invoices/{iid}').json();assert not row['accepted']
    assert row['bank_verification']['baseline_version']==1
    assert approve(c,sid,iid,3).status_code==200
    frozen=copy.deepcopy(store.snapshot(owner,sid)[1][0])
    assert trusted(c,sid,v,number='000000111111',version=1).status_code==200
    assert store.snapshot(owner,sid)[1][0]==frozen
    reveal=c.post(f'/api/sessions/{sid}/vendors/{v["id"]}/bank/reveal').json()
    assert reveal['history'][0]['account']=='000000123456'


def test_bank_uncertainty_required_policy_and_correction(client):
    c,store=client;sid,owner,po,v=setup(c,store);iid=add_ready(store,owner,sid)
    base=f'/api/sessions/{sid}/invoices/{iid}/bank'
    assert next(x for x in checks(c,sid,iid) if x['code']=='bank_missing')['level']=='info'
    assert c.post(f'/api/sessions/{sid}/vendors/{v["id"]}/bank-policy',json={'required':True,'reason':'Require established bank account'}).status_code==200
    assert approve(c,sid,iid).status_code==409
    assert trusted(c,sid,v,verified=False).status_code==200
    invoice_bank(store,owner,sid,iid)
    assert any(x['code']=='bank_baseline' and x['level']=='review' for x in checks(c,sid,iid))
    assert trusted(c,sid,v,version=1).status_code==200
    invoice_bank(store,owner,sid,iid,number='****3456',uncertain=True)
    assert c.post(base+'/verify',json={'expected_run':1,'method':'Established contact','reason':'External test verification note'}).status_code==409
    response=c.post(base+'/correct',json={'expected_run':1,'bank_beneficiary':'Fictional Treasury','bank_account':'000000123456','bank_ifsc':'TEST0000001','compared_with_source':True,'reason':'Source evidence read clearly on page one'})
    assert response.status_code==200,response.text
    assert response.json()['data']['bank_account']=='****3456'
    assert next(x for x in checks(c,sid,iid) if x['code']=='bank_match')['level']=='pass'


def test_bank_masking_extraction_and_access(client):
    c,store=client;sid,owner,po,v=setup(c,store);iid=add_ready(store,owner,sid)
    trusted(c,sid,v);invoice_bank(store,owner,sid,iid,number='000000654321')
    for url in ['/api/sessions',f'/api/sessions/{sid}','/api/invoices',f'/api/sessions/{sid}/invoices/{iid}',f'/api/sessions/{sid}/export?format=json']:
        text=c.get(url).text;assert '000000654321' not in text and '000000123456' not in text
    assert c.post(f'/api/sessions/{sid}/invoices/{iid}/bank/reveal').json()['bank_account']=='000000654321'
    parsed,_=parse_pages([(1,'Account number: 0000 0012-3456\nIFSC: TEST0000001\nBeneficiary name: Fictional Treasury','PDF text')])
    assert account(parsed.bank_account)=='000000123456' and ifsc(parsed.bank_ifsc)=='TEST0000001'
    parsed,_=parse_pages([(1,'Account number: 000000123456\nAccount number: 000000654321','PDF text')])
    assert parsed.bank_account is None and parsed.bank_ambiguous
    from cloud.procurement_controls import public
    safe=public({'data':parsed.model_dump(mode='json')})
    assert '000000654321' not in str(safe)
    demo(c)
    assert c.post(f'/api/sessions/{sid}/vendors/{v["id"]}/bank/reveal').status_code==404
    assert c.post(f'/api/sessions/{sid}/invoices/{iid}/bank/reveal').status_code==404


def test_partial_invoice_availability_and_receipt_reference_reservation(client):
    c,store=client;sid,owner,po,v=setup(c,store);policy(c,sid,po)
    r,body=receipt(c,sid,po,60)
    first=add_ready(store,owner,sid,'PART-40',40)
    assert approve(c,sid,first).status_code==200
    twenty=add_ready(store,owner,sid,'PART-20',20);thirty=add_ready(store,owner,sid,'PART-30',30)
    line='receipt_'+po['lines'][0]['id']
    assert next(x for x in checks(c,sid,twenty) if x['code']==line)['level']=='pass'
    assert next(x for x in checks(c,sid,thirty) if x['code']==line)['level']=='review'
    body.update(expected_revision=1,reference='CORRECTED-REF',reason='Correct the delivery reference only')
    assert c.post(f'/api/sessions/{sid}/receipts',json=body).status_code==200
    assert receipt(c,sid,po,10,'GR-001')[0].status_code==409


def test_ifsc_beneficiary_changes_invalidate_prior_verification(client):
    c,store=client;sid,owner,po,v=setup(c,store);iid=add_ready(store,owner,sid)
    trusted(c,sid,v);invoice_bank(store,owner,sid,iid,code='TEST0000002')
    assert next(x for x in checks(c,sid,iid) if x['code']=='bank_match')['level']=='review'
    base=f'/api/sessions/{sid}/invoices/{iid}/bank'
    assert c.post(base+'/verify',json={'expected_run':1,'method':'Known established contact','reason':'Independently confirmed reference 12'}).status_code==200
    assert next(x for x in checks(c,sid,iid) if x['code']=='bank_match')['level']=='pass'
    assert trusted(c,sid,v,number='000000333333',version=1).status_code==200
    assert next(x for x in checks(c,sid,iid) if x['code']=='bank_match')['level']=='review'
    def change_name(m,rows):
        rows[iid]['data']['bank_beneficiary']='Different beneficiary';decision(m,rows,rows[iid])
    store.atomic(owner,sid,change_name)
    assert next(x for x in checks(c,sid,iid) if x['code']=='bank_beneficiary')['level']=='review'
    assert not c.get(f'/api/sessions/{sid}/invoices/{iid}').json()['accepted']


def test_reports_mask_bank_accounts_and_import_never_trusts(client):
    import io
    from openpyxl import load_workbook
    c,store=client;sid,owner,po,v=setup(c,store);iid=add_ready(store,owner,sid)
    trusted(c,sid,v);invoice_bank(store,owner,sid,iid)
    csv=c.get(f'/api/sessions/{sid}/export').text
    assert 'Receipt findings' in csv and 'Bank findings' in csv and '000000123456' not in csv
    workbook=load_workbook(io.BytesIO(c.get('/api/invoices/export.xlsx',params={'folder':sid}).content),data_only=False)
    cells=[cell.value for row in workbook.active for cell in row]
    assert 'Invoice account (masked)' in cells and '****3456' in cells and '000000123456' not in str(cells)
    import_file=('vendors.csv',b'Vendor name,bank_account\nFictional Imported Vendor,000000999999','text/csv')
    p=c.post(f'/api/sessions/{sid}/vendor-import/preview',files={'file':import_file}).json()
    assert c.post(f'/api/sessions/{sid}/vendor-import/confirm',json={'token':p['token']}).status_code==200
    meta=store.snapshot(owner,sid)[0];new=next(v for v in meta['master']['vendors'] if v['name']=='Fictional Imported Vendor')
    assert new['id'] not in meta['bank_accounts']

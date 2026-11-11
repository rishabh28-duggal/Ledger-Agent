"""Early procurement resolution uses persisted, scoped references and real checks."""
import copy
import pytest
from test_cloud import client,demo,uid,add_ready
from cloud.engine import decision

def setup(c,store,**changes):
    sid=demo(c);owner=uid(c);iid=add_ready(store,owner,sid)
    def alter(meta,rows):
        rows[iid]['data'].update(changes);decision(meta,rows,rows[iid])
    store.atomic(owner,sid,alter)
    return sid,owner,iid

def resolve(c,sid,iid,operation,run=1,**values):
    return c.post(f'/api/sessions/{sid}/invoices/{iid}/procurement',json={'operation':operation,'expected_run':run,'reason':'Independently checked authorisation reference TEST-01',**values})

def new_vendor():return dict(id='fiction-new',name='Fictional Cedar Furniture',gstin='36ZZZCX0009A1Z8',aliases=[],status='approved')
def new_po(store,owner,sid):
    p=copy.deepcopy(store.snapshot(owner,sid)[0]['master']['pos'][0]);p.update(number='PO-CEDAR-100',vendor_id='fiction-new');p['lines'][0]['id']='cedar-chair';return p

def test_missing_vendor_and_po_rerun_with_uncertainty_preserved(client):
    c,store=client;sid,owner,iid=setup(c,store,vendor=new_vendor()['name'],gstin=new_vendor()['gstin'],po_ref='PO-CEDAR-100',uncertain_fields=['vendor','lines'])
    before=copy.deepcopy(store.snapshot(owner,sid)[1][0]['data'])
    r=resolve(c,sid,iid,'vendor_create',vendor=new_vendor(),verified=True);assert r.status_code==200,r.text
    row=r.json()['invoice'];assert row['vendor_id']=='fiction-new';assert not row['accepted'];assert row['data']==before;assert row['run']==2
    assert not r.json()['session'].get('bank_status')
    r=resolve(c,sid,iid,'po_create',run=2,po=new_po(store,owner,sid),verified=True);assert r.status_code==200,r.text
    row=r.json()['invoice'];assert row['po']=='PO-CEDAR-100';assert row['selected_po']=='PO-CEDAR-100';assert row['data']==before
    assert row['result']['status']=='Needs review'
    assert {'vendor_approved','po_created_and_linked'}<={a['action'] for a in row['audit']}
    assert any(a['details'].get('checks') for a in row['audit'])
    assert c.post(f'/api/sessions/{sid}/invoices/{iid}/approve',json={'expected_run':row['run']}).status_code==409

def test_duplicate_vendor_offers_existing_link_without_duplicate(client):
    c,store=client;sid,owner,iid=setup(c,store,vendor='Acme Office Furniture')
    meta,_=store.snapshot(owner,sid);vendor=copy.deepcopy(meta['master']['vendors'][0]);count=len(meta['master']['vendors']);vendor['id']='duplicate-id'
    r=resolve(c,sid,iid,'vendor_create',vendor=vendor,verified=True);assert r.status_code==409;assert 'existing vendor' in r.json()['detail']
    r=resolve(c,sid,iid,'vendor_link',existing_vendor='acme',verified=True);assert r.status_code==200,r.text
    row=r.json()['invoice'];assert row['vendor_id']=='acme';assert not any(x['code']=='vendor_name' for x in row['result']['checks'])
    meta,_=store.snapshot(owner,sid);assert len(meta['master']['vendors'])==count;assert 'Acme Office Furniture' in meta['master']['vendors'][0]['aliases']
    assert resolve(c,sid,iid,'vendor_link',existing_vendor='acme',verified=True).status_code==409

def test_duplicate_po_selects_existing_without_new_record(client):
    c,store=client;sid,owner,iid=setup(c,store,po_ref='PO-NOT-RECORDED')
    meta,_=store.snapshot(owner,sid);p=copy.deepcopy(meta['master']['pos'][0]);count=len(meta['master']['pos']);p['number']='po-1042';p['lines'][0]['id']='different-line'
    assert resolve(c,sid,iid,'po_create',po=p,verified=True).status_code==409
    r=resolve(c,sid,iid,'po_link',existing_po='PO-1042');assert r.status_code==200,r.text
    row=r.json()['invoice'];assert row['po']=='PO-1042';assert row['selected_po']=='PO-1042';assert not row['accepted']
    assert len(store.snapshot(owner,sid)[0]['master']['pos'])==count
    assert any(a['action']=='po_linked' for a in row['audit'])

def test_explicit_verification_validation_and_other_findings(client):
    c,store=client;sid,owner,iid=setup(c,store,vendor=new_vendor()['name'],gstin=new_vendor()['gstin'],po_ref='PO-CEDAR-100',total='1')
    before=copy.deepcopy(store.snapshot(owner,sid))
    assert resolve(c,sid,iid,'vendor_create',vendor=new_vendor()).status_code==409
    assert store.snapshot(owner,sid)==before
    bad=new_vendor();bad['name']=''
    assert resolve(c,sid,iid,'vendor_create',vendor=bad,verified=True).status_code==422
    assert resolve(c,sid,iid,'vendor_create',vendor=new_vendor(),verified=True).status_code==200
    assert resolve(c,sid,iid,'po_create',run=2,po=new_po(store,owner,sid)).status_code==409
    row=resolve(c,sid,iid,'po_create',run=2,po=new_po(store,owner,sid),verified=True).json()['invoice']
    assert row['result']['status']!='Ready for approval'
    assert c.post(f'/api/sessions/{sid}/invoices/{iid}/approve',json={'expected_run':row['run']}).status_code==409
    assert resolve(c,sid,iid,'vendor_link',run=row['run'],existing_vendor='blocked',verified=True).status_code==409

def test_ownership_csrf_and_existing_master_lock(client):
    c,store=client;sid,owner,iid=setup(c,store)
    assert resolve(c,sid,iid,'po_link',existing_po='PO-1042').status_code==200
    assert c.post(f'/api/sessions/{sid}/invoices/{iid}/procurement',json={'operation':'po_link','expected_run':2,'reason':'Existing authorisation','existing_po':'PO-1042'},headers={'X-CSRF-Token':''}).status_code==403
    second=add_ready(store,owner,sid,name='PREVIOUS-APPROVED',qty=1)
    store.atomic(owner,sid,lambda m,rows:rows[second].update(accepted=True))
    assert resolve(c,sid,iid,'vendor_create',run=2,vendor=new_vendor(),verified=True).status_code==409
    assert resolve(c,sid,iid,'po_link',run=2,existing_po='PO-1042').status_code==200
    cookie=c.cookies.get('ledger_demo');c.cookies.clear();demo(c)
    assert resolve(c,sid,iid,'po_link',run=3,existing_po='PO-1042').status_code==404

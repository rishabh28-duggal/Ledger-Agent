"""Removal is scoped, audited and cannot resurrect work or consume an approved PO twice."""
import asyncio,json
import pytest
from test_cloud import client,demo,uid,add_ready
from cloud.engine import process,new_record,decision
from cloud import engine
from app.domain import Invoice


def delete(c,path,**body):
    return c.request('DELETE',path,json=body)


def test_remove_invoice_hides_file_and_rechecks_duplicates(client):
    c,store=client;sid=demo(c);owner=uid(c);iid=add_ready(store,owner,sid)
    store.put_file(owner,sid,iid,b'original','application/pdf')
    assert delete(c,f'/api/sessions/{sid}/invoices/{iid}',expected_run=99).status_code==409
    other=add_ready(store,owner,sid,name='TEST-001')
    assert any(x['code'].startswith('duplicate') and x['level']=='block' for x in c.get(f'/api/sessions/{sid}/invoices/{other}').json()['result']['checks'])
    r=delete(c,f'/api/sessions/{sid}/invoices/{iid}',expected_run=1);assert r.status_code==200,r.text
    for suffix in ['', '/file','/original','/preview-page']:
        assert c.get(f'/api/sessions/{sid}/invoices/{iid}'+suffix).status_code==404
    rows=c.get(f'/api/sessions/{sid}').json()['invoices'];assert [x['id'] for x in rows]==[other]
    assert not any(x['code'].startswith('duplicate') and x['level']=='block' for x in rows[0]['result']['checks'])
    assert iid not in c.get('/api/invoices').text
    with store.connect() as db:
        row=json.loads(db.execute('SELECT data FROM invoices WHERE uid=? AND sid=? AND id=?',(owner,sid,iid)).fetchone()[0])
    assert row['deleted'];assert row['audit'][-1]['action']=='invoice_deleted'
    assert delete(c,f'/api/sessions/{sid}/invoices/{iid}',expected_run=2).status_code==404


def test_approved_invoice_protection_and_folder_deletion(client):
    c,store=client;sid=demo(c);owner=uid(c);iid=add_ready(store,owner,sid)
    assert c.post(f'/api/sessions/{sid}/invoices/{iid}/approve',json={'expected_run':1}).status_code==200
    assert delete(c,f'/api/sessions/{sid}/invoices/{iid}',expected_run=1).status_code==409
    version=c.get(f'/api/sessions/{sid}').json()['session']['version']
    assert delete(c,f'/api/sessions/{sid}',expected_version=version-1).status_code==409
    r=delete(c,f'/api/sessions/{sid}',expected_version=version);assert r.status_code==200,r.text
    assert c.get('/api/sessions').json()==[]
    assert c.get(f'/api/sessions/{sid}').status_code==404
    assert c.get(f'/api/sessions/{sid}/invoices/{iid}').status_code==404
    assert c.get('/api/invoices').json()['invoices']==[]
    with pytest.raises(KeyError):store.atomic(owner,sid,lambda m,r:None)
    with store.connect() as db:
        meta=json.loads(db.execute('SELECT data FROM sessions WHERE uid=? AND sid=?',(owner,sid)).fetchone()[0])
    assert meta['deleted'];assert meta['control_audit'][-1]['action']=='folder_deleted'


def test_delete_scope_and_csrf(client):
    c,store=client;sid=demo(c);iid=add_ready(store,uid(c),sid)
    c.headers.pop('X-CSRF-Token')
    assert delete(c,f'/api/sessions/{sid}/invoices/{iid}',expected_run=1).status_code==403
    demo(c)
    assert delete(c,f'/api/sessions/{sid}/invoices/{iid}',expected_run=1).status_code==404
    assert delete(c,f'/api/sessions/{sid}',expected_version=0).status_code==404


def test_running_invoice_is_not_resurrected(client,monkeypatch):
    c,store=client;sid=demo(c);owner=uid(c)
    row=new_record('wrong.pdf',b'file','application/pdf',1,'test');iid=row['id']
    store.atomic(owner,sid,lambda m,rows:rows.update({iid:row}));store.put_file(owner,sid,iid,b'file','application/pdf')
    async def reader(*args,**kwargs):
        def remove(meta,rows):rows[iid].update(deleted=True,execution='cancelled',run=2)
        store.atomic(owner,sid,remove)
        return Invoice(),{'source':'Test reader','fallback':True,'note':'test'}
    monkeypatch.setattr(engine,'read',reader)
    asyncio.run(process(store,owner,sid,iid,1,True))
    assert store.snapshot(owner,sid)[1]==[]
    assert c.get(f'/api/sessions/{sid}/invoices/{iid}').status_code==404

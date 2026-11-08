import copy
import io
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from openpyxl import Workbook, load_workbook
from test_cloud import client, demo, uid, add_ready
from cloud import vendor_import as vi


def csv_file(text):
    return ('vendors.csv', text.encode('utf-8-sig'), 'text/csv')


def xlsx_file(rows, title='Vendors', extra=False):
    book=Workbook();ws=book.active;ws.title=title
    for row in rows:ws.append(row)
    if extra:book.create_sheet('Other').append(['Something'])
    data=io.BytesIO();book.save(data)
    return ('vendors.xlsx',data.getvalue(),'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


def preview(c,sid,file,update=False,sheet=''):
    return c.post(f'/api/sessions/{sid}/vendor-import/preview',files={'file':file},data={'update':str(update).lower(),'sheet':sheet})


def confirm(c,sid,p):
    return c.post(f'/api/sessions/{sid}/vendor-import/confirm',json={'token':p['token']})


@pytest.mark.parametrize('file',[csv_file('Vendor_Name,GSTIN,Status,Aliases\n Fictional New Vendor ,,, New alias ; Other alias \n'),
    xlsx_file([vi.HEADERS,['Fictional New Vendor','','Active','New alias;Other alias']])])
def test_preview_no_writes_confirm_idempotent_preserves_pos(client,file):
    c,store=client;sid=demo(c);owner=uid(c);before=store.snapshot(owner,sid)
    p=preview(c,sid,file);assert p.status_code==200,p.text;p=p.json()
    assert p['counts']['eligible']==1 and p['rows'][0]['values']['status']=='approved'
    assert store.snapshot(owner,sid)==before
    response=confirm(c,sid,p);assert response.status_code==200,response.text
    assert response.json()['imported']==1
    after=store.snapshot(owner,sid)[0]
    assert after['master']['pos']==before[0]['master']['pos']
    assert after['master']['vendors'][:-1]==before[0]['master']['vendors']
    assert after['master']['vendors'][-1]['aliases']==['New alias','Other alias']
    assert confirm(c,sid,p).json()==response.json()
    assert len(store.snapshot(owner,sid)[0]['master']['vendors'])==len(before[0]['master']['vendors'])+1


def test_validation_duplicates_formulas_and_counts(client):
    c,store=client;sid=demo(c)
    p=preview(c,sid,csv_file('Vendor name,GSTIN,Status,Aliases\nGood vendor,,,\nBad GST,123,Active,\nBad state,,Unknown,\nDuplicate,,,\nDuplicate,,,\n=SUM(1),,,\n,,Blocked,\n')).json()
    assert p['counts']=={'new':1,'existing':0,'conflicts':2,'invalid':4,'eligible':1}
    assert p['rows'][0]['defaulted']
    result=confirm(c,sid,p).json();assert result['imported']==1 and result['skipped']==6 and result['failed']==0
    assert result['rows'][-1]['errors']
    for content in ['GSTIN,Status\n,Active','Vendor Name,vendor_name\nA,B']:
        assert preview(c,sid,csv_file(content)).status_code==400
    assert preview(c,sid,('bad.xls',b'bad','application/octet-stream')).status_code==400
    assert preview(c,sid,('bad.xlsx',b'bad','application/octet-stream')).status_code==400
    assert preview(c,sid,csv_file('Vendor name\n'+('X'*40+'\n')*501)).status_code==400


def test_excel_sheets_formulas_template(client):
    c,_=client;sid=demo(c)
    multi=xlsx_file([vi.HEADERS,['Selected vendor','','','']],title='First',extra=True)
    choose=preview(c,sid,multi).json();assert choose['choose_sheet'] and choose['sheets']==['First','Other']
    p=preview(c,sid,multi,sheet='First').json();assert p['counts']['new']==1
    assert preview(c,sid,multi,sheet='Missing').status_code==400
    formula=xlsx_file([vi.HEADERS,['Formula vendor','=1+1','Active','']])
    p=preview(c,sid,formula).json();assert p['counts']['invalid']==1 and 'formulas' in ' '.join(p['rows'][0]['errors'])
    preferred=preview(c,sid,xlsx_file([vi.HEADERS,['Preferred','','','']],extra=True)).json()
    assert preferred['sheet']=='Vendors' and preferred['counts']['new']==1
    template=c.get('/api/vendor-template.xlsx');assert template.status_code==200
    book=load_workbook(io.BytesIO(template.content),data_only=False)
    assert list(c.value for c in book['Vendors'][1])==vi.HEADERS
    assert not book['Vendors']['B2'].value and 'REMOVE BEFORE IMPORT' in book['Vendors']['A2'].value
    assert all(cell.data_type!='f' for ws in book for row in ws for cell in row)


def test_skip_update_and_protect_blocked_identity(client):
    c,store=client;sid=demo(c);owner=uid(c);before=store.snapshot(owner,sid)[0]['master'];old=before['vendors'][0]
    content=f"Vendor name,GSTIN,Status,Aliases\n{old['name']},,Blocked,New alias\n"
    p=preview(c,sid,csv_file(content)).json();assert p['counts']['existing']==1 and p['counts']['eligible']==0
    assert confirm(c,sid,p).status_code==409
    p=preview(c,sid,csv_file(content),update=True).json();assert p['rows'][0]['action']=='Update'
    assert confirm(c,sid,p).json()['updated']==1
    after=store.snapshot(owner,sid)[0]['master'];vendor=after['vendors'][0]
    assert vendor['id']==old['id'] and vendor['gstin']==old['gstin'] and vendor['status']=='blocked'
    assert set(vendor['aliases'])==set(old['aliases']+['New alias']) and after['pos']==before['pos']
    p=preview(c,sid,csv_file(f"Vendor name,Status,Aliases\n{old['name']},Active,Another alias\n"),True).json()
    assert p['rows'][0]['note'] and p['rows'][0]['changes']['after']['status']=='blocked'
    assert confirm(c,sid,p).json()['updated']==1
    conflict=preview(c,sid,csv_file(f"Vendor name,GSTIN\n{old['name']},27ABCDE1234F1Z5"),True).json()
    assert conflict['counts']['conflicts']==1
    # Alias identifies two existing vendors; never guess which to update.
    store.atomic(owner,sid,lambda m,r:m['master']['vendors'][1]['aliases'].append(old['name']))
    p=preview(c,sid,csv_file(f"Vendor name\n{old['name']}"),True).json()
    assert p['counts']['conflicts']==1


def test_confirmation_revalidates_and_ownership(client):
    c,store=client;sid=demo(c);owner=uid(c)
    file=csv_file('Vendor name\nNew Vendor\n');p=preview(c,sid,file).json()
    other=c.post('/api/sessions',json={'name':'Other'}).json()['id']
    assert confirm(c,other,p).status_code==404
    store.atomic(owner,sid,lambda m,r:m['master']['vendors'][0].update(name='Changed'))
    assert confirm(c,sid,p).status_code==409
    p=preview(c,sid,file).json();demo(c)
    assert preview(c,sid,file).status_code==404 and confirm(c,sid,p).status_code==404
    own=c.post('/api/sessions',json={'name':'New owner'}).json()['id']
    assert confirm(c,own,p).status_code==404
    assert confirm(c,own,{'token':p['token']+'tamper'}).status_code==400


def test_locked_and_recheck_unapproved_preserves_po_refs(client):
    c,store=client;sid=demo(c);owner=uid(c);iid=add_ready(store,owner,sid)
    master=copy.deepcopy(store.snapshot(owner,sid)[0]['master']);vendor=master['vendors'][0]
    file=csv_file(f"Vendor name,Status\n{vendor['name']},Blocked\n")
    p=preview(c,sid,file,True).json();assert confirm(c,sid,p).json()['updated']==1
    meta,rows=store.snapshot(owner,sid);row=next(r for r in rows if r['id']==iid)
    assert row['result']['status']=='Blocked' and row['audit'][-1]['action']=='vendors_imported'
    assert meta['master']['pos']==master['pos'] and row['vendor_id']==vendor['id']
    # Both new additions and updates obey the existing whole-master approval lock.
    store.atomic(owner,sid,lambda m,r:r[iid].update(accepted=True))
    before=store.snapshot(owner,sid)
    p=preview(c,sid,csv_file('Vendor name\nNew Vendor')).json();assert p['counts']['eligible']==0 and p['locked']
    assert confirm(c,sid,p).status_code==409 and store.snapshot(owner,sid)==before


def test_concurrent_confirmation_is_atomic(client):
    from cloud.main import confirm_vendors, VendorImportConfirm
    from cloud.auth import User
    c,store=client;sid=demo(c);owner=uid(c)
    p=preview(c,sid,csv_file('Vendor name\nOne new vendor')).json()
    actor=User(uid=owner,username='demo',demo=True)
    def run(_):return confirm_vendors(sid,VendorImportConfirm(token=p['token']),actor,store)
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,range(2)))
    assert results[0]==results[1] and results[0]['imported']==1
    assert sum(v['name']=='One new vendor' for v in store.snapshot(owner,sid)[0]['master']['vendors'])==1


def test_gstin_rename_retains_name_and_expired_preview(client,monkeypatch):
    from app.domain import name_norm
    c,store=client;sid=demo(c);owner=uid(c);old=store.snapshot(owner,sid)[0]['master']['vendors'][0]
    p=preview(c,sid,csv_file(f"Vendor name,GSTIN\nRenamed fictional vendor,{old['gstin']}"),True).json()
    assert p['rows'][0]['action']=='Update'
    assert name_norm(old['name']) in {name_norm(a) for a in p['rows'][0]['changes']['after']['aliases']}
    import itsdangerous.timed
    original=itsdangerous.timed.time.time
    monkeypatch.setattr(itsdangerous.timed.time,'time',lambda:original()+901)
    assert confirm(c,sid,p).status_code==400


def test_preview_lock_race_and_alias_target_conflict(client):
    c,store=client;sid=demo(c);owner=uid(c)
    iid=add_ready(store,owner,sid)
    p=preview(c,sid,csv_file('Vendor name\nAdditional vendor')).json()
    assert c.post(f'/api/sessions/{sid}/invoices/{iid}/approve',json={'expected_run':1}).status_code==200
    before=store.snapshot(owner,sid)
    assert confirm(c,sid,p).status_code==409 and store.snapshot(owner,sid)==before
    c2sid=c.post('/api/sessions',json={'name':'Alias matches'}).json()['id']
    old=store.snapshot(owner,c2sid)[0]['master']['vendors'][0]
    store.atomic(owner,c2sid,lambda m,r:m['master']['vendors'][0]['aliases'].extend(['Alias One','Alias Two']))
    p=preview(c,c2sid,csv_file('Vendor name\nAlias One\nAlias Two'),True).json()
    assert p['counts']['conflicts']==2


def test_import_rolls_back_on_check_failure(client,monkeypatch):
    from cloud import main
    c,store=client;sid=demo(c);owner=uid(c);add_ready(store,owner,sid)
    p=preview(c,sid,csv_file('Vendor name\nValid new vendor')).json()
    before=store.snapshot(owner,sid)
    def fail(*args):raise main.Conflict('Cannot save this invoice revision.')
    monkeypatch.setattr(main,'audit',fail)
    assert confirm(c,sid,p).status_code==409 and store.snapshot(owner,sid)==before

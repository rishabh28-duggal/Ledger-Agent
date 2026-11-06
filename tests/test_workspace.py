import io
from datetime import date
from openpyxl import load_workbook
from test_cloud import client, demo, uid, add_ready
from cloud.excel import filtered_rows, group_key


def test_all_folder_history_is_owned_and_summaries_only(client):
    c,store=client
    first=demo(c);owner=uid(c);one=add_ready(store,owner,first)
    second=c.post('/api/sessions',json={'name':'Second folder'}).json()['id']
    two=add_ready(store,owner,second,'OTHER-002')
    rows=c.get('/api/invoices').json()['invoices']
    assert {row['id'] for row in rows}=={one,two}
    assert {row['folder_id'] for row in rows}=={first,second}
    assert all('audit' not in row and 'original' not in row and 'lease_token' not in row for row in rows)
    assert [row['id'] for row in c.get('/api/invoices',params={'folder':first}).json()['invoices']]==[one]
    demo(c)
    assert c.get('/api/invoices').json()['invoices']==[]
    assert c.get('/api/invoices',params={'folder':first}).status_code==404
    assert c.get('/api/invoices/export.xlsx',params={'folder':first}).status_code==404


def test_excel_download_is_real_numeric_and_formula_safe(client):
    c,store=client;sid=demo(c);owner=uid(c);iid=add_ready(store,owner,sid)
    store.atomic(owner,sid,lambda m,rows:rows[iid].update(filename='=HYPERLINK("evil")'))
    response=c.get('/api/invoices/export.xlsx',params={'folder':sid,'group_by':'vendor'})
    assert response.status_code==200
    assert response.headers['content-type'].startswith('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    sheet=load_workbook(io.BytesIO(response.content),data_only=False).active
    headers={cell.value:cell.column for cell in sheet[1]}
    assert sheet.max_row==2 and sheet.freeze_panes=='A2'
    assert sheet.cell(2,headers['Amount']).value==141600
    cell=sheet.cell(2,headers['File']);assert cell.value=='=HYPERLINK("evil")' and cell.data_type=='s'
    assert sheet.cell(2,headers['Group']).value=='Acme Furniture Private Limited'
    empty=c.get('/api/invoices/export.xlsx',params={'outcome':'Approved'})
    assert load_workbook(io.BytesIO(empty.content)).active.max_row==1
    assert c.get('/api/invoices/export.xlsx',params={'dated':'bad'}).status_code==400
    assert c.get('/api/invoices/export.xlsx',params={'as_of':'not-date'}).status_code==400


def test_bulk_style_approvals_recheck_remaining_po_balance(client):
    c,store=client;sid=demo(c);owner=uid(c)
    a=add_ready(store,owner,sid,'BATCH-001',60)
    b=add_ready(store,owner,sid,'BATCH-002',50)
    assert c.post(f'/api/sessions/{sid}/invoices/{a}/approve',json={'expected_run':1}).status_code==200
    assert c.post(f'/api/sessions/{sid}/invoices/{b}/approve',json={'expected_run':1}).status_code==409
    rows=c.get('/api/invoices').json()['invoices'];assert sum(row['accepted'] for row in rows)==1
    assert not next(row for row in rows if row['id']==b)['accepted']


def test_export_filters_date_search_and_grouping():
    rows=[{'id':'a','execution':'completed','accepted':True,'folder_name':'Folder A','data':{'date':'2026-11-06','vendor':'Acme','invoice_no':'A1'},'filename':'one.pdf'},
          {'id':'b','execution':'completed','accepted':False,'result':{'status':'Blocked'},'data':{'date':'2026-10-01','vendor':'Beta'},'filename':'two.pdf'},
          {'id':'c','execution':'completed','accepted':False,'result':{'status':'Needs review'},'data':{},'filename':'missing.pdf'}]
    assert [r['id'] for r in filtered_rows(rows,dated='7',as_of=date(2026,11,6))]==['a']
    assert [r['id'] for r in filtered_rows(rows,outcome='Held')]==['b','c']
    assert [r['id'] for r in filtered_rows(rows,search='BETA')]==['b']
    assert group_key(rows[0],'month')=='2026-11'
    assert group_key(rows[0],'folder')=='Folder A'

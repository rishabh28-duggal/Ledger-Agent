import json
from pathlib import Path
from app.features import *
from app.main import resolve,approve
from app.domain import Invoice
from app.extract import extract
import asyncio

def submit_fixture(id):
    inv,_=asyncio.run(extract((s.ROOT/'samples/01_happy_60_chairs.pdf').read_bytes(),'local'))
    with s.connection() as db:
        db.execute('INSERT INTO invoices(id,filename,hash,mode,created,execution,data,original) VALUES(?,?,?,?,?,?,?,?)',(id,'sample.pdf','same-hash','local',s.now(),'completed',inv.model_dump_json(),inv.model_dump_json()))
        row=s.get(db,id);result=resolve(db,row)
        db.execute('UPDATE invoices SET result=?,po=?,vendor_id=? WHERE id=?',(s.dumps(result),result['po'],result['vendor_id'],id))
    return result

def test_archived_workspaces_survive_reopen_and_isolate_duplicate_balance(tmp_path,monkeypatch):
    monkeypatch.setenv('LEDGER_ARCHIVE_DIR',str(tmp_path))
    key='a'*32
    a=new_workspace(key,'First');b=new_workspace(key,'Second')
    with s.use_workspace(a):
        assert submit_fixture('first')['status']=='Ready for approval';approve('first')
        assert submit_fixture('duplicate')['status']=='Blocked'
    with s.use_workspace(b):assert submit_fixture('fresh')['status']=='Ready for approval'
    assert len(workspaces(key))==2
    with s.use_workspace(workspace_path(key,a.name)):
        with s.connection() as db:assert s.get(db,'first')['accepted']
    assert not workspaces('b'*32)

def test_original_score_not_corrected_and_fractional_tax_preserved():
    original={'tax_rate':.18,'total':118000}
    expected={'tax_rate':18,'total':118000}
    fields=evaluate_original(original,expected)
    assert [f['correct'] for f in fields]==[False,True]
    assert evaluate_original({'tax_rate':.5},{'tax_rate':.5})[0]['correct']

def test_lines_can_be_aggregated_but_price_errors_fail():
    gold={'lines':[{'item':'Chair','qty':80,'line_total':80000,'unit_price':1000},{'item':'Chair','qty':120,'line_total':120000,'unit_price':1000}]}
    actual={'lines':[{'item':'Chair','qty':200,'line_total':200000,'unit_price':1000}]}
    assert evaluate_original(actual,gold)[0]['correct']
    actual['lines'][0]['unit_price']=999
    assert not evaluate_original(actual,gold)[0]['correct']

def test_priority_fixes_and_accepted_only_export():
    result={'checks':[{'code':'vendor','level':'block','evidence':{}}]}
    assert priority(result)==('Critical',4)
    assert 'corrected invoice' in fix_for({'code':'quantity_0','level':'review'})
    rows=[{'id':'a','accepted':True,'po':'PO1','data':{'invoice_no':'=BAD','total':'20'}},{'id':'b','accepted':False,'data':{}}]
    csv=accepted_csv(rows)
    assert "'=BAD" in csv and '\nb,' not in csv

def test_batch_cooldown_and_limit():
    files=[('same.pdf',b'a'),('same.pdf',b'b'),('third.pdf',b'c')];calls=[]
    def submit(raw,name):calls.append(raw);return str(len(calls))
    rows={'1':{'execution':'completed','result':{'status':'Ready for approval'}},'2':{'execution':'failed','result':None}}
    result=run_batch(files,submit,rows.get,lambda id:id=='2')
    assert calls==[b'a',b'b']
    assert result['summary'][0]['Outcome']=='Ready for approval'
    assert result['summary'][2]['Outcome']=='Not submitted: provider cooldown'
    with __import__('pytest').raises(ValueError):run_batch(files*2,submit,rows.get,lambda _:False)

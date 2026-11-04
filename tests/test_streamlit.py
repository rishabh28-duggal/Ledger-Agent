from pathlib import Path
import asyncio
import pytest
from streamlit.testing.v1 import AppTest
from app import store as s
from app.main import process,approve
from app.domain import Invoice

ROOT=Path(__file__).resolve().parents[1]

def button(at,label):
    return next(b for b in at.button if b.label==label)

def has_status(at,status):
    return any(status in str(x.proto) for x in at.get('html'))

def queue_count(at,count):
    return any(f'{count} invoices received.' in x.value for x in at.caption) if count else any('Upload an invoice or run a demo document.'==x.value for x in at.info)

def test_workspace_context_isolation_and_restoration(tmp_path):
    default=s.db_path()
    for workspace in ['one','two']:
        with s.use_workspace(tmp_path/workspace):
            s.init()
            with s.connection() as db:
                assert not s.all_invoices(db)
                db.execute("INSERT INTO invoices(id,filename,hash,mode,created,execution) VALUES(?,?,?,?,?,?)",(workspace,'a.pdf',workspace,'local',s.now(),'failed'))
    for workspace in ['one','two']:
        with s.use_workspace(tmp_path/workspace):
            with s.connection() as db:
                assert [r['id'] for r in s.all_invoices(db)]==[workspace]
    assert s.db_path()==default

def test_streamlit_local_happy_and_split_flow():
    at=AppTest.from_file(str(ROOT/'streamlit_app.py'),default_timeout=20).run()
    assert not at.exception
    button(at,'Demo documents').click().run()
    assert not at.exception
    # Default local mode on a machine with no configured model keys.
    next(x for x in at.selectbox if x.label=='Document reader').select('local').run()
    next(x for x in at.selectbox if x.label=='Demo invoice').select(ROOT/'samples/01_happy_60_chairs.pdf').run()
    button(at,'Run sample review').click().run()
    assert not at.exception
    assert has_status(at,'Ready for approval')
    button(at,'Approve invoice').click().run()
    assert not at.exception
    assert any('Accepted by Demo reviewer' in x.value for x in at.success)
    button(at,'Demo documents').click().run()
    next(x for x in at.selectbox if x.label=='Demo invoice').select(ROOT/'samples/02_split_50_chairs.pdf').run()
    button(at,'Run sample review').click().run()
    assert not at.exception
    assert has_status(at,'Needs review')
    button(at,'Purchase orders').click().run()
    assert not at.exception
    assert any('141,600' in p.proto.text for p in at.get('progress'))
    # Separate visitor starts without this session's records or approvals.
    other=AppTest.from_file(str(ROOT/'streamlit_app.py'),default_timeout=20).run()
    assert not other.exception
    assert queue_count(other,0)

def test_streamlit_po_selection_and_correction():
    at=AppTest.from_file(str(ROOT/'streamlit_app.py'),default_timeout=20).run()
    button(at,'Demo documents').click().run()
    next(x for x in at.selectbox if x.label=='Document reader').select('local').run()
    next(x for x in at.selectbox if x.label=='Demo invoice').select(ROOT/'samples/06_ambiguous_po.pdf').run()
    button(at,'Run sample review').click().run()
    assert not at.exception
    assert has_status(at,'Needs review')
    button(at,'Select PO & rerun').click().run()
    assert not at.exception
    assert has_status(at,'Ready for approval')
    button(at,'Demo documents').click().run()
    next(x for x in at.selectbox if x.label=='Demo invoice').select(ROOT/'samples/07_arithmetic_error.pdf').run()
    button(at,'Run sample review').click().run()
    assert has_status(at,'Needs review')
    next(x for x in at.text_input if x.label=='Total').input('23600')
    button(at,'Save corrections & rerun').click().run()
    assert not at.exception
    assert has_status(at,'Ready for approval')

def test_streamlit_verify_correct_values_without_editing():
    at=AppTest.from_file(str(ROOT/'streamlit_app.py'),default_timeout=20).run()
    button(at,'Demo documents').click().run()
    next(x for x in at.selectbox if x.label=='Document reader').select('local').run()
    next(x for x in at.selectbox if x.label=='Demo invoice').select(ROOT/'samples/06_ambiguous_po.pdf').run()
    button(at,'Run sample review').click().run()
    button(at,'Select PO & rerun').click().run()
    id=at.session_state.selected_invoice
    with s.use_workspace(at.session_state.workspace):
        with s.connection() as db:
            record=s.get(db,id);data=record['data'];data['uncertain_fields']=['date','tax_basis','subtotal','tax']
            for field in data['uncertain_fields']:data['evidence'][field]={'page':1,'snippet':'Source excerpt','confidence':'medium'}
            db.execute('UPDATE invoices SET data=?,original=? WHERE id=?',(s.dumps(data),s.dumps(data),id))
        asyncio.run(process(id,True))
    at.run()
    assert has_status(at,'Needs review')
    next(x for x in at.multiselect if x.label=='Fields verified against source PDF').set_value(['date','tax_basis','subtotal','tax'])
    button(at,'Confirm selected fields & rerun').click().run()
    assert any('tick the confirmation' in x.value for x in at.warning)
    next(x for x in at.checkbox if x.label.startswith('I compared')).check()
    button(at,'Confirm selected fields & rerun').click().run()
    assert not at.exception
    assert has_status(at,'Ready for approval')
    with s.use_workspace(at.session_state.workspace):
        with s.connection() as db:
            record=s.get(db,id)
            assert record['data']['subtotal']==data['subtotal']
            assert not record['accepted']
            assert db.execute("SELECT COUNT(*) FROM reviews WHERE invoice_id=? AND action='verify_fields'",(id,)).fetchone()[0]==1

def test_saved_workspace_reopen_and_scorecard():
    at=AppTest.from_file(str(ROOT/'streamlit_app.py'),default_timeout=20).run()
    first_id=Path(at.session_state.workspace).name;history=at.session_state.history_key
    button(at,'Demo documents').click().run()
    next(x for x in at.selectbox if x.label=='Document reader').select('local').run()
    button(at,'Run sample review').click().run()
    button(at,'Extraction scorecard').click().run()
    button(at,'Score original extraction').click().run()
    assert not at.exception
    assert any(x.label=='Original extraction field accuracy' for x in at.metric)
    next(x for x in at.text_input if x.label=='New session name').input('Second session')
    button(at,'Start new session').click().run()
    assert not at.exception and queue_count(at,0)
    next(x for x in at.selectbox if x.label=='Saved review sessions').select(first_id).run()
    assert not at.exception and queue_count(at,1)
    reopened=AppTest.from_file(str(ROOT/'streamlit_app.py'),default_timeout=20)
    reopened.query_params['history']=history;reopened.run()
    next(x for x in reopened.selectbox if x.label=='Saved review sessions').select(first_id).run()
    assert not reopened.exception and queue_count(reopened,1)


def test_redesign_queue_search_navigation_and_confirmed_reset():
    at=AppTest.from_file(str(ROOT/'streamlit_app.py'),default_timeout=20).run()
    assert len(at.title)==1 and at.title[0].value=='Review queue'
    assert not at.metric
    assert not any(b.label=='View invoice' for b in at.button)
    button(at,'Demo documents').click().run()
    button(at,'Run sample review').click().run()
    assert has_status(at,'Ready for approval')
    assert any(e.label.startswith('Checks that passed (') for e in at.expander)
    button(at,'Review queue').click().run()
    next(x for x in at.text_input if x.label=='Search invoices').input('unmatched-search').run()
    assert any('No invoices match' in x.value for x in at.info)
    next(x for x in at.text_input if x.label=='Search invoices').input('PO-1042').run()
    assert not any('No invoices match' in x.value for x in at.info)
    assert button(at,'Reset demo session').disabled
    next(x for x in at.checkbox if x.label=='Delete invoices in this session').check().run()
    button(at,'Reset demo session').click().run()
    assert queue_count(at,0)

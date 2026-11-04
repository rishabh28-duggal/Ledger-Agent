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
    assert any(x.value=='Ready for approval' for x in at.success)
    button(at,'Approve invoice').click().run()
    assert not at.exception
    assert any('Accepted by Demo reviewer' in x.value for x in at.success)
    button(at,'Demo documents').click().run()
    next(x for x in at.selectbox if x.label=='Demo invoice').select(ROOT/'samples/02_split_50_chairs.pdf').run()
    button(at,'Run sample review').click().run()
    assert not at.exception
    assert any(x.value=='Needs review' for x in at.warning)
    button(at,'Purchase orders').click().run()
    assert not at.exception
    assert any('141,600' in p.proto.text for p in at.get('progress'))
    # Separate visitor starts without this session's records or approvals.
    other=AppTest.from_file(str(ROOT/'streamlit_app.py'),default_timeout=20).run()
    assert not other.exception
    assert other.metric[0].value=='0'

def test_streamlit_po_selection_and_correction():
    at=AppTest.from_file(str(ROOT/'streamlit_app.py'),default_timeout=20).run()
    button(at,'Demo documents').click().run()
    next(x for x in at.selectbox if x.label=='Document reader').select('local').run()
    next(x for x in at.selectbox if x.label=='Demo invoice').select(ROOT/'samples/06_ambiguous_po.pdf').run()
    button(at,'Run sample review').click().run()
    assert not at.exception
    assert any(x.value=='Needs review' for x in at.warning)
    button(at,'Select PO & rerun').click().run()
    assert not at.exception
    assert any(x.value=='Ready for approval' for x in at.success)
    button(at,'Demo documents').click().run()
    next(x for x in at.selectbox if x.label=='Demo invoice').select(ROOT/'samples/07_arithmetic_error.pdf').run()
    button(at,'Run sample review').click().run()
    assert any(x.value=='Needs review' for x in at.warning)
    next(x for x in at.text_input if x.label=='Total').input('23600')
    button(at,'Save corrections & rerun').click().run()
    assert not at.exception
    assert any(x.value=='Ready for approval' for x in at.success)

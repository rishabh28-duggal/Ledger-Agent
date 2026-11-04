import asyncio,json
import pytest
from fastapi.responses import JSONResponse
from app import store as s
from app.extract import extract
from app.main import process,approve
from app.review import prepare_verification,pending_verifications

FIELDS=['date','tax_basis','subtotal','tax']

@pytest.fixture
def workspace(tmp_path):
    with s.use_workspace(tmp_path):
        s.init();yield

def seed(name='01_happy_60_chairs.pdf',id='test',fields=None):
    raw=(s.ROOT/'samples'/name).read_bytes()
    inv,_=asyncio.run(extract(raw,'local'))
    inv.uncertain_fields=fields or FIELDS.copy()
    for field in inv.uncertain_fields:
        inv.evidence[field]={'page':1,'snippet':'Source excerpt','confidence':'medium'}
    with s.connection() as db:
        db.execute('INSERT INTO invoices(id,filename,hash,mode,created,execution,data,original) VALUES(?,?,?,?,?,?,?,?)',(id,name,id,'local',s.now(),'queued',inv.model_dump_json(),inv.model_dump_json()))
    (s.data_dir()/(id+'.pdf')).write_bytes(raw)
    asyncio.run(process(id,True))
    return id

def row(id):
    with s.connection() as db:return s.get(db,id)

def verify(id,fields):
    prepare_verification(id,fields,expected_run=row(id)['run']);asyncio.run(process(id,True))

def test_verify_unchanged_fields_preserves_evidence_and_audit(workspace):
    id=seed();before=row(id)
    assert before['result']['status']=='Needs review'
    verify(id,['date'])
    partial=row(id)
    assert partial['result']['status']=='Needs review'
    assert partial['data']['uncertain_fields']==['tax_basis','subtotal','tax']
    verify(id,['tax_basis','subtotal','tax'])
    after=row(id)
    assert after['result']['status']=='Ready for approval'
    assert not after['accepted'] and after['allocations']==[]
    assert after['data']['date']==before['data']['date']
    assert after['data']['subtotal']==before['data']['subtotal']
    assert after['data']['evidence']['date']['confidence']=='medium'
    assert after['data']['evidence']['date']['reviewer_verification']['reviewer']=='Demo reviewer'
    assert after['original']==before['original']
    with s.connection() as db:
        events=[json.loads(r[0]) for r in db.execute("SELECT details FROM reviews WHERE invoice_id=? AND action='verify_fields' ORDER BY seq",(id,))]
    assert events[0]['fields']==['date']
    assert events[0]['before']['date']==events[0]['after']['date']

def test_verification_does_not_override_arithmetic(workspace):
    id=seed('07_arithmetic_error.pdf')
    verify(id,FIELDS)
    result=row(id)['result']
    assert result['status']=='Needs review'
    assert any(c['code']=='total' and c['level']=='review' for c in result['checks'])
    assert isinstance(approve(id),JSONResponse)

def test_verification_does_not_override_po_balance(workspace):
    first=seed(id='first');verify(first,FIELDS);approve(first)
    second=seed('02_split_50_chairs.pdf',id='second');verify(second,FIELDS)
    result=row(second)['result']
    assert result['status']=='Needs review'
    assert next(c for c in result['checks'] if c['code']=='quantity_0')['evidence']['remaining']=='40'
    assert isinstance(approve(second),JSONResponse)

def test_invalid_missing_stale_and_accepted_verifications_rejected(workspace):
    id=seed()
    for fields,run in [([],1),(['total'],1),(['date'],99),(['made_up_field'],1)]:
        with pytest.raises(ValueError):prepare_verification(id,fields,run)
    assert row(id)['run']==1
    verify(id,FIELDS);approve(id)
    with pytest.raises(ValueError,match='read-only'):prepare_verification(id,['date'],row(id)['run'])
    missing=seed('05_missing_information.pdf',id='missing',fields=['invoice_no','total'])
    assert pending_verifications(row(missing)['data'])==[]
    with pytest.raises(ValueError,match='Correct missing'):prepare_verification(missing,['total'],row(missing)['run'])

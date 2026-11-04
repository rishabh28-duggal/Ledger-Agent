import asyncio,json,re
from unittest.mock import AsyncMock
import httpx,pytest
from app import store as s
from app.domain import Invoice,evaluate
from app.extract import provider_retry_delay,ProviderRetryLater,extract
from app.main import process
from test_groq import FakeClient,good


def test_printed_gstin_and_reference_stay_separate():
    from pypdf import PdfReader
    master=json.loads((s.ROOT/'samples/master.json').read_text())
    for vendor in master['vendors']:
        assert re.fullmatch(r'\d{2}[A-Z]{5}\d{4}[A-Z][A-Z0-9]Z[A-Z0-9]',vendor['gstin'])
        assert vendor['vendor_reference'].startswith('DEMO-')
    pack=json.loads((s.ROOT/'test_pack/answer_key.json').read_text())
    for case in pack['cases']:
        text=''.join(p.extract_text() or '' for p in PdfReader(s.ROOT/'test_pack'/case['file']).pages)
        if text:
            assert 'GSTIN:' in text
            assert case['expected_extraction']['gstin'] in text
            assert case['expected_extraction']['vendor_reference'] in text


def test_missing_total_defers_reconciliation_and_balance():
    pack=json.loads((s.ROOT/'test_pack/answer_key.json').read_text())
    inv=Invoice.model_validate(pack['cases'][5]['expected_extraction'])
    master=json.loads((s.ROOT/'samples/master.json').read_text())
    result=evaluate(inv,master['vendors'],master['pos'],[],'current','current')
    assert result['status']=='Needs review'
    for code in ['balance','total']:
        check=next(c for c in result['checks'] if c['code']==code)
        assert check['level']=='not_evaluated'
        assert 'Not evaluated' in check['message']
    assert next(c for c in result['checks'] if c['code']=='quantity_0')['level']=='pass'
    assert 'Not evaluated' in result['summary']


def test_reset_reloads_updated_fixture_masters(tmp_path):
    with s.use_workspace(tmp_path):
        s.init()
        with s.connection() as db:
            old=s.records(db,'vendors')[0];old['gstin']='DEMO-OLD'
            db.execute("UPDATE records SET payload=? WHERE kind='vendors' AND id=?",(s.dumps(old),old['id']))
        s.reset_demo_records()
        with s.connection() as db:
            assert all(not v['gstin'].startswith('DEMO-') for v in s.records(db,'vendors'))


@pytest.mark.parametrize('headers,expected',[
    ({'retry-after':'12'},12),
    ({'x-ratelimit-reset-tokens':'1m2.5s'},62.5),
    ({'x-ratelimit-remaining-requests':'0','x-ratelimit-reset-requests':'2h'},7200),
    ({},60),
])
def test_rate_limit_headers(headers,expected):
    assert provider_retry_delay(httpx.Response(429,headers=headers))==expected


def test_waits_for_retry_after_and_reports_progress(monkeypatch):
    monkeypatch.setenv('GROQ_API_KEY','test-key')
    monkeypatch.setattr(httpx,'AsyncClient',FakeClient)
    FakeClient.calls=0;FakeClient.replies=[httpx.Response(429,headers={'retry-after':'12'},json={}),good()]
    sleep=AsyncMock();monkeypatch.setattr(asyncio,'sleep',sleep)
    progress=[]
    asyncio.run(extract((s.ROOT/'samples/01_happy_60_chairs.pdf').read_bytes(),'groq',on_progress=lambda m,n:progress.append((m,n))))
    assert FakeClient.calls==2
    assert [args.args[0] for args in sleep.await_args_list]==[5,5,2]
    assert [p[1] for p in progress]==[12,7,2]


def test_long_wait_does_not_retry_early(monkeypatch):
    monkeypatch.setenv('GROQ_API_KEY','test-key')
    monkeypatch.setattr(httpx,'AsyncClient',FakeClient)
    FakeClient.calls=0;FakeClient.replies=[httpx.Response(429,headers={'retry-after':'200'},json={})]
    with pytest.raises(ProviderRetryLater) as error:
        asyncio.run(extract((s.ROOT/'samples/01_happy_60_chairs.pdf').read_bytes(),'groq'))
    assert error.value.retry_after==200
    assert FakeClient.calls==1


def test_cooldown_persisted_after_provider_failure(tmp_path,monkeypatch):
    import app.main as main
    async def limited(*args,**kwargs):raise ProviderRetryLater('Groq rate limited',60)
    monkeypatch.setattr(main,'extract',limited)
    with s.use_workspace(tmp_path):
        s.init();id='limited'
        (s.data_dir()/(id+'.pdf')).write_bytes((s.ROOT/'samples/01_happy_60_chairs.pdf').read_bytes())
        with s.connection() as db:
            db.execute('INSERT INTO invoices(id,filename,hash,mode,created,execution) VALUES(?,?,?,?,?,?)',(id,'x.pdf','x','groq',s.now(),'queued'))
        asyncio.run(process(id))
        assert 0<s.retry_remaining(id)<=60
        with s.connection() as db:
            row=s.get(db,id)
            assert row['execution']=='failed' and row['result'] is None and not row['accepted']

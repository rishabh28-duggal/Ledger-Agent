import asyncio,json,io
import httpx,pytest
from pypdf import PdfWriter
from app.extract import extract,render_groq_pages
from app.store import ROOT

class FakeClient:
    captured=None
    replies=[]
    calls=0
    def __init__(self,**kwargs):pass
    async def __aenter__(self):return self
    async def __aexit__(self,*args):pass
    async def post(self,url,**kwargs):
        FakeClient.captured={'url':url,**kwargs};FakeClient.calls+=1
        return FakeClient.replies.pop(0)

def run(monkeypatch,replies):
    monkeypatch.setenv('GROQ_API_KEY','gsk-test-secret')
    monkeypatch.setattr(httpx,'AsyncClient',FakeClient)
    FakeClient.replies=list(replies);FakeClient.calls=0
    return asyncio.run(extract((ROOT/'samples/09_scan_requires_gemini.pdf').read_bytes(),'groq'))

def good():
    payload={'vendor':'Acme Furniture','total':23600,'evidence':{'total':{'page':1,'snippet':'23600','confidence':'low'}}}
    return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(payload)}}]})

def test_real_scan_rendered_and_submitted(monkeypatch):
    inv,source=run(monkeypatch,[good()])
    assert source.startswith('Groq vision extraction')
    assert 'total' in inv.uncertain_fields and 'vendor' in inv.uncertain_fields
    request=FakeClient.captured
    assert request['url']=='https://api.groq.com/openai/v1/chat/completions'
    parts=request['json']['messages'][0]['content']
    images=[p for p in parts if p['type']=='image_url']
    assert len(images)==1 and images[0]['image_url']['url'].startswith('data:image/jpeg;base64,/9j/')
    assert request['json']['response_format']=={'type':'json_object'}

def test_retries_transient_error(monkeypatch):
    inv,source=run(monkeypatch,[httpx.Response(503,json={}),good()])
    assert FakeClient.calls==2

@pytest.mark.parametrize('status',[400,401,403,404])
def test_errors_clear_and_redacted(monkeypatch,status):
    with pytest.raises(ValueError) as error:
        run(monkeypatch,[httpx.Response(status,json={'error':{'message':'bad gsk-test-secret'}})])
    assert 'gsk-test-secret' not in str(error.value)
    assert '[redacted]' in str(error.value) and str(status) in str(error.value)
    assert FakeClient.calls==1

@pytest.mark.parametrize('choice',[{'finish_reason':'length','message':{'content':'{}'}},{'finish_reason':'stop','message':{'content':'NOT JSON'}}])
def test_invalid_response_no_fake_success(monkeypatch,choice):
    with pytest.raises(ValueError):run(monkeypatch,[httpx.Response(200,json={'choices':[choice]})])

def test_page_limit_never_silently_truncates():
    writer=PdfWriter()
    for _ in range(4):writer.add_blank_page(width=595,height=842)
    raw=io.BytesIO();writer.write(raw)
    with pytest.raises(ValueError,match='No pages were submitted'):render_groq_pages(raw.getvalue())

def test_all_three_pages_are_rendered():
    writer=PdfWriter()
    for _ in range(3):writer.add_blank_page(width=595,height=842)
    raw=io.BytesIO();writer.write(raw)
    assert len(render_groq_pages(raw.getvalue()))==3

def test_groq_key_required(monkeypatch):
    monkeypatch.delenv('GROQ_API_KEY',raising=False)
    with pytest.raises(ValueError,match='GROQ_API_KEY'):
        asyncio.run(extract((ROOT/'samples/01_happy_60_chairs.pdf').read_bytes(),'groq'))


def test_schema_error_names_field_without_exposing_value():
    from app.extract import parse_groq_invoice
    with pytest.raises(ValueError) as error:
        parse_groq_invoice('{"total":"PRIVATE_BAD_VALUE"}')
    assert 'total' in str(error.value) and 'decimal_parsing' in str(error.value)
    assert 'PRIVATE_BAD_VALUE' not in str(error.value)

def test_fence_and_unambiguous_wrapper():
    from app.extract import parse_groq_invoice
    inv=parse_groq_invoice('```json\n{"invoice":{"total":123}}\n```')
    assert inv.total==123

def test_truncated_output_not_salvaged():
    from app.extract import parse_groq_invoice
    with pytest.raises(ValueError,match='not valid JSON'):
        parse_groq_invoice('{"total":123')

import asyncio, json
import httpx
import pytest
from app.extract import extract,gemini_schema
from app.store import ROOT

class FakeClient:
    response=None
    captured=None
    def __init__(self,**kwargs):pass
    async def __aenter__(self):return self
    async def __aexit__(self,*args):pass
    async def post(self,url,**kwargs):
        FakeClient.captured={'url':url,**kwargs}
        return FakeClient.response

def run(monkeypatch,response):
    monkeypatch.setenv('GEMINI_API_KEY','fake-test-key')
    monkeypatch.setattr(httpx,'AsyncClient',FakeClient)
    FakeClient.response=response
    return asyncio.run(extract((ROOT/'samples/09_scan_requires_gemini.pdf').read_bytes(),'gemini'))

def test_scan_sent_as_pdf_and_low_confidence_review(monkeypatch):
    payload={'vendor':'Acme Furniture','invoice_no':None,'date':'2026-11-03','currency':'INR','total':23600,'evidence':{'vendor':{'page':1,'snippet':'Acme Furniture','confidence':'high'},'total':{'page':1,'snippet':'23600','confidence':'low'}}}
    response=httpx.Response(200,json={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps(payload)}]}}]})
    inv,source=run(monkeypatch,response)
    assert source=='Gemini PDF extraction'
    assert 'total' in inv.uncertain_fields and 'date' in inv.uncertain_fields
    request=FakeClient.captured
    assert 'fake-test-key' not in request['url']
    assert request['headers']['x-goog-api-key']=='fake-test-key'
    assert request['json']['contents'][0]['parts'][0]['inlineData']['mimeType']=='application/pdf'
    assert request['json']['generationConfig']['responseJsonSchema']==gemini_schema()

@pytest.mark.parametrize('code',[400,403,404,429,503])
def test_errors_do_not_leak_keys(monkeypatch,code):
    with pytest.raises(ValueError) as error:run(monkeypatch,httpx.Response(code,json={'error':{'message':'fake-test-key'}}))
    assert 'fake-test-key' not in str(error.value)
    assert str(code) in str(error.value)

@pytest.mark.parametrize('candidate',[{'finishReason':'MAX_TOKENS','content':{'parts':[{'text':'{}'}]}},{'finishReason':'STOP','content':{'parts':[{'text':'not JSON'}]}},{}])
def test_invalid_output_fails_instead_of_guessing(monkeypatch,candidate):
    with pytest.raises(ValueError):run(monkeypatch,httpx.Response(200,json={'candidates':[candidate]}))

def test_key_required(monkeypatch):
    monkeypatch.delenv('GEMINI_API_KEY',raising=False)
    with pytest.raises(ValueError,match='GEMINI_API_KEY'):
        asyncio.run(extract((ROOT/'samples/01_happy_60_chairs.pdf').read_bytes(),'gemini'))

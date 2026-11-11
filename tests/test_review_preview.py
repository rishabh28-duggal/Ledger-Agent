"""Authenticated selected-page rendering, dimensions and isolation."""
import io
import pytest
from PIL import Image
from test_cloud import client, demo, uid, add_ready
from cloud.repository import ROOT

@pytest.mark.parametrize('name,pages', [('R01_acme_modern_happy.pdf',1),('R04_orbit_two_page_invoice.pdf',2)])
def test_pdf_preview(client,name,pages):
    c,store=client;sid=demo(c);owner=uid(c);iid=add_ready(store,owner,sid)
    store.put_file(owner,sid,iid,(ROOT/'test_pack/invoices'/name).read_bytes(),'application/pdf')
    url=f'/api/sessions/{sid}/invoices/{iid}/preview-page'
    for page in range(1,pages+1):
        r=c.get(url,params={'page':page,'width':700,'height':1000})
        assert r.status_code==200,r.text
        assert int(r.headers['X-Page-Count'])==pages
        assert 'no-store' in r.headers['Cache-Control']
        with Image.open(io.BytesIO(r.content)) as image:
            assert image.width<=700 and image.height<=1000
            ratio=float(r.headers['X-Page-Width'])/float(r.headers['X-Page-Height'])
            assert abs(image.width/image.height-ratio)<.01
    assert c.get(url,params={'page':pages+1}).status_code==404
    assert c.get(url,params={'width':99999}).status_code==422
    c.cookies.clear();demo(c)
    assert c.get(url).status_code==404

@pytest.mark.parametrize('size',[(1200,500),(500,1200)])
def test_image_preview(client,size):
    c,store=client;sid=demo(c);owner=uid(c);iid=add_ready(store,owner,sid)
    out=io.BytesIO();Image.new('RGB',size,'white').save(out,'PNG')
    store.put_file(owner,sid,iid,out.getvalue(),'image/png')
    r=c.get(f'/api/sessions/{sid}/invoices/{iid}/preview-page?width=600&height=600')
    assert r.status_code==200
    with Image.open(io.BytesIO(r.content)) as image:
        assert max(image.size)==600
        assert abs(image.width/image.height-size[0]/size[1])<.01

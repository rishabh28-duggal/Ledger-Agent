import json
from pathlib import Path
from app.domain import Invoice,evaluate
from pypdf import PdfReader

ROOT=Path(__file__).resolve().parents[1]

def test_pack_arithmetic_pages_and_expected_decisions():
    pack=json.loads((ROOT/'test_pack/answer_key.json').read_text())
    master=json.loads((ROOT/'samples/master.json').read_text())
    first=pack['cases'][0]['expected_extraction']
    accepted={'id':'r01','hash':'first-hash','data':first,'accepted':True,'vendor_id':'acme','po':'PO-1042','allocations':[{'po_line':'PO-1042-1','qty':'60'}]}
    for index,case in enumerate(pack['cases']):
        pdf=PdfReader(ROOT/'test_pack'/case['file'])
        assert len(pdf.pages)==case['pages']<=3
        if index==6:assert not ''.join(p.extract_text() for p in pdf.pages).strip()
        history=[accepted] if index in [1,2] else []
        result=evaluate(Invoice.model_validate(case['expected_extraction']),master['vendors'],master['pos'],history,'current','different-hash',today=__import__('datetime').date(2026,11,4))
        assert result['status']==case['expected_recommendation'],(case['file'],result)
        if index==1:
            quantity=next(c for c in result['checks'] if c['code']=='quantity_0')
            assert quantity['evidence']['remaining']=='40'
        if index==4:
            assert set(result['candidates'])=={'PO-3001','PO-3002'}

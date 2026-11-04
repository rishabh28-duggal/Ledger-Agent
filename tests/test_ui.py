"""Presentation-only regression tests, including escaping and urgency."""
from ui.components import money, pill, queue_rank, problem_message

def row(status='Needs review',code='date',variance=0,accepted=False):
    return {'accepted':accepted,'result':{'status':status,'checks':[{'code':code,'level':'review','evidence':{'variance_percent':variance}}]}}

def test_money_missing_values_and_consistent_decimals():
    assert money(None)=='Not available'
    assert money('236000')=='₹236,000.00'
    assert money('0')=='₹0.00'

def test_status_has_text_symbol_and_escapes_untrusted_values():
    assert '✓' in pill('Ready for approval')
    assert 'Ready for approval' in pill('Ready for approval')
    assert '<script>' not in pill('<script>')

def test_queue_exception_order_is_presentation_only():
    rows=[row('Blocked'),row(code='possible_duplicate'),row(code='price_0',variance=6),row(code='missing_total'),row(code='balance'),row('Ready for approval'),row(accepted=True)]
    assert [queue_rank(r) for r in rows]==sorted(queue_rank(r) for r in rows)

def test_failed_comparisons_have_plain_problem_descriptions():
    assert 'does not reconcile' in problem_message({'code':'tax_math','level':'review','message':'Stated tax rate reconciled with tax amount.'})
    assert 'Invoice number is missing' in problem_message({'code':'missing_invoice_no','level':'review','message':''})

"""Pure invoice checks. No model participates in the decision."""
from decimal import Decimal, InvalidOperation
from datetime import date, timedelta
import re
from difflib import SequenceMatcher
from pydantic import BaseModel, ConfigDict, Field

class Line(BaseModel):
    model_config = ConfigDict(extra='forbid')
    item: str
    qty: Decimal | None = None
    unit_price: Decimal | None = None
    line_total: Decimal | None = None
    unit: str = 'each'

class Invoice(BaseModel):
    model_config = ConfigDict(extra='forbid')
    vendor: str | None = None
    gstin: str | None = None
    vendor_reference: str | None = None
    invoice_no: str | None = None
    date: str | None = None
    po_ref: str | None = None
    currency: str | None = None
    subtotal: Decimal | None = None
    tax: Decimal | None = None
    tax_rate: Decimal | None = None
    total: Decimal | None = None
    tax_basis: str | None = None
    lines: list[Line] = Field(default_factory=list)
    evidence: dict = Field(default_factory=dict)
    uncertain_fields: list[str] = Field(default_factory=list)

def norm(x): return re.sub(r'[^a-z0-9]', '', (x or '').lower())
def name_norm(x):
    return norm((x or '').lower().replace('private','pvt').replace('limited','ltd'))
def dec(x): return Decimal(str(x))
def serial(x):
    import json
    return json.loads(__import__('json').dumps(x, default=str))

def evaluate(inv: Invoice, vendors, pos, history, current_id, file_hash, selected_po=None, today=None):
    today = today or date.today()
    checks=[]
    def add(code, level, message, **evidence):
        checks.append(dict(code=code, level=level, message=message, evidence=serial(evidence)))
    for f in ['vendor','invoice_no','date','currency','total']:
        if getattr(inv,f) is None or getattr(inv,f)=='': add('missing_'+f,'review',f'Required field missing: {f}.',field=f)
    for f in inv.uncertain_fields:
        add('uncertain_'+f,'review',f'Confirm {f} against the PDF.', field=f,source=inv.evidence.get(f))
    if inv.currency and inv.currency!='INR': add('currency','review','Only INR is supported.',observed=inv.currency)
    try:
        d=date.fromisoformat(inv.date) if inv.date else None
        if d and (d>today or d<today-timedelta(days=365)): add('date','review','Invoice date is outside the 365-day policy window.',observed=inv.date)
        elif d: add('date','pass','Invoice date is within policy.')
    except ValueError: add('date','review','Invoice date must be YYYY-MM-DD.')
    identifier = [v for v in vendors if inv.gstin and norm(v['gstin'])==norm(inv.gstin)]
    names=[v for v in vendors if name_norm(inv.vendor) in [name_norm(v['name'])]+[name_norm(a) for a in v['aliases']]] if inv.vendor else []
    matches=identifier or names
    vendor=matches[0] if len(matches)==1 else None
    if vendor:
        if inv.gstin and norm(inv.gstin)!=norm(vendor['gstin']): add('gstin','review','GSTIN conflicts with the vendor master.',expected=vendor['gstin'],observed=inv.gstin)
        if identifier and inv.vendor and vendor not in names: add('vendor_name','review','GSTIN matches but vendor name is not a recognised alias.')
        add('vendor','block' if vendor['status']=='blocked' else 'pass', 'Vendor is explicitly blocked.' if vendor['status']=='blocked' else 'Approved vendor identified.',vendor=vendor['name'])
    else:
        candidates=[v['name'] for v in vendors if SequenceMatcher(None,name_norm(inv.vendor),name_norm(v['name'])).ratio()>.5]
        add('vendor','review','Vendor identity is unknown or ambiguous.',candidates=candidates)
    prior=[h for h in history if h['id']!=current_id and h.get('data')]
    for h in prior:
        old=h['data']
        if h['hash']==file_hash:
            add('duplicate_file','block','Identical PDF already exists.',original_id=h['id']); break
        if vendor and h.get('vendor_id')==vendor['id'] and inv.invoice_no and norm(inv.invoice_no)==norm(old.get('invoice_no')):
            same=inv.total is not None and old.get('total') is not None and inv.total==dec(old['total'])
            add('duplicate_identity','block' if same else 'review','Invoice already processed.' if same else 'Conflicting version: same invoice number, different amount.',original_id=h['id']); break
        if vendor and h.get('vendor_id')==vendor['id'] and inv.total is not None and old.get('total'):
            try:
                close=abs(inv.total-dec(old['total']))/max(abs(dec(old['total'])),Decimal('1'))<=Decimal('.005')
                days=abs((date.fromisoformat(inv.date)-date.fromisoformat(old['date'])).days)
                items={norm(l.item) for l in inv.lines}; olditems={norm(l['item']) for l in old.get('lines',[])}
                if close and days<=30 and items and len(items&olditems)/len(items|olditems)>=.5:
                    add('possible_duplicate','review','Possible duplicate: similar vendor, amount, date and items.',original_id=h['id'])
            except (ValueError,TypeError): pass
    po=None; candidates=[]
    if vendor:
        eligible=[p for p in pos if p['vendor_id']==vendor['id'] and p['status']=='open']
        ref=selected_po or inv.po_ref
        if ref:
            po=next((p for p in pos if p['number']==ref),None)
            if not po or po['vendor_id']!=vendor['id'] or po['status']!='open':
                add('po','review','Selected/referenced PO is missing, closed or belongs to another vendor.',reference=ref);po=None
        else:
            for p in eligible:
                nameset=[norm(a) for l in p['lines'] for a in [l['item'],*l.get('aliases',[])]]
                if inv.lines and all(norm(l.item) in nameset for l in inv.lines): candidates.append(p['number'])
            if len(candidates)==1: po=next(p for p in eligible if p['number']==candidates[0])
            else: add('po_ambiguous','review','Select a PO; automatic matching is not unambiguous.',candidates=candidates)
    if not po: add('po_checks','not_evaluated','PO-dependent checks cannot run until a valid PO is established.')
    else: add('po','pass','PO linked with matching vendor ownership.',po=po['number'],method='reviewer selection' if selected_po else 'explicit reference' if inv.po_ref else 'unique item-compatible PO')
    if not inv.lines: add('lines','review','No line items available to validate.')
    for i,l in enumerate(inv.lines):
        if any(x is None for x in [l.qty,l.unit_price,l.line_total]) or (l.qty is not None and l.qty<=0) or (l.unit_price is not None and l.unit_price<0):
            add('line_'+str(i),'review','Line quantity, price or total is missing or invalid.',line=i+1)
        else: add('line_math_'+str(i),'pass' if abs(l.qty*l.unit_price-l.line_total)<=1 else 'review','Line arithmetic checked.',line=i+1,expected=l.qty*l.unit_price,observed=l.line_total)
    if inv.lines and all(l.line_total is not None for l in inv.lines) and inv.subtotal is not None:
        summed=sum(l.line_total for l in inv.lines)
        add('subtotal','pass' if abs(summed-inv.subtotal)<=1 else 'review','Line amounts compared with subtotal.',expected=summed,observed=inv.subtotal)
    else: add('subtotal','not_evaluated','Not evaluated: subtotal reconciliation requires a subtotal and complete line amounts.')
    if all(x is not None for x in [inv.subtotal,inv.tax,inv.total]):
        add('total','pass' if abs(inv.subtotal+inv.tax-inv.total)<=1 and inv.total>0 and inv.tax>=0 else 'review','Subtotal plus tax compared with total.',expected=inv.subtotal+inv.tax,observed=inv.total)
        if inv.tax_rate is not None and inv.tax_basis=='exclusive': add('tax_math','pass' if abs(inv.subtotal*inv.tax_rate/100-inv.tax)<=1 else 'review','Stated tax rate reconciled with tax amount.',expected=inv.subtotal*inv.tax_rate/100,observed=inv.tax)
    else:
        missing=[f for f in ['subtotal','tax','total'] if getattr(inv,f) is None]
        add('total','not_evaluated','Not evaluated: total reconciliation requires missing '+', '.join(missing)+'.',missing=missing)
    mappings=[]
    if po:
        if inv.currency!=po['currency']: add('po_currency','review','Invoice and PO currencies differ.')
        accepted=[h for h in prior if h.get('accepted') and h.get('po')==po['number']]
        used=sum((dec(h['data']['total']) for h in accepted),Decimal(0)); available=dec(po['total'])-used
        if inv.total is None:
            add('balance','not_evaluated','Not evaluated: invoice total is missing, so PO-value comparison cannot run.',remaining=available,invoice=None,accepted=used)
        else:
            add('balance','pass' if inv.total<=available+Decimal('1') else 'review','Invoice compared with remaining authorised PO value.',remaining=available,invoice=inv.total,accepted=used)
        for i,l in enumerate(inv.lines):
            hits=[p for p in po['lines'] if norm(l.item) in [norm(p['item']),*[norm(a) for a in p.get('aliases',[])]]]
            if len(hits)!=1: add('mapping_'+str(i),'review','Line does not map unambiguously to a PO line.',item=l.item);continue
            p=hits[0]; mappings.append({'index':i,'po_line':p['id']})
            if l.unit!=p['unit']: add('unit_'+str(i),'review','Units differ; conversion is not supported.')
            usedqty=sum((dec(m['qty']) for h in accepted for m in h.get('allocations',[]) if m['po_line']==p['id']),Decimal(0))
            # Aggregate all current lines mapped to the same PO line.
            currentqty=sum((k.qty or 0 for k in inv.lines if norm(k.item) in [norm(p['item']),*[norm(a) for a in p.get('aliases',[])]]),Decimal(0))
            remaining=dec(p['qty'])-usedqty
            add('quantity_'+str(i),'pass' if l.qty is not None and currentqty<=remaining else 'review',f'Bills {currentqty}; {remaining} remain on {po["number"]}.',ordered=p['qty'],accepted=usedqty,remaining=remaining,billed=currentqty)
            price=l.unit_price
            if inv.tax_basis not in ['inclusive','exclusive'] or inv.tax_rate is None:
                add('price_'+str(i),'review','Tax basis/rate must be established before price comparison.');continue
            if price is None: continue
            actual=price/(1+inv.tax_rate/100) if inv.tax_basis=='inclusive' else price
            expected=dec(p['price'])/(1+dec(p['tax_rate'])/100) if p['tax_basis']=='inclusive' else dec(p['price'])
            variance=abs(actual-expected)/expected if expected else Decimal(1)
            add('price_'+str(i),'pass' if variance<=Decimal('.02') else 'review','Unit-price comparison: '+('within policy.' if variance<=Decimal('.02') else 'high-severity dispute.' if variance>Decimal('.05') else 'minor variance.'),expected=expected,observed=actual,variance_percent=variance*100)
    status='Blocked' if any(c['level']=='block' for c in checks) else 'Needs review' if any(c['level'] in ['review','not_evaluated'] for c in checks) else 'Ready for approval'
    issues=[c['message'] for c in checks if c['level'] in ['review','block','not_evaluated']]
    email=('Subject: Clarification required — invoice '+(inv.invoice_no or '(number missing)')+'\n\nHello,\nPlease help resolve the following before we can complete invoice review:\n'+ '\n'.join('- '+x for x in issues)+'\n\nThank you,\nAccounts Payable') if issues else None
    return serial(dict(status=status,checks=checks,vendor_id=vendor['id'] if vendor else None,po=po['number'] if po else None,candidates=candidates,mappings=mappings,summary=' '.join(issues) if issues else 'All required checks passed. Awaiting reviewer approval.',email=email))

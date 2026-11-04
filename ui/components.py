"""Escaped, presentation-only renderers; invoice checks remain authoritative."""
from html import escape
from datetime import datetime
from decimal import Decimal, InvalidOperation
import streamlit as st

STATUS = {'Ready for approval':('ready','✓'),'Needs review':('review','!'),
          'Blocked':('blocked','×'),'Accepted':('ready','✓'),
          'Processing failed':('blocked','×')}
STAGES = {'ingest':'Receive document','extract':'Read invoice','completeness':'Check required fields',
          'vendor':'Identify vendor','po':'Match purchase order','checks':'Check rules and balances','decision':'Record recommendation'}

def money(value):
    if value is None or value=='':return 'Not available'
    try:return f'₹{Decimal(str(value)):,.2f}'
    except InvalidOperation:return 'Not available'

def pill(status):
    style,icon=STATUS.get(status,('neutral','○'))
    return f'<span class="ledger-pill {style}"><span aria-hidden="true">{icon}</span>{escape(status)}</span>'

def timestamp(value):
    try:
        from zoneinfo import ZoneInfo
        return datetime.fromisoformat(value).astimezone(ZoneInfo('Asia/Kolkata')).strftime('%d %b %Y, %H:%M IST')
    except (ValueError,TypeError):return str(value or 'Time not recorded')

def friendly(field):
    return {'gstin':'GSTIN','po_ref':'PO reference','invoice_no':'Invoice number','tax_basis':'Tax basis','tax_rate':'Tax rate (%)'}.get(field,field.replace('_',' ').capitalize())

def show_finding(check):
    evidence=check.get('evidence') or {}
    expected=evidence.get('expected',evidence.get('remaining'))
    observed=evidence.get('observed',evidence.get('billed',evidence.get('invoice')))
    def display(value):
        if value is None:return 'Not available'
        if isinstance(value,(dict,list)):return 'See source evidence below'
        return str(value)
    compare=''
    if expected is not None or observed is not None:
        compare=f'<div class="compare"><div><span>Expected or available</span><b>{escape(display(expected))}</b></div><div><span>Found on invoice</span><b>{escape(display(observed))}</b></div></div>'
    st.html(f'<div class="finding"><strong>{escape(problem_message(check))}</strong>{compare}<p>Next step: {escape(check.get("fix", "Compare with the source PDF and resolve this finding."))}</p></div>')
    source=evidence.get('source')
    if isinstance(source,dict) and source.get('snippet'):st.caption(f'Page {source.get("page") or "unknown"}: {source["snippet"]}')

def fields_table(data):
    uncertain=set(data.get('uncertain_fields',[]));rows=[]
    for field,value in data.items():
        if field in ['lines','evidence','uncertain_fields']:continue
        ev=data.get('evidence',{}).get(field) or {}
        if not isinstance(ev,dict):ev={}
        flag=field in uncertain
        confidence=str(ev.get('confidence') or 'Not supplied')
        snippet=f'Page {ev.get("page") or "unknown"}: {ev.get("snippet") or "No source excerpt"}'
        action='<a href="#verify-fields">Verify against PDF</a>' if flag else 'No confirmation requested'
        cells=[escape(friendly(field)),escape(str(value) if value is not None else 'Missing'),escape(confidence),escape(snippet),action]
        rows.append('<tr'+(' class="uncertain"' if flag else '')+'>'+''.join('<td>'+c+'</td>' for c in cells)+'</tr>')
    st.html('<div class="evidence"><table><caption>Original model confidence is self-reported. Highlighted fields require source confirmation.</caption><thead><tr><th>Field</th><th>Value</th><th>Confidence</th><th>Source evidence</th><th>Review</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table></div>')

def queue_rank(row):
    if row['accepted']:return 9
    result=row.get('result') or {};checks=result.get('checks',[])
    if result.get('status')=='Blocked':return 0
    if any(c['code']=='possible_duplicate' and c['level']!='pass' for c in checks):return 1
    if any(c['code'].startswith('price') and c['level']=='review' and float(c['evidence'].get('variance_percent',0))>5 for c in checks):return 2
    if any(c['code'].startswith(('missing_','uncertain_')) for c in checks):return 3
    return 4 if result.get('status')!='Ready for approval' else 5

def audit_timeline(events,reviews):
    entries=[]
    for e in events:
        if e['state']=='done' and e['stage'] in ['ingest','extract','decision']:
            label={'ingest':'Document received','extract':'Invoice extracted','decision':'Invoice checks completed'}[e['stage']]
            if e['stage']=='decision' and e['run']>1:label='Invoice rechecked after review update'
            entries.append((e['created'],label,'Ledger'))
    names={'correct':'Extracted fields corrected','verify_fields':'Fields verified against PDF','select_po':'Purchase order selected','retry':'Review retried','accept':'Invoice approved'}
    for r in reviews:entries.append((r['created'],names.get(r['action'],'Review updated'),'Demo reviewer'))
    for when,label,who in sorted(entries):
        st.html(f'<div class="timeline"><p><strong>{escape(label)}</strong></p><small>{escape(who)}; {escape(timestamp(when))}</small></div>')


def problem_message(check):
    """Explain failed comparisons without changing their result or evidence."""
    code=check['code']
    if code.startswith('missing_'):return friendly(code[8:])+' is missing from the extracted invoice.'
    if code.startswith('uncertain_'):return 'Confirm '+friendly(code[10:]).lower()+' against the source PDF.'
    if code.startswith('line_math'):return 'The line quantity multiplied by its price does not match the line amount.'
    return {'subtotal':'Line amounts do not reconcile with the invoice subtotal.',
            'total':'The subtotal plus tax does not reconcile with the invoice total.',
            'tax_math':'The stated tax rate does not reconcile with the tax amount.',
            'balance':'The invoice exceeds the remaining authorised PO value.'}.get(code,check['message']) if check['level']=='review' else check['message']

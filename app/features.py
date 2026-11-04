"""Persistent demo workspaces, review guidance and evaluation/export helpers."""
import csv,io,json,os,re,uuid
from pathlib import Path
from decimal import Decimal,InvalidOperation
from . import store as s
from .domain import norm,name_norm

def owner_root(key):
    if not re.fullmatch('[a-f0-9]{32}',key):raise ValueError('Invalid history key.')
    root=Path(os.getenv('LEDGER_ARCHIVE_DIR',str(s.ROOT/'data/archive')))/key
    root.mkdir(parents=True,exist_ok=True)
    return root

def workspaces(key):
    root=owner_root(key)
    return sorted([json.loads(p.read_text()) for p in root.glob('*/workspace.json')],key=lambda x:x['created'],reverse=True)

def new_workspace(key,name):
    id=uuid.uuid4().hex;path=owner_root(key)/id
    path.mkdir()
    meta={'id':id,'name':name.strip()[:80] or 'New review session','created':s.now()}
    (path/'workspace.json').write_text(json.dumps(meta))
    with s.use_workspace(path):s.init()
    return path

def workspace_path(key,id):
    if not re.fullmatch('[a-f0-9]{32}',id):raise ValueError('Invalid workspace.')
    path=owner_root(key)/id
    if not (path/'workspace.json').is_file():raise ValueError('Workspace not found.')
    return path

def priority(result):
    checks=(result or {}).get('checks',[])
    if any(c['level']=='block' and c['code']=='vendor' for c in checks):return 'Critical',4
    if any(c['level']=='block' or c['code']=='possible_duplicate' and c['level']=='review' for c in checks):return 'High',3
    for c in checks:
        if c['level']=='review' and (c['code'].startswith('quantity') or c['code']=='balance' or c['code'].startswith('price') and Decimal(str(c['evidence'].get('variance_percent',0)))>5):return 'High',3
    if any(c['level'] in ['review','not_evaluated'] for c in checks):return 'Medium',2
    return 'Low',1

def fix_for(check):
    code=check['code'];level=check['level']
    if level=='pass':return 'No action needed.'
    if code.startswith('uncertain_'):return 'Compare the field with the source PDF; verify it if correct, or correct it and rerun.'
    if code.startswith('missing_'):return 'Ask the vendor to supply the missing '+code[8:].replace('_',' ')+'.'
    if code.startswith('duplicate'):return 'Open the original invoice. Do not approve another copy; ask whether this replaces an existing obligation.'
    if code=='possible_duplicate':return 'Compare the linked prior invoice and ask the vendor whether this is a reissue.'
    if code.startswith('quantity') or code=='balance':return 'Request a corrected invoice within the remaining PO commitment, or obtain an authorised PO amendment.'
    if code.startswith('po'):return 'Select or correct the PO reference, then rerun vendor ownership and balance checks.'
    if code=='gstin':return 'Compare the printed GSTIN with the master; correct an extraction error or investigate the mismatch.'
    if code.startswith('vendor'):return 'Ask procurement to confirm vendor identity and approved status.'
    if code.startswith('price'):return 'Confirm the agreed unit price and tax basis; request correction or an authorised PO amendment.'
    if code in ['total','subtotal','tax_math'] or code.startswith('line_math'):return 'Check the printed amounts and tax-rate format; correct extraction errors or request a corrected invoice.'
    if code=='date':return 'Verify the invoice date and request clarification if it is outside policy.'
    if code.startswith('mapping') or code.startswith('unit'):return 'Confirm item identity and compatible units against the PO; resolve ambiguity before approval.'
    return 'Resolve the stated prerequisite against the source document and rerun checks.'

def accepted_csv(rows):
    output=io.StringIO();writer=csv.writer(output)
    writer.writerow(['invoice_number','vendor','invoice_date','currency','subtotal','tax','total','purchase_order','accepted','record_id'])
    def safe(value):
        value=str(value or '')
        return "'"+value if value.startswith(('=','+','-','@','\t','\r')) else value
    for row in rows:
        if not row['accepted']:continue
        d=row['data'];writer.writerow([safe(d.get(k)) for k in ['invoice_no','vendor','date','currency','subtotal','tax','total']]+[safe(row['po']),'true',row['id']])
    return output.getvalue()

def evaluate_original(original,expected):
    """Compare original extraction only. Never supplies ground truth to the model."""
    results=[]
    for field,target in expected.items():
        actual=original.get(field)
        if field=='lines':
            def aggregate(lines):
                totals={}
                for line in lines or []:
                    key=(norm(line.get('item')),norm(line.get('unit','each')))
                    qty=Decimal(str(line.get('qty')));value=Decimal(str(line.get('line_total')))
                    price=Decimal(str(line.get('unit_price')))
                    old=totals.get(key,(Decimal(0),Decimal(0),set()))
                    totals[key]=(old[0]+qty,old[1]+value,old[2]|{price})
                return totals
            try:correct=aggregate(actual)==aggregate(target)
            except (InvalidOperation,TypeError,ValueError):correct=False
        elif target is None:correct=actual is None
        elif field in ['subtotal','tax','tax_rate','total']:
            try:correct=Decimal(str(actual))==Decimal(str(target))
            except (InvalidOperation,TypeError):correct=False
        elif field=='vendor':correct=name_norm(actual)==name_norm(target)
        elif field in ['invoice_no','gstin','po_ref','vendor_reference']:correct=norm(actual)==norm(target)
        else:correct=actual==target
        results.append({'field':field,'correct':correct,'expected':target,'original_extraction':actual})
    return results

def run_batch(files,submit,lookup,cooldown):
    """Sequential submissions with per-file outcomes and cooldown-aware stopping."""
    if not 1<=len(files)<=5:raise ValueError('Select between one and five PDFs.')
    summary=[];followups={}
    for index,(name,raw) in enumerate(files):
        try:
            id=submit(raw,name);row=lookup(id);result=row.get('result') or {}
            summary.append({'File':name,'Outcome':result.get('status',row['execution']),'Record':id})
            if result.get('email'):
                d=row.get('data') or {};vendor=d.get('vendor') or 'Unidentified vendor'
                findings=[c['message']+' Next action: '+c.get('fix',fix_for(c)) for c in result['checks'] if c['level'] in ['review','block','not_evaluated']]
                followups.setdefault(vendor,[]).append((d.get('invoice_no') or name)+':\n'+'\n'.join(findings))
            if cooldown(id):
                summary.extend({'File':n,'Outcome':'Not submitted: provider cooldown'} for n,_ in files[index+1:]);break
        except ValueError as error:summary.append({'File':name,'Outcome':str(error)})
    return {'summary':summary,'vendor_followups':followups}

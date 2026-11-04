"""Reviewer confirmation of extraction uncertainties; never bypasses policy checks."""
from copy import deepcopy
from . import store as s
from .domain import Invoice

VERIFIABLE_FIELDS = frozenset(Invoice.model_fields) - {'lines','evidence','uncertain_fields'}

def pending_verifications(data):
    """Only present scalar values can be confirmed. Missing values require correction."""
    return [field for field in dict.fromkeys(data.get('uncertain_fields',[]))
            if field in VERIFIABLE_FIELDS and data.get(field) is not None
            and str(data[field]).strip()]

def prepare_verification(invoice_id, fields, expected_run, reviewer='Demo reviewer'):
    fields=list(dict.fromkeys(fields))
    if not fields: raise ValueError('Select at least one field you checked against the source PDF.')
    with s.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        row=s.get(db,invoice_id)
        if row is None: raise ValueError('Invoice not found.')
        if row['accepted']: raise ValueError('Accepted invoices are read-only.')
        if row['execution']!='completed': raise ValueError('Wait for a completed review before verifying fields.')
        if row['run']!=expected_run: raise ValueError('This review has changed. Refresh it before verifying fields.')
        before=row['data']
        if not before: raise ValueError('Extract invoice data before verifying fields.')
        eligible=set(pending_verifications(before))
        if any(field not in eligible for field in fields):
            raise ValueError('Only currently uncertain fields with an extracted value can be verified. Correct missing or invalid values first.')
        after=deepcopy(before)
        timestamp=s.now()
        for field in fields:
            evidence=after['evidence'].get(field)
            evidence=dict(evidence) if isinstance(evidence,dict) else {}
            # Keep model confidence and source evidence intact; human confirmation is separate.
            evidence['reviewer_verification']={'reviewer':reviewer,'at':timestamp,'method':'Compared with source PDF','value':before[field]}
            after['evidence'][field]=evidence
        after['uncertain_fields']=[field for field in after['uncertain_fields'] if field not in fields]
        validated=Invoice.model_validate(after)
        s.review(db,invoice_id,'verify_fields',{'reviewer':reviewer,'fields':fields,
            'values':{field:before[field] for field in fields},'at':timestamp,'source_run':expected_run,
            'before':before,'after':__import__('json').loads(validated.model_dump_json())})
        db.execute("UPDATE invoices SET data=?,run=run+1,execution='queued',result=NULL WHERE id=?",(validated.model_dump_json(),invoice_id))
    # Caller must run process(invoice_id, rerun=True); no model re-extraction is needed.
    return invoice_id

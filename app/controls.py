"""Independent receipt and bank checks. No extraction provider or payment actions."""
import hashlib
import json
import re
from decimal import Decimal

BANK_FIELDS = ('bank_beneficiary', 'bank_account', 'bank_ifsc')


def account(value):
    return re.sub(r'[\s-]', '', value or '')


def ifsc(value):
    return re.sub(r'\s', '', value or '').upper()


def masked(value):
    value = account(value)
    return ('****' + value[-4:]) if len(value) > 4 else ('****' if value else 'Not provided')


def bank_key(data, baseline):
    return hashlib.sha256(json.dumps([account(data.get('bank_account')), ifsc(data.get('bank_ifsc')),
                                     data.get('bank_beneficiary'), baseline.get('version')], sort_keys=True).encode()).hexdigest()


def received(receipts, po, line):
    return sum((Decimal(str(l['qty'])) for r in receipts.values() if r['po'] == po and not r.get('reversed')
                for l in r['lines'] if l['po_line'] == line), Decimal(0))


def consumed(history, po, line, current_id=None):
    return sum((Decimal(str(a['qty'])) for h in history if h.get('accepted') and h.get('po') == po and h['id'] != current_id
                for a in h.get('allocations', []) if a['po_line'] == line), Decimal(0))


def extra_checks(inv, vendor, po, mappings, history, current_id, receipts, baseline, verification):
    checks = []
    def add(code, level, message, fix, **evidence):
        checks.append(dict(code=code, level=level, message=message, fix=fix, evidence=evidence))
    if po:
        if not po.get('require_receipts', False):
            add('receipt_optional','info','Receipt matching not required.','No delivery match is claimed. Enable receipt matching for quantity-based goods when appropriate.')
        for p in po['lines']:
            total = received(receipts, po['number'], p['id'])
            used = consumed(history, po['number'], p['id'], current_id)
            mapped = [inv.lines[m['index']] for m in mappings if m['po_line'] == p['id']]
            if total > Decimal(str(p['qty'])):
                add('receipt_over_'+p['id'], 'review', f'Accepted receipts exceed the authorised quantity for {p["item"]}.',
                    'Correct the receipt or obtain a separately authorised PO amendment. Receipt entries do not enlarge PO authorisation.', received=str(total), ordered=p['qty'])
            if not po.get('require_receipts', False) or not mapped:
                continue
            billed = sum((line.qty or 0 for line in mapped), Decimal(0))
            available = total-used
            valid = all(line.qty is not None and line.qty > 0 and line.unit == p['unit'] for line in mapped)
            passes = valid and billed <= available
            add('receipt_'+p['id'], 'pass' if passes else 'review',
                f'Invoice bills {billed} {p["item"]}; {available} received and available.' + (f' {max(Decimal(0),billed-available)} require receipt confirmation.' if not passes else ''),
                'Record independently confirmed accepted goods receipts, or correct the invoice. The whole invoice is held; no partial approval.' if not passes else 'Accepted quantities cover this invoice; other checks still apply.',
                po_line=p['id'], received=str(total), consumed=str(used), available=str(available), billed=str(billed), unit=p['unit'])
        if po.get('require_receipts') and (len(mappings)!=len(inv.lines) or not inv.lines):
            add('receipt_mapping','review','Receipt quantities cannot be established for all invoice lines.',
                'Resolve line mapping and units before comparing accepted goods receipts. Unit conversion and service acceptance are unsupported.')
    data = inv.model_dump(mode='json')
    baseline = baseline or {}
    required = bool((vendor or {}).get('bank_required',False))
    observed = account(inv.bank_account)
    code = ifsc(inv.bank_ifsc)
    evidence = dict(invoice_account=masked(observed),trusted_account=masked(baseline.get('account')),
                    invoice_ifsc=code or 'Not provided',trusted_ifsc=baseline.get('ifsc') or 'Not provided',
                    baseline_version=baseline.get('version'),source={k:inv.evidence.get(k) for k in BANK_FIELDS})
    next_step = 'Correct extraction against the source, or independently verify the change using an established vendor contact and record a note/reference. Do not rely only on contact details printed on this invoice.'
    provided = any(getattr(inv,k) for k in BANK_FIELDS) or inv.bank_ambiguous
    complete = bool(re.fullmatch(r'[0-9]{6,34}',observed) and re.fullmatch(r'[A-Z]{4}0[A-Z0-9]{6}',code))
    if not provided:
        add('bank_missing','review' if required else 'info','Bank details: Not provided.', 'Obtain and confirm bank details before readiness.' if required else 'No bank match is claimed.', **evidence)
    elif not complete or inv.bank_ambiguous or any(k in inv.uncertain_fields for k in BANK_FIELDS):
        add('bank_uncertain','review','Bank details are incomplete, masked or uncertain; confirmation required.', next_step, **evidence)
    elif not baseline.get('verified'):
        add('bank_baseline','review' if required else 'info','No verified bank details on file.', 'Establish and explicitly verify the trusted account in vendor management. Format checks do not verify account ownership.', **evidence)
    else:
        match = observed == account(baseline.get('account')) and code == ifsc(baseline.get('ifsc'))
        externally_verified = bool(verification and verification.get('fingerprint') == bank_key(data,baseline))
        add('bank_match','pass' if match or externally_verified else 'review',
            'Bank details match the verified vendor account.' if match else 'Different payment details independently verified for this invoice.' if externally_verified else 'Payment details differ from the verified vendor record; verification required.', next_step, **evidence)
        beneficiary = lambda s: re.sub(r'[^a-z0-9]', '', (s or '').lower())
        if beneficiary(inv.bank_beneficiary) != beneficiary(baseline.get('beneficiary')):
            add('bank_beneficiary','pass' if externally_verified else 'review',
                'Beneficiary-name difference independently verified.' if externally_verified else 'Beneficiary name differs or is missing. Name similarity does not prove account ownership.',next_step,**evidence)
    return checks

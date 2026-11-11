"""Folder-owned receipt evidence and explicit, versioned bank verification."""
import copy
import hashlib
import json
import re
import uuid
from datetime import date
from decimal import Decimal

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from app.controls import BANK_FIELDS, account, ifsc, masked, bank_key, received, consumed
from .auth import User
from .engine import Conflict, decision, audit, event
from .repository import now, encode


def public(value):
    """Mask account strings and evidence everywhere; trusted accounts never enter backups."""
    numbers=set()
    def collect(x):
        if isinstance(x,dict):
            for k,v in x.items():
                if k in {'bank_account','account'} and isinstance(v,str) and len(account(v))>=6:
                    numbers.add(account(v))
                collect(v)
        elif isinstance(x,list):
            for v in x:collect(v)
    collect(value)
    def clean(x,bank_context=False):
        if isinstance(x,dict):
            bank_context=bank_context or str(x.get('code','')).startswith(('bank','uncertain_bank'))
            out={k:(masked(v) if k=='bank_account' and isinstance(v,str) else clean(v,bank_context or k in BANK_FIELDS)) for k,v in x.items() if k!='bank_accounts'}
            if 'bank_accounts' in x:
                out['bank_status']={vid:{**{k:clean(v) for k,v in record.get('current',{}).items() if k!='account'},
                                          'account_masked':masked(record.get('current',{}).get('account'))}
                                    for vid,record in x['bank_accounts'].items()}
            return out
        if isinstance(x,list):return [clean(v,bank_context) for v in x]
        if isinstance(x,str):
            if bank_context and not re.fullmatch(r'[A-Z]{4}0[A-Z0-9]{6}',ifsc(x)):
                x=re.sub(r'(?<![A-Za-z0-9])[0-9](?:[ -]?[0-9]){5,33}(?![A-Za-z0-9])',lambda m:masked(m.group(0)),x)
            for number in sorted(numbers,key=len,reverse=True):
                if number.isdigit():
                    x=re.sub(r'[\s-]*'.join(re.escape(d) for d in number),lambda _:masked(number),x)
                else:x=x.replace(number,masked(number))
            return x
        return x
    return clean(copy.deepcopy(value))


def recheck(meta,rows):
    for row in rows.values():
        if not row['accepted'] and row.get('data') and row['execution']=='completed':
            decision(meta,rows,row)


def log(meta,action,actor,details):
    meta.setdefault('control_audit',[]).append(dict(at=now(),actor=actor,action=action,details=details))
    if len(encode(meta).encode())>800_000:
        raise Conflict('Folder control history is full. Export its masked audit history and start a new folder.')


class Input(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)


class ReceiptLine(Input):
    po_line:str=Field(min_length=1,max_length=100)
    qty:Decimal=Field(ge=0,le=10**12)


class ReceiptInput(Input):
    id:str=Field(pattern=r'^[a-f0-9]{32}$')
    expected_revision:int=Field(default=0,ge=0)
    reference:str=Field(min_length=1,max_length=100)
    po:str=Field(min_length=1,max_length=100)
    date:date
    lines:list[ReceiptLine]=Field(min_length=1,max_length=100)
    delivery_note:str=Field(default='',max_length=150)
    notes:str=Field(default='',max_length=500)
    reason:str=Field(min_length=5,max_length=500)
    reversed:bool=False


class Policy(Input):
    required:bool
    reason:str=Field(min_length=5,max_length=500)


class TrustedBank(Input):
    beneficiary:str=Field(min_length=1,max_length=150)
    account:str=Field(min_length=6,max_length=100)
    ifsc:str=Field(min_length=11,max_length=30)
    verified:bool=False
    expected_version:int=Field(ge=0)
    reason:str=Field(min_length=5,max_length=500)


class BankCorrection(Input):
    expected_run:int=Field(ge=1)
    bank_beneficiary:str|None=Field(default=None,max_length=150)
    bank_account:str|None=Field(default=None,max_length=100)
    bank_ifsc:str|None=Field(default=None,max_length=30)
    compared_with_source:bool=False
    reason:str=Field(min_length=5,max_length=500)


class BankVerification(Input):
    expected_run:int=Field(ge=1)
    reason:str=Field(min_length=5,max_length=500)
    method:str=Field(min_length=5,max_length=150)


def install(app,repo,user,valid_id,editable):
    def po_for(meta,ref):
        po=next((p for p in meta['master']['pos'] if p['number']==ref),None)
        if not po:raise KeyError(ref)
        return po
    def vendor_for(meta,vid):
        vendor=next((v for v in meta['master']['vendors'] if v['id']==vid),None)
        if not vendor:raise KeyError(vid)
        return vendor

    @app.post('/api/sessions/{sid}/receipts')
    def save_receipt(sid:str,body:ReceiptInput,who:User=Depends(user),store=Depends(repo)):
        valid_id(sid)
        def update(meta,rows):
            receipts=meta.setdefault('receipts',{})
            old=receipts.get(body.id)
            payload=body.model_dump(mode='json');payload.pop('expected_revision')
            digest=hashlib.sha256(encode(payload).encode()).hexdigest()
            if old and old.get('request_hash')==digest:return public(old)
            if (old and old['revision']!=body.expected_revision) or (not old and body.expected_revision):
                raise Conflict('Receipt changed. Refresh its history before correcting it.')
            if not body.reason.strip() or not body.reference.strip():raise Conflict('Enter a receipt reference and audit reason.')
            if body.date>date.today():raise Conflict('Receipt date cannot be in the future.')
            po=po_for(meta,body.po)
            if old and old['po']!=body.po:raise Conflict('A correction cannot move a receipt to another PO.')
            if any(r['id']!=body.id and body.reference.strip().casefold() in {ref.strip().casefold() for ref in [r['reference'],*[h.get('after',{}).get('reference','') for h in r.get('history',[])],*[h.get('before',{}).get('reference','') for h in r.get('history',[])]]} for r in receipts.values()):
                raise Conflict('This receipt reference already exists in the folder, including reversed receipts.')
            if len({l.po_line for l in body.lines})!=len(body.lines):raise Conflict('Each PO line may appear once per receipt.')
            if not any(l.qty>0 for l in body.lines) and not body.reversed:raise Conflict('Enter at least one positive accepted quantity.')
            if not old and body.reversed:raise Conflict('Record the original receipt before reversing it.')
            if not old and len(receipts)>=100:raise Conflict('This folder supports 100 receipts.')
            for line in body.lines:
                if line.po_line not in {l['id'] for l in po['lines']}:raise Conflict('Receipt lines must belong to the selected PO.')
            before={p['id']:received(receipts,po['number'],p['id']) for p in po['lines']}
            record={**payload,'revision':(old or {}).get('revision',0)+1,'created_by':(old or {}).get('created_by',who.username),
                    'created_at':(old or {}).get('created_at',now()),'request_hash':digest,
                    'history':copy.deepcopy((old or {}).get('history',[]))}
            record['reference']=body.reference.strip()
            record['history'].append(dict(at=now(),actor=who.username,reason=body.reason,
                                          before={k:v for k,v in (old or {}).items() if k not in {'history','request_hash'}},
                                          after=payload))
            receipts[body.id]=record
            for line in po['lines']:
                after=received(receipts,po['number'],line['id'])
                if old and after<before[line['id']] and after<consumed(rows.values(),po['number'],line['id']):
                    raise Conflict('Accepted quantities already consumed by approved invoices cannot be reversed or reduced. A separate corrective workflow is required; approved history is unchanged.')
            log(meta,'receipt_corrected' if old else 'receipt_recorded',who.username,{'receipt':body.id,'reason':body.reason})
            recheck(meta,rows)
            return public(record)
        return store.atomic(who.uid,sid,update)

    @app.post('/api/sessions/{sid}/receipt-policy')
    def receipt_policy(sid:str,po:str,body:Policy,who:User=Depends(user),store=Depends(repo)):
        valid_id(sid)
        def update(meta,rows):
            target=po_for(meta,po)
            if len(body.reason.strip())<5:raise Conflict('Explain the policy change.')
            before=target.get('require_receipts',False);target['require_receipts']=body.required
            log(meta,'receipt_policy_changed',who.username,{'po':po,'before':before,'after':body.required,'reason':body.reason})
            recheck(meta,rows);return {'ok':True}
        return store.atomic(who.uid,sid,update)

    @app.post('/api/sessions/{sid}/vendors/{vid}/bank-policy')
    def bank_policy(sid:str,vid:str,body:Policy,who:User=Depends(user),store=Depends(repo)):
        valid_id(sid)
        def update(meta,rows):
            target=vendor_for(meta,vid)
            if len(body.reason.strip())<5:raise Conflict('Explain the policy change.')
            before=target.get('bank_required',False);target['bank_required']=body.required
            log(meta,'bank_policy_changed',who.username,{'vendor':vid,'before':before,'after':body.required,'reason':body.reason})
            recheck(meta,rows);return {'ok':True}
        return store.atomic(who.uid,sid,update)

    @app.post('/api/sessions/{sid}/vendors/{vid}/bank/reveal')
    def reveal_bank(sid:str,vid:str,who:User=Depends(user),store=Depends(repo)):
        valid_id(sid)
        def read(meta,rows):
            vendor_for(meta,vid)
            log(meta,'trusted_bank_revealed',who.username,{'vendor':vid})
            return meta.get('bank_accounts',{}).get(vid,{'current':{},'history':[]})
        return store.atomic(who.uid,sid,read)

    @app.put('/api/sessions/{sid}/vendors/{vid}/bank')
    def update_bank(sid:str,vid:str,body:TrustedBank,who:User=Depends(user),store=Depends(repo)):
        valid_id(sid)
        number=account(body.account);code=ifsc(body.ifsc)
        if not re.fullmatch(r'[0-9]{6,34}',number) or not re.fullmatch(r'[A-Z]{4}0[A-Z0-9]{6}',code):
            raise HTTPException(400,'Use a complete account number (6–34 digits) and an 11-character IFSC. These are format checks only.')
        if len(body.reason.strip())<5 or not body.beneficiary.strip():raise HTTPException(400,'Provide a beneficiary and independent verification reason/reference.')
        def update(meta,rows):
            vendor_for(meta,vid)
            entry=meta.setdefault('bank_accounts',{}).setdefault(vid,{'current':{},'history':[]})
            old=entry['current']
            if old.get('version',0)!=body.expected_version:raise Conflict('Trusted bank details changed. Reveal the latest version before saving.')
            if old:entry['history'].append(copy.deepcopy(old))
            entry['current']=dict(beneficiary=body.beneficiary.strip(),account=number,ifsc=code,verified=body.verified,
                                  verified_by=who.username if body.verified else None,verified_at=now() if body.verified else None,
                                  version=body.expected_version+1,reason=body.reason,changed_by=who.username,changed_at=now())
            log(meta,'trusted_bank_updated',who.username,{'vendor':vid,'version':body.expected_version+1,'verified':body.verified})
            recheck(meta,rows);return public({'bank_accounts':{vid:entry}})
        return store.atomic(who.uid,sid,update)

    @app.post('/api/sessions/{sid}/invoices/{iid}/bank/reveal')
    def reveal_invoice_bank(sid:str,iid:str,who:User=Depends(user),store=Depends(repo)):
        valid_id(sid);valid_id(iid)
        def read(meta,rows):
            row=rows[iid];data=row.get('data') or {}
            log(meta,'invoice_bank_revealed',who.username,{'invoice':iid})
            return {**{k:data.get(k) for k in BANK_FIELDS},'ambiguous':data.get('bank_ambiguous',False),'run':row['run']}
        return store.atomic(who.uid,sid,read)

    @app.post('/api/sessions/{sid}/invoices/{iid}/bank/correct')
    def correct_bank(sid:str,iid:str,body:BankCorrection,who:User=Depends(user),store=Depends(repo)):
        valid_id(sid);valid_id(iid)
        if not body.compared_with_source:raise HTTPException(400,'Compare all bank fields with the original source first.')
        if len(body.reason.strip())<5:raise HTTPException(400,'Explain the extraction correction.')
        def update(meta,rows):
            row=rows[iid];editable(row,body.expected_run)
            if not row.get('data'):raise Conflict('Complete extraction first.')
            d=row['data'];before={k:d.get(k) for k in BANK_FIELDS}
            for key in BANK_FIELDS:
                d[key]=getattr(body,key) or None
                d.setdefault('evidence',{}).setdefault(key,{})['reviewer_verification']={'at':now(),'reviewer':who.username,'method':'Compared bank fields with original source'}
            d['bank_ambiguous']=False
            d['uncertain_fields']=[k for k in d.get('uncertain_fields',[]) if k not in {*BANK_FIELDS,'bank_ambiguous'}]
            row.pop('bank_verification',None);row['run']+=1
            audit(row,'bank_extraction_corrected',who.username,public({'before':before,'after':{k:d[k] for k in BANK_FIELDS},'reason':body.reason}))
            decision(meta,rows,row);event(row,'Decision ready',message='Bank extraction corrected; business mismatch checks rerun.')
            return public(row)
        return store.atomic(who.uid,sid,update)

    @app.post('/api/sessions/{sid}/invoices/{iid}/bank/verify')
    def verify_bank(sid:str,iid:str,body:BankVerification,who:User=Depends(user),store=Depends(repo)):
        valid_id(sid);valid_id(iid)
        if len(body.reason.strip())<5 or len(body.method.strip())<5:raise HTTPException(400,'Record how the change was verified and a note/reference.')
        def update(meta,rows):
            row=rows[iid];editable(row,body.expected_run);result=decision(meta,rows,row)
            d=row.get('data') or {};baseline=meta.get('bank_accounts',{}).get(result.get('vendor_id'),{}).get('current',{})
            if not baseline.get('verified'):raise Conflict('Establish a verified vendor baseline first.')
            if any(c['code']=='bank_uncertain' for c in result['checks']) or not d.get('bank_account') or not d.get('bank_ifsc'):
                raise Conflict('Correct incomplete or uncertain extraction before external verification.')
            row['bank_verification']=dict(fingerprint=bank_key(d,baseline),at=now(),actor=who.username,
                                          method=body.method,reason=body.reason,baseline_version=baseline['version'])
            row['run']+=1
            audit(row,'bank_change_externally_verified',who.username,public({'bank_account':d.get('bank_account'),'method':body.method,'reason':body.reason,'baseline_version':baseline['version']}))
            decision(meta,rows,row);event(row,'Decision ready',message='External bank verification recorded for this invoice only; approval remains separate.')
            return public(row)
        return store.atomic(who.uid,sid,update)

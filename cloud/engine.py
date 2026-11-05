"""Per-invoice durable worker. Extraction happens outside transactional decisions."""
import asyncio
import copy
import hashlib
import json
import os
import time
import uuid
from decimal import Decimal
from app.domain import Invoice, evaluate
from .repository import now, encode
from .reader import read

STAGES = ['Uploaded','Reading document','Checking policy','Decision ready']

class Conflict(ValueError):
    pass

def event(row, stage, state='done', message=''):
    row.setdefault('events', []).append(dict(at=now(), stage=stage, state=state, message=message[:400], run=row['run']))
    row['events'] = row['events'][-32:]
    row['updated'] = now()

def audit(row, action, actor, details=None):
    row.setdefault('audit', []).append(dict(at=now(), action=action, actor=actor, details=details or {}))
    # Audit entries are never silently deleted. A new revision requires room.
    if len(encode(row).encode()) > 700_000:
        raise Conflict('This invoice has reached its revision size limit. Export its audit trail before creating a new record.')

def decision(meta, rows, row):
    earlier = [h for h in rows.values() if h['id'] != row['id'] and h.get('data') and (h.get('accepted') or (h['created'],h['id']) < (row['created'],row['id']))]
    result = evaluate(Invoice.model_validate(row['data']), meta['master']['vendors'], meta['master']['pos'], list(rows.values()), row['id'], row['hash'], row.get('selected_po'), duplicate_history=earlier)
    if row.get('result') != result:
        row['updated'] = now()
    row['result'] = result
    row['po'] = result['po']; row['vendor_id'] = result['vendor_id']
    return result

def new_record(filename, raw, mime, pages, batch):
    iid = uuid.uuid4().hex
    row = dict(id=iid, filename=filename, hash=hashlib.sha256(raw).hexdigest(), mime=mime, pages=pages,
               batch=batch, created=now(), updated=now(), execution='queued', run=1, accepted=False, data=None,
               original=None, result=None, po=None, vendor_id=None, selected_po=None, allocations=[], events=[], audit=[], lease_until=0)
    event(row,'Uploaded',message='File saved. Waiting for a worker.')
    return row

async def process(repo, uid, sid, iid, run, local_only=False):
    token = uuid.uuid4().hex
    def claim(meta, rows):
        row = rows.get(iid)
        if not row or row['run'] != run or row['accepted'] or row['execution'] == 'completed':
            return None
        if row['execution'] == 'running' and row.get('lease_until',0) > time.time():
            raise Conflict('Invoice is already being processed.')
        row.update(execution='running',lease_until=time.time()+1900,lease_token=token)
        event(row,'Reading document','running','Reading all pages; using OCR if required.')
        return copy.deepcopy(row)
    row = await asyncio.to_thread(repo.atomic,uid,sid,claim)
    if row is None:
        return
    try:
        raw = await asyncio.to_thread(repo.get_file,uid,sid,iid)
        inv, extraction = await read(raw,row['mime'],local_only)
        data = inv.model_dump(mode='json')
        if len(encode(data).encode()) > 450_000:
            data = Invoice().model_dump(mode='json')
            extraction = {'source':'Manual review','fallback':True,'note':'Extraction exceeded the safe record size. Review the original and enter a concise set of fields.','pages':[]}
        def finish(meta, rows):
            current = rows[iid]
            if current['run'] != run or current.get('lease_token') != token:
                return
            current.update(data=data, original=data, extraction=extraction, execution='completed', lease_until=0)
            event(current,'Reading document',message=extraction['note'])
            event(current,'Checking policy',message='Checking vendor, PO, duplicates, arithmetic, price and remaining balance.')
            decision(meta, rows, current)
            # Concurrent readers can finish out of upload order. Refresh later
            # decisions so an early result cannot leave a duplicate marked ready.
            for other in rows.values():
                if other['id'] != iid and not other['accepted'] and other.get('data') and other['execution'] == 'completed' and (other['created'],other['id']) > (current['created'],current['id']):
                    decision(meta, rows, other)
            event(current,'Decision ready',message=current['result']['summary'])
            audit(current,'processed','system',{'source':extraction['source'],'fallback':extraction['fallback']})
        await asyncio.to_thread(repo.atomic,uid,sid,finish)
    except Exception:
        def failed(meta, rows):
            current = rows[iid]
            if current['run'] == run and current.get('lease_token') == token:
                current.update(execution='failed',lease_until=0,error='Processing was interrupted. Retry this invoice; the original file is saved.')
                event(current,'Reading document','failed',current['error'])
        await asyncio.to_thread(repo.atomic,uid,sid,failed)
        raise

class Dispatcher:
    def __init__(self, repo):
        self.repo = repo
        self.tasks = set()
        self.semaphore = asyncio.Semaphore(3)

    async def enqueue(self, uid, sid, iid, run, local_only=False):
        if os.getenv('LEDGER_STORAGE') == 'cloud':
            await asyncio.to_thread(self._cloud,uid,sid,iid,run,local_only)
        else:
            async def work():
                async with self.semaphore:
                    try:
                        await process(self.repo,uid,sid,iid,run,local_only)
                    except Exception:
                        # Failure is recorded for the user, independent of other files.
                        pass
            task = asyncio.create_task(work()); self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)

    def _cloud(self, uid, sid, iid, run, local_only):
        from google.cloud import tasks_v2
        from google.api_core.exceptions import AlreadyExists
        from google.protobuf import duration_pb2
        client = tasks_v2.CloudTasksClient()
        project = os.environ['GOOGLE_CLOUD_PROJECT']
        region = os.environ.get('LEDGER_REGION','asia-south1')
        parent = client.queue_path(project,region,os.environ.get('LEDGER_QUEUE','ledger-invoices'))
        # Duplicate enqueue attempts are harmless. Retry endpoint increments run.
        name = client.task_path(project,region,os.environ.get('LEDGER_QUEUE','ledger-invoices'),f'{iid}-{run}')
        url = os.environ['LEDGER_WORKER_URL'].rstrip('/')
        task = {'name':name,'dispatch_deadline':duration_pb2.Duration(seconds=1800),'http_request':{
            'http_method':tasks_v2.HttpMethod.POST,'url':url+'/internal/process',
            'headers':{'Content-Type':'application/json'},
            'body':json.dumps(dict(uid=uid,sid=sid,iid=iid,run=run,local_only=local_only)).encode(),
            'oidc_token':{'service_account_email':os.environ['LEDGER_TASK_SERVICE_ACCOUNT'],'audience':url}}}
        try:
            client.create_task(parent=parent,task=task)
        except AlreadyExists:
            pass

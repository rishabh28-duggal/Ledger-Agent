"""Durable per-user sessions. All decisions and approvals use atomic updates.

SQLite is for local use only. Hosted instances use Firestore + private Cloud Storage.
The session version document serializes competing decisions without holding a lock
while OCR or Gemini runs. Each invoice has its own Firestore document.
"""
import copy
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.getenv('LEDGER_DATA_DIR', str(ROOT / 'data/cloud')))

def now():
    return datetime.now(timezone.utc).isoformat()

def encode(value):
    return json.dumps(value, default=str, ensure_ascii=False)

def procurement_master():
    """Each folder gets its own editable copy of the repository procurement list."""
    return json.loads((ROOT / 'samples/master.json').read_text(encoding='utf-8'))

def initial(name, demo=False):
    return dict(id=uuid.uuid4().hex, name=name, created=now(), master=procurement_master(),
                procurement_version=1, version=0, demo=demo)

class LocalRepository:
    def __init__(self, directory=DATA):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.dbpath = self.directory / 'ledger.sqlite3'
        with self.connect() as db:
            db.executescript('''PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS sessions(uid TEXT, sid TEXT, data TEXT, PRIMARY KEY(uid,sid));
            CREATE TABLE IF NOT EXISTS invoices(uid TEXT, sid TEXT, id TEXT, data TEXT, PRIMARY KEY(uid,sid,id));''')
            # Local execution has no durable external worker. Preserve interrupted
            # uploads and make their Retry action available after a restart.
            for uid,sid,iid,raw in db.execute('SELECT uid,sid,id,data FROM invoices').fetchall():
                row=json.loads(raw)
                if row.get('execution') in {'queued','running'}:
                    row.update(execution='failed',lease_until=0,error='The local server restarted. Retry this saved invoice to resume processing.')
                    db.execute('UPDATE invoices SET data=? WHERE uid=? AND sid=? AND id=?',(encode(row),uid,sid,iid))

    def connect(self):
        return sqlite3.connect(self.dbpath, timeout=30)

    def sessions(self, uid):
        with self.connect() as db:
            return [json.loads(x[0]) for x in db.execute('SELECT data FROM sessions WHERE uid=? ORDER BY sid', (uid,))]

    def create(self, uid, name, demo=False):
        meta = initial(name, demo)
        with self.connect() as db:
            db.execute('INSERT INTO sessions VALUES(?,?,?)', (uid, meta['id'], encode(meta)))
        return meta

    def snapshot(self, uid, sid):
        with self.connect() as db:
            db.execute('BEGIN')
            meta = db.execute('SELECT data FROM sessions WHERE uid=? AND sid=?', (uid, sid)).fetchone()
            if not meta:
                raise KeyError('Session not found')
            rows = [json.loads(r[0]) for r in db.execute('SELECT data FROM invoices WHERE uid=? AND sid=?', (uid, sid))]
            return json.loads(meta[0]), rows

    def atomic(self, uid, sid, callback):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            raw = db.execute('SELECT data FROM sessions WHERE uid=? AND sid=?', (uid, sid)).fetchone()
            if not raw:
                raise KeyError('Session not found')
            meta = json.loads(raw[0])
            rows = {r[0]: json.loads(r[1]) for r in db.execute('SELECT id,data FROM invoices WHERE uid=? AND sid=?', (uid, sid))}
            before = copy.deepcopy(rows)
            result = callback(meta, rows)
            meta['version'] += 1
            db.execute('UPDATE sessions SET data=? WHERE uid=? AND sid=?', (encode(meta), uid, sid))
            for key, row in rows.items():
                if before.get(key) != row:
                    db.execute('INSERT OR REPLACE INTO invoices VALUES(?,?,?,?)', (uid, sid, key, encode(row)))
            return result

    def put_file(self, uid, sid, iid, raw, mime):
        path = self.directory / 'files' / uid / sid
        path.mkdir(parents=True, exist_ok=True)
        (path / iid).write_bytes(raw)

    def get_file(self, uid, sid, iid):
        return (self.directory / 'files' / uid / sid / iid).read_bytes()

class CloudRepository:
    def __init__(self):
        from google.cloud import firestore, storage
        self.db = firestore.Client()
        self.bucket = storage.Client().bucket(os.environ['LEDGER_BUCKET'])
        self.fs = firestore

    def ref(self, uid, sid):
        return self.db.collection('users').document(uid).collection('sessions').document(sid)

    def sessions(self, uid):
        return [d.to_dict() for d in self.db.collection('users').document(uid).collection('sessions').stream()]

    def create(self, uid, name, demo=False):
        meta = initial(name, demo)
        self.ref(uid, meta['id']).create(meta)
        return meta

    def snapshot(self, uid, sid):
        # A transaction avoids mixing a session version with invoices from another version.
        @self.fs.transactional
        def read(tx):
            ref = self.ref(uid, sid)
            snap = ref.get(transaction=tx)
            if not snap.exists:
                raise KeyError('Session not found')
            return snap.to_dict(), [x.to_dict() for x in ref.collection('invoices').stream(transaction=tx)]
        return read(self.db.transaction())

    def atomic(self, uid, sid, callback):
        @self.fs.transactional
        def update(tx):
            ref = self.ref(uid, sid)
            snap = ref.get(transaction=tx)
            if not snap.exists:
                raise KeyError('Session not found')
            meta = snap.to_dict()
            rows = {d.id: d.to_dict() for d in ref.collection('invoices').stream(transaction=tx)}
            before = copy.deepcopy(rows)
            result = callback(meta, rows)
            meta['version'] += 1
            tx.set(ref, meta)
            for iid, row in rows.items():
                if before.get(iid) != row:
                    tx.set(ref.collection('invoices').document(iid), row)
            return result
        return update(self.db.transaction(max_attempts=10))

    def put_file(self, uid, sid, iid, raw, mime):
        self.bucket.blob(f'{uid}/{sid}/{iid}').upload_from_string(raw, content_type=mime)

    def get_file(self, uid, sid, iid):
        return self.bucket.blob(f'{uid}/{sid}/{iid}').download_as_bytes()

def repository():
    return CloudRepository() if os.getenv('LEDGER_STORAGE') == 'cloud' else LocalRepository()

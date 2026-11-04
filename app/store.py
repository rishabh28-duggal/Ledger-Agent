import json, sqlite3, os
from pathlib import Path
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
ROOT=Path(__file__).resolve().parents[1]
DATA=Path(os.getenv('AP_DATA_DIR',str(ROOT/'data')))
DATA.mkdir(parents=True,exist_ok=True)
DB=DATA/'review.sqlite3'
_workspace = ContextVar('ap_workspace', default=None)
def data_dir():
    return _workspace.get() or DATA
def db_path():
    return data_dir()/'review.sqlite3' if _workspace.get() is not None else DB
@contextmanager
def use_workspace(path):
    path=Path(path);path.mkdir(parents=True,exist_ok=True)
    token=_workspace.set(path)
    try: yield
    finally: _workspace.reset(token)
def now(): return datetime.now(timezone.utc).isoformat()
def dumps(x): return json.dumps(x,default=str)
@contextmanager
def connection():
    db=sqlite3.connect(db_path(),timeout=20)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback();raise
    finally: db.close()
def init():
    with connection() as db:
        db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS records(kind TEXT, id TEXT, payload TEXT, PRIMARY KEY(kind,id));
        CREATE TABLE IF NOT EXISTS invoices(id TEXT PRIMARY KEY, filename TEXT, hash TEXT, mode TEXT, created TEXT, execution TEXT, accepted INTEGER DEFAULT 0, data TEXT, original TEXT, result TEXT, po TEXT, vendor_id TEXT, allocations TEXT DEFAULT '[]', selected_po TEXT, run INTEGER DEFAULT 1);
        CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, invoice_id TEXT REFERENCES invoices(id), run INTEGER, stage TEXT, state TEXT, payload TEXT, created TEXT);
        CREATE TABLE IF NOT EXISTS reviews(seq INTEGER PRIMARY KEY AUTOINCREMENT, invoice_id TEXT REFERENCES invoices(id), action TEXT, details TEXT, created TEXT);
        ''')
        # No background job survives a process restart. Preserve records and mark retryable.
        db.execute("UPDATE invoices SET execution='failed' WHERE execution IN ('queued','running')")
        if not db.execute('SELECT 1 FROM records LIMIT 1').fetchone():
            seed=json.loads((ROOT/'samples/master.json').read_text())
            for kind,key in [('vendors','id'),('pos','number')]:
                for x in seed[kind]: db.execute('INSERT INTO records VALUES(?,?,?)',(kind,x[key],dumps(x)))
def records(db,kind): return [json.loads(r[0]) for r in db.execute('SELECT payload FROM records WHERE kind=?',(kind,))]
def unpack(row):
    if row is None: return None
    r=dict(row)
    for k in ['data','original','result','allocations']:
        r[k]=json.loads(r[k]) if r.get(k) else None
    return r
def get(db,id): return unpack(db.execute('SELECT * FROM invoices WHERE id=?',(id,)).fetchone())
def all_invoices(db): return [unpack(r) for r in db.execute('SELECT * FROM invoices ORDER BY created DESC')]
def event(db,id,run,stage,state,payload=None):
    db.execute('INSERT INTO events(invoice_id,run,stage,state,payload,created) VALUES(?,?,?,?,?,?)',(id,run,stage,state,dumps(payload or {}),now()))
def review(db,id,action,details):
    db.execute('INSERT INTO reviews(invoice_id,action,details,created) VALUES(?,?,?,?)',(id,action,dumps(details),now()))

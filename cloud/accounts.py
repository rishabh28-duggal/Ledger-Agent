"""Server-only authentication records, separate from existing invoice ownership.

Both backends serialize multi-key updates: uniqueness and rate limits do not
depend on process-local locks (Cloud Run may have several instances).
"""
import copy
import json
import sqlite3


class SQLiteAccounts:
    def __init__(self, directory):
        self.path = directory / 'ledger.sqlite3'
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS auth_records (kind TEXT, key TEXT, data TEXT, PRIMARY KEY(kind,key))')

    def connect(self):
        return sqlite3.connect(self.path, timeout=30)

    def get(self, kind, key):
        with self.connect() as db:
            row = db.execute('SELECT data FROM auth_records WHERE kind=? AND key=?', (kind, key)).fetchone()
            return json.loads(row[0]) if row else None

    def atomic(self, keys, change):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            records = {}
            for kind, key in keys:
                row = db.execute('SELECT data FROM auth_records WHERE kind=? AND key=?', (kind, key)).fetchone()
                records[(kind, key)] = json.loads(row[0]) if row else None
            result = change(records)
            for (kind, key), value in records.items():
                if value is None:
                    db.execute('DELETE FROM auth_records WHERE kind=? AND key=?', (kind, key))
                else:
                    db.execute('INSERT OR REPLACE INTO auth_records VALUES (?,?,?)', (kind, key, json.dumps(value)))
            return result


class FirestoreAccounts:
    def __init__(self, db, firestore):
        self.db, self.fs = db, firestore

    def ref(self, kind, key):
        return self.db.collection('ledger_auth_' + kind).document(key)

    def get(self, kind, key):
        snap = self.ref(kind, key).get()
        return snap.to_dict() if snap.exists else None

    def atomic(self, keys, change):
        @self.fs.transactional
        def update(tx):
            records = {}
            for kind, key in keys:
                snap = self.ref(kind, key).get(transaction=tx)
                records[(kind, key)] = snap.to_dict() if snap.exists else None
            before = copy.deepcopy(records)
            result = change(records)
            # All reads precede writes, as required by Firestore transactions.
            for (kind, key), value in records.items():
                if value != before[(kind, key)]:
                    if value is None:
                        tx.delete(self.ref(kind, key))
                    else:
                        tx.set(self.ref(kind, key), value)
            return result
        return update(self.db.transaction(max_attempts=10))

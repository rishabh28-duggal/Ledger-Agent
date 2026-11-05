"""Dry run by default. Review output before passing --apply. Requires cloud ADC."""
import argparse
import os
from datetime import datetime, timezone, timedelta
from google.cloud import firestore, storage
from google.cloud.firestore_v1.base_query import FieldFilter
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--apply',action='store_true',help='Permanently remove expired demo sessions and their files')
args=p.parse_args()
db=firestore.Client();bucket=storage.Client().bucket(os.environ['LEDGER_BUCKET'])
cutoff=(datetime.now(timezone.utc)-timedelta(hours=24)).isoformat()
for doc in db.collection_group('sessions').where(filter=FieldFilter('demo','==',True)).stream():
    meta=doc.to_dict()
    if meta['created']>=cutoff:continue
    owner=doc.reference.parent.parent.id
    if not owner.startswith('demo_'):continue
    print(('REMOVE' if args.apply else 'WOULD REMOVE'),owner,doc.id,meta['created'])
    if args.apply:
        # A private bucket prefix contains only this user's/session's objects.
        for blob in bucket.list_blobs(prefix=f'{owner}/{doc.id}/'):blob.delete()
        db.recursive_delete(doc.reference)

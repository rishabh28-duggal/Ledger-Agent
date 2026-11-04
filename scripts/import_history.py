"""Copy an existing installation's history into a named saved workspace."""
import argparse,json,sqlite3,shutil,sys,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.features import new_workspace
parser=argparse.ArgumentParser()
parser.add_argument('--source',required=True,help='Directory containing review.sqlite3 and uploaded PDFs')
parser.add_argument('--history-key',help='Existing 32-character history key from the app URL; otherwise create a new history collection')
parser.add_argument('--name',default='Imported previous invoices')
args=parser.parse_args();source=Path(args.source).resolve()
if not (source/'review.sqlite3').is_file():parser.error('Source directory has no review.sqlite3')
key=args.history_key or uuid.uuid4().hex
path=new_workspace(key,args.name)
with sqlite3.connect(f'file:{(source/"review.sqlite3").as_posix()}?mode=ro',uri=True) as old,sqlite3.connect(path/'review.sqlite3') as new:
    old.backup(new)
    ids=[r[0] for r in new.execute('SELECT id FROM invoices')]
for id in ids:
    if not __import__('re').fullmatch('[a-f0-9]{32}',id):continue
    pdf=source/(id+'.pdf')
    if pdf.is_file():shutil.copy2(pdf,path/pdf.name)
print('Imported',len(ids),'records. Original files were not changed.')
print('Open your local app using: http://localhost:8501/?history='+key)
print('Keep the history URL private; it grants access to these demo records.')

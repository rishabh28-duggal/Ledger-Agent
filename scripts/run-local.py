"""Small local launcher. Environment values override the optional .env file."""
import os
import sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
os.chdir(root);sys.path.insert(0,str(root))
env=root/'.env'
if env.exists():
    for line in env.read_text().splitlines():
        line=line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key,value=line.split('=',1)
        os.environ.setdefault(key.strip(),value.strip().strip('"').strip("'"))
import uvicorn
print('Open http://localhost:8080 — choose Try the demo to begin.')
uvicorn.run('cloud.main:app',host='127.0.0.1',port=8080)

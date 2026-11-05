import os
import secrets
from dataclasses import dataclass
from fastapi import Request, HTTPException
from itsdangerous import URLSafeTimedSerializer, BadSignature

_LOCAL_SECRET = secrets.token_hex(32)

def serializer():
    secret = os.getenv('LEDGER_SESSION_SECRET')
    if os.getenv('K_SERVICE') and not secret:
        raise RuntimeError('LEDGER_SESSION_SECRET must be configured on Cloud Run.')
    return URLSafeTimedSerializer(secret or _LOCAL_SECRET, salt='ledger-demo-v2')

@dataclass
class User:
    uid: str
    demo: bool
    email: str

def firebase_app():
    import firebase_admin
    try:
        return firebase_admin.get_app()
    except ValueError:
        return firebase_admin.initialize_app()

def user(request:Request):
    header = request.headers.get('authorization','')
    if header.startswith('Bearer '):
        try:
            from firebase_admin import auth
            firebase_app()
            decoded = auth.verify_id_token(header[7:],check_revoked=True)
            return User(decoded['uid'],False,decoded.get('email','Your account'))
        except Exception:
            raise HTTPException(401,'Your sign-in expired. Please sign in again.') from None
    cookie = request.cookies.get('ledger_demo')
    if cookie:
        try:
            uid = serializer().loads(cookie,max_age=24*60*60)
            if isinstance(uid,str) and uid.startswith('demo_'):
                return User(uid,True,'Demo workspace')
        except BadSignature:
            pass
    raise HTTPException(401,'Sign in or choose Try demo to open your workspace.')

def same_origin(request:Request):
    origin = request.headers.get('origin')
    if origin and origin != str(request.base_url).rstrip('/'):
        raise HTTPException(403,'Open Ledger directly before making changes.')

async def verify_worker(request:Request):
    if os.getenv('LEDGER_SERVICE') != 'worker':
        raise HTTPException(404)
    token = request.headers.get('authorization','').removeprefix('Bearer ')
    try:
        from google.oauth2 import id_token
        from google.auth.transport.requests import Request as GoogleRequest
        import asyncio
        decoded = await asyncio.to_thread(id_token.verify_oauth2_token,token,GoogleRequest(),os.environ['LEDGER_WORKER_URL'].rstrip('/'))
        if decoded.get('email') != os.environ['LEDGER_TASK_SERVICE_ACCOUNT'] or not decoded.get('email_verified'):
            raise ValueError('Incorrect task identity')
    except Exception:
        raise HTTPException(403,'Task identity could not be verified.') from None

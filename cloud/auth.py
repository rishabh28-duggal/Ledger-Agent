import os
import secrets
import hashlib
import re
import time
import threading
import unicodedata
import uuid
from dataclasses import dataclass
from fastapi import Request, HTTPException
from itsdangerous import URLSafeTimedSerializer, BadSignature
from argon2 import PasswordHasher, Type
from argon2.exceptions import VerificationError, InvalidHashError

_LOCAL_SECRET = secrets.token_hex(32)
PASSWORDS = PasswordHasher(type=Type.ID)
_HASH_SLOTS = threading.BoundedSemaphore(4)
# Unknown usernames still perform a real Argon2 verification.
_DUMMY_HASH = PASSWORDS.hash(secrets.token_urlsafe(32))
LOGIN_COOKIE = 'ledger_login'
CSRF_COOKIE = 'ledger_csrf'

def secure_cookies():
    return bool(os.getenv('K_SERVICE')) or os.getenv('LEDGER_COOKIE_SECURE') == '1'

def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()

def canonical_username(value):
    return unicodedata.normalize('NFKC', value).casefold()

def valid_username(value):
    return 3 <= len(value) <= 32 and all(c.isalnum() or c in '_.-' for c in value)

def login_ttl():
    return max(60, min(int(os.getenv('LEDGER_LOGIN_TTL_SECONDS', '86400')), 30*86400))

def serializer():
    secret = os.getenv('LEDGER_SESSION_SECRET')
    if os.getenv('K_SERVICE') and not secret:
        raise RuntimeError('LEDGER_SESSION_SECRET must be configured on Cloud Run.')
    return URLSafeTimedSerializer(secret or _LOCAL_SECRET, salt='ledger-demo-v2')

@dataclass
class User:
    uid: str
    demo: bool
    username: str

def user(request:Request):
    token = request.cookies.get(LOGIN_COOKIE)
    if token:
        record = request.app.state.accounts.get('logins', digest(token)) if re.fullmatch(r'[A-Za-z0-9_-]{43}', token) else None
        if record and record['expires'] > time.time():
            return User(record['uid'], False, record['username'])
        raise HTTPException(401,'Your sign-in expired. Please sign in again.')
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
    if request.headers.get('sec-fetch-site') == 'cross-site':
        raise HTTPException(403,'Open Ledger directly before making changes.')

def check_csrf(request):
    cookie = request.cookies.get(CSRF_COOKIE, '')
    header = request.headers.get('x-csrf-token', '')
    try:
        if not cookie or not secrets.compare_digest(cookie, header):
            raise BadSignature('CSRF mismatch')
        payload = serializer().loads(cookie, salt='ledger-csrf-v1', max_age=86400)
        if not isinstance(payload, str):
            raise BadSignature('Invalid CSRF token')
    except BadSignature:
        raise HTTPException(403, 'Refresh Ledger before making changes.') from None

def rate_limit(request, username, registering=False):
    """Fixed windows, atomically counted across processes; no trusted client headers."""
    now = time.time()
    ip = request.client.host if request.client else 'unknown'
    buckets = [('rates', digest('ip:' + ip)), ('rates', digest('name:' + username))]
    if registering:
        buckets = [('rates', digest('signup:' + ip))]
    limits = [10] if registering else [60, 10]
    def update(records):
        allowed = True
        for key, limit in zip(buckets, limits):
            record = records[key]
            if not record or record['expires'] <= now:
                record = {'count':0, 'expires':now+900}
            if record['count'] >= limit:
                allowed = False
            record['count'] = min(record['count']+1, limit+1)
            records[key] = record
        return allowed
    if not request.app.state.accounts.atomic(buckets, update):
        raise HTTPException(429, 'Too many attempts. Please try again later.', headers={'Retry-After':'900'})

def revoke_login(request):
    token = request.cookies.get(LOGIN_COOKIE)
    if token:
        key = ('logins', digest(token))
        request.app.state.accounts.atomic([key], lambda records: records.update({key:None}))

def issue_login(request, account):
    from fastapi.responses import JSONResponse
    revoke_login(request)
    token = secrets.token_urlsafe(32)
    key = ('logins', digest(token))
    record = {'uid':account['uid'], 'username':account['username'], 'expires':time.time()+login_ttl()}
    request.app.state.accounts.atomic([key], lambda records: records.update({key:record}))
    response = JSONResponse({'ok':True})
    response.set_cookie(LOGIN_COOKIE, token, max_age=login_ttl(), httponly=True, secure=secure_cookies(), samesite='lax', path='/')
    response.delete_cookie('ledger_demo', secure=secure_cookies(), httponly=True, samesite='lax')
    return response

def register(request, username, password):
    canonical = canonical_username(username)
    rate_limit(request, canonical, registering=True)
    if not valid_username(username) or not valid_username(canonical):
        raise HTTPException(400, 'Use a username of 3–32 letters, numbers, dots, underscores or hyphens.')
    if not 8 <= len(password) <= 1024:
        raise HTTPException(400, 'Use a password of 8–1024 characters.')
    with _HASH_SLOTS:
        password_hash = PASSWORDS.hash(password)
    account = {'uid':'acct_' + uuid.uuid4().hex, 'username':username,
               'password_hash':password_hash, 'created':time.time()}
    key = ('accounts', digest(canonical))
    def create(records):
        if records[key] is not None:
            raise HTTPException(409, 'This username is unavailable.')
        records[key] = account
    request.app.state.accounts.atomic([key], create)
    return issue_login(request, account)

def login(request, username, password):
    canonical = canonical_username(username)
    rate_limit(request, canonical)
    key = ('accounts', digest(canonical))
    account = request.app.state.accounts.get(*key)
    try:
        with _HASH_SLOTS:
            PASSWORDS.verify(account['password_hash'] if account else _DUMMY_HASH, password)
    except (VerificationError, InvalidHashError):
        raise HTTPException(401, 'Username or password is incorrect.') from None
    if not account:
        raise HTTPException(401, 'Username or password is incorrect.')
    if PASSWORDS.check_needs_rehash(account['password_hash']):
        with _HASH_SLOTS:
            account['password_hash'] = PASSWORDS.hash(password)
        request.app.state.accounts.atomic([key], lambda records: records.update({key:account}))
    return issue_login(request, account)

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

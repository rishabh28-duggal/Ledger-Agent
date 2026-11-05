"""Real account endpoints and storage; no authentication dependency overrides."""
import time
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from cloud.main import app
from cloud.auth import digest, PASSWORDS, LOGIN_COOKIE, canonical_username
from cloud.accounts import SQLiteAccounts
from test_cloud import client, add_ready, demo


def credentials(username='123', password='12345678'):
    return {'username':username, 'password':password}


def register(c, username='123', password='12345678'):
    r=c.post('/api/register',json=credentials(username,password))
    assert r.status_code==200,r.text
    return app.state.accounts.get('accounts',digest(canonical_username(username)))


def test_numeric_registration_hashes_and_matching_password(client):
    c,store=client
    account=register(c)
    assert c.get('/api/me').json()=={'username':'123','demo':False}
    assert account['uid'].startswith('acct_')
    assert account['password_hash'].startswith('$argon2id$')
    assert PASSWORDS.verify(account['password_hash'],'12345678')
    token=c.cookies.get(LOGIN_COOKIE)
    assert len(token)==43
    saved=app.state.accounts.get('logins',digest(token))
    assert saved['uid']==account['uid'] and token not in str(saved)
    with store.connect() as db:
        rows=db.execute('SELECT key,data FROM auth_records').fetchall()
        assert all(token not in str(row) and '12345678' not in str(row) for row in rows)
    c.post('/api/logout')
    bad=c.post('/api/login',json=credentials(password='wrongpassword'))
    missing=c.post('/api/login',json=credentials(username='unknown'))
    assert bad.status_code==missing.status_code==401
    assert bad.json()==missing.json()=={'detail':'Username or password is incorrect.'}
    assert c.get('/api/me').status_code==401
    assert c.post('/api/login',json=credentials()).status_code==200


@pytest.mark.parametrize('name',['ab','x'*33,'has space','a/b'])
def test_username_validation(client,name):
    c,_=client
    assert c.post('/api/register',json=credentials(name)).status_code==400


def test_case_insensitive_duplicates_and_login(client):
    c,_=client
    register(c,'Analyst')
    assert c.post('/api/register',json=credentials('ANALYST')).status_code==409
    assert c.post('/api/login',json=credentials('aNaLySt')).status_code==200
    assert c.get('/api/me').json()['username']=='Analyst'
    assert c.post('/api/register',json=credentials('another','1234567')).status_code==400
    assert c.post('/api/register',json=credentials('x'*32)).status_code==200


def test_logout_revokes_token_and_login_rotates(client):
    c,_=client
    register(c)
    old=c.cookies.get(LOGIN_COOKIE)
    assert c.post('/api/login',json=credentials()).status_code==200
    assert c.cookies.get(LOGIN_COOKIE)!=old
    assert app.state.accounts.get('logins',digest(old)) is None
    token=c.cookies.get(LOGIN_COOKIE)
    assert c.post('/api/logout').status_code==200
    assert app.state.accounts.get('logins',digest(token)) is None
    c.cookies.set(LOGIN_COOKIE,token)
    assert c.get('/api/me').status_code==401


def test_expiry_is_enforced_server_side(client):
    c,_=client
    register(c)
    key=('logins',digest(c.cookies.get(LOGIN_COOKIE)))
    def expire(records):records[key]['expires']=time.time()-1
    app.state.accounts.atomic([key],expire)
    assert c.get('/api/me').status_code==401
    assert c.get('/api/sessions').status_code==401


def test_login_survives_app_restart(client):
    c,_=client
    register(c)
    token=c.cookies.get(LOGIN_COOKIE)
    with TestClient(app) as restarted:
        restarted.cookies.set(LOGIN_COOKIE,token)
        assert restarted.get('/api/me').json()=={'username':'123','demo':False}


def test_csrf_required_on_all_browser_mutations(client):
    c,_=client
    c.headers.pop('X-CSRF-Token')
    for path in ['/api/register','/api/login','/api/logout','/api/demo','/api/sessions']:
        assert c.post(path,json=credentials()).status_code==403
    token=c.get('/api/csrf').json()['token']
    assert c.post('/api/register',json=credentials(),headers={'X-CSRF-Token':token+'bad'}).status_code==403
    assert c.post('/api/register',json=credentials(),headers={'X-CSRF-Token':token,'Origin':'https://evil.invalid'}).status_code==403
    assert c.post('/api/register',json=credentials(),headers={'X-CSRF-Token':token,'Sec-Fetch-Site':'cross-site'}).status_code==403
    assert c.post('/api/register',json=credentials(),headers={'X-CSRF-Token':token}).status_code==200


def test_login_rate_limit_persists_across_clients(client):
    c,_=client
    register(c)
    for _ in range(10):
        assert c.post('/api/login',json=credentials(password='wrongpass')).status_code==401
    r=c.post('/api/login',json=credentials())
    assert r.status_code==429 and r.headers['Retry-After']=='900'
    # A new client/process has the same durable username limit.
    with TestClient(app,client=('other-address',123)) as other:
        other.headers['X-CSRF-Token']=other.get('/api/csrf').json()['token']
        assert other.post('/api/login',json=credentials()).status_code==429


def test_unknown_username_also_rate_limited_and_window_expires(client):
    c,_=client
    for _ in range(10):
        assert c.post('/api/login',json=credentials('missing')).status_code==401
    assert c.post('/api/login',json=credentials('missing')).status_code==429
    key=('rates',digest('name:missing'))
    def expire(records):records[key]['expires']=time.time()-1
    app.state.accounts.atomic([key],expire)
    assert c.post('/api/login',json=credentials('missing')).status_code==401


def test_two_accounts_and_legacy_demo_ownership(client):
    c,store=client
    legacy=store.create('legacy_firebase_uid','Old history')['id']
    demo_sid=demo(c)
    account=register(c,'Alice')
    assert c.get('/api/sessions').json()==[]
    sid=c.post('/api/sessions',json={'name':'Alice folder'}).json()['id']
    iid=add_ready(store,account['uid'],sid)
    store.put_file(account['uid'],sid,iid,b'original','application/pdf')
    alice_cookie=c.cookies.get(LOGIN_COOKIE)
    c.post('/api/logout')
    register(c,'Bob')
    assert c.get('/api/sessions').json()==[]
    for folder in [sid,demo_sid,legacy]:
        assert c.get('/api/sessions/'+folder).status_code==404
    base=f'/api/sessions/{sid}'
    for path in [f'/invoices/{iid}',f'/invoices/{iid}/file',f'/invoices/{iid}/original','/export','/export?format=json']:
        assert c.get(base+path).status_code==404
    for action in ['approve','retry','review']:
        body={'expected_run':1}
        if action=='review':body['data']={}
        assert c.post(base+f'/invoices/{iid}/{action}',json=body).status_code==404
    assert c.put(base+'/master',json={'vendors':[],'pos':[]}).status_code==404
    from cloud.repository import ROOT
    assert c.post(base+'/invoices',files={'file':('invoice.pdf',(ROOT/'samples/01_happy_60_chairs.pdf').read_bytes(),'application/pdf')}).status_code==404
    assert store.snapshot('legacy_firebase_uid',legacy)[0]['name']=='Old history'
    assert store.get_file(account['uid'],sid,iid)==b'original'
    # Logging back in restores only Alice's account, not her prior demo.
    assert c.post('/api/login',json=credentials('alice')).status_code==200
    assert [x['id'] for x in c.get('/api/sessions').json()]==[sid]
    assert c.get(base+f'/invoices/{iid}/original').content==b'original'
    assert alice_cookie!=c.cookies.get(LOGIN_COOKIE)


def test_demo_remains_separate_and_revokes_current_login(client):
    c,_=client
    register(c)
    token=c.cookies.get(LOGIN_COOKIE)
    sid=demo(c)
    assert c.get('/api/me').json()['demo'] is True
    assert app.state.accounts.get('logins',digest(token)) is None
    assert c.get('/api/sessions/'+sid).status_code==200
    c.post('/api/logout')
    assert c.get('/api/me').status_code==401


def test_cookie_flags_and_no_firebase_configuration(client,monkeypatch):
    c,_=client
    r=c.post('/api/register',json=credentials())
    cookie=r.headers.get_list('set-cookie')[0]
    assert 'HttpOnly' in cookie and 'SameSite=lax' in cookie and 'Path=/' in cookie
    monkeypatch.setenv('LEDGER_COOKIE_SECURE','1')
    r=c.post('/api/login',json=credentials())
    assert 'Secure' in r.headers.get_list('set-cookie')[0]
    assert 'firebase' not in c.get('/api/config').text.lower()


def test_sqlite_uniqueness_is_atomic_and_survives_restart(tmp_path):
    store=SQLiteAccounts(tmp_path)
    key=('accounts',digest('123'))
    def attempt(i):
        def create(records):
            if records[key]:return False
            records[key]={'uid':str(i)}
            return True
        return store.atomic([key],create)
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(attempt,range(8)))==1
    assert SQLiteAccounts(tmp_path).get(*key)==store.get(*key)

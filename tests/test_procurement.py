from test_cloud import client, demo, uid, add_ready
from cloud.repository import procurement_master


def test_each_new_folder_gets_an_independent_procurement_list(client):
    c,store=client;sid=demo(c);owner=uid(c)
    second=c.post('/api/sessions',json={'name':'Next folder'}).json()['id']
    master=procurement_master()
    assert master['vendors'] and master['pos']
    assert c.get('/api/sessions/'+second).json()['session']['master']==master
    store.atomic(owner,sid,lambda meta,rows:meta['master']['vendors'][0].update(name='Changed vendor'))
    assert c.get('/api/sessions/'+second).json()['session']['master']==master


def test_existing_empty_folder_is_initialized_once_and_findings_rechecked(client):
    c,store=client;sid=demo(c);owner=uid(c)
    def legacy(meta,rows):
        meta.pop('procurement_version',None)
        meta['master']={'vendors':[],'pos':[]}
    store.atomic(owner,sid,legacy)
    iid=add_ready(store,owner,sid)
    assert store.snapshot(owner,sid)[1][0]['result']['status']=='Needs review'
    response=c.get('/api/sessions/'+sid).json()
    assert response['session']['master']==procurement_master()
    assert response['invoices'][0]['result']['status']=='Ready for approval'
    before=store.snapshot(owner,sid)
    assert before[1][0]['audit'][-1]['action']=='procurement_initialized'
    assert c.get('/api/sessions/'+sid).status_code==200
    assert store.snapshot(owner,sid)==before
    assert before[1][0]['id']==iid


def test_existing_custom_and_approved_procurement_is_unchanged(client):
    c,store=client;sid=demo(c);owner=uid(c)
    def custom(meta,rows):
        meta.pop('procurement_version',None)
        meta['master']={'vendors':[{'id':'custom','name':'Own vendor'}],'pos':[]}
    store.atomic(owner,sid,custom)
    assert c.get('/api/sessions/'+sid).json()['session']['master']['vendors'][0]['id']=='custom'
    locked=store.create(owner,'Legacy approval',True)['id']
    iid=add_ready(store,owner,locked)
    def legacy_approval(meta,rows):
        meta.pop('procurement_version',None)
        meta['master']={'vendors':[],'pos':[]}
        rows[iid]['accepted']=True
    store.atomic(owner,locked,legacy_approval)
    assert c.get('/api/sessions/'+locked).json()['session']['master']=={'vendors':[],'pos':[]}


def test_intentionally_cleared_list_is_not_repopulated(client):
    c,store=client;sid=demo(c)
    assert c.put('/api/sessions/'+sid+'/master',json={'vendors':[],'pos':[]}).status_code==200
    assert c.get('/api/sessions/'+sid).json()['session']['master']=={'vendors':[],'pos':[]}

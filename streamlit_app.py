"""Streamlit Community Cloud entry point. Reuses the tested FastAPI service functions."""
import asyncio
import hashlib
import json
import os
import secrets
import tempfile
import uuid
from pathlib import Path

import streamlit as st
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from app import store as s
from app.domain import Invoice
from app.features import owner_root,workspaces,new_workspace,workspace_path,priority,accepted_csv,evaluate_original,fix_for,run_batch
from app.extract import read_pdf
from app.review import pending_verifications, prepare_verification
from app.main import process, approve, dashboard

st.set_page_config(page_title='Ledger | Invoice Review', page_icon='📋',layout='wide')

@st.cache_resource
def configure_providers():
    """Copy deployment-owned secrets to server environment, never browser inputs."""
    for name in ['GROQ_API_KEY','GROQ_MODEL','GEMINI_API_KEY','GEMINI_MODEL','AP_ACCESS_TOKEN']:
        try: value=st.secrets.get(name)
        except FileNotFoundError: value=None
        if value is not None: os.environ[name]=str(value)
    return True

configure_providers()
access=os.getenv('AP_ACCESS_TOKEN')
if access and not st.session_state.get('access_granted'):
    st.title('Ledger')
    with st.form('access'):
        entered=st.text_input('Demo access code',type='password')
        if st.form_submit_button('Open workspace'):
            if secrets.compare_digest(entered,access):
                st.session_state.access_granted=True;st.rerun()
            else: st.error('Incorrect access code.')
    st.stop()

# A capability key in the bookmarked URL isolates each visitor's durable history.
if 'history_key' not in st.session_state:
    key=st.query_params.get('history','')
    if not __import__('re').fullmatch('[a-f0-9]{32}',key):key=uuid.uuid4().hex
    st.session_state.history_key=key
    st.query_params['history']=key
if 'workspace' not in st.session_state:
    saved=workspaces(st.session_state.history_key)
    path=workspace_path(st.session_state.history_key,saved[0]['id']) if saved else new_workspace(st.session_state.history_key,'First review session')
    st.session_state.workspace=str(path)
    st.session_state.selected_invoice=None
    st.session_state.page='Review queue'

def money(value):
    return f'₹{float(value or 0):,.2f}'

def load(id):
    with s.connection() as db: return s.get(db,id)

def notify(message):
    st.session_state.flash=message

def run_invoice(id,rerun=False):
    names={'ingest':'Receive & fingerprint','extract':'Read invoice','completeness':'Check required fields','vendor':'Identify vendor','po':'Match purchase order','checks':'Check rules and balances','decision':'Record recommendation'}
    with st.status('Review in progress',expanded=True) as status:
        stage_boxes={}
        def event(stage,state,payload):
            if stage not in stage_boxes: stage_boxes[stage]=st.empty()
            symbol={'running':'⏳','done':'✓','failed':'✕'}[state]
            stage_boxes[stage].write(f"{symbol} {names[stage]} — {payload.get('message') or state}")
            if state=='failed': st.error(payload['error'])
        asyncio.run(process(id,rerun,on_event=event))
        row=load(id)
        status.update(label='Review complete' if row['execution']=='completed' else 'Processing failed — see details',state='complete' if row['execution']=='completed' else 'error',expanded=True)
    st.session_state.selected_invoice=id
    st.session_state.page='Invoice detail'

def ingest(raw,filename,mode):
    if len(raw)>10*1024*1024: raise ValueError('Maximum PDF size is 10 MB.')
    if not raw.startswith(b'%PDF-'): raise ValueError('Upload a valid PDF.')
    read_pdf(raw)
    with s.connection() as db:
        if db.execute('SELECT COUNT(*) FROM invoices').fetchone()[0]>=30:
            raise ValueError('This demo workspace has 30 submissions. Reset your workspace before adding more.')
    id=uuid.uuid4().hex
    (s.data_dir()/(id+'.pdf')).write_bytes(raw)
    with s.connection() as db:
        db.execute('INSERT INTO invoices(id,filename,hash,mode,created,execution) VALUES(?,?,?,?,?,?)',(id,Path(filename).name,hashlib.sha256(raw).hexdigest(),mode,s.now(),'queued'))
    run_invoice(id)
    return id

def rerun_invoice(id,action,details,data=None,po=None):
    if action=='retry':
        remaining=s.retry_remaining(id)
        if remaining:raise ValueError(f'Rate limited. Retry after {remaining} seconds.')
    with s.connection() as db:
        db.execute('BEGIN IMMEDIATE');row=s.get(db,id)
        if row['accepted']: raise ValueError('Accepted invoices are read-only.')
        if row['execution'] in ['queued','running']: raise ValueError('A review is already running.')
        s.review(db,id,action,details)
        if data is not None: db.execute('UPDATE invoices SET data=? WHERE id=?',(data.model_dump_json(),id))
        if po is not None: db.execute('UPDATE invoices SET selected_po=? WHERE id=?',(po,id))
        db.execute("UPDATE invoices SET run=run+1,execution='queued',result=NULL WHERE id=?",(id,))
    run_invoice(id,rerun=bool(data or row['data']))

def source_view(row):
    raw=(s.data_dir()/(row['id']+'.pdf')).read_bytes()
    st.download_button('Download source PDF',raw,file_name=row['filename'],mime='application/pdf',key='pdf_download_'+row['id'])
    try: st.pdf(raw,height=680)
    except Exception:
        # Server-side raster preview remains functional if the optional PDF widget cannot load.
        import pypdfium2 as pdfium
        doc=pdfium.PdfDocument(raw)
        try:
            page_index=st.selectbox('Preview page',range(len(doc)),format_func=lambda i:f'Page {i+1}')
            page=doc[page_index]
            try:
                bitmap=page.render(scale=1.4)
                try: st.image(bitmap.to_pil(),use_container_width=True)
                finally: bitmap.close()
            finally: page.close()
        finally: doc.close()

def detail_view(row):
    if not row: st.info('Select an invoice from the review queue.');return
    data=row['data'] or {};result=row['result']
    st.subheader(data.get('invoice_no') or row['filename'])
    st.caption(f"{data.get('vendor') or 'Vendor unresolved'} · {money(data.get('total'))} · {row['mode'].upper()} reader · Run {row['run']}")
    left,right=st.columns([1.05,1],gap='large')
    with right:
        st.markdown('#### Source document');source_view(row)
    with left:
        if row['accepted']: st.success('Accepted by Demo reviewer. PO balance recorded once. This invoice is read-only.')
        if result:
            status=result['status']
            {'Ready for approval':st.success,'Needs review':st.warning,'Blocked':st.error}[status](status)
            st.write(result['summary'])
            if status=='Ready for approval' and not row['accepted']:
                if st.button('Approve invoice',type='primary',key='approve_'+row['id']):
                    response=approve(row['id'])
                    if isinstance(response,JSONResponse):
                        notify(json.loads(response.body)['detail'])
                    else: notify('Invoice accepted. PO balance updated once.')
                    st.rerun()
            if result.get('candidates') and len(result['candidates'])>1 and not row['accepted']:
                st.caption('Choose the intended purchasing record; selection still runs all checks.')
                with st.form('po_selection'):
                    po=st.selectbox('Purchase order',result['candidates'])
                    if st.form_submit_button('Select PO & rerun'):
                        rerun_invoice(row['id'],'select_po',{'after':po},po=po);st.rerun()
            st.markdown('#### Checks and evidence')
            for check in result['checks']:
                symbol={'pass':'✓','review':'⚠','block':'✕','not_evaluated':'—'}[check['level']]
                with st.expander(f"{symbol} {check['message']}"):
                    st.json(check['evidence'])
                    st.info('Next action: '+check.get('fix',fix_for(check)))
            if result.get('email'):
                with st.expander('Vendor email draft — not sent'):
                    st.text_area('Review and copy this draft',result['email'],height=220,disabled=True)
        elif row['execution']=='failed':
            st.error('Processing failed. This is separate from an invoice rejection.')
            with s.connection() as db:
                failure=db.execute("SELECT payload FROM events WHERE invoice_id=? AND state='failed' ORDER BY seq DESC LIMIT 1",(row['id'],)).fetchone()
            if failure: st.write(json.loads(failure[0]))
            remaining=s.retry_remaining(row['id'])
            if remaining:
                st.warning(f'Provider rate limit: retry available in about {remaining} seconds.')
                if st.button('Refresh retry availability'):st.rerun()
            if st.button('Retry processing',key='retry_'+row['id'],disabled=remaining>0):
                rerun_invoice(row['id'],'retry',{});st.rerun()
        if data:
            confirmable=pending_verifications(data)
            if confirmable and not row['accepted'] and row['execution']=='completed':
                st.markdown('#### Verify uncertain fields')
                st.caption('Compare the values with the PDF on the right. Confirm only values you can read clearly. All invoice and PO rules will run again.')
                for field in confirmable:
                    evidence=data.get('evidence',{}).get(field) or {}
                    st.write(f"**{field.replace('_',' ').title()}:** {data[field]}")
                    if isinstance(evidence,dict):
                        st.caption(f"Source page {evidence.get('page') or '?'} · {evidence.get('snippet') or 'No model source snippet'}")
                with st.form('verify_fields_'+row['id']+'_'+str(row['run'])):
                    selected=st.multiselect('Fields verified against source PDF',confirmable,format_func=lambda field:field.replace('_',' ').title())
                    compared=st.checkbox('I compared the selected values with the source PDF and confirm they are correct.')
                    if st.form_submit_button('Confirm selected fields & rerun'):
                        if not compared: st.warning('Compare the selected values with the PDF and tick the confirmation first.')
                        elif not selected: st.warning('Select the fields you verified.')
                        else:
                            prepare_verification(row['id'],selected,expected_run=row['run'])
                            run_invoice(row['id'],rerun=True)
                            notify('Selected fields verified and logged. All invoice and PO checks have been rerun.')
                            st.rerun()
            with st.expander('Extracted fields and source evidence'):
                st.json(data)
            if not row['accepted']:
                with st.expander('Correct extracted fields'):
                    st.caption('Verify against the source. Every edit is logged and revalidated.')
                    with st.form('field_corrections_'+row['id']):
                        scalar=['vendor','gstin','vendor_reference','invoice_no','date','po_ref','currency','tax_basis','subtotal','tax','tax_rate','total']
                        values={key:st.text_input(key.replace('_',' ').title(),str(data.get(key) or ''),key='field_'+row['id']+'_'+key) for key in scalar}
                        st.markdown('**Invoice lines**')
                        lines=st.data_editor(data.get('lines',[]),num_rows='dynamic',hide_index=True,key='lines_'+row['id'],use_container_width=True)
                        if st.form_submit_button('Save corrections & rerun'):
                            corrected=dict(data)
                            corrected['evidence']=dict(data.get('evidence',{}))
                            corrected['uncertain_fields']=list(data.get('uncertain_fields',[]))
                            for key,value in values.items():
                                value=value.strip() or None
                                if str(value or '')!=str(data.get(key) or ''):
                                    corrected['evidence'][key]={'page':None,'snippet':'Reviewer correction; original preserved','confidence':'human corrected'}
                                    corrected['uncertain_fields']=[f for f in corrected['uncertain_fields'] if f!=key]
                                corrected[key]=value
                            corrected['lines']=lines
                            validated=Invoice.model_validate(corrected)
                            rerun_invoice(row['id'],'correct',{'before':data,'after':json.loads(validated.model_dump_json())},data=validated)
                            st.rerun()
        with st.expander('Run and review history'):
            with s.connection() as db:
                for event in db.execute('SELECT * FROM events WHERE invoice_id=? ORDER BY seq',(row['id'],)):
                    st.caption(f"Run {event['run']} · {event['stage']} · {event['state']} · {event['created']}")
                for review in db.execute('SELECT * FROM reviews WHERE invoice_id=? ORDER BY seq',(row['id'],)):
                    st.write(review['action']+' · '+review['created']);st.json(json.loads(review['details']))

@st.cache_resource
def recover_saved_workspace(path):
    with s.use_workspace(path):s.init()
    return True

def application():
    recover_saved_workspace(str(s.data_dir()))
    with st.sidebar:
        st.title('ledger.')
        st.caption('ACCOUNTS PAYABLE · DEMO')
        saved=workspaces(st.session_state.history_key)
        ids=[m['id'] for m in saved]
        selected=st.selectbox('Saved review sessions',ids,index=ids.index(Path(st.session_state.workspace).name),format_func=lambda id:next(m['name']+' · '+m['created'][:10] for m in saved if m['id']==id))
        if selected!=Path(st.session_state.workspace).name:
            st.session_state.workspace=str(workspace_path(st.session_state.history_key,selected))
            st.session_state.selected_invoice=None;st.session_state.page='Review queue';st.session_state.pop('batch_summary',None);st.rerun()
        with st.form('create_workspace'):
            name=st.text_input('New session name',placeholder='Demo rehearsal 2')
            if st.form_submit_button('Start new session'):
                st.session_state.workspace=str(new_workspace(st.session_state.history_key,name))
                st.session_state.selected_invoice=None;st.session_state.page='Review queue';st.session_state.pop('batch_summary',None);st.rerun()
        pages=['Review queue','New invoice','Purchase orders','Demo documents','Extraction scorecard','Invoice detail']
        for destination in pages:
            if st.button(destination,key='nav_'+destination,type='primary' if st.session_state.page==destination else 'secondary',use_container_width=True):
                st.session_state.page=destination;st.rerun()
        st.divider()
        st.caption('Bookmark this URL to reopen your saved sessions. Anyone with the history link can access them. Local history survives restarts; hosted history needs a durable LEDGER_ARCHIVE_DIR mount.')
        st.caption('Recommendation only. No payment execution.')
        configured=[name for name,key in [('Groq','GROQ_API_KEY'),('Gemini','GEMINI_API_KEY')] if os.getenv(key)]
        st.caption('Configured readers: '+(', '.join(configured) or 'Local sample reader only'))
    st.title('Invoice review')
    st.caption('From document to decision, with the evidence to back it up.')
    if st.session_state.get('flash'):st.info(st.session_state.pop('flash'))
    snapshot=dashboard();rows=sorted(snapshot['invoices'],key=lambda r:priority(r['result'])[1] if not r['accepted'] else 0,reverse=True)
    if any(v.get('gstin','').startswith('DEMO-') for v in snapshot['vendors']):
        st.warning('This workspace has older demo GSTINs. To use the updated PDFs, choose Show demo reset → Reset my workspace. This clears this workspace’s invoices and reloads the current vendor/PO fixtures.')
    accepted=sum(bool(r['accepted']) for r in rows)
    cols=st.columns(4)
    for col,label,value in zip(cols,['Total invoices','Ready for approval','Needs review','Accepted'],[len(rows),sum(not r['accepted'] and (r['result'] or {}).get('status')=='Ready for approval' for r in rows),sum((r['result'] or {}).get('status')=='Needs review' for r in rows),accepted]):col.metric(label,value)
    page=st.session_state.page
    if page=='Review queue':
        batchfile=s.data_dir()/'last_batch.json'
        if batchfile.exists():
            batch=json.loads(batchfile.read_text())
            st.markdown('#### Last batch results');st.dataframe(batch['summary'],hide_index=True,use_container_width=True)
            for vendor,requests in batch.get('vendor_followups',{}).items():
                with st.expander('Combined vendor follow-up: '+vendor):
                    draft='Subject: Invoice review clarifications\n\nHello,\nPlease help resolve these findings:\n\n'+'\n\n'.join(requests)+'\n\nThank you,\nAccounts Payable'
                    st.text_area('Draft only; no email is sent',draft,height=220,key='vendor_email_'+vendor)
        if not rows:st.info('Upload an invoice or start with a demo document.')
        else:
            status_filter=st.selectbox('Filter',['All','Ready for approval','Needs review','Blocked','Accepted','failed'])
            visible=[r for r in rows if status_filter=='All' or (('Accepted' if r['accepted'] else (r['result'] or {}).get('status',r['execution']))==status_filter)]
            st.dataframe([{'Priority':priority(r['result'])[0],'Invoice':(r['data'] or {}).get('invoice_no') or r['filename'],'Vendor':(r['data'] or {}).get('vendor'),'Amount':money((r['data'] or {}).get('total')),'PO':r['po'],'Status':'Accepted' if r['accepted'] else (r['result'] or {}).get('status',r['execution']),'Received':r['created']} for r in visible],use_container_width=True,hide_index=True)
            if visible:
                id=st.selectbox('Open invoice',[r['id'] for r in visible],format_func=lambda id:next(((r['data'] or {}).get('invoice_no') or r['filename'])+' · '+id[:6] for r in visible if r['id']==id))
                if st.button('View invoice'):
                    st.session_state.selected_invoice=id;st.session_state.page='Invoice detail';st.rerun()
            st.download_button('Export accepted invoices (CSV)',accepted_csv(rows),file_name='accepted-invoices.csv',mime='text/csv')
            st.download_button('Export review records (JSON)',s.dumps(rows),file_name='ledger-review-export.json',mime='application/json')
    elif page in ['New invoice','Demo documents']:
        readers=['groq','gemini','local'];default=0 if os.getenv('GROQ_API_KEY') else 1 if os.getenv('GEMINI_API_KEY') else 2
        mode=st.selectbox('Document reader',readers,index=default,format_func=lambda x:{'groq':'Groq vision · up to 3 pages','gemini':'Gemini · up to 20 pages','local':'Local labelled sample reader · not AI'}[x])
        if mode=='local':st.caption('Local mode only parses the labelled sample text PDFs. Varied layouts and scans require an AI reader.')
        else:st.caption('The selected provider receives your document/pages for extraction. Use synthetic invoices in this public demo.')
        if page=='New invoice':
            files=st.file_uploader('Upload up to five invoice PDFs',type=['pdf'],accept_multiple_files=True)
            if st.button('Start review',type='primary',disabled=not files):
                if len(files)>5:st.error('Select at most five PDFs.')
                else:
                    batch=run_batch([(f.name,f.getvalue()) for f in files],lambda raw,name:ingest(raw,name,mode),load,s.retry_remaining)
                    (s.data_dir()/'last_batch.json').write_text(s.dumps(batch))
                    st.session_state.page='Review queue';st.rerun()
        else:
            st.info('Run 01 and explicitly approve it before running 02. Then test duplicates, the ambiguous PO and scan.')
            pack=st.selectbox('Document set',['Basic workflow samples','Realistic extraction test pack'])
            sample_dir=s.ROOT/('samples' if pack=='Basic workflow samples' else 'test_pack/invoices')
            if pack!='Basic workflow samples':st.caption('Run R01 and approve it before R02; R03 is a reissued duplicate. Test R04-R07 independently. Answer key is in GitHub test_pack/answer_key.json.')
            samples=sorted(sample_dir.glob('*.pdf'))
            selected=st.selectbox('Demo invoice',samples,format_func=lambda p:p.name)
            a,b=st.columns(2)
            with a:
                if st.button('Run sample review',type='primary'):
                    ingest(selected.read_bytes(),selected.name,mode);st.rerun()
            with b:st.download_button('Download sample PDF',selected.read_bytes(),file_name=selected.name,mime='application/pdf')
    elif page=='Extraction scorecard':
        st.caption('Measures original extraction before corrections. Match each run to a fixture explicitly; the answer key is never sent to a model.')
        cases=json.loads((s.ROOT/'test_pack/answer_key.json').read_text())['cases']
        eligible=[r for r in rows if r['original']]
        if not eligible:st.info('Process a realistic invoice first.')
        else:
            chosen=st.selectbox('Extraction run',[r['id'] for r in eligible],format_func=lambda id:next(r['filename']+' · '+id[:6] for r in eligible if r['id']==id))
            case=st.selectbox('Expected fixture',cases,format_func=lambda c:Path(c['file']).name)
            record=next(r for r in eligible if r['id']==chosen)
            scorefile=s.data_dir()/'scorecard.json'
            scores=json.loads(scorefile.read_text()) if scorefile.exists() else {}
            if st.button('Score original extraction'):
                scores[chosen]={'fixture':case['file'],'fields':evaluate_original(record['original'],case['expected_extraction'])}
                scorefile.write_text(s.dumps(scores))
            selected=[v for key,v in scores.items() if key in {r['id'] for r in rows}]
            observations=[field for value in selected for field in value['fields']]
            if observations:
                st.metric('Original extraction field accuracy',f"{sum(f['correct'] for f in observations)/len(observations):.1%}")
                st.caption(f'{len(selected)} scored runs; user-selected synthetic fixtures, not an independent production benchmark.')
                st.dataframe([{'Field':name,'Correct':sum(f['correct'] for f in observations if f['field']==name),'Evaluated':sum(f['field']==name for f in observations)} for name in sorted({f['field'] for f in observations})],hide_index=True)
                st.json(selected)
                st.download_button('Export scorecard',s.dumps(selected),file_name='extraction-scorecard.json',mime='application/json')
    elif page=='Purchase orders':
        st.caption('Only accepted invoices consume quantity and authorised value.')
        for po in snapshot['pos']:
            with st.container(border=True):
                st.subheader(po['number']);st.write(next(v['name'] for v in snapshot['vendors'] if v['id']==po['vendor_id']))
                st.progress(min(1.0,max(0,float(po['used'])/float(po['total']))),text=f"Accepted {money(po['used'])} of {money(po['total'])}")
                st.dataframe([{'Item':l['item'],'Accepted quantity':l['used'],'Ordered quantity':l['qty'],'Unit price':money(l['price'])} for l in po['lines']],hide_index=True,use_container_width=True)
    else:detail_view(load(st.session_state.selected_invoice) if st.session_state.selected_invoice else None)

with s.use_workspace(st.session_state.workspace):
    try: application()
    except (ValueError,ValidationError,HTTPException) as error:
        st.error(error.detail if isinstance(error,HTTPException) else str(error))

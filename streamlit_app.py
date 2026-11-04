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
from app.extract import read_pdf
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

if 'workspace' not in st.session_state:
    st.session_state.workspace=tempfile.mkdtemp(prefix='ledger-demo-')
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
            stage_boxes[stage].write(f'{symbol} {names[stage]} — {state}')
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

def rerun_invoice(id,action,details,data=None,po=None):
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
            if result.get('email'):
                with st.expander('Vendor email draft — not sent'):
                    st.text_area('Review and copy this draft',result['email'],height=220,disabled=True)
        elif row['execution']=='failed':
            st.error('Processing failed. This is separate from an invoice rejection.')
            with s.connection() as db:
                failure=db.execute("SELECT payload FROM events WHERE invoice_id=? AND state='failed' ORDER BY seq DESC LIMIT 1",(row['id'],)).fetchone()
            if failure: st.write(json.loads(failure[0]))
            if st.button('Retry processing',key='retry_'+row['id']):
                rerun_invoice(row['id'],'retry',{});st.rerun()
        if data:
            with st.expander('Extracted fields and source evidence'):
                st.json(data)
            if not row['accepted']:
                with st.expander('Correct extracted fields'):
                    st.caption('Verify against the source. Every edit is logged and revalidated.')
                    with st.form('field_corrections_'+row['id']):
                        scalar=['vendor','gstin','invoice_no','date','po_ref','currency','tax_basis','subtotal','tax','tax_rate','total']
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

def application():
    if not s.db_path().exists(): s.init()
    with st.sidebar:
        st.title('ledger.')
        st.caption('ACCOUNTS PAYABLE · DEMO')
        pages=['Review queue','New invoice','Purchase orders','Demo documents','Invoice detail']
        for destination in pages:
            if st.button(destination,key='nav_'+destination,type='primary' if st.session_state.page==destination else 'secondary',use_container_width=True):
                st.session_state.page=destination;st.rerun()
        st.divider()
        st.caption('Your workspace is private to this browser session. History may reset after refresh, disconnect, reboot or redeployment. Download an export before leaving.')
        st.caption('Recommendation only. No payment execution.')
        configured=[name for name,key in [('Groq','GROQ_API_KEY'),('Gemini','GEMINI_API_KEY')] if os.getenv(key)]
        st.caption('Configured readers: '+(', '.join(configured) or 'Local sample reader only'))
        if st.checkbox('Show demo reset'):
            if st.button('Reset my workspace',type='secondary'):
                with s.connection() as db:
                    db.execute('DELETE FROM events');db.execute('DELETE FROM reviews');db.execute('DELETE FROM invoices')
                for p in s.data_dir().glob('*.pdf'):p.unlink(missing_ok=True)
                st.session_state.selected_invoice=None;st.session_state.page='Review queue';notify('Your workspace was reset.');st.rerun()
    st.title('Invoice review')
    st.caption('From document to decision, with the evidence to back it up.')
    if st.session_state.get('flash'):st.info(st.session_state.pop('flash'))
    snapshot=dashboard();rows=snapshot['invoices']
    accepted=sum(bool(r['accepted']) for r in rows)
    cols=st.columns(4)
    for col,label,value in zip(cols,['Total invoices','Ready for approval','Needs review','Accepted'],[len(rows),sum(not r['accepted'] and (r['result'] or {}).get('status')=='Ready for approval' for r in rows),sum((r['result'] or {}).get('status')=='Needs review' for r in rows),accepted]):col.metric(label,value)
    page=st.session_state.page
    if page=='Review queue':
        if not rows:st.info('Upload an invoice or start with a demo document.')
        else:
            status_filter=st.selectbox('Filter',['All','Ready for approval','Needs review','Blocked','Accepted','failed'])
            visible=[r for r in rows if status_filter=='All' or (('Accepted' if r['accepted'] else (r['result'] or {}).get('status',r['execution']))==status_filter)]
            st.dataframe([{'Invoice':(r['data'] or {}).get('invoice_no') or r['filename'],'Vendor':(r['data'] or {}).get('vendor'),'Amount':money((r['data'] or {}).get('total')),'PO':r['po'],'Status':'Accepted' if r['accepted'] else (r['result'] or {}).get('status',r['execution']),'Received':r['created']} for r in visible],use_container_width=True,hide_index=True)
            if visible:
                id=st.selectbox('Open invoice',[r['id'] for r in visible],format_func=lambda id:next(((r['data'] or {}).get('invoice_no') or r['filename'])+' · '+id[:6] for r in visible if r['id']==id))
                if st.button('View invoice'):
                    st.session_state.selected_invoice=id;st.session_state.page='Invoice detail';st.rerun()
            st.download_button('Export review records (JSON)',s.dumps(rows),file_name='ledger-review-export.json',mime='application/json')
    elif page in ['New invoice','Demo documents']:
        readers=['groq','gemini','local'];default=0 if os.getenv('GROQ_API_KEY') else 1 if os.getenv('GEMINI_API_KEY') else 2
        mode=st.selectbox('Document reader',readers,index=default,format_func=lambda x:{'groq':'Groq vision · up to 3 pages','gemini':'Gemini · up to 20 pages','local':'Local labelled sample reader · not AI'}[x])
        if mode=='local':st.caption('Local mode only parses the labelled sample text PDFs. Varied layouts and scans require an AI reader.')
        else:st.caption('The selected provider receives your document/pages for extraction. Use synthetic invoices in this public demo.')
        if page=='New invoice':
            file=st.file_uploader('Upload invoice PDF',type=['pdf'])
            if st.button('Start review',type='primary',disabled=file is None):
                ingest(file.getvalue(),file.name,mode);st.rerun()
        else:
            st.info('Run 01 and explicitly approve it before running 02. Then test duplicates, the ambiguous PO and scan.')
            samples=sorted((s.ROOT/'samples').glob('*.pdf'))
            selected=st.selectbox('Demo invoice',samples,format_func=lambda p:p.name)
            a,b=st.columns(2)
            with a:
                if st.button('Run sample review',type='primary'):
                    ingest(selected.read_bytes(),selected.name,mode);st.rerun()
            with b:st.download_button('Download sample PDF',selected.read_bytes(),file_name=selected.name,mime='application/pdf')
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

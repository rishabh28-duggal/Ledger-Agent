"""Streamlit Community Cloud entry point. Reuses the tested FastAPI service functions."""
import asyncio
import hashlib
import json
import os
import secrets
import tempfile
import uuid
import time
from html import escape
from ui.theme import apply_theme
from ui.components import money, pill, STAGES, fields_table, show_finding, audit_timeline, timestamp, queue_rank, problem_message
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

st.set_page_config(page_title='Ledger | Invoice Review', layout='wide')

apply_theme()

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

def load(id):
    with s.connection() as db: return s.get(db,id)

def notify(message):
    st.session_state.flash=message

def run_invoice(id,rerun=False):
    started=time.monotonic()
    with st.status('Review in progress',expanded=True) as status:
        stage_boxes={stage:st.empty() for stage in STAGES}
        states={stage:'Waiting' for stage in STAGES}
        def paint(stage,message=''):
            symbol={'Waiting':'○','Running':'…','Done':'✓','Failed':'×'}[states[stage]]
            stage_boxes[stage].html(f'<div class="stage"><span>{symbol} {states[stage]}</span> {escape(STAGES[stage])}<br>{escape(message)}</div>')
        for stage in STAGES:paint(stage)
        def event(stage,state,payload):
            states[stage]={'running':'Running','done':'Done','failed':'Failed'}[state]
            message=payload.get('message') or payload.get('error') or ''
            paint(stage,f'{message}  Elapsed: {int(time.monotonic()-started)} seconds')
        asyncio.run(process(id,rerun,on_event=event))
        row=load(id)
        status.update(label='Review complete' if row['execution']=='completed' else 'Review interrupted; document saved',state='complete' if row['execution']=='completed' else 'error',expanded=True)
    st.session_state.selected_invoice=id
    st.session_state.page='Invoice detail'

def ingest(raw,filename,mode):
    if len(raw)>10*1024*1024: raise ValueError('Maximum PDF size is 10 MB.')
    if not raw.startswith(b'%PDF-'): raise ValueError('Upload a valid PDF.')
    read_pdf(raw)
    with s.connection() as db:
        if db.execute('SELECT COUNT(*) FROM invoices').fetchone()[0]>=30:
            raise ValueError('This demo workspace has 30 submissions. Start a new review session before adding more.')
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
    st.title(data.get('invoice_no') or row['filename'])
    header,amount=st.columns([3,1])
    with header:st.write(data.get('vendor') or 'Vendor unresolved')
    with amount:st.html(f'<div class="amount">{escape(money(data.get("total")))}</div>')
    if result:
        findings=[c for c in result['checks'] if c['level']!='pass']
        st.write(problem_message(findings[0]) if findings else 'All required checks passed; review the source PDF before approving.')
    left,right=st.columns([1.15,1],gap='large')
    with left:
        if row['accepted']: st.success('Accepted by Demo reviewer. PO balance recorded once. This invoice is read-only.')
        if result:
            status=result['status']
            issues=[c for c in result['checks'] if c['level']!='pass']
            displayed='Accepted' if row['accepted'] else status
            action='Invoice approved' if row['accepted'] else ('Approve invoice' if status=='Ready for approval' else f'Resolve {len(issues)} issues first' if status=='Needs review' else 'Approval blocked; resolve the findings below')
            style={'Ready for approval':'ready','Needs review':'review','Blocked':'blocked'}[status]
            st.html(f'<section class="decision {style}">{pill(displayed)}<p><strong>{escape(action)}</strong></p></section>')
            enabled=status=='Ready for approval' and not row['accepted']
            if not enabled:st.caption('Approval unavailable: '+('this invoice has already been accepted.' if row['accepted'] else 'the findings below must be resolved.'))
            if st.button('Approve invoice',type='primary',key='approve_'+row['id'],disabled=not enabled):
                response=approve(row['id'])
                if isinstance(response,JSONResponse):notify(json.loads(response.body)['detail'])
                else:notify('Invoice accepted. PO balance updated once.')
                st.rerun()
            st.subheader('What needs attention')
            if not issues:st.write('All required checks passed. Review the source before approval.')
            for index,check in enumerate(issues):
                show_finding(check)
                original=check.get('evidence',{}).get('original_id')
                if original and st.button('Open original invoice',key=f'original_{row["id"]}_{index}'):
                    st.session_state.selected_invoice=original;st.rerun()
            if result.get('candidates') and len(result['candidates'])>1 and not row['accepted']:
                st.caption('Choose the intended purchasing record; selection still runs all checks.')
                with st.form('po_selection'):
                    po=st.selectbox('Purchase order',result['candidates'])
                    if st.form_submit_button('Select PO & rerun'):
                        rerun_invoice(row['id'],'select_po',{'after':po},po=po);st.rerun()
            passed=[c for c in result['checks'] if c['level']=='pass']
            with st.expander(f'Checks that passed ({len(passed)})'):
                for check in passed:st.write('✓ '+check['message'])
            if result.get('email'):
                st.subheader('Vendor email draft')
                st.caption('Draft only. No email is sent. Use the copy control in the draft box.')
                st.code(result['email'],language=None)
        elif row['execution']=='failed':
            st.error('The review could not finish. Your document was saved. Retry processing when the provider is available.')
            with s.connection() as db:
                failure=db.execute("SELECT payload FROM events WHERE invoice_id=? AND state='failed' ORDER BY seq DESC LIMIT 1",(row['id'],)).fetchone()
            if failure: st.write(json.loads(failure[0]).get('error','The document could not be read. Check the provider configuration and retry.'))
            remaining=s.retry_remaining(row['id'])
            if remaining:
                st.warning(f'Provider rate limit: retry available in about {remaining} seconds.')
                if st.button('Refresh retry availability'):st.rerun()
            if st.button('Retry processing',key='retry_'+row['id'],disabled=remaining>0):
                rerun_invoice(row['id'],'retry',{});st.rerun()
        if data:
            confirmable=pending_verifications(data)
            if confirmable and not row['accepted'] and row['execution']=='completed':
                st.html('<span id="verify-fields"></span>')
                st.subheader('Verify uncertain fields')
                st.caption('Compare the values with the PDF on the right. Confirm only values you can read clearly. All invoice and PO rules will run again.')
                for field in confirmable:
                    evidence=data.get('evidence',{}).get(field) or {}
                    st.write(f"**{field.replace('_',' ').title()}:** {data[field]}")
                    if isinstance(evidence,dict):
                        st.caption(f"Source page {evidence.get('page') or '?'}: {evidence.get('snippet') or 'No model source snippet'}")
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
            st.subheader('Extracted fields and source evidence')
            with st.container():
                fields_table(data)
                if data.get('lines'):st.dataframe(data['lines'],hide_index=True,use_container_width=True)
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
    with right:
        st.subheader('Source PDF')
        st.caption('Source document for checking the extracted fields. Download it if the preview is unavailable.')
        source_view(row)
    st.subheader('Audit timeline')
    with s.connection() as db:
        events=[dict(e) for e in db.execute('SELECT * FROM events WHERE invoice_id=? ORDER BY seq',(row['id'],))]
        reviews=[dict(r) for r in db.execute('SELECT * FROM reviews WHERE invoice_id=? ORDER BY seq',(row['id'],))]
    audit_timeline(events,reviews)

@st.cache_resource
def recover_saved_workspace(path):
    with s.use_workspace(path):s.init()
    return True

def application():
    recover_saved_workspace(str(s.data_dir()))
    with st.sidebar:
        st.html('<div class="wordmark">ledger</div>')
        saved=workspaces(st.session_state.history_key)
        ids=[m['id'] for m in saved]
        selected=st.selectbox('Saved review sessions',ids,index=ids.index(Path(st.session_state.workspace).name),format_func=lambda id:next(m['name']+' ('+m['created'][:10]+')' for m in saved if m['id']==id))
        if selected!=Path(st.session_state.workspace).name:
            st.session_state.workspace=str(workspace_path(st.session_state.history_key,selected))
            st.session_state.selected_invoice=None;st.session_state.page='Review queue';st.session_state.pop('batch_summary',None);st.rerun()
        with st.form('create_workspace'):
            name=st.text_input('New session name',placeholder='Demo rehearsal 2')
            if st.form_submit_button('Start new session'):
                st.session_state.workspace=str(new_workspace(st.session_state.history_key,name))
                st.session_state.selected_invoice=None;st.session_state.page='Review queue';st.session_state.pop('batch_summary',None);st.rerun()
        for destination in ['Review queue','New invoice','Purchase orders']:
            if st.button(destination,key='nav_'+destination,type='primary' if st.session_state.page==destination else 'secondary',use_container_width=True):
                st.session_state.page=destination;st.rerun()
        with st.expander('Demo tools'):
            for destination in ['Demo documents','Extraction scorecard']:
                if st.button(destination,key='nav_'+destination,use_container_width=True):
                    st.session_state.page=destination;st.rerun()
            reset=st.checkbox('Delete invoices in this session',key='reset_confirm_'+Path(st.session_state.workspace).name)
            if st.button('Reset demo session',disabled=not reset):
                s.reset_demo_records()
                for filename in ['last_batch.json','scorecard.json']:(s.data_dir()/filename).unlink(missing_ok=True)
                st.session_state.selected_invoice=None;st.session_state.page='Review queue';st.rerun()
        with st.popover('About this demo'):
            st.write('Bookmark this URL to reopen saved sessions. Anyone with the history link can access them. Hosted history requires a durable LEDGER_ARCHIVE_DIR mount.')
            st.write('AI providers receive the document or rendered pages. Use synthetic documents in this demo. Local sample reading does not use AI.')
            st.write('Invoice matching is against purchase orders only; receipt of goods is not confirmed. Approval is always a human action.')
        st.caption('Recommendation only. No payments are made.')
    if st.session_state.get('flash'):st.info(st.session_state.pop('flash'))
    snapshot=dashboard();rows=sorted(snapshot['invoices'],key=queue_rank)
    if any(v.get('gstin','').startswith('DEMO-') for v in snapshot['vendors']):
        st.warning('This session uses older vendor fixtures. Start a new session to use the current demo documents while retaining history.')
    page=st.session_state.page
    if page!='Invoice detail':st.title(page)
    if page=='Review queue':
        batchfile=s.data_dir()/'last_batch.json'
        if batchfile.exists():
            batch=json.loads(batchfile.read_text())
            st.subheader('Last batch results');st.dataframe([{k:v for k,v in item.items() if k!='Record'} for item in batch['summary']],hide_index=True,use_container_width=True)
            for vendor,requests in batch.get('vendor_followups',{}).items():
                with st.expander('Combined vendor follow-up: '+vendor):
                    draft='Subject: Invoice review clarifications\n\nHello,\nPlease help resolve these findings:\n\n'+'\n\n'.join(requests)+'\n\nThank you,\nAccounts Payable'
                    st.text_area('Draft only; no email is sent',draft,height=220,key='vendor_email_'+vendor)
        attention=sum(not r['accepted'] and ((r['result'] or {}).get('status') in ['Needs review','Blocked'] or r['execution']=='failed') for r in rows)
        st.subheader(f'{attention} invoice'+('s need' if attention!=1 else ' needs')+' your attention')
        status_options=['All','Ready for approval','Needs review','Blocked','Accepted','Processing failed']
        def row_status(r):return 'Accepted' if r['accepted'] else (r['result'] or {}).get('status','Processing failed' if r['execution']=='failed' else 'In progress')
        counts={status:sum(row_status(r)==status for r in rows) for status in status_options[1:]}
        if rows:st.caption(f'{len(rows)} invoices received. Exception rate: {attention/len(rows):.0%}.')
        status_filter=st.pills('Filter invoices',status_options,default='All',format_func=lambda value:value if value=='All' else f'{value} ({counts[value]})',key='queue_status') or 'All'
        search=st.text_input('Search invoices',placeholder='Invoice number, vendor or PO',key='queue_search').casefold().strip()
        visible=[r for r in rows if (status_filter=='All' or row_status(r)==status_filter) and (not search or search in ' '.join(str(x or '') for x in [(r['data'] or {}).get('invoice_no'),(r['data'] or {}).get('vendor'),r['po']]).casefold())]
        if not rows:
            st.info('Upload an invoice or run a demo document.')
            if st.button('Upload an invoice',type='primary'):st.session_state.page='New invoice';st.rerun()
            if st.button('Run a demo document'):st.session_state.page='Demo documents';st.rerun()
        elif not visible:st.info('No invoices match these filters. Clear the search or choose All.')
        else:
            table=[]
            for r in visible:
                d=r['data'] or {};status=row_status(r)
                icon={'Ready for approval':'✓','Needs review':'!','Blocked':'×','Accepted':'✓'}.get(status,'○')
                findings=[c for c in (r['result'] or {}).get('checks',[]) if c['level']!='pass']
                table.append({'Status':icon+' '+status,'Invoice number':d.get('invoice_no') or r['filename'],'Vendor':d.get('vendor') or 'Unresolved','Amount':float(d['total']) if d.get('total') is not None else None,'PO':r['po'] or 'Unlinked','Main reason':problem_message(findings[0]) if findings else 'Accepted' if r['accepted'] else 'All required checks passed','Received':timestamp(r['created'])})
            st.caption('Select an invoice row to open its source and findings. Amounts are in INR.')
            selection=st.dataframe(table,use_container_width=True,hide_index=True,on_select='rerun',selection_mode='single-row',key='queue_table',column_config={'Amount':st.column_config.NumberColumn('Amount (INR)',format='%.2f')})
            if selection.selection.rows:
                st.session_state.selected_invoice=visible[selection.selection.rows[0]]['id'];st.session_state.page='Invoice detail';st.rerun()
        if rows:
            st.download_button('Export accepted invoices (CSV)',accepted_csv(rows),file_name='accepted-invoices.csv',mime='text/csv')
            st.download_button('Export review records (JSON)',s.dumps(rows),file_name='ledger-review-export.json',mime='application/json')
    elif page in ['New invoice','Demo documents']:
        readers=['groq','gemini','local'];default=0 if os.getenv('GROQ_API_KEY') else 1 if os.getenv('GEMINI_API_KEY') else 2
        with st.expander('Advanced'):
            mode=st.selectbox('Document reader',readers,index=default,format_func=lambda x:{'groq':'Groq vision (up to 3 pages)','gemini':'Gemini (up to 20 pages)','local':'Local sample reader (not AI)'}[x])
        if mode=='local':st.caption('The local reader only parses the labelled sample text PDFs. Varied layouts and scans require an AI reader.')
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
            st.caption('Follow the checklist below. Approve the first invoice before testing the remaining PO balance.')
            pack=st.selectbox('Document set',['Basic workflow samples','Realistic extraction test pack'])
            sample_dir=s.ROOT/('samples' if pack=='Basic workflow samples' else 'test_pack/invoices')
            if pack!='Basic workflow samples':st.caption('Use an AI reader. Run R01, approve it, then R02 and R03. Start a new session for independent R04, R05 and R07 checks. R06 must retain missing values.')
            samples=sorted(sample_dir.glob('*.pdf'))
            expectations=(['Ready for approval; approve before the next step','Needs review: 40 chairs remain','Blocked: duplicate invoice','Ready if extraction is reliable; independent session','Needs review; select the intended PO','Needs review; invoice number and total missing','Ready if scan evidence is reliable; independent session'] if pack!='Basic workflow samples' else ['Ready for approval; approve before step 2','Needs review: remaining PO quantity exceeded','First copy ready; re-upload blocks','Needs review: possible duplicate after step 3','Needs review: missing invoice information','Needs review; select a PO','Needs review: arithmetic mismatch','Needs review: unknown vendor','AI reader needed for the scan'])
            for index,document in enumerate(samples):
                done=any(r['filename']==document.name for r in rows)
                with st.container(border=True):
                    text,control=st.columns([4,1])
                    with text:
                        st.write(('✓ Reviewed: ' if done else '○ Not reviewed: ')+document.name)
                        st.write(expectations[index] if index<len(expectations) else 'Compare with the answer key')
                    with control:
                        if st.button('Run',key='demo_run_'+document.stem):
                            ingest(document.read_bytes(),document.name,mode);st.rerun()
            st.caption('Or choose a specific document to review or download.')
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
            chosen=st.selectbox('Extraction run',[r['id'] for r in eligible],format_func=lambda id:next(r['filename'] for r in eligible if r['id']==id))
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
                with st.expander('Field comparison details'):
                    st.dataframe([{'Fixture':Path(v['fixture']).name,**f} for v in selected for f in v['fields']],hide_index=True)
                st.download_button('Export scorecard',s.dumps(selected),file_name='extraction-scorecard.json',mime='application/json')
    elif page=='Purchase orders':
        st.caption('Only accepted invoices consume quantity and authorised value.')
        for po in snapshot['pos']:
            with st.container(border=True):
                st.subheader(po['number']);st.write(next(v['name'] for v in snapshot['vendors'] if v['id']==po['vendor_id']))
                st.progress(min(1.0,max(0,float(po['used'])/float(po['total']))),text=f"Accepted {money(po['used'])} of {money(po['total'])}")
                st.dataframe([{'Item':l['item'],'Accepted quantity':l['used'],'Ordered quantity':l['qty'],'Remaining quantity':float(l['qty'])-float(l['used']),'Unit price':money(l['price'])} for l in po['lines']],hide_index=True,use_container_width=True)
    else:detail_view(load(st.session_state.selected_invoice) if st.session_state.selected_invoice else None)

with s.use_workspace(st.session_state.workspace):
    try: application()
    except (ValueError,ValidationError,HTTPException) as error:
        st.error(error.detail if isinstance(error,HTTPException) else str(error))

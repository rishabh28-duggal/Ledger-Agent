// Exercise real review handlers with a stateful DOM harness; not visual browser QA.
const {readFileSync}=require('node:fs');
const {runInNewContext}=require('node:vm');
const assert=require('node:assert/strict');
const nodes=new Map(),lists=new Map();
function node(key){if(!nodes.has(key))nodes.set(key,{innerHTML:'',textContent:'',value:'',checked:false,hidden:false,disabled:false,tabIndex:0,scrollTop:0,style:{},dataset:{},attrs:{},listeners:{},classList:{add(){},remove(){},toggle(){},contains(){return false;}},setAttribute(k,v){this.attrs[k]=v;},focus(){document.activeElement=this;},scrollIntoView(){},insertAdjacentHTML(position,html){this.innerHTML+=html;},querySelector(selector){return selector==='img'?null:node(key+' '+selector);},querySelectorAll(){return [];},reportValidity(){return true;},addEventListener(k,fn){(this.listeners[k]??=[]).push(fn);},showModal(){this.open=true;},close(){this.open=false;for(const fn of this.listeners.close||[])fn();},remove(){}});return nodes.get(key);}
const document={querySelector:node,querySelectorAll:s=>lists.get(s)||[],body:{classList:{add(){},remove(){},toggle(){}},append(el){document.lastDialog=el;}},createElement:()=>node('dialog-'+nodes.size)};
const window={scrollY:250,scrollTo:value=>window.lastScroll=value,matchMedia:()=>({matches:false})};
const location={hash:'#invoice/'+ 'a'.repeat(32)+'/'+ 'b'.repeat(32)};
const history={replaceState:(s,t,hash)=>location.hash=hash};
const source=readFileSync('web/app.js','utf8').split("$$('[data-auth]').forEach")[0];
const result=runInNewContext(source+`function syncSidebar(){}
(async()=>{
who={demo:true};sid='a'.repeat(32);selected='b'.repeat(32);page='detail';
snapshot={session:{name:'Review folder',master:{vendors:[],pos:[]}},invoices:[]};
const fixture={id:selected,filename:'invoice.pdf',pages:2,mime:'application/pdf',run:1,execution:'completed',accepted:false,data:{invoice_no:'INV-1',vendor:'Vendor',total:'100',currency:'INR',lines:[],evidence:{},uncertain_fields:[]},events:[],audit:[],result:{status:'Needs review',checks:[
 {code:'missing_total',level:'review',message:'Total missing',fix:'Ask vendor',evidence:{field:'total'}},
 {code:'duplicate_file',level:'block',message:'Duplicate file',fix:'Open original',evidence:{}},
 {code:'total',level:'not_evaluated',message:'Waiting for total',fix:'Supply total',evidence:{missing:['total']}},
 {code:'line_math_0',level:'pass',message:'Line passed',fix:'No action',evidence:{line:1}},
 {code:'receipt_optional',level:'info',message:'Receipt matching not required',fix:'No delivery match claimed',evidence:{}},
 {code:'bank_match',level:'review',message:'Bank mismatch',fix:'Verify independently',evidence:{invoice_account:'****1234'}}]}};
const group=groupedFindings(fixture.result.checks);assert.equal(group.reduce((n,g)=>n+g.checks.length,0),6);assert.equal(group[0].key,'identity');assert.equal(group.find(g=>g.key==='passed').checks.length,1);assert.equal(group.find(g=>g.key==='waiting').checks.length,1);
assert(reviewSummary(fixture).includes('1 blocking'));assert(!displayFinding(fixture.result.checks[0]).includes('Ask vendor'));assert(displayFinding(fixture.result.checks[0]).includes('enter the value if shown'));
const html=issueGroupsHTML(fixture);assert(html.includes('data-issue-group="passed"'));assert(!html.match(/data-issue-group="passed" open/));assert(html.includes('Waiting on information'));assert(!followupDraft({...fixture,result:{checks:[fixture.result.checks[0]]}}));
const originalJson=json,originalApi=api;
json=async()=>structuredClone(fixture);api=async()=>({blob:async()=>new Blob(['pdf'],{type:'application/pdf'})});
$('#review-form').elements=Object.fromEntries(fields.map(([k])=>[k,{value:String(fixture.data[k]||'')} ]));
await renderDetail();
assert($('#page').innerHTML.includes('role="tablist"'));assert($('#page').innerHTML.includes('form="review-form"'));assert($('#page').innerHTML.includes('Review queue'));assert($('#page').innerHTML.includes('Original extraction (bank details masked)'));
$('#review-form').elements.total.value='150';$('#review-po').value='PO-42';$('#confirm-source').checked=true;
switchReviewTab('details');const formRef=$('#review-form');switchReviewTab('activity');switchReviewTab('details');assert.equal($('#review-form'),formRef);assert.equal(formRef.elements.total.value,'150');assert.equal($('#review-po').value,'PO-42');assert.equal($('#confirm-source').checked,true);
markReviewDirty();assert.equal($('#confirm-source').checked,false);assert.equal($('#approve').disabled,true);assert.equal($('#review-save-state').textContent,'Unsaved changes');
$('#confirm-source').checked=true;markReviewDirty(false);switchReviewTab('issues');assert.equal($('#confirm-source').checked,true);
const typedHtml=$('#page').innerHTML;notifyReviewUpdate({...fixture,updated:'new'});assert.equal($('#page').innerHTML,typedHtml);assert.equal(formRef.elements.total.value,'150');assert.equal($('#approve').disabled,true);
json=async()=>{throw Error('Stale revision');};assert.equal(await saveReview(false),false);assert.equal(formRef.elements.total.value,'150');assert.equal(reviewContext.dirty,true);assert($('#review-error').textContent.includes('edits are retained'));
let waiting=confirmReviewLeave();document.lastDialog.querySelector('#review-stay').onclick();assert.equal(await waiting,false);assert.equal(reviewContext.dirty,true);
waiting=confirmReviewLeave();document.lastDialog.querySelector('#review-discard').onclick();assert.equal(await waiting,true);assert.equal(reviewContext.dirty,false);
markReviewDirty(false);let savedPayload;
json=async(path,options)=>{savedPayload=JSON.parse(options.body);return {};};refresh=async()=>snapshot;
assert.equal(await saveReview(false),true);assert.equal(savedPayload.expected_run,1);assert.equal(savedPayload.data.total,'150');assert.equal(savedPayload.po,'PO-42');assert.equal(reviewContext.dirty,false);assert.equal(reviewContext.dataDirty,false);assert.equal(fixture.accepted,false);
reviewContext.row={...fixture,result:{status:'Ready for approval'}};reviewContext.stale=false;updateReviewActions();assert.equal($('#approve').disabled,false);markReviewDirty();assert.equal($('#approve').disabled,true);
// Clean Save is quiet; confirmation-only changes enable it and can be undone.
reviewContext.dirty=false;reviewContext.dataDirty=false;$('#confirm-source').checked=false;updateReviewActions();assert.equal($('#review-save').disabled,true);
$('#confirm-source').checked=true;markReviewDirty(false);assert.equal($('#review-save').disabled,false);assert.equal($('#review-save').textContent,'Save confirmation');
$('#confirm-source').checked=false;markReviewDirty(false);assert.equal(reviewContext.dirty,false);assert.equal($('#review-save').disabled,true);
// A pending approval cannot be submitted again, including during action refresh.
let approveCalls=0,rejectApproval;json=async()=>{approveCalls++;return new Promise((resolve,reject)=>rejectApproval=reject);};
const approvalHandler=$('#approve').onclick,pendingApproval=approvalHandler({target:$('#approve')});await approvalHandler({target:$('#approve')});
assert.equal(approveCalls,1);assert.equal($('#approve').disabled,true);assert.equal($('#approve').textContent,'Approving...');
rejectApproval(Error('Approval changed'));await pendingApproval;assert.equal(reviewContext.approving,false);assert.equal(reviewContext.stale,true);
reviewContext.dirty=false;reviewContext.row.accepted=true;updateReviewActions();assert.equal($('#approve').disabled,true);assert.equal($('#review-save').disabled,true);
// Reference dialogs are local and cancellable; they cannot create records on open.
reviewContext.row={...fixture,accepted:false,run:1};reviewContext.dirty=true;reviewContext.dataDirty=true;reviewContext.stale=false;
let referenceRequests=0;json=async()=>{referenceRequests++;throw Error('Unexpected write');};
vendorForm(-1,true);$('#cancel-vendor').onclick();assert.equal(referenceRequests,0);assert.equal(reviewContext.dirty,true);
poForm(-1,true);$('#cancel-po').onclick();assert.equal(referenceRequests,0);assert.equal(formRef.elements.total.value,'150');
// A successful persisted recheck updates only references/findings, preserving edits and source state.
reviewContext.sourceView={page:2,zoom:150,fitPage:false,scrollTop:70,scrollLeft:5};switchReviewTab('details');
const previewBefore=$('#source-preview').innerHTML,sourceState=JSON.stringify(reviewContext.sourceView);
json=async()=>({invoice:{...fixture,accepted:false,run:2,selected_po:'PO-NEW'},session:{...snapshot.session}});
assert.equal(await submitReviewReference({operation:'po_link',existing_po:'PO-NEW',reason:'Verified authorisation'}),true);
assert.equal(reviewContext.row.run,2);assert.equal(formRef.elements.total.value,'150');assert.equal(reviewContext.dirty,true);assert.equal(reviewContext.tab,'details');
assert.equal($('#source-preview').innerHTML,previewBefore);assert.equal(JSON.stringify(reviewContext.sourceView),sourceState);assert.equal($('#approve').disabled,true);
// Save uses the same in-place renderer as live updates, rather than remounting the source.
const realDetailRenderer=renderDetail;let actionRefresh;
renderDetail=async(row,background)=>{actionRefresh=background;};
json=async()=>({...fixture,run:3});reviewContext.row={...fixture,run:2};reviewContext.dirty=true;reviewContext.dataDirty=true;
assert.equal(await saveReview(),true);assert.equal(actionRefresh,true);assert.equal(reviewContext.row.run,3);
renderDetail=realDetailRenderer;
// Mistaken selections are removable before upload; upload-in-progress is immutable.
files=[{name:'wrong.pdf',size:100},{name:'right.pdf',size:200}];uploadResults=[];
removeSelectedFile(0);assert.equal(files.length,1);assert.equal(files[0].name,'right.pdf');assert.equal($('#start-upload').disabled,false);
uploading=true;removeSelectedFile(0);assert.equal(files.length,1);uploading=false;
removeSelectedFile(0);assert.equal(files.length,0);assert.equal($('#start-upload').disabled,true);
// Opening or cancelling deletion cannot write records or discard a draft.
let deletionWrites=0;json=async()=>{deletionWrites++;throw Error('Unexpected deletion');};
reviewContext.dirty=true;reviewContext.row.accepted=false;
await deleteSavedInvoice();assert.equal(deletionWrites,0);document.lastDialog.querySelector('#delete-cancel').onclick();assert.equal(deletionWrites,0);assert.equal(reviewContext.dirty,true);
// Returning to the queue retains existing criteria, page and outer scroll.
search='Vendor';statusFilter='Blocked';queuePage=2;queueGroup='vendor';queueScroll=250;
snapshot.invoices=Array.from({length:60},(_,i)=>({...fixture,id:String(i),filename:'Vendor.pdf',data:{vendor:'Vendor'},result:{status:'Blocked'}}));
reviewContext.dirty=false;location.hash='#queue';await route({skipGuard:true});assert.equal(search,'Vendor');assert.equal(statusFilter,'Blocked');assert.equal(queuePage,2);assert.equal(queueGroup,'vendor');assert.equal(window.lastScroll.top,250);
// Dashboard return restores its own scroll without replacing queue state.
page='detail';overviewRows=[];overviewScroll=410;location.hash='#dashboard';await route({skipGuard:true});assert.equal(window.lastScroll.top,410);assert.equal(queuePage,2);
json=originalJson;api=originalApi;
})()`,{document,window,location,history,assert,console,Blob,URL,structuredClone,crypto:require('node:crypto').webcrypto,setTimeout,clearTimeout,requestAnimationFrame:fn=>fn(),sessionStorage:{setItem(){}}});
Promise.resolve(result).then(()=>console.log('Review grouping, tabs, drafts, save failure, approval guards and queue-context checks passed')).catch(error=>{console.error(error);process.exitCode=1;});

// Exercise the real renderers without adding browser or frontend dependencies.
const {readFileSync}=require('node:fs');
const {runInNewContext}=require('node:vm');
const assert=require('node:assert/strict');
const elements=new Map();
function classes(){const items=new Set();return {contains:key=>items.has(key),add:key=>items.add(key),remove:key=>items.delete(key),toggle(key,force){const on=force===undefined?!items.has(key):force;if(on)items.add(key);else items.delete(key);return on;}};}
const element=key=>{
 if(!elements.has(key))elements.set(key,{innerHTML:'',textContent:'',dataset:{},attrs:{},classList:classes(),addEventListener(){},setAttribute(key,value){this.attrs[key]=value;},removeAttribute(key){delete this.attrs[key];},focus(){document.activeElement=this;},close(){this.open=false;}});
 return elements.get(key);
};
const lists=new Map();
const document={querySelector:element,querySelectorAll:selector=>lists.get(selector)||[],documentElement:{dataset:{}},body:{classList:classes()}};
const fullSource=readFileSync('web/app.js','utf8');
const stylesheet=readFileSync('web/style.css','utf8');
const markup=readFileSync('web/index.html','utf8');
assert(markup.includes('id="export-excel" aria-describedby="export-excel-help">Export Excel</button>'));
assert(markup.includes('Exports all invoices in the current folder, including invoices hidden by filters.'));
assert(!fullSource.includes('Excel: entire folder scope'));

assert.equal((stylesheet.match(/:root\s*\{/g)||[]).length,1);
assert(!/--(?:green|mint|saffron|cornflower|coral)\b/.test(stylesheet));
const tokenMap=raw=>Object.fromEntries([...raw.matchAll(/--([\w-]+):([^;\n}]+)/g)].map(m=>[m[1],m[2].trim()]));
const lightTokens=tokenMap(stylesheet.match(/:root\s*\{([^}]+)/)[1]);
const darkTokens={...lightTokens,...tokenMap(stylesheet.match(/\[data-theme="dark"\]\s*\{([^}]+)/)[1])};
const token=(name,tokens)=>tokens[name].startsWith('var(')?token(tokens[name].slice(6,-1),tokens):tokens[name].replace('#','');
const luminance=hex=>[0,2,4].map(i=>parseInt(hex.slice(i,i+2),16)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((n,v,i)=>n+v*[.2126,.7152,.0722][i],0);
for(const tokens of [lightTokens,darkTokens]){
 const pairs=[['text','surface'],['text-muted','surface'],['text-muted','surface-muted'],['action-text','action-bg'],['action-text','action-hover'],['link','surface'],['sidebar-text','sidebar-bg'],['accent-text','surface'],...['approved','review','ready','blocked','processing'].map(s=>['status-'+s+'-text','status-'+s+'-bg']),...['approved','review','ready','blocked'].map(s=>['text','status-'+s+'-bg'])];
 for(const [fg,bg] of pairs){const [a,b]=[luminance(token(fg,tokens)),luminance(token(bg,tokens))].sort((a,b)=>a-b);assert((b+.05)/(a+.05)>=4.5,fg+' / '+bg);}
}
const source=fullSource.split("$$('[data-auth]').forEach")[0];
const settings=fullSource.slice(fullSource.indexOf('function preference('),fullSource.indexOf("window.addEventListener('hashchange'"));
const prefs=new Map();let mobile=false;
const localStorage={getItem:key=>prefs.get(key)||null,setItem:(key,value)=>prefs.set(key,value)};
const window={matchMedia:query=>({matches:query.includes('max-width')?mobile:false,addEventListener(){}}),addEventListener(){}};
const location={hash:''};
const history={replaceState:(state,title,hash)=>location.hash=hash};
const sessionStorage={getItem:key=>prefs.get('session:'+key)||null,setItem:(key,value)=>prefs.set('session:'+key,value),removeItem:key=>prefs.delete('session:'+key)};
const result=runInNewContext(source+settings+`(async()=>{
applyTheme('dark');assert.equal(document.documentElement.dataset.theme,'dark');assert.equal($('#theme-toggle').textContent,'Light mode');
applyTheme('light');assert.equal(preference('ledger-theme',''),'light');
savePreference('ledger-sidebar','hidden');syncSidebar();assert.equal($('#sidebar').inert,true);assert(document.body.classList.contains('sidebar-hidden'));
savePreference('ledger-sidebar','shown');syncSidebar();assert.equal($('#sidebar').inert,false);
setMobile(true);syncSidebar();assert.equal($('#sidebar').inert,true);$('#sidebar').classList.add('open');syncSidebar();assert.equal($('#sidebar').inert,false);setMobile(false);
who={demo:true};
snapshot={session:{name:'Test <folder>',master:{vendors:[],pos:[]}},invoices:[]};
sessionList=[{id:'folder-a',name:'Test <folder>'}];sid='folder-a';overviewRows=[];
renderDashboard();
assert($('#dashboard-results').innerHTML.includes('Total invoices'));
assert($('#dashboard-results').innerHTML.includes('This folder is empty'));
assert($('#page').innerHTML.includes('Test &lt;folder&gt;'));
snapshot.invoices=[{id:'a',filename:'invoice.pdf',execution:'completed',accepted:false,data:{invoice_no:'A-1',vendor:'Vendor',date:'2026-11-06',total:'100',currency:'INR'},result:{status:'Ready for approval'}}];
overviewRows=snapshot.invoices.map(row=>({...row,folder_id:sid,folder_name:'Test <folder>'}));
renderDashboard();
assert($('#dashboard-results').innerHTML.includes('2026-11-06'));
assert($('#dashboard-results').innerHTML.includes('Ready for approval'));
assert($('#dashboard-results').innerHTML.includes('Amount by invoice month'));
assert($('#dashboard-results').innerHTML.includes('stat-blocked'));
assert($('#dashboard-results').innerHTML.includes('Review invoice'));
// Combined filters, calendar boundaries, count semantics and selection reconciliation.
const filterFixture=[
 {id:'f1',folder_id:sid,execution:'completed',data:{vendor:'Acme',date:'2026-10-31',currency:'INR',total:100,po_ref:'PO-1'},result:{status:'Ready for approval'}},
 {id:'f2',folder_id:sid,accepted:true,execution:'completed',data:{vendor:'Acme',date:'2026-11-30',currency:'INR',total:200,po_ref:'PO-1'}},
 {id:'f3',folder_id:sid,execution:'failed',data:{vendor:'Other',date:null,currency:'USD',total:100}}
];
overviewDate='month';assert.equal(dashboardMatches(filterFixture,false,'2026-11-08').length,1);
overviewDate='last-month';assert.equal(dashboardMatches(filterFixture,false,'2026-11-08')[0].id,'f1');
overviewDate='custom';dashboardFilters={vendor:'Acme',start:'2026-10-31',end:'2026-11-30',min:'100',max:'200',po:'PO-1',currency:'INR'};
assert.equal(dashboardMatches(filterFixture,false).length,2);
overviewOutcome='Approved';assert.equal(dashboardMatches(filterFixture).length,1);assert.equal(dashboardMatches(filterFixture,false).length,2);
assert(validateRanges({...dashboardFilters,min:'201'}));assert(validateRanges({...dashboardFilters,min:'-1'}));assert(validateRanges({...dashboardFilters,start:'2026-12-01'}));
overviewRows=filterFixture;overviewPage=9;selectedInvoices.add('f1');changeDashboard();assert.equal(overviewPage,0);assert.equal(selectedInvoices.size,0);
const savedGroup=overviewGroup,savedFolder=overviewFolder;clearDashboard();assert.equal(overviewDate,'all');assert.equal(overviewOutcome,'');assert.equal(overviewGroup,savedGroup);assert.equal(overviewFolder,savedFolder);
overviewSearch='Acme';renderDashboard();renderDashboard();assert.equal(overviewSearch,'Acme');clearDashboard();
// The compact toolbar keeps extra statuses available and leaves inactive chips hidden.
assert(!$('#page').innerHTML.includes('vendor-search'));assert.equal($('#filter-summary').hidden,true);
assert($('#status-filters').innerHTML.includes('More statuses'));
$('#more-statuses').onchange({target:{value:'Interrupted'}});assert.equal(overviewOutcome,'Interrupted');assert.equal($('#filter-summary').hidden,false);clearDashboard();
// Exercise the actual drawer submit/cancel handlers with draft form controls.
let drawer,closedHandler;
document.body.append=node=>drawer=node;
document.createElement=()=>{
 const controls=Object.fromEntries(['dated','vendor','currency','start','end','min','max','po'].map(k=>[k,{value:k==='dated'?overviewDate:k==='currency'?'INR':dashboardFilters[k],focus(){}}]));
 const parts={form:{elements:controls},'.drawer-dates':{},'#range-error':{},'#draft-clear':{},'#draft-cancel':{}};
 return {setAttribute(){},querySelector:k=>parts[k],showModal(){},close(){closedHandler();},remove(){},addEventListener:(event,fn)=>{if(event==='close')closedHandler=fn;}};
};
moreFilters();let draftForm=drawer.querySelector('form');draftForm.elements.min.value='90';drawer.querySelector('#draft-cancel').onclick();assert.equal(dashboardFilters.min,'');
moreFilters();draftForm=drawer.querySelector('form');draftForm.elements.min.value='200';draftForm.elements.max.value='100';draftForm.onsubmit({preventDefault(){}});assert(drawer.querySelector('#range-error').textContent);assert.equal(dashboardFilters.min,'');
draftForm.elements.max.value='300';draftForm.elements.vendor.value='Acme';draftForm.elements.po.value='PO-1';draftForm.onsubmit({preventDefault(){}});assert.equal(dashboardFilters.vendor,'Acme');assert.equal(dashboardFilters.min,'200');assert.equal($('#more-filters').textContent,'Filters (3)');
moreFilters();drawer.querySelector('#draft-clear').onclick();assert.equal(drawer.querySelector('form').elements.vendor.value,'');assert.equal(dashboardFilters.vendor,'Acme');drawer.querySelector('#draft-cancel').onclick();clearDashboard();
// Procurement controls and previews expose user-facing values and escape uploaded text.
renderMaster();assert($('#page').innerHTML.includes('Import vendor Excel'));assert($('#page').innerHTML.includes('Download vendor template'));assert($('#page').innerHTML.includes('Import vendors &amp; POs'));assert($('#page').innerHTML.includes('JSON backup containing vendors and purchase orders.'));
const importHtml=vendorImportPreview({counts:{new:0,existing:1,conflicts:0,invalid:0},rows:[{row:2,values:{name:'<unsafe>',gstin:'',status:'approved'},action:'Existing',errors:[],defaulted:true}]});
assert(importHtml.includes('&lt;unsafe&gt;'));assert(importHtml.includes('Skip existing'));assert(importHtml.includes('default: Active'));assert(importHtml.includes('will be skipped'));
renderQueue();assert($('#page').innerHTML.includes('Approve all ready'));
renderUpload();assert(!$('#page').innerHTML.includes('Sample invoices'));assert($('#page').innerHTML.includes('Run invoice checks'));
files=[{name:'unsafe<script>.pdf',size:1024}];uploadResults=[{error:'Invalid <PDF>'}];
renderFileList();
assert($('#file-summary').innerHTML.includes('Invalid &lt;PDF&gt;'));
assert($('#file-summary').innerHTML.includes('unsafe&lt;script&gt;.pdf'));
assert($('#file-summary').innerHTML.includes('<th>Upload status</th>'));
const ready=snapshot.invoices[0];
const approved={...ready,id:'b',accepted:true,folder_id:'other',data:{...ready.data,vendor:'Another vendor',total:'50',date:'2026-10-01'}};
const blocked={...ready,id:'c',result:{status:'Blocked'},folder_id:'folder-a'};
const mixed=[{...ready,folder_id:'folder-a'},approved,blocked];
snapshot.invoices=mixed;
const boxes=mixed.map(row=>({dataset:{select:row.id},checked:false}));
setList('[data-select]',boxes);renderQueue();
assert(!rowsTable([blocked],{selectable:true}).match(/data-select="c"[^>]*disabled/));
boxes[2].checked=true;boxes[2].onchange();
assert(selectedInvoices.has('c'));assert.equal($('#approve-selected').disabled,true);assert($('#selection-summary').textContent.includes('1 selected'));
$('#select-ready').onchange({target:{checked:true}});
assert.equal(selectedInvoices.size,3);assert.equal($('#approve-selected').disabled,false);assert.equal($('#approve-selected').textContent,'Approve selected (1)');
statusFilter='Blocked';renderQueue();assert.equal($('#approve-selected').disabled,true);
$('#select-ready').onchange({target:{checked:false}});assert(!selectedInvoices.has('c'));assert(selectedInvoices.has('a'));
statusFilter='';selectedInvoices.clear();snapshot.invoices=Array.from({length:30},(_,i)=>({...ready,id:'page-'+i}));setList('[data-select]',[]);queuePage=1;renderQueue();
$('#select-ready').onchange({target:{checked:true}});assert.equal(selectedInvoices.size,30);assert.equal($('#approve-selected').textContent,'Approve selected (30)');
selectedInvoices.clear();queuePage=0;snapshot.invoices=[ready];
assert.equal(filterRows(mixed,{folder:'folder-a'}).length,2);
assert.equal(filterRows(mixed,{outcome:'Held'}).length,1);
assert.equal(filterRows(mixed,{dated:'7'},'2026-11-06').length,2);
assert.equal(filterRows(mixed,{query:'another'}).length,1);
assert.equal(filterRows(mixed,{outcome:'Approved'}).length,1);
assert.equal(groupKey(ready,'month'),'2026-11');assert.equal(groupKey(ready,'year'),'2026');
assert.equal(groupKey(approved,'vendor'),'Another vendor');
const amounts=amountData([...mixed,{...ready,id:'usd',data:{...ready.data,currency:'USD',total:'999'}}],'INR');
assert.equal(amounts.total,250);assert.equal(amounts.approved,50);assert.equal(amounts.pending,200);
const missing={...ready,id:'missing',data:{currency:'INR',total:null}};assert.equal(amountData([missing],'INR').known,0);
const calls=[];const results=await approveInvoiceBatch([ready,approved,blocked,{...ready,id:'stale'}],async row=>{calls.push(row.id);if(row.id==='stale')throw Error('PO balance changed');});
assert.equal(calls.join(','),'a,stale');assert.equal(results.filter(r=>r.ok).length,1);assert.equal(results[1].error,'PO balance changed');
// Login keeps signup-only help out of the way; validation/autocomplete stay intact.
setAuthMode('login');assert.equal($('#username-help').hidden,true);assert.equal($('#password-help').hidden,true);assert.equal($('#password').autocomplete,'current-password');
setAuthMode('signup');assert.equal($('#username-help').hidden,false);assert.equal($('#password-help').hidden,false);assert.equal($('#password').autocomplete,'new-password');
assert.equal($('#username').attrs['aria-describedby'],'username-help');
togglePasswordVisibility();assert.equal($('#password').type,'text');assert.equal($('#toggle-password').attrs['aria-label'],'Hide password');
togglePasswordVisibility();assert.equal($('#password').type,'password');assert.equal($('#toggle-password').attrs['aria-label'],'Show password');
// Both entry buttons share one guarded request and recover inline after failure.
const demoControls=[$('#try-demo'),$('#auth-demo')];demoControls[0].textContent='Try the demo';demoControls[1].textContent='Try demo instead';setList('[data-demo]',demoControls);
$('#landing').hidden=false;$('#shell').hidden=true;config={};
const originalJson=json;json=async()=>{throw Error('Offline');};await startDemo();
assert.equal($('#landing').hidden,false);assert.equal($('#demo-error').hidden,false);assert($('#demo-error').textContent.includes('Offline'));assert.equal(demoControls[0].disabled,false);assert.equal(demoControls[0].textContent,'Try the demo');
let demoRequests=0,release;const pending=new Promise(resolve=>release=resolve);
json=async path=>{if(path==='/demo'){demoRequests++;return pending;}if(path==='/me')return {demo:true,username:'Demo'};if(path==='/sessions')return [{id:'folder-a',name:'Demo'}];if(path==='/sessions/folder-a')return {session:{id:'folder-a',name:'Demo',master:{vendors:[],pos:[]}},invoices:[]};throw Error('Unexpected '+path);};
const opening=startDemo();assert.equal(demoControls[0].disabled,true);assert.equal(demoControls[1].disabled,true);await startDemo();assert.equal(demoRequests,1);release({session:'folder-a'});await opening;
assert.equal(location.hash,'#upload');assert.equal(page,'upload');assert.equal($('#shell').hidden,false);assert.equal($('#skip-link').attrs.href,'#content');assert.equal(demoControls[1].textContent,'Try demo instead');
// Concurrent startup and demo entry share one CSRF request.
csrfToken=null;let csrfCalls=0;json=async path=>{assert.equal(path,'/csrf');csrfCalls++;await Promise.resolve();return {token:'shared-token'};};
await Promise.all([ensureCsrf(),ensureCsrf()]);assert.equal(csrfCalls,1);assert.equal(csrfToken,'shared-token');
const originalApi=api;const sampleRequests=[];api=async path=>{sampleRequests.push(path);return {blob:async()=>new Blob(['pdf'],{type:'application/pdf'})};};
await loadDemoExample();assert.equal(sampleRequests.join(','),'/samples/01_happy_60_chairs.pdf');assert.equal(files.length,1);assert.equal(uploading,false);
who={demo:false};renderUpload();assert(!$('#page').innerHTML.includes('id="demo-example"'));await loadDemoExample();assert.equal(sampleRequests.length,1);
api=originalApi;json=originalJson;
})()
`,{document,window,location,history,sessionStorage,localStorage,setMobile:value=>mobile=value,setList:(key,value)=>lists.set(key,value),assert,console,URL,Blob,File,setTimeout,clearTimeout});
Promise.resolve(result).then(()=>console.log('UI rendering, filters, grouping, currencies, bulk approval, themes and sidebar checks passed')).catch(error=>{console.error(error);process.exitCode=1;});

// Exercise the real renderers without adding browser or frontend dependencies.
const {readFileSync}=require('node:fs');
const {runInNewContext}=require('node:vm');
const assert=require('node:assert/strict');
const elements=new Map();
const element=key=>{
 if(!elements.has(key))elements.set(key,{innerHTML:'',textContent:'',dataset:{},addEventListener(){}});
 return elements.get(key);
};
const document={querySelector:element,querySelectorAll:()=>[]};
const source=readFileSync('web/app.js','utf8').split("$$('[data-auth]').forEach")[0];
runInNewContext(source+`
who={demo:true};
snapshot={session:{name:'Test <folder>',master:{vendors:[],pos:[]}},invoices:[]};
renderDashboard();
assert($('#page').innerHTML.includes('Total invoices'));
assert($('#page').innerHTML.includes('No invoices in this folder'));
assert($('#page').innerHTML.includes('Test &lt;folder&gt;'));
snapshot.invoices=[{id:'a',filename:'invoice.pdf',execution:'completed',accepted:false,data:{invoice_no:'A-1',vendor:'Vendor',date:'2026-11-06',total:'100',currency:'INR'},result:{status:'Ready for approval'}}];
renderDashboard();
assert($('#page').innerHTML.includes('2026-11-06'));
assert($('#page').innerHTML.includes('Ready for approval'));
files=[{name:'unsafe<script>.pdf',size:1024}];uploadResults=[{error:'Invalid <PDF>'}];
renderFileList();
assert($('#file-summary').innerHTML.includes('Invalid &lt;PDF&gt;'));
assert($('#file-summary').innerHTML.includes('unsafe&lt;script&gt;.pdf'));
assert($('#file-summary').innerHTML.includes('<th>Upload status</th>'));
`,{document,assert,console,URL,Blob,setTimeout,clearTimeout});
console.log('UI rendering checks passed');

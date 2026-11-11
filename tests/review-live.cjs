const {readFileSync}=require('node:fs');
const {runInNewContext}=require('node:vm');
const assert=require('node:assert/strict');
const nodes=new Map(),timers=new Map();let timerId=0;
const node=k=>{if(!nodes.has(k))nodes.set(k,{hidden:false,textContent:'',disabled:false,dataset:{},querySelector:s=>node(k+s)});return nodes.get(k);};
const document={querySelector:node,querySelectorAll:()=>[],hidden:false,activeElement:null};
const source=readFileSync('web/app.js','utf8').split("$$('[data-auth]').forEach")[0];
const result=runInNewContext(source+`
(async()=>{
 page='detail';sid='folder';selected='invoice';who={};
 const queued={id:selected,run:1,execution:'queued',updated:'1',data:null,result:null};
 const final={...queued,execution:'completed',updated:'3',data:{invoice_no:'ACTUAL'},result:{status:'Needs review',checks:[]}};
 const session={session:{master:{vendors:[],pos:[]}},invoices:[final]};
 const setup=()=>{stopReviewLive();reviewLiveFailures=0;reviewContext={folder:sid,row:structuredClone(queued),dirty:false};document.activeElement=null;};
 let applied=[];renderDetail=async(row,background)=>{assert(background);applied.push(row);reviewContext.row=row;};updateReviewActions=()=>{};
 setup();let calls=0;json=async path=>{calls++;return path.endsWith('/invoice')?final:session;};
 await refreshActiveReview();assert.equal(applied.at(-1).data.invoice_no,'ACTUAL');assert.equal(calls,2);assert.equal(timers.size,1);
 // Continue after a nominal completion without its final result, and receive same-run changes.
 setup();const partial={...final,result:null,updated:'2'};let response=partial;json=async path=>path.endsWith('/invoice')?response:session;
 await refreshActiveReview();assert.equal(reviewContext.row.result,null);assert.equal(timers.size,1);response=final;await refreshActiveReview();assert(reviewContext.row.result);
 // Dirty input and active focus never get replaced; approval is marked stale.
 setup();reviewContext.dirty=true;const before=applied.length;json=async()=>final;await refreshActiveReview();assert.equal(applied.length,before);assert(reviewContext.stale);assert.equal(reviewContext.row.execution,'queued');
 setup();document.activeElement={closest:()=>true};await refreshActiveReview();assert.equal(applied.length,before);
 // One request in flight; an invoice switched away from cannot apply late data.
 setup();let resolveRead;json=()=>new Promise(resolve=>resolveRead=resolve);const request=refreshActiveReview();await refreshActiveReview();assert(reviewLiveBusy);stopReviewLive();page='queue';reviewContext=null;resolveRead(final);await request;assert.equal(applied.length,before);assert.equal(timers.size,0);
 page='detail';setup();json=()=>new Promise(resolve=>resolveRead=resolve);const stale=refreshActiveReview();reviewContext.row={...final,run:2};resolveRead(final);await stale;assert.equal(reviewContext.row.run,2);
 // Mutation responses invalidate an earlier read even at the same run.
 setup();json=()=>new Promise(resolve=>resolveRead=resolve);const sameRun=refreshActiveReview();reviewContext.row={...queued,updated:'4'};resolveRead(final);await sameRun;assert.equal(reviewContext.row.updated,'4');
 // Temporary failure backs off to 20 seconds, recovers and displays a real job failure.
 setup();json=async()=>{throw Error('Offline');};for(let i=0;i<6;i++)await refreshActiveReview();assert.equal([...timers.values()][0].delay,20000);assert($('#review-live').textContent.includes('Reconnecting'));assert(reviewContext.disconnected);
 const failed={...queued,execution:'failed',updated:'5',error:'Worker failed'};json=async path=>path.endsWith('/invoice')?failed:session;await refreshActiveReview();assert.equal(reviewContext.row.error,'Worker failed');assert.equal(reviewLiveFailures,0);assert.equal($('#review-live').hidden,true);
 stopReviewLive();assert.equal(timers.size,0);
})()`,{document,assert,console,structuredClone,timers,setTimeout:(fn,delay)=>{timers.set(++timerId,{fn,delay});return timerId;},clearTimeout:id=>timers.delete(id)});
Promise.resolve(result).then(()=>console.log('Live review completion, conflicts, focus, serial requests, cleanup, ordering and reconnect checks passed')).catch(error=>{console.error(error);process.exitCode=1;});

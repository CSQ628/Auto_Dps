const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');
function fixture(){
 const f={callbacks:null,calls:0,attachCount:0,failHook:false};
 const c={rpc:{exports:{}},withManagedThread:()=>({}),klass:n=>n,method:()=>({readPointer:()=>123}),
  Interceptor:{attach:(p,callbacks)=>{if(f.failHook)throw Error('unavailable');f.attachCount++;f.callbacks=callbacks;return {detach(){}};}},
  stat:()=> 'C:/save/account',list:x=>x,read:(o,k)=>o[k],single:()=>({}),
  call:(p,k,args=[])=>p[k](...args),sceneObject:()=>f.popup};
 vm.createContext(c);vm.runInContext(fs.readFileSync('bridge/planner.js','utf8')+'\n'+fs.readFileSync('bridge/automation.js','utf8')+
  '\nopportunityScan=()=>globalThis.testScan;globalThis.observe=mailClaimObservation;globalThis.run=executeAction;',c);
 f.c=c;f.observe=()=>c.observe();
 f.popup={_isLoading:false,_isClaiming:false,_slots:[{get_Mail:()=>({mailId:'a',state:'unread'})}],IsReceivable:()=>true,OnClickReceiveAll:()=>f.calls++};
 f.action={kind:'mail_claim',key:'mail_claim:a',ids:['a'],label:'领取',priority:98};
 c.testScan={snapshot:{account:'account',sync:{},currencies:{}},actions:[f.action]};
 f.execute=()=>c.run({...f.action,account:'account'});
 f.receipt=(rows)=>{const context={};f.callbacks.onEnter.call(context,[{},rows.map(p=>({...p,isNull:()=>false}))]);f.callbacks.onLeave.call(context);};
 return f;
}
test('native result observer installs once and records applied per-mail server results',()=>{
 const f=fixture();assert.equal(f.observe().available,true);f.observe();assert.equal(f.attachCount,1);
 f.receipt([{mailId:'a',status:'CLAIMED'},{mailId:'b',status:'ALREADY_CLAIMED'}]);
 const observed=JSON.parse(JSON.stringify(f.observe()));assert.equal(observed.sequence,1);
 assert.equal(observed.receipts[0].account,'account');
 assert.deepEqual(observed.receipts[0].results,[{id:'a',status:'CLAIMED'},{id:'b',status:'ALREADY_CLAIMED'}]);
 assert.equal(f.calls,0);
});
test('claim execution rechecks observer, native busy state and exact fresh unread ids',()=>{
 const f=fixture();assert.equal(f.execute().status,'pending');assert.equal(f.calls,1);
 for(const mutate of [f=>f.popup._isClaiming=true,f=>f.popup._isLoading=true,
     f=>f.popup.IsReceivable=()=>false,f=>f.popup._slots.push({get_Mail:()=>({mailId:'b',state:'unread'})})]){
  const g=fixture();mutate(g);assert.notEqual(g.execute().status,'pending');assert.equal(g.calls,0);
 }
 const g=fixture();g.failHook=true;assert.equal(g.execute().reason,'native_mail_observer_unavailable');assert.equal(g.calls,0);
});
test('an unread list disappearing does not create a native claim receipt',()=>{
 const f=fixture();f.observe();f.popup._slots=[];assert.equal(f.observe().receipts.length,0);
 assert.equal(f.execute().reason,'native_mail_list_changed');assert.equal(f.calls,0);
});

const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');
function fixture({withPopup=true,refreshThrows=false,accepted=true,advance=true,persist=true,before=0,scanned=before,uiLevel=before,max=5,preview=false}={}){
 const calls=[],saved={42:before},wallet={value:1000};let provider,created=0;
 const make=(name,levels)=>({name,levels,isNull:()=>false,GetLevel:id=>levels[id]||0,CanLearn:()=>saved[42]<max,
  Learn:()=>{calls.push(name+'.Learn');if(advance){levels[42]++;if(persist)saved[42]++;wallet.value-=60;}return accepted;}});
 const ui=make('ui',{42:uiLevel});ui.type=preview?'Preview':'DG.UI.Rune.RuneSaveStateProvider';
 const fresh=()=>provider=make('save'+(++created),{...saved});fresh();
 const view={isNull:()=>false,get_State:()=>ui,SetStateProvider:p=>{calls.push('SetStateProvider');view.get_State=()=>p;}};
 const popup={_view:view,isNull:()=>false,Refresh:()=>{calls.push('Refresh');if(refreshThrows)throw Error('refresh_failed');}};
 const rune={Header:0,MaxLevel:max,GoodsIDs:[201],Price:[60]},dm={GetRune:()=>rune},currency={Get:()=>wallet.value};
 const action={kind:'rune',key:'rune:42',id:42,level:scanned,cost:{goods:201,amount:60}};
 const scan={snapshot:{account:'acct',currencies:{soul:1000},automationBlocked:[],sync:{blocked:false,backlogged:false},connection:{online:true},manualBlockedKinds:[],manualPanels:withPopup?['DG.UI.Rune.RuneTreePopup']:[]},actions:[action]};
 const c={api:()=>()=>0,A:{fields:{},objectClass:o=>o.type},iter:()=>[],klass:x=>x,fullname:x=>x,withManagedThread:f=>f(),rpc:{exports:{}},jsonSafe:x=>x,ref:x=>x,list:x=>x,
  single:n=>n.includes('DataManager')?dm:n.includes('CurrencyManager')?currency:{},call:(o,n,args=[])=>o[n](...args),read:(o,n)=>o[n],sceneObject:()=>withPopup?popup:null,
  runesProvider:()=>provider,refreshRunesProvider:fresh};vm.createContext(c);
 vm.runInContext(fs.readFileSync('bridge/planner.js','utf8')+'\n'+fs.readFileSync('bridge/automation.js','utf8')+'\nglobalThis.execute=executeAction;',c);c.opportunityScan=()=>scan;
 return {c,action,calls,ui,view,execute:()=>c.execute({account:'acct',key:action.key,kind:'rune'})};
}
test('scan provider learns, persisted levels confirm, and stale UI gets the new provider',()=>{
 const f=fixture({uiLevel:3}),r=f.execute();assert.equal(r.status,'confirmed');assert.equal(r.uiRefresh,'refreshed');
 assert.equal(r.beforeLevel,0);assert.equal(r.afterLevel,1);assert.equal(r.learnAccepted,true);
 assert.equal(r.currencyBefore,1000);assert.equal(r.currencyAfter,940);assert.equal(f.ui.GetLevel(42),3);assert.equal(f.view.get_State().GetLevel(42),1);
 assert.deepEqual(f.calls,['save1.Learn','SetStateProvider','Refresh']);assert.equal(f.c.panelActionBlocked('rune',['DG.UI.Rune.RuneTreePopup']),false);
});
test('maxed node cannot confirm against an old scanned level',()=>{
 const f=fixture({before:3,scanned:2,uiLevel:3,max:3,accepted:false,advance:false}),r=f.execute();assert.equal(r.status,'stale');assert.equal(r.reason,'rune_level_changed');assert.deepEqual(f.calls,[]);
});
test('refused unchanged learn is rejected',()=>{
 const f=fixture({accepted:false,advance:false}),r=f.execute();assert.equal(r.status,'rejected');assert.equal(r.learnAccepted,false);assert.equal(r.afterLevel,r.beforeLevel);assert.deepEqual(f.calls,['save1.Learn']);
});
test('unexpected growth with Learn false is not a confirmation',()=>{
 const r=fixture({accepted:false}).execute();assert.notEqual(r.status,'confirmed');assert.equal(r.learnAccepted,false);
});
test('accepted learn cannot confirm from a changed cache without persisted growth',()=>{
 const r=fixture({persist:false}).execute();assert.equal(r.status,'pending');assert.equal(r.afterLevel,0);
});
for(const header of ['OfflineExpGain','OfflineGoodsGain','OfflineReward'])test(header+' can learn through the same native validation as online nodes',()=>{
 const f=fixture();f.action.header=header;assert.equal(f.execute().status,'confirmed');assert.equal(f.calls.filter(x=>x.endsWith('.Learn')).length,1);
});
test('no UI is required for learning and verification',()=>{
 const f=fixture({withPopup:false}),r=f.execute();assert.equal(r.status,'confirmed');assert.equal(r.uiRefresh,'unavailable');assert.deepEqual(f.calls,['save1.Learn']);
});
test('preview provider is never replaced',()=>{
 const f=fixture({preview:true}),r=f.execute();assert.equal(r.status,'confirmed');assert.equal(r.uiRefresh,'incompatible');assert.deepEqual(f.calls,['save1.Learn']);
});
test('refresh failure does not replay completed learning',()=>{
 const f=fixture({refreshThrows:true}),r=f.execute();assert.equal(r.status,'confirmed');assert.equal(r.uiRefresh,'failed');assert.equal(f.calls.filter(x=>x.endsWith('.Learn')).length,1);
});
test('budget protection remains effective',()=>{
 const f=fixture();f.action.cost.amount=1001;assert.equal(f.execute().reason,'budget_changed');assert.deepEqual(f.calls,[]);
});
test('each complete scan creates a fresh save provider',()=>{
 const c={refreshes:0,api:()=>()=>0,A:{fields:{}},iter:()=>[],klass:x=>x,withManagedThread:f=>f(),rpc:{exports:{}},bridgeStrategy:()=>({}),maintenanceStatus:()=>({active:false}),single:x=>x,call:()=>true,
 snapshot:()=>({squad:[],characters:[]}),list:x=>x,combatSnapshot:()=>({}),refreshRunesProvider:()=>++c.refreshes,battleReadiness:()=>{throw Error('stop');}};vm.createContext(c);
 vm.runInContext(fs.readFileSync('bridge/automation.js','utf8')+'\nglobalThis.scan=opportunityScan;',c);
 for(let i=0;i<2;i++)assert.throws(()=>c.scan(),/stop/);assert.equal(c.refreshes,2);
});
test('provider handles stay bounded and failed construction preserves the last provider',()=>{
 const source=fs.readFileSync('bridge/worker.js','utf8'),live=new Set();let next=0,fail=false;
 const c={klass:x=>x,objectNew:()=>({id:++next}),gcNew:o=>{live.add(o.id);return o.id;},gcFree:id=>{assert.ok(live.delete(id));},call:()=>{if(fail)throw Error('ctor_failed');}};vm.createContext(c);
 vm.runInContext(source.slice(source.indexOf('const handles=[]'),source.indexOf('const queue=[]'))+'\nglobalThis.fresh=refreshRunesProvider;globalThis.current=runesProvider;globalThis.release=releaseRunesProvider;',c);
 for(let i=0;i<100;i++){const p=c.fresh();assert.equal(c.current(),p);assert.equal(live.size,1);}
 const p=c.current();fail=true;assert.throws(()=>c.fresh(),/ctor_failed/);assert.equal(c.current(),p);assert.equal(live.size,1);c.release();c.release();assert.equal(live.size,0);
});

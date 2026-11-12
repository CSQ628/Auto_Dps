const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');

function fixture(type,blocked=[],kind='ui_cleanup',detail={}){
 let active=true;
 const calls=[],action={kind,key:'close:'+type,type,...detail};
 const context={rpc:{exports:{}},A:{fields:{}},iter:()=>[],klass:x=>x,withManagedThread:fn=>fn(),
  scan:{snapshot:{account:'1001',automationBlocked:blocked,sync:{},currencies:{soul:0}},actions:[action]},
  read:()=>false,single:x=>x,sceneObject:x=>({type:x}),call:(obj,name)=>{calls.push(name);if(name==='Hide')active=false;if(name==='get_gameObject')return {};if(name==='get_activeInHierarchy')return active;}};
 vm.createContext(context);
 vm.runInContext(fs.readFileSync('bridge/planner.js','utf8')+'\n'+fs.readFileSync('bridge/automation.js','utf8')+
  '\nopportunityScan=()=>scan;globalThis.execute=executeAction;',context);
 return {calls,execute:(strategy={preserve_open_panels:false})=>context.execute({...action,account:'1001',strategy})};
}

test('an active confirmation prevents every native submission',()=>{
 const f=fixture('DG.UI.Popup.HeroPopup',['DG.UI.ConfirmPopup']);
 assert.equal(f.execute().reason,'native_modal_active');assert.deepEqual(f.calls,[]);
});

test('an unsafe cleanup command cannot close a confirmation even if a scan omits its blocker',()=>{
 const f=fixture('DG.UI.ConfirmPopup');
 assert.equal(f.execute().reason,'popup_not_approved_for_cleanup');assert.deepEqual(f.calls,[]);
});

test('a known ordinary panel retains its native close behavior',()=>{
 const f=fixture('DG.UI.Popup.HeroPopup');
 assert.equal(f.execute().status,'confirmed');assert.deepEqual(f.calls,['OnClickClose']);
});

test('settled offline display uses its continuation callback through Hide',()=>{
 const f=fixture('DG.UI.Popup.OfflineRewardPopup',[],'offline_close');
 assert.equal(f.execute().status,'confirmed');assert.deepEqual(f.calls,['Hide','get_gameObject','get_activeInHierarchy']);
});

test('native submission rechecks crystal permission and changed balance',()=>{
 const f=fixture('ignored',[],'rune',{cost:{goods:202,amount:1},permanent:true});
 assert.equal(f.execute().reason,'budget_changed');assert.deepEqual(f.calls,[]);
});

test('execution refuses a stale cleanup command when panel preservation is enabled',()=>{
 const f=fixture('DG.UI.Popup.HeroPopup');assert.equal(f.execute({}).reason,'user_popup_open');assert.deepEqual(f.calls,[]);
});

const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');

function fixture(type,blocked=[],kind='ui_cleanup',detail={},native={}){
 let active=native.active??true;
 const calls=[],action={kind,key:'close:'+type,type,...detail};
 const context={rpc:{exports:{}},A:{fields:{}},iter:()=>[],klass:x=>x,withManagedThread:fn=>fn(),
  scan:{snapshot:{account:'1001',automationBlocked:blocked,sync:{},currencies:{soul:0}},actions:[action]},
  read:()=>false,single:x=>x,sceneObject:x=>native.missing?null:({type:x}),call:(obj,name)=>{calls.push(name);if(name==='Hide'||name==='OnClickClose'&&native.closes!==false)active=false;if(name==='get_gameObject')return {};if(name==='get_activeInHierarchy')return active;}};
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
 assert.equal(f.execute().status,'confirmed');assert.deepEqual(f.calls,['get_gameObject','get_activeInHierarchy','OnClickClose','get_gameObject','get_activeInHierarchy']);
});

test('the native skill tree closes through its inherited button and verifies visibility',()=>{
 const f=fixture('DG.UI.Popup.SkillTreePopup');
 assert.equal(f.execute().status,'confirmed');
 assert.deepEqual(f.calls,['get_gameObject','get_activeInHierarchy','OnClickClose','get_gameObject','get_activeInHierarchy']);
});

test('a native close that leaves a panel visible is retryable and never confirmed',()=>{
 const f=fixture('DG.UI.Popup.SkillTreePopup',[],'ui_cleanup',{}, {closes:false});
 assert.deepEqual(JSON.parse(JSON.stringify(f.execute())),{status:'waiting',reason:'popup_close_not_complete',type:'DG.UI.Popup.SkillTreePopup'});
 assert.equal(f.execute().status,'waiting');
 assert.equal(f.calls.filter(n=>n==='OnClickClose').length,2);
});

test('already hidden or destroyed panels cannot produce successful close evidence',()=>{
 for(const native of [{active:false},{missing:true}]){
  const f=fixture('DG.UI.Popup.SkillTreePopup',[],'ui_cleanup',{},native);
  assert.equal(f.execute().reason,'popup_already_closed');assert.equal(f.calls.includes('OnClickClose'),false);
 }
});

test('skill tree cleanup respects both confirmation blockers and player preservation',()=>{
 const confirmed=fixture('DG.UI.Popup.SkillTreePopup',['DG.UI.ConfirmPopup']);
 assert.equal(confirmed.execute().reason,'native_modal_active');assert.deepEqual(confirmed.calls,[]);
 const preserved=fixture('DG.UI.Popup.SkillTreePopup');
 assert.equal(preserved.execute({preserve_open_panels:true}).reason,'user_popup_open');assert.deepEqual(preserved.calls,[]);
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
 const f=fixture('DG.UI.Popup.HeroPopup');assert.equal(f.execute({preserve_open_panels:true}).reason,'user_popup_open');assert.deepEqual(f.calls,[]);
});

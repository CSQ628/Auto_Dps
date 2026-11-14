const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');
function fixture({active=true,visible=true,owner='.AppQuitHandler',name='Exit',multicast=[],interactable=true,staticTarget=true}={}){
 const calls=[],ptr=(id,empty=false)=>({id,isNull:()=>empty}),nil=ptr('nil',true),p=ptr('popup'),d=ptr('delegate'),m=ptr('method');
 const c={rpc:{exports:{}},A:{fields:{},objectClass:x=>x,methodName:()=>name},iter:()=>[],klass:x=>x,withManagedThread:fn=>fn(),
  stat:()=>active,api:()=>()=>owner,fullname:x=>x,utf:x=>x,list:x=>x,
  sceneObject:()=>p,read:(o,n)=>n==='method'?m:n==='m_target'?(staticTarget?nil:p):n==='delegates'?multicast:ptr(n),
  call:(o,n)=>{calls.push(n);if(n==='get_activeInHierarchy')return visible;if(n==='get_interactable')return interactable;return p;}};
 vm.createContext(c);vm.runInContext(fs.readFileSync('bridge/planner.js','utf8')+'\n'+fs.readFileSync('bridge/automation.js','utf8')+'\nglobalThis.observe=maintenanceStatus;globalThis.execute=executeAction;',c);
 return {calls,observe:()=>c.observe(),scan:()=>c.opportunityScan(),execute:()=>c.execute({kind:'maintenance_exit',strategy:{}})};
}
test('native maintenance is identified before account or save initialization',()=>{
 const f=fixture();assert.equal(f.observe().active,true);assert.equal(f.observe().canExit,true);
 assert.equal(f.execute().status,'submitted');assert.equal(f.calls.filter(n=>n==='OnClickConfirm').length,1);
});
test('exit requires every native maintenance prerequisite, never popup text',()=>{
 for(const options of [{active:false},{visible:false},{owner:'OtherHandler'},{name:'Purchase'},{multicast:[{}]},{interactable:false},{staticTarget:false}]){
  const f=fixture(options);assert.equal(f.execute().status,'waiting');assert.ok(!f.calls.includes('OnClickConfirm'));
 }
});
test('early scan does not require a loaded account and permits scan performance without a snapshot',()=>{
 const f=fixture();assert.equal(f.scan().snapshot,null);assert.equal(f.scan().runtime.maintenance.active,true);
 const loading=fixture({active:false});assert.equal(loading.scan().snapshot,null);assert.equal(loading.scan().runtime.ready,false);
});
test('ordinary stale commands cannot submit during maintenance',()=>{
 // Exercise the real early scan, before any data-manager access.
 const context={rpc:{exports:{}},A:{fields:{}},iter:()=>[],klass:x=>x,withManagedThread:fn=>fn()};
 vm.createContext(context);vm.runInContext(fs.readFileSync('bridge/planner.js','utf8')+'\n'+fs.readFileSync('bridge/automation.js','utf8')+
  '\nmaintenanceStatus=()=>({known:true,active:true,canExit:false});globalThis.execute=executeAction;',context);
 assert.equal(context.execute({account:'old',kind:'rune',strategy:{}}).reason,'native_maintenance_active');
});

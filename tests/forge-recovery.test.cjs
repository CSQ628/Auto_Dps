const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');
function fixture(){
 const selected=[],calls=[],ore={uid:'ore',id:510100,count:8},part={get_Part:()=>1};let tier=4,include=true;
 const inventory={items:[ore]},produced={uid:'new',id:1010402,count:1};
 const cube={get_IsEmpty:()=>selected.length===0,get_Has:()=>selected,CanReserveMore:p=>selected.filter(q=>q===p).length<2};
 const toggle={get_isOn:()=>include,set_isOn:v=>{include=v;calls.push('storage:'+v);}};
 const popup={OnClickClose:()=>calls.push('close')};
 const view={get_SelectedTier:()=>tier,SetSelectedTier:v=>{tier=v;calls.push('tier:'+v);},get_IncludeStorageToggle:()=>toggle,
  CollectSlots:()=>{},_partSlots:[part],SelectPart:()=>{},ApplyRequirements:()=>{},RebuildRules:()=>{},get_CurrentConfig:()=>({ID:50001}),
  get_IsReady:()=>selected.length===2,TryExecute:()=>{calls.push('execute');ore.count-=2;inventory.items.push(produced);return true;},
  ReleaseAll:()=>{calls.push('release');selected.length=0;}};
 const im={get_Cube:()=>cube,get_Input:()=>({get_IsHolding:()=>false}),TryMoveToCube:p=>{selected.push(p);return true;}};
 const c={api:()=>()=>0,single:()=>im,ref:x=>x,read:(o,n)=>o[n],list:x=>x,call:(o,n,a=[])=>o[n](...a)};
 vm.createContext(c);vm.runInContext(fs.readFileSync('bridge/systems.js','utf8'),c);
 c.sceneObject=()=>view;c.activateCubeView=()=>popup;c.approvedMaterials=()=>[ore];c.itemInfo=p=>({...p});
 c.inventoryItems=()=>inventory.items;c.isTradable=()=>false;
 // Preserve the native-item interface used by the implementation.
 Object.assign(ore,{isNull:()=>false,get_Uid:()=>ore.uid,get_Count:()=>ore.count,get_IsLocked:()=>false});
 const cmd={recipe:50001,part:1,tier:2,allowed:['ore'],materialCounts:{ore:2},batchSize:2};
 return {view,toggle,popup,im,cube,ore,selected,calls,inventory,cmd,run:()=>c.forgeAction(cmd),tier:()=>tier,include:()=>include};
}
test('forge consumes the exact reserved quantity and reports the actual material receipt',()=>{
 const f=fixture(),r=f.run();assert.equal(r.status,'confirmed');assert.equal(f.ore.count,6);
 assert.equal(r.consumed.length,1);assert.equal(r.consumed[0].count,2);assert.equal(r.produced.length,1);
 assert.equal(f.tier(),4);assert.equal(f.include(),true);assert.equal(f.selected.length,0);
});
test('forge cleanup failures cannot suppress a proven result or skip the remaining cleanup steps',()=>{
 for(const failed of ['release','close','tier','storage']){
  const f=fixture();
  if(failed==='release')f.view.ReleaseAll=()=>{f.selected.length=0;throw Error('release_failed');};
  if(failed==='close')f.popup.OnClickClose=()=>{throw Error('close_failed');};
  if(failed==='tier')f.view.SetSelectedTier=v=>{if(v===4)throw Error('tier_failed');};
  if(failed==='storage')f.toggle.set_isOn=v=>{if(v)throw Error('storage_failed');};
  const r=f.run();assert.equal(r.status,'confirmed',failed);assert.equal(r.reason,'native_cleanup_incomplete');
  assert.ok(r.cleanupIssues.includes(failed));assert.equal(f.ore.count,6);
  if(failed!=='storage')assert.equal(f.include(),true,failed);
  if(failed!=='tier')assert.equal(f.tier(),4,failed);
 }
});
test('forge preparation failure is retryable and never becomes an uncertain consumption',()=>{
 const f=fixture();f.view.RebuildRules=()=>{throw Error('private-path');};f.popup.OnClickClose=()=>{throw Error('close_failed');};
 const r=f.run();assert.equal(r.status,'waiting');assert.equal(r.reason,'native_preparation_failed');
 assert.equal(r.step,'configure');assert.equal(f.ore.count,8);assert.equal(f.include(),true);assert.equal(f.tier(),4);
 assert.ok(!f.calls.includes('execute'));assert.ok(!JSON.stringify(r).includes('private-path'));
});
test('forge lost response remains uncertain while cleanup still runs',()=>{
 const f=fixture();f.view.TryExecute=()=>{f.ore.count-=2;throw Error('response_lost');};f.popup.OnClickClose=()=>{throw Error('close_failed');};
 assert.throws(()=>f.run(),/response_lost/);assert.equal(f.ore.count,6);assert.equal(f.include(),true);assert.equal(f.tier(),4);assert.equal(f.selected.length,0);
});
test('forge rejects invalid quantity budgets before opening its view',()=>{
 for(const mode of ['missing','overstock','extra_uid','fractional','mismatch','array']){
  const f=fixture();
  if(mode==='missing')delete f.cmd.materialCounts;
  if(mode==='overstock'){f.cmd.materialCounts.ore=9;f.cmd.batchSize=9;}
  if(mode==='extra_uid')f.cmd.materialCounts.extra=1;
  if(mode==='fractional'){f.cmd.materialCounts.ore=1.5;f.cmd.batchSize=1.5;}
  if(mode==='mismatch')f.cmd.batchSize=1;
  if(mode==='array')f.cmd.materialCounts=['ore'];
  const r=f.run();assert.equal(r.status,'stale',mode);assert.equal(r.reason,'material_quantity_changed');
  assert.equal(f.calls.length,0,mode);assert.equal(f.ore.count,8);
 }
});
test('forge reservation refusals and over-reservations never submit consumption',()=>{
 for(const mode of ['refused','extra']){
  const f=fixture();f.im.TryMoveToCube=p=>{if(mode==='refused')return false;f.selected.push(p,p,p);return true;};
  const r=f.run();assert.equal(r.status,'waiting',mode);assert.equal(r.reason,'material_quantity_changed');assert.equal(f.ore.count,8);
  assert.ok(!f.calls.includes('execute'));assert.equal(f.selected.length,0);assert.equal(f.include(),true);
 }
});
test('a produced item alone does not confirm missing or excessive forge consumption',()=>{
 for(const amount of [0,1,3]){
  const f=fixture();f.view.TryExecute=()=>{f.ore.count-=amount;f.inventory.items.push({uid:'made',id:1010402,count:1});return true;};
  const r=f.run();assert.equal(r.status,'pending',String(amount));assert.equal(r.reason,'forge_result_unconfirmed');
 }
 const f=fixture();f.view.TryExecute=()=>{f.ore.count-=2;return true;};assert.equal(f.run().status,'pending');
});

function recovery(options){
 const moves=[],gm={GetRequireItemID:()=>0,CanEnterStage:()=>true,HasStageData:()=>true,GoToStage:(...args)=>moves.push(args),IsStageEnding:()=>true};
 const s={account:'test',characters:[],stage:{level:49,category:0,difficulty:1,alivePlayers:1,aliveMonsters:0,wave:10,running:false,repeat:false},squad:[1],record:{maxCleared:49},
  battleReadiness:{known:true,charactersInitialized:true,expected:1,missing:[],arrangedCount:1,syncRunning:false,syncPending:false,pendingSpawn:false,timeScale:1,enterSequence:7},
  combat:{available:true,current:{level:49,difficulty:1,result:'Cleared'}},sync:{blocked:false},connection:{online:true}};
 const c={rpc:{exports:{}},withManagedThread:()=>({}),single:()=>gm,call:(o,n,a=[])=>o[n](...a)};
 vm.createContext(c);vm.runInContext(fs.readFileSync('bridge/planner.js','utf8')+'\n'+fs.readFileSync('bridge/automation.js','utf8'),c);
 c.maintenanceStatus=()=>({active:false});
 c.opportunityScan=()=>({snapshot:s,actions:c.battleRecoveryPlans(s,c.bridgeStrategy(options))});
 const action=c.opportunityScan().actions[0];return {moves,run:()=>c.executeAction({account:'test',kind:action.kind,key:action.key,strategy:options})};
}
test('recovery executes its own current-stage plan when automatic pushing is disabled',()=>{
 const f=recovery({progress_push:false});assert.equal(f.run().status,'pending');assert.deepEqual(f.moves,[[0,49,1]]);
});
test('recovery preserves the configured main-story ceiling during execution revalidation',()=>{
 const f=recovery({progress_max_stage:49});assert.equal(f.run().status,'pending');assert.deepEqual(f.moves,[[0,49,1]]);
 const next=recovery({progress_max_stage:50});assert.equal(next.run().status,'pending');assert.deepEqual(next.moves,[[0,50,1]]);
});

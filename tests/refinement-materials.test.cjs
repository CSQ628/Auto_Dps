const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');

function planning({counts=[10],characters=[1],storage=false,upgrades=[]}={}){
 const entries=counts.map((count,i)=>({place:storage?'storage':'inventory',index:i,info:{uid:'mat-'+i,id:410101,count,kind:16,grade:1,tier:0},item:{}}));
 entries.forEach(e=>e.item.info=e.info);
 const gear=new Map(characters.map(id=>[id,[{uid:'gear-'+id,info:{grade:1,tier:1,kind:1,count:1,confirmed:true,tradable:false},get_Uid:()=>'gear-'+id,get_IsLocked:()=>false,get_Sockets:()=>[]}]]));
 const store={get_TabCount:()=>1,IsTabUnlocked:()=>true,get_OccupiedCount:()=>storage?entries.length:0,get_SlotCountPerTab:()=>49,get_IsFull:()=>false};
 const im={get_Storage:()=>store,get_Cube:()=>({get_Level:()=>10}),GetEquipment:id=>({get_Has:()=>gear.get(id)})};
 const c={call:(o,n,args=[])=>o[n](...args),list:x=>x,read:(o,n)=>o[n],itemInfo:p=>p.info,
  isTradable:p=>p.tradable===true,protectedItem:(_,p)=>p.protected===true,canMoveStoredItem:()=>true,
  canRecycleItem:()=>false,protectedEquipped:()=>true,workshopCapacity:()=>9,containerEntries:()=>entries,keyHash:x=>x,
  equipmentPlans:()=>upgrades,hasAttachmentSpace:(_,p,m)=>!p.full&&!m.incompatible,equipmentRevision:p=>JSON.stringify([p.uid,p.revision||0]),
  fixtureCatalogue:{recipes:[{ID:1,CraftType:0,FusionType:3,Grade:1,MinTier:0,MaxTier:0,RequireCubeLevel:0,FusionCount:9}],tiers:[{tier:1,min:1}],normalMax:160,towerMax:10,maxCharacterLevel:101}};
 vm.createContext(c);vm.runInContext(fs.readFileSync('bridge/planner.js','utf8')+'\ncatalogueCache=fixtureCatalogue;',c);
 c.equipmentPlans=()=>upgrades;
 return {c,entries,gear,scan(modules={},capacity=100,options={}){
  const s={characters:characters.map(id=>({id,level:10})),squad:characters,record:{maxCleared:9},inventory:{count:storage?0:entries.length,capacity}};
  const actions=[];c.inventoryOpportunities(s,{},im,(kind,key,label,priority,data)=>actions.push({kind,key,label,priority,...data}),[],c.bridgeStrategy({modules,...options}));
  return {snapshot:s,actions};
 }};
}

test('refinement uses one unit and lets nine surplus materials synthesize without overlap',()=>{
 const f=planning(),r=f.scan(),refine=r.actions.find(a=>a.kind==='refine'),combine=r.actions.find(a=>a.kind==='combine');
 assert.ok(refine);assert.ok(combine);assert.equal(refine.materialCounts['mat-0'],1);assert.equal(combine.materialCounts['mat-0'],9);
 assert.equal(r.snapshot.refining.reservedMaterials,1);assert.equal(r.snapshot.refining.ready,1);
 assert.equal(f.entries[0].info.count,10,'planning must not change the native stock');
});
test('every hero receives one reservation and the same stack cannot be overallocated',()=>{
 for(const count of [1,2,3,11,12]){
  const r=planning({counts:[count],characters:[1,2,3]}).scan();
  const expected=Math.min(count-(count>=9?9:0),3);
  assert.equal(r.actions.filter(a=>a.kind==='refine').length,expected);
  const total=r.actions.filter(a=>['refine','combine'].includes(a.kind)).reduce((n,a)=>n+(a.materialCounts['mat-0']||0),0);
  assert.ok(total<=count);assert.equal(r.snapshot.refining.reservedMaterials,expected);
  assert.equal(r.actions.some(a=>a.kind==='combine'),count>=9);
 }
});
test('refinement and synthesis switches independently control reservations',()=>{
 for(const refine of [false,true])for(const combine of [false,true]){
  const r=planning().scan({refine,combine});assert.equal(r.actions.some(a=>a.kind==='refine'),refine);
  assert.equal(r.actions.some(a=>a.kind==='combine'),combine);assert.equal(r.snapshot.refining.status,refine?'ready':'disabled');
 }
});
test('warehouse attachments require enabled storage and use existing safe staging on full inventory',()=>{
 const f=planning({storage:true});
 let r=f.scan();assert.equal(r.snapshot.refining.status,'storage_pending');assert.ok(r.actions.some(a=>a.kind==='withdraw'));assert.ok(!r.actions.some(a=>a.kind==='refine'));
 r=f.scan({storage:false});assert.ok(!r.actions.some(a=>a.kind==='withdraw'||a.kind==='refine'));assert.equal(r.snapshot.refining.reservedMaterials,0);
 r=f.scan({},0);assert.ok(!r.actions.some(a=>a.kind==='refine'));assert.equal(r.snapshot.refining.warehousePending,1);
});
test('locked, tradable, full and mismatched targets never consume attachments',()=>{
 for(const mode of ['locked','trade','full','mismatch','protectedMaterial']){
  const f=planning(),gear=f.gear.get(1)[0];
  if(mode==='locked')gear.get_IsLocked=()=>true;if(mode==='trade')gear.tradable=true;if(mode==='full')gear.full=true;
  if(mode==='mismatch')f.entries[0].item.incompatible=true;if(mode==='protectedMaterial')f.entries[0].item.protected=true;
  assert.ok(!f.scan().actions.some(a=>a.kind==='refine'),mode);
 }
});
test('unknown append submission identity survives inventory churn and material reselection',()=>{
 const f=planning({counts:[2,3]}),first=f.scan().actions.find(a=>a.kind==='refine');
 f.entries[0].info.count=1;f.entries[1].info.grade=2;
 const second=f.scan().actions.find(a=>a.kind==='refine');assert.notEqual(first.allowed[0],second.allowed[0]);assert.equal(first.key,second.key);
 f.gear.get(1)[0].revision=1;assert.notEqual(f.scan().actions.find(a=>a.kind==='refine').key,first.key);
});

function execution(){
 const selected=[],sockets=[{index:5,id:410100,ability:1,value:2}],material={uid:'mat',id:410101,count:10,kind:16};
 const equipment={uid:'gear',id:1010404,count:1,kind:1},inv={get_Has:()=>material.count?[material]:[]};
 for(const p of [material,equipment])Object.assign(p,{isNull:()=>false,get_Uid:()=>p.uid,get_ConfigID:()=>p.id,get_Count:()=>p.count,get_Kind:()=>p.kind,get_Config:()=>({Tradable:p.tradable===true,Grade:p.grade??1,Tier:1}),get_IsLocked:()=>p.locked===true,get_IsServerConfirmed:()=>p.confirmed!==false,get_Sockets:()=>p===equipment?sockets:[],get_EquipmentConfig:()=>({}),get_AttachmentConfig:()=>({ItemType:1})});
 const im={get_Cube:()=>({get_IsEmpty:()=>selected.length===0,get_Has:()=>selected}),get_Inventory:()=>inv,get_Storage:()=>({get_Has:()=>[],get_SlotCountPerTab:()=>49}),
  get_Input:()=>({get_IsHolding:()=>false}),GetEquipment:()=>({get_Has:()=>[equipment]}),CanAttach:()=>true,GetSocketCount:()=>2,
  TryMoveToCube:p=>{selected.push(p);return true;},IsInUse:()=>false,IsEquipped:p=>p===equipment,FindRegistrations:()=>[]};
 let include=true,executed=0;
 const view={get_IncludeStorageToggle:()=>({get_isOn:()=>include,set_isOn:x=>include=x}),CollectSlots:()=>{},SetMode:x=>{assert.equal(x,0);},RebuildRules:()=>{},
  TryExecute:()=>{executed++;material.count--;sockets.push({index:6,id:material.id,ability:2,value:3});return true;},ReleaseAll:()=>{selected.length=0;}};
 const c={api:()=>()=>0,list:x=>x,read:(o,n)=>o[n],ref:x=>x,single:()=>im,
  call:(o,n,a=[])=>{if(typeof o[n]==='function')return o[n](...a);if(n==='get_Config')return {ItemType:1};return o[({get_Index:'index',get_ConfigID:'id',get_Ability:'ability',get_Value:'value'})[n]];}};
 vm.createContext(c);vm.runInContext(fs.readFileSync('bridge/systems.js','utf8')+'\nsceneObject=()=>viewFixture;activateCubeView=()=>({OnClickClose(){}});',c);c.viewFixture=view;
 const cmd={id:1,uid:'gear',slot:0,itemRevision:c.equipmentRevision(equipment),allowed:['mat'],materialCounts:{mat:1},batchSize:1};
 return {c,im,view,cmd,material,equipment,sockets,selected,executed:()=>executed,include:()=>include,run:()=>c.refineAction(cmd)};
}
test('native refinement confirms one consumed unit plus one appended socket and preserves the old effect',()=>{
 const f=execution(),old=JSON.stringify(f.sockets[0]),r=f.run();assert.equal(r.status,'confirmed');assert.equal(r.consumed[0].count,1);
 assert.equal(r.before,1);assert.equal(r.after,2);assert.equal(JSON.stringify(f.sockets[0]),old);assert.equal(f.material.count,9);
 assert.equal(f.selected.length,0);assert.equal(f.include(),true);
});
test('invalid budgets, changed targets and unavailable sockets fail before native consumption',()=>{
 for(const mode of ['quantity','count','revision','slot','full','trade','locked']){
  const f=execution();
  if(mode==='quantity')f.cmd.materialCounts.mat=2;if(mode==='count')f.material.count=0;if(mode==='revision')f.cmd.itemRevision='changed';
  if(mode==='slot')f.cmd.slot=1;if(mode==='full')f.im.GetSocketCount=()=>1;if(mode==='trade')f.equipment.tradable=true;if(mode==='locked')f.equipment.locked=true;
  assert.ok(['stale','waiting'].includes(f.run().status),mode);assert.equal(f.executed(),0);assert.equal(f.selected.length,0);
 }
});
test('native over-reservation and failed acceptance cannot cause refinement',()=>{
 for(const mode of ['extra','rejected']){
  const f=execution();f.im.TryMoveToCube=p=>{if(p===f.material&&mode==='rejected')return false;f.selected.push(p);if(p===f.material&&mode==='extra')f.selected.push(p);return true;};
  assert.equal(f.run().status,'waiting');assert.equal(f.executed(),0);assert.equal(f.material.count,10);assert.equal(f.selected.length,0);assert.equal(f.include(),true);
 }
});
test('added sockets alone never confirm missing, excessive or wrong material consumption',()=>{
 for(const mode of ['noConsumption','excessConsumption','wrongSocket','rewroteOld','extraSocket']){
  const f=execution();f.view.TryExecute=()=>{f.material.count-=mode==='noConsumption'?0:mode==='excessConsumption'?2:1;f.sockets.push({index:6,id:mode==='wrongSocket'?999:f.material.id,ability:2,value:3});
   if(mode==='rewroteOld')f.sockets[0].value=999;if(mode==='extraSocket')f.sockets.push({index:7,id:f.material.id,ability:3,value:4});return true;};
  const r=f.run();assert.equal(r.status,'pending',mode);assert.equal(r.reason,'refine_result_unconfirmed');assert.equal(r.socketAppend,undefined);
 }
});
test('preparation and cleanup faults recover without losing confirmation or replaying a lost response',()=>{
 let f=execution();f.view.RebuildRules=()=>{throw Error('not_ready');};assert.equal(f.run().reason,'native_preparation_failed');assert.equal(f.executed(),0);assert.equal(f.include(),true);
 f=execution();f.view.ReleaseAll=()=>{f.selected.length=0;throw Error('cleanup_failed');};assert.equal(f.run().status,'confirmed');assert.equal(f.material.count,9);assert.equal(f.include(),true);
 f=execution();f.view.TryExecute=()=>{f.material.count--;throw Error('lost_after_submit');};assert.throws(()=>f.run(),/lost_after_submit/);assert.equal(f.material.count,9);assert.equal(f.selected.length,0);assert.equal(f.include(),true);
});

test('refinement status explains warehouse supply, material protection and independent switches',async()=>{
 const {refinementStatusMessage:message}=await import('../web/src/refinement-status.mjs');
 assert.match(message({status:'disabled'}),/合成开关/);assert.match(message({status:'storage_pending',warehousePending:2}),/2 次.*取出仓库/);
 assert.match(message({status:'no_match',availableMaterials:1,protectedMaterials:3}),/3 件受保护/);
 assert.match(message({status:'ready',planned:3,ready:2}),/同槽换装先完成/);
});

test('nine refining materials are preserved for synthesis before any equipment append',()=>{
 const f=planning({counts:[4,3,2],characters:[1,2,3]});
 f.entries[1].info.id=420101;f.entries[2].info.id=430101;
 const r=f.scan(),a=r.actions.find(a=>a.kind==='combine'),s=r.snapshot.combining.refinementMaterials;
 assert.equal(a.category,2);assert.equal(a.batchSize,9);assert.equal(r.actions.some(a=>a.kind==='refine'),false);
 assert.equal(s.status,'ready');assert.equal(s.reservedForSynthesis,9);assert.equal(s.reservedForEquipment,0);
 assert.match(a.label,/合成精炼材料/);assert.equal(s.ready,1);
});

test('all complete material batches survive append planning while execution stays one batch',()=>{
 for(const counts of [[18],[19],[27],[4,7,8]]){
  const r=planning({counts,characters:[1,2,3]}).scan(),total=counts.reduce((a,b)=>a+b,0),complete=Math.floor(total/9)*9;
  assert.equal(r.snapshot.combining.refinementMaterials.reservedForSynthesis,complete);
  assert.equal(r.snapshot.refining.reservedMaterials,Math.min(total-complete,3));
  assert.equal(r.actions.find(a=>a.kind==='combine').batchSize,9);
 }
});

test('material synthesis follows the native batch size and unlock level without a fixed nine',()=>{
 const f=planning({counts:[5]});Object.assign(f.c.fixtureCatalogue.recipes[0],{FusionCount:4,RequireCubeLevel:11});
 let r=f.scan();assert.equal(r.snapshot.combining.refinementMaterials.status,'native_locked');assert.ok(!r.actions.some(a=>a.kind==='combine'));
 f.c.fixtureCatalogue.recipes[0].RequireCubeLevel=10;r=f.scan();
 assert.equal(r.actions.find(a=>a.kind==='combine').batchSize,4);assert.equal(r.actions.find(a=>a.kind==='refine').batchSize,1);
 assert.equal(r.snapshot.combining.refinementMaterials.reservedForSynthesis,4);
});

test('warehouse synthesis, protected stock and equipment switches remain independent',()=>{
 let f=planning({counts:[9],storage:true}),r=f.scan({refine:false});
 assert.equal(r.snapshot.combining.refinementMaterials.status,'storage_pending');assert.ok(r.actions.some(a=>a.kind==='withdraw'&&a.purpose==='combine'));
 r=f.scan({refine:false,storage:false});assert.equal(r.snapshot.combining.refinementMaterials.warehouse,9);
 assert.equal(r.snapshot.combining.refinementMaterials.storageEnabled,false);assert.equal(r.actions.some(a=>a.kind==='withdraw'||a.kind==='combine'),false);
 f=planning({counts:[9]});f.entries[0].item.protected=true;r=f.scan();
 assert.equal(r.snapshot.combining.refinementMaterials.protected,9);assert.equal(r.actions.some(a=>a.kind==='combine'||a.kind==='refine'),false);
});

test('synthesis status distinguishes material shortfall, native unlock and equipment refinement',async()=>{
 const {refinementMaterialStatusMessage:m}=await import('../web/src/refinement-status.mjs');
 assert.match(m({status:'ready',groups:1,ready:1}),/完整配方.*不被镶嵌占用/);
 assert.match(m({status:'materials_missing',nearest:[{available:6,required:9}]}),/6 \/ 9/);
 assert.match(m({status:'native_locked'}),/原生方块等级/);
 assert.match(m({status:'no_materials',storageEnabled:false,warehouse:9}),/仓库 9 件.*关闭/);
});


test('all tradable equipment grades through immortal are eligible, higher and unknown grades stay protected',()=>{
 for(const grade of [1,2,3,4,5,6,7,8,9,0,null]){
  const f=planning({counts:[1]}),p=f.gear.get(1)[0];p.tradable=true;Object.assign(p.info,{grade,tradable:true});
  const action=f.scan().actions.find(a=>a.kind==='refine');assert.equal(!!action,Number.isInteger(grade)&&grade>=1&&grade<=7,String(grade));
  if(action){assert.equal(action.allowTradableTarget,true);assert.equal(action.targetGrade,grade);}
  assert.ok(!f.scan({},100,{refine_tradable_equipment:false}).actions.some(a=>a.kind==='refine'));
 }
});
test('scarce attachments go to highest quality equipment across heroes before hero or slot order',()=>{
 const f=planning({counts:[1,1],characters:[1,2,3]});
 for(const [id,grade] of [[1,2],[2,7],[3,6]]){const p=f.gear.get(id)[0];p.tradable=grade>=6;Object.assign(p.info,{grade,tradable:p.tradable});}
 f.entries[1].info.grade=5;
 const actions=f.scan({combine:false}).actions.filter(a=>a.kind==='refine');
 assert.deepEqual(actions.map(a=>a.id),[2,3]);assert.equal(actions[0].allowed[0],'mat-1');assert.equal(actions[1].allowed[0],'mat-0');
 const p=f.gear.get(2)[0];f.gear.get(1).push({...p,uid:'better-slot',get_Uid:()=>'better-slot',info:{...p.info,grade:7,tier:2}});
 assert.equal(f.scan({combine:false}).actions.find(a=>a.kind==='refine').uid,'better-slot');
});
test('explicit tradable append keeps old sockets and does not grant permission for locked gear or materials',()=>{
 for(const grade of [1,5,6,7]){
  const f=execution();Object.assign(f.equipment,{grade,tradable:true});Object.assign(f.cmd,{allowTradableTarget:true,targetGrade:grade});
  const old=JSON.stringify(f.sockets[0]);const r=f.c.guardedItemAction(()=>f.run(),[{id:1}],[],[f.cmd.uid],[],f.cmd.uid,true);
  assert.equal(r.status,'confirmed');assert.equal(r.protectedChanged.length,0);assert.equal(r.tradeChanged.length,0);
  assert.equal(JSON.stringify(f.sockets[0]),old);assert.equal(f.equipment.tradable,true);assert.equal(f.material.count,9);
 }
 for(const mode of ['overGrade','gradeChanged','locked','unconfirmed','materialTrade','materialLocked','noPermission']){
  const f=execution();Object.assign(f.equipment,{grade:7,tradable:true});Object.assign(f.cmd,{allowTradableTarget:true,targetGrade:7});
  if(mode==='overGrade'){f.equipment.grade=8;f.cmd.targetGrade=8;}if(mode==='gradeChanged')f.equipment.grade=6;
  if(mode==='locked')f.equipment.locked=true;if(mode==='unconfirmed')f.equipment.confirmed=false;
  if(mode==='materialTrade')f.material.tradable=true;if(mode==='materialLocked')f.material.locked=true;if(mode==='noPermission')f.cmd.allowTradableTarget=false;
  assert.notEqual(f.run().status,'confirmed',mode);assert.equal(f.executed(),0,mode);assert.equal(f.material.count,10);
 }
});
test('authorized target append cannot hide other protected mutations or loss of trade attributes',()=>{
 for(const mode of ['oldSocket','tradeFlag','targetCount','materialCount']){
  const f=execution();Object.assign(f.equipment,{grade:7,tradable:true});Object.assign(f.cmd,{allowTradableTarget:true,targetGrade:7});
  const native=f.view.TryExecute;f.view.TryExecute=()=>{const r=native();if(mode==='oldSocket')f.sockets[0].value=999;
   if(mode==='tradeFlag')f.equipment.tradable=false;if(mode==='targetCount')f.equipment.count=0;if(mode==='materialCount')f.material.count--;return r;};
  const r=f.c.guardedItemAction(()=>f.run(),[{id:1}],[],[f.cmd.uid],[],f.cmd.uid,true);
  assert.ok(r.status==='pending'||r.protectedChanged.length||r.tradeChanged.length,mode);
 }
});

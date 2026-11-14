const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');
const recipe={ID:1,CraftType:0,FusionType:0,Grade:1,MinTier:1,MaxTier:1,RequireCubeLevel:0,FusionCount:9};
const gemRecipe={...recipe,ID:2,FusionType:3,MinTier:0,MaxTier:0};
function entry(uid,count=1,kind=1,place='inventory'){
 const info={uid,id:1,count,kind,grade:1,tier:kind===16?0:1};return {info,place,item:{info}};
}
function planning(entries,recipes=[recipe],extra={}){
 const storage={get_TabCount:()=>1,IsTabUnlocked:()=>true,get_OccupiedCount:()=>entries.filter(e=>e.place==='storage').length,get_SlotCountPerTab:()=>extra.storageCapacity??100,get_IsFull:()=>entries.filter(e=>e.place==='storage').length>=(extra.storageCapacity??100)};
 const gear=extra.gear||[],im={get_Storage:()=>storage,get_Cube:()=>({get_Level:()=>extra.cubeLevel??10,get_Capacity:()=>Object.hasOwn(extra,"cubeCapacity")?extra.cubeCapacity:9}),GetEquipment:()=>({get_Has:()=>gear})};
 const c={call:(o,n,args=[])=>o[n](...args),list:x=>x,itemInfo:p=>p.info,read:(o,n)=>o[n],isTradable:p=>!!p?.tradable,protectedItem:(_,p)=>entries.some(e=>e.item===p&&(e.protected||e.socketed)),canMoveStoredItem:()=>true,canRecycleItem:(_,p,allow)=>entries.some(e=>e.item===p&&!e.protected&&(!e.socketed||allow)),protectedEquipped:(_,p)=>!!p?.locked,workshopCapacity:()=>Object.hasOwn(extra,'cubeCapacity')?extra.cubeCapacity:9,containerEntries:()=>entries,keyHash:x=>x,hasAttachmentSpace:()=>true,
  fixtureCatalogue:{recipes,tiers:extra.tiers||[{tier:1,min:1}],materialSources:extra.materialSources,normalMax:100,towerMax:100,maxCharacterLevel:100},upgrades:extra.upgrades||[]};
 vm.createContext(c);vm.runInContext(fs.readFileSync('bridge/planner.js','utf8')+'\ncatalogueCache=fixtureCatalogue;equipmentPlans=(_,a,b,c,needed)=>{for(const p of upgrades)needed.add(p.uid);return upgrades;};globalThis.run=inventoryOpportunities;',c);
 return {scan(modules={},options={}){const snapshot={characters:extra.characters||[{id:1,level:1}],squad:[1],record:{maxCleared:extra.frontier??0},inventory:{count:entries.filter(e=>e.place==='inventory').length,capacity:extra.capacity??100}},actions=[],issues=[];
  c.run(snapshot,{},im,(kind,key,label,priority,data)=>actions.push({kind,key,priority,...data}),issues,c.bridgeStrategy({modules,...options}));return {snapshot,actions,issues};}};
}
test('ready and warehouse fusion ingredients never overlap decomposition across module switches',()=>{
 for(const combine of [true,false])for(const decompose of [true,false])for(const storage of [true,false]){
  const entries=[entry('batch',4),entry('stored',5,1,'storage'),entry('obsolete')];entries[2].info.grade=2;
  const {actions}=planning(entries,[recipe],{capacity:2}).scan({combine,decompose,storage});
  const consumed=actions.filter(a=>['combine','decompose','forge','refine'].includes(a.kind));
  const owner=new Map();for(const a of consumed)for(const uid of a.allowed){assert.ok(!owner.has(uid),`${uid}: ${owner.get(uid)} and ${a.kind}`);owner.set(uid,a.kind);}
  assert.equal(actions.some(a=>a.kind==='combine'),false);
  assert.equal(actions.some(a=>a.kind==='decompose'),decompose);
  if(combine&&storage){assert.equal(owner.has('batch'),false);assert.equal(owner.get('obsolete'),decompose?'decompose':undefined);}
  else if(decompose){assert.equal(owner.get('batch'),'decompose');}
  if(!storage)assert.ok(!actions.some(a=>['deposit','withdraw'].includes(a.kind)));
 }
});
test('complete held batch is allocated once and obsolete remainder can be decomposed',()=>{
 const {actions}=planning([entry('batch',9),entry('remainder')],[recipe],{capacity:2}).scan();
 const combine=actions.find(a=>a.kind==='combine'),decompose=actions.find(a=>a.kind==='decompose');
 assert.deepEqual(Array.from(combine.allowed),['batch']);assert.deepEqual(Array.from(decompose.allowed),['remainder']);
 assert.equal(combine.materialCounts.batch,9);assert.equal(combine.batchSize,9);
});
test('disabled recipes release reservation and cannot manufacture a false ready state',()=>{
 const f=planning([entry('batch',9)],[recipe],{capacity:1});
 let result=f.scan({combine:false});assert.equal(result.snapshot.combining.groups,0);assert.equal(result.actions.find(a=>a.kind==='decompose').materialCounts.batch,9);
 result=f.scan({combine:false,decompose:false});assert.ok(result.actions.some(a=>a.kind==='deposit'));assert.ok(!result.actions.some(a=>['combine','decompose','withdraw'].includes(a.kind)));
});
test('decomposition quantity limit counts units in a stack instead of only UIDs',()=>{
 const {actions}=planning([entry('stack',100),entry('extra')],[],{capacity:2}).scan({}, {recycle_batch:3});
 const action=actions.find(a=>a.kind==='decompose');assert.equal(action.batchSize,3);assert.equal(action.materialCounts.stack,3);assert.deepEqual(Array.from(action.allowed),['stack']);
});
test('equippable gear is retained even when synthesis is disabled',()=>{
 const upgrades=[{id:1,uid:'upgrade',slot:0,source:'inventory'}];
 const {actions}=planning([entry('upgrade'),entry('obsolete')],[],{capacity:2,upgrades}).scan({combine:false});
 assert.ok(actions.some(a=>a.kind==='equipment'));assert.deepEqual(Array.from(actions.find(a=>a.kind==='decompose').allowed),['obsolete']);
});
test('socket material belongs to one hero and cannot also be combined',()=>{
 const gear=[{get_IsLocked:()=>false,get_Uid:()=>'equipped',get_Sockets:()=>[]}];
 const f=planning([entry('gems',9,16)],[gemRecipe],{gear,characters:[{id:1,level:1},{id:2,level:1}],capacity:1});
 let {actions,snapshot}=f.scan();assert.equal(actions.filter(a=>a.kind==='refine').length,1);assert.ok(!actions.some(a=>a.kind==='combine'));assert.equal(snapshot.inventoryFlow.blocked,false);
 actions=f.scan({refine:false}).actions;assert.equal(actions.find(a=>a.kind==='combine').materialCounts.gems,9);assert.ok(!actions.some(a=>a.kind==='refine'));
});
test('forge reservation cannot also enter synthesis and releases when forge is disabled',()=>{
 const forge={ID:3,CraftType:1,RequireCubeLevel:0,MinTier:1,MaxTier:1,CraftPart:1,MaterialID:[1],MaterialCount:[1]};
 const f=planning([entry('gems',9,16)],[forge,gemRecipe],{capacity:1});
 let result=f.scan();assert.ok(result.actions.some(a=>a.kind==='forge'));assert.ok(!result.actions.some(a=>a.kind==='combine'));assert.equal(result.snapshot.inventoryFlow.blocked,false);
 result=f.scan({forge:false});assert.ok(result.actions.some(a=>a.kind==='combine'));assert.ok(!result.actions.some(a=>a.kind==='forge'));
});
function execution(kind='combine'){
 const data={uid:'stack',id:1,count:100,kind:kind==='combine'?16:1,tier:kind==='combine'?0:1,grade:1};
 const item={isNull:()=>false,get_Uid:()=>data.uid,get_ConfigID:()=>data.id,get_Count:()=>data.count,get_Kind:()=>data.kind,get_Config:()=>({Tradable:false,Grade:data.grade,Tier:data.tier}),get_IsLocked:()=>false,get_IsServerConfirmed:()=>true,get_Sockets:()=>data.sockets||[]};
 const selected=[],calls=[],inventory={items:[item],get_Has(){return this.items;}};
 const cube={get_IsEmpty:()=>!selected.length,get_Has:()=>selected,CanReserveMore:()=>selected.length<100};
 let tier=0,category=0,include=true;
 const view={CanStartExecute:()=>true,get_SelectedTier:()=>tier,get_SelectedCategory:()=>category,get_IncludeStorageToggle:()=>({get_isOn:()=>include,set_isOn:x=>{include=x;}}),SetCategory:x=>{category=x;},SetSelectedTier:x=>{tier=x;},RefreshLevelRangeOptions:()=>{},RebuildRules:()=>{},get_CanExecute:()=>true,
  TryExecute:()=>{calls.push('execute');data.count-=selected.length;return true;},ReleaseAll:()=>{selected.length=0;}};
 const im={get_Inventory:()=>inventory,get_Storage:()=>({get_Has:()=>[],get_SlotCountPerTab:()=>49,IsTabUnlocked:()=>true}),get_Cube:()=>cube,get_Input:()=>({get_IsHolding:()=>false}),IsInUse:()=>false,IsEquipped:()=>false,FindRegistrations:()=>[],TryMoveToCube:p=>{selected.push(p);return true;}};
 const c={api:()=>()=>0,list:x=>x,read:(o,n)=>o[n],ref:x=>x,call:(o,n,a=[])=>o[n](...a),single:n=>n==='DG.UI.PopupLayoutHandler'?{get_AnyPopupOpen:()=>false}:n==='DG.Manager.CurrencyManager'?{Get:()=>0}:im};
 vm.createContext(c);vm.runInContext(fs.readFileSync('bridge/systems.js','utf8')+'\nsceneObject=()=>testView;activateCubeView=()=>({});globalThis.run=cubeAction;globalThis.recycle=guardedRecycleAction;',c);c.testView=view;
 const cmd={kind,category:2,tier:kind==='combine'?0:1,maxGrade:1,allowed:['stack'],materialCounts:{stack:kind==='combine'?9:3},batchSize:kind==='combine'?9:3};
 return {data,view,cube,selected,calls,im,cmd,run:()=>c.run(cmd),guarded:()=>c.recycle(cmd,[]),get include(){return include;}};
}
for(const kind of ['combine','decompose'])test(kind+' consumes one exact planned batch even if native cube accepts more',()=>{
 const f=execution(kind),r=f.run();assert.equal(r.status,'confirmed');assert.equal(r.consumed[0].count,f.cmd.batchSize);assert.equal(f.data.count,100-f.cmd.batchSize);assert.equal(f.selected.length,0);assert.equal(f.include,true);assert.equal(f.calls.length,1);
});
test('partial, excessive and changed native reservations cannot consume',()=>{
 for(const mode of ['partial','excess','tier','kind','quantity']){
  const f=execution();
  if(mode==='partial')f.cube.CanReserveMore=()=>f.selected.length<5;
  if(mode==='excess')f.im.TryMoveToCube=p=>{f.selected.push(p,p);return true;};
  if(mode==='tier')f.data.tier=2;if(mode==='kind')f.data.kind=32;if(mode==='quantity')f.data.count=8;
  const r=f.run();assert.ok(['waiting','stale'].includes(r.status));assert.equal(f.calls.length,0);assert.equal(f.data.count,mode==='quantity'?8:100);assert.equal(f.selected.length,0);assert.equal(f.include,true);
 }
});
test('invalid material budgets fail before opening native cube',()=>{
 for(const change of [{materialCounts:{stack:0}},{materialCounts:{stack:9,other:1}},{batchSize:10}]){
  const f=execution();Object.assign(f.cmd,change);f.view.CanStartExecute=()=>{throw Error('must not open');};
  assert.equal(f.run().reason,'material_quantity_changed');assert.equal(f.calls.length,0);
 }
});

test('upper-bound equipment submits the unlocked recipe band with exact material quantities',()=>{
 const gear=entry('boundary',9);gear.info.tier=6;gear.info.grade=2;
 const band={...recipe,ID:10502,Grade:2,MinTier:5,MaxTier:6,RequireCubeLevel:20};
 const {actions}=planning([gear],[band],{cubeLevel:21}).scan();
 const action=actions.find(a=>a.kind==='combine');assert.ok(action);assert.equal(action.recipe,10502);
 assert.equal(action.tier,5);assert.equal(action.materialTier,6);assert.equal(action.batchSize,9);assert.equal(action.materialCounts.boundary,9);
});


test('recycling respects the native cube capacity and configured unit ceiling',()=>{
 for(const [capacity,configured,expected] of [[9,12,9],[4,12,4],[20,12,12],[9,3,3]]){
  for(const stacked of [true,false]){
   const entries=stacked?[entry('stack',25)]:Array.from({length:25},(_,i)=>entry('item-'+i));
   const {snapshot,actions}=planning(entries,[],{capacity:entries.length,cubeCapacity:capacity}).scan({}, {recycle_batch:configured});
   const action=actions.find(a=>a.kind==='decompose');assert.ok(action);
   assert.equal(action.batchSize,expected);assert.equal(Object.values(action.materialCounts).reduce((n,c)=>n+c,0),expected);
   assert.equal(snapshot.recycling.planned,expected);assert.equal(snapshot.recycling.batchLimit,Math.min(capacity,configured));
   assert.equal(snapshot.recycling.nativeCapacity,capacity);
  }
 }
});

test('unknown or invalid native capacity cannot schedule decomposition',()=>{
 for(const capacity of [undefined,null,0,-1,NaN,Infinity,1.5,true,'9']){
  const {snapshot,actions}=planning([entry('old',25)],[],{capacity:1,cubeCapacity:capacity}).scan();
  assert.equal(actions.some(a=>a.kind==='decompose'),false);assert.equal(snapshot.recycling.planned,0);
 }
});

test('native nine-slot recycling drains a larger stack across exact replanned batches',()=>{
 const f=execution('decompose');f.data.count=25;f.cube.CanReserveMore=()=>f.selected.length<9;
 const batches=[];
 while(f.data.count>0){
  const {actions}=planning([entry('stack',f.data.count)],[],{capacity:1,cubeCapacity:9}).scan();
  Object.assign(f.cmd,actions.find(a=>a.kind==='decompose'));
  const r=f.run();assert.equal(r.status,'confirmed');assert.equal(r.consumed[0].count,f.cmd.batchSize);
  assert.equal(f.selected.length,0);assert.equal(f.include,true);batches.push(r.consumed[0].count);
 }
 assert.deepEqual(batches,[9,9,7]);assert.equal(f.calls.length,3);
});

test('decomposition still refuses incomplete or excessive reservations after capacity planning',()=>{
 for(const mode of ['partial','excess']){
  const f=execution('decompose');f.cmd.materialCounts.stack=9;f.cmd.batchSize=9;
  if(mode==='partial')f.cube.CanReserveMore=()=>f.selected.length<5;
  else f.im.TryMoveToCube=p=>{f.selected.push(p,p);return true;};
  assert.equal(f.run().reason,'material_quantity_changed');assert.equal(f.calls.length,0);
  assert.equal(f.data.count,100);assert.equal(f.selected.length,0);assert.equal(f.include,true);
 }
});

test('authorized socketed retirement excludes upgrades, locked gear and recipe ingredients',()=>{
 const old=entry('old');old.socketed=true;old.info.sockets=2;
 const upgrade=entry('upgrade');upgrade.socketed=true;
 const locked=entry('locked');locked.protected=true;locked.socketed=true;
 const f=planning([old,upgrade,locked],[],{capacity:3,upgrades:[{uid:'upgrade',id:1,slot:0}]});
 assert.equal(f.scan({}, {recycle_socketed_equipment:false}).actions.some(a=>a.kind==='decompose'),false);
 const r=f.scan({}, {recycle_socketed_equipment:true});
 assert.deepEqual(Array.from(r.actions.find(a=>a.kind==='decompose').allowed),['old']);
 assert.equal(r.actions.find(a=>a.kind==='decompose').recycleSocketed,true);
 assert.equal(r.actions.some(a=>a.kind==='combine'),false);
});
test('tradable current gear creates forge demand while locked slots do not',()=>{
 const forge={ID:3,CraftType:1,RequireCubeLevel:0,MinTier:1,MaxTier:2,CraftPart:1,MaterialID:[1],MaterialCount:[1]};
 const current={info:{tier:1,grade:1},tradable:true,get_IsLocked:()=>false};
 const f=planning([entry('mat',1,8)],[forge],{gear:[current]});
 assert.ok(f.scan().actions.some(a=>a.kind==='forge'));
 current.locked=true;assert.ok(!f.scan().actions.some(a=>a.kind==='forge'));
});
test('forge diagnostics state missing and protected material quantities',()=>{
 const forge={ID:3,CraftType:1,RequireCubeLevel:0,MinTier:1,MaxTier:1,CraftPart:1,MaterialID:[1,2],MaterialCount:[1,1]};
 const material=entry('partial',1,8),protectedMat=entry('protected',1,8);protectedMat.info.id=2;protectedMat.protected=true;
 const r=planning([material,protectedMat],[forge]).scan();assert.equal(r.snapshot.forging.status,'materials_missing');
 assert.equal(r.snapshot.forging.materials.find(m=>m.id===2).protected,1);assert.equal(r.actions.some(a=>a.kind==='forge'),false);
});

test('socketed old equipment requires explicit retirement authorization at execution',()=>{
 const f=execution('decompose');f.data.sockets=[{get_Index:()=>0,get_ConfigID:()=>1,get_Ability:()=>2,get_Value:()=>3}];
 assert.equal(f.run().reason,'protected_or_missing_material');assert.equal(f.calls.length,0);
 f.cmd.recycleSocketed=true;const r=f.guarded();assert.equal(r.status,'confirmed');assert.equal(r.protectedChanged.length,0);
});

test('authorized socketed retirement still detects loss of a different locked item',()=>{
 const f=execution('decompose'),inventory=f.im.get_Inventory();f.data.sockets=[{get_Index:()=>0,get_ConfigID:()=>1,get_Ability:()=>2,get_Value:()=>3}];
 const other={...inventory.items[0],get_Uid:()=>'locked-other',get_IsLocked:()=>true,get_Sockets:()=>[]};inventory.items.push(other);
 f.view.TryExecute=()=>{f.data.count-=3;inventory.items=inventory.items.filter(p=>p!==other);return true;};f.cmd.recycleSocketed=true;
 const r=f.guarded();assert.equal(r.protectedChanged.length,1);assert.equal(r.protectedChanged[0].uid,'locked-other');
});

test('old accessories join native retirement without consuming crafting materials',()=>{
 const accessory=entry('old-accessory',1,4),material=entry('material',1,8);
 const r=planning([accessory,material],[],{capacity:2}).scan();
 assert.deepEqual(Array.from(r.actions.find(a=>a.kind==='decompose').allowed),['old-accessory']);
 const f=execution('decompose');f.data.kind=4;assert.equal(f.run().status,'confirmed');
});

test('partially stocked forge recipe reserves ingredients against material synthesis',()=>{
 const partial=entry('partial',9,8),forge={ID:3,CraftType:1,RequireCubeLevel:0,MinTier:1,MaxTier:1,CraftPart:1,MaterialID:[1,2],MaterialCount:[1,1]};
 const fusion={...recipe,FusionType:4};
 const r=planning([partial],[forge,fusion]).scan();assert.equal(r.snapshot.forging.status,'materials_missing');
 assert.equal(r.actions.some(a=>['forge','combine','decompose'].includes(a.kind)),false);
});

const partialForge={ID:3,CraftType:1,RequireCubeLevel:0,MinTier:1,MaxTier:1,CraftPart:1,MaterialID:[1,2],MaterialCount:[1,1]};
const forgeMaterialFusion={...recipe,FusionType:4};
test('incomplete forging retains exact demand while surplus stacks can synthesize',()=>{
 for(const required of [1,2,3])for(const count of [1,8,9,10,11,12,18,20,100]){
  const forge={...partialForge,MaterialCount:[required,1]};
  const r=planning([entry('partial',count,8)],[forge,forgeMaterialFusion]).scan();
  const combine=r.actions.find(a=>a.kind==='combine');
  assert.equal(!!combine,count-required>=9,`stock=${count}, reserve=${required}`);
  if(combine){assert.equal(combine.materialCounts.partial,9);assert.ok(count-combine.batchSize>=required);}
  assert.equal(r.actions.some(a=>a.kind==='forge'),false);
 }
});

test('incomplete forge reservations share only surplus quantities across inventory and storage',()=>{
 const stored=entry('stored',4,8,'storage'),held=entry('held',6,8);
 const f=planning([held,stored],[partialForge,forgeMaterialFusion]);
 let r=f.scan();assert.equal(r.snapshot.combining.warehousePending,1);
 assert.equal(r.actions.find(a=>a.kind==='withdraw').uid,'stored');
 assert.equal(r.actions.some(a=>a.kind==='combine'),false);
 stored.place='inventory';r=f.scan();
 const combine=r.actions.find(a=>a.kind==='combine');assert.ok(combine);
 assert.equal(combine.materialCounts.held,5);assert.equal(combine.materialCounts.stored,4);
 assert.equal(held.info.count,6);assert.equal(stored.info.count,4);
 assert.equal(f.scan({storage:false}).actions.some(a=>a.kind==='combine'),true);
});

test('complete forging and protected or inaccessible ingredients never release reserved units',()=>{
 const other=entry('other',1,8);other.info.id=2;
 const stock=entry('stock',10,8),f=planning([stock,other],[partialForge,forgeMaterialFusion]);
 let r=f.scan();assert.ok(r.actions.some(a=>a.kind==='forge'));assert.equal(r.actions.some(a=>a.kind==='combine'),false);
 other.place='storage';r=f.scan();assert.ok(r.actions.some(a=>a.kind==='withdraw'&&a.purpose==='forge'));assert.equal(r.actions.some(a=>a.kind==='combine'),false);
 stock.protected=true;r=f.scan();assert.equal(r.actions.some(a=>['forge','combine'].includes(a.kind)),false);
 stock.protected=false;stock.place='storage';r=f.scan({storage:false});assert.equal(r.actions.some(a=>['forge','combine','withdraw'].includes(a.kind)),false);
});

test('surplus synthesis replans until only forge demand and an incomplete batch remain',()=>{
 const stock=entry('stock',29,8);let batches=0;
 while(true){
  const r=planning([stock],[partialForge,forgeMaterialFusion]).scan();const action=r.actions.find(a=>a.kind==='combine');
  if(!action)break;
  stock.info.count-=action.materialCounts.stock;batches++;
 }
 assert.equal(batches,3);assert.equal(stock.info.count,2);
 const other=entry('other',1,8);other.info.id=2;
 const action=planning([stock,other],[partialForge,forgeMaterialFusion]).scan().actions.find(a=>a.kind==='forge');
 assert.ok(action);assert.ok(action.allowed.includes('stock'));assert.ok(action.allowed.includes('other'));
});

test('planned surplus executes natively without consuming retained forge demand',()=>{
 const f=execution();f.data.kind=8;f.data.tier=1;f.data.count=10;
 const planned=planning([entry('stack',10,8)],[partialForge,forgeMaterialFusion]).scan().actions.find(a=>a.kind==='combine');
 assert.ok(planned);Object.assign(f.cmd,planned);
 const result=f.run();assert.equal(result.status,'confirmed');assert.equal(result.consumed[0].count,9);
 assert.equal(f.data.count,1);assert.equal(f.selected.length,0);assert.equal(f.include,true);
 assert.equal(planning([entry('stack',f.data.count,8)],[partialForge,forgeMaterialFusion]).scan().actions.some(a=>a.kind==='combine'),false);
 const other=entry('other',1,8);other.info.id=2;
 const next=planning([entry('stack',f.data.count,8),other],[partialForge,forgeMaterialFusion]).scan();
 assert.ok(next.actions.some(a=>a.kind==='forge'));assert.equal(next.actions.some(a=>a.kind==='combine'),false);
});

test('craft priorities are configurable and missing first-choice material does not block ready parts',()=>{
 const main={ID:1,CraftType:1,RequireCubeLevel:0,MinTier:1,MaxTier:1,CraftPart:1,MaterialID:[1],MaterialCount:[1]},accessory={...main,ID:7,CraftPart:7};
 const f=planning([entry('material',1,8)],[accessory,main]);
 assert.equal(f.scan().actions.find(a=>a.kind==='forge').part,1);
 assert.equal(f.scan({}, {forge_priority_main_weapon:7,forge_priority_accessory:1}).actions.find(a=>a.kind==='forge').part,7);
 const r=planning([entry('material',1,8)],[{...main,MaterialID:[2]},accessory]).scan();
 assert.equal(r.actions.find(a=>a.kind==='forge').part,7);
});


test('whole inventory planning retains reachable lower upgrades and releases only exact surplus to fusion',()=>{
 const low={ID:501,CraftType:1,CraftPart:1,RequireCubeLevel:20,MinTier:5,MaxTier:6,MaterialID:[11,12],MaterialCount:[1,1]};
 const high={...low,ID:601,RequireCubeLevel:30,MinTier:6,MaxTier:7,MaterialID:[21,22]};
 const sources={known:true,materials:Object.fromEntries([11,12,21,22].map(id=>[id,{firstStage:id<20?21:40,firstFreeStage:id<20?21:41,fusion:[]}]))};
 const alloy={...recipe,ID:705,FusionType:4,Grade:1,MinTier:5,MaxTier:5,RequireCubeLevel:20};
 const stock=entry('stock',10,8);stock.info.id=11;stock.info.tier=5;
 const options={cubeLevel:33,characters:[{id:1,level:33}],tiers:[{tier:5,min:20},{tier:6,min:30}],frontier:39,materialSources:sources};
 let r=planning([stock],[high,low,alloy],options).scan();
 assert.equal(r.snapshot.forging.recipe,501);assert.equal(r.snapshot.forging.source,'drop');
 assert.equal(r.actions.find(a=>a.kind==='combine').materialCounts.stock,9);assert.equal(stock.info.count,10);
 stock.info.count=9;r=planning([stock],[high,low,alloy],options).scan();
 assert.equal(r.actions.some(a=>a.kind==='combine'),false);
 const b=entry('b',1,8);b.info.id=12;b.info.tier=5;
 r=planning([stock,b],[high,low,alloy],options).scan();
 assert.equal(r.actions.find(a=>a.kind==='forge').recipe,501);assert.equal(r.actions.some(a=>a.kind==='combine'),false);
});

test('alternative part retention never enters the selected native forge input list',()=>{
 const main={ID:11,CraftType:1,CraftPart:1,RequireCubeLevel:0,MinTier:1,MaxTier:1,MaterialID:[1],MaterialCount:[1]},accessory={...main,ID:12,CraftPart:7,MaterialID:[2,3],MaterialCount:[1,1]};
 const entries=[entry('main',1,8),entry('other',1,8)];entries[1].info.id=2;
 const materialSources={known:true,materials:{1:{firstStage:1,firstFreeStage:1,fusion:[]},2:{firstStage:1,firstFreeStage:1,fusion:[]},3:{firstStage:1,firstFreeStage:1,fusion:[]}}};
 const r=planning(entries,[main,accessory],{frontier:1,materialSources}).scan();
 assert.deepEqual(Array.from(r.actions.find(a=>a.kind==='forge').allowed),['main']);
 assert.equal(r.snapshot.inventoryFlow.recipeReserved,2);
});

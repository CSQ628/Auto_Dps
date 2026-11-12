const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');
const recipe={ID:1,CraftType:0,FusionType:0,Grade:1,MinTier:1,MaxTier:1,RequireCubeLevel:0,FusionCount:9};
const gemRecipe={...recipe,ID:2,FusionType:3,MinTier:0,MaxTier:0};
function entry(uid,count=1,kind=1,place='inventory'){
 const info={uid,id:1,count,kind,grade:1,tier:kind===16?0:1};return {info,place,item:{info}};
}
function planning(entries,recipes=[recipe],extra={}){
 const storage={get_TabCount:()=>1,IsTabUnlocked:()=>true,get_OccupiedCount:()=>entries.filter(e=>e.place==='storage').length,get_SlotCountPerTab:()=>extra.storageCapacity??100,get_IsFull:()=>entries.filter(e=>e.place==='storage').length>=(extra.storageCapacity??100)};
 const gear=extra.gear||[],im={get_Storage:()=>storage,get_Cube:()=>({get_Level:()=>extra.cubeLevel??10}),GetEquipment:()=>({get_Has:()=>gear})};
 const c={call:(o,n,args=[])=>o[n](...args),list:x=>x,itemInfo:p=>p.info,read:(o,n)=>o[n],isTradable:()=>false,protectedItem:(_,p)=>!!p.protected,canMoveStoredItem:()=>true,containerEntries:()=>entries,keyHash:x=>x,hasAttachmentSpace:()=>true,
  fixtureCatalogue:{recipes,tiers:[{tier:1,min:1}],normalMax:100,towerMax:100,maxCharacterLevel:100},upgrades:extra.upgrades||[]};
 vm.createContext(c);vm.runInContext(fs.readFileSync('bridge/planner.js','utf8')+'\ncatalogueCache=fixtureCatalogue;equipmentPlans=(_,a,b,c,needed)=>{for(const p of upgrades)needed.add(p.uid);return upgrades;};globalThis.run=inventoryOpportunities;',c);
 return {scan(modules={},options={}){const snapshot={characters:extra.characters||[{id:1,level:1}],squad:[1],inventory:{count:entries.filter(e=>e.place==='inventory').length,capacity:extra.capacity??100}},actions=[],issues=[];
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
 const item={isNull:()=>false,get_Uid:()=>data.uid,get_ConfigID:()=>data.id,get_Count:()=>data.count,get_Kind:()=>data.kind,get_Config:()=>({Tradable:false,Grade:data.grade,Tier:data.tier}),get_IsLocked:()=>false,get_IsServerConfirmed:()=>true,get_Sockets:()=>[]};
 const selected=[],calls=[],inventory={items:[item],get_Has(){return this.items;}};
 const cube={get_IsEmpty:()=>!selected.length,get_Has:()=>selected,CanReserveMore:()=>selected.length<100};
 let tier=0,category=0,include=true;
 const view={CanStartExecute:()=>true,get_SelectedTier:()=>tier,get_SelectedCategory:()=>category,get_IncludeStorageToggle:()=>({get_isOn:()=>include,set_isOn:x=>{include=x;}}),SetCategory:x=>{category=x;},SetSelectedTier:x=>{tier=x;},RefreshLevelRangeOptions:()=>{},RebuildRules:()=>{},get_CanExecute:()=>true,
  TryExecute:()=>{calls.push('execute');data.count-=selected.length;return true;},ReleaseAll:()=>{selected.length=0;}};
 const im={get_Inventory:()=>inventory,get_Cube:()=>cube,get_Input:()=>({get_IsHolding:()=>false}),IsInUse:()=>false,IsEquipped:()=>false,FindRegistrations:()=>[],TryMoveToCube:p=>{selected.push(p);return true;}};
 const c={api:()=>()=>0,list:x=>x,read:(o,n)=>o[n],ref:x=>x,call:(o,n,a=[])=>o[n](...a),single:n=>n==='DG.UI.PopupLayoutHandler'?{get_AnyPopupOpen:()=>false}:n==='DG.Manager.CurrencyManager'?{Get:()=>0}:im};
 vm.createContext(c);vm.runInContext(fs.readFileSync('bridge/systems.js','utf8')+'\nsceneObject=()=>testView;activateCubeView=()=>({});globalThis.run=cubeAction;',c);c.testView=view;
 const cmd={kind,category:2,tier:kind==='combine'?0:1,maxGrade:1,allowed:['stack'],materialCounts:{stack:kind==='combine'?9:3},batchSize:kind==='combine'?9:3};
 return {data,view,cube,selected,calls,im,cmd,run:()=>c.run(cmd),get include(){return include;}};
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

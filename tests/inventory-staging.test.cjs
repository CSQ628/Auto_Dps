const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');
const c={};vm.createContext(c);vm.runInContext(fs.readFileSync('bridge/planner.js','utf8')+'\nglobalThis.subject={stagingDeposit,fusionPlans,fusionTasks};',c);
const entry=(uid,count=1,kind=1,place='inventory')=>({place,info:{uid,count,kind,grade:1,tier:kind===16?0:1}});
test('full inventory can stage retained gear without consuming it or moving the active recipe ingredients',()=>{
 const gems=entry('held-gems',4,16),stored=entry('warehouse-gems',5,16,'storage');
 const held=[gems,...Array.from({length:45},(_,i)=>entry('retained-'+i))];
 const needed=new Set(held.map(e=>e.info.uid)),materials=new Set([gems.info.uid,stored.info.uid]);
 const recalls=[{entries:[gems,stored],priority:103}];
 const stash=c.subject.stagingDeposit(held,needed,materials,new Set(),true,recalls);
 assert.ok(stash);assert.notEqual(stash.info.uid,gems.info.uid);assert.equal(stash.info.count,1);
 assert.equal(c.subject.stagingDeposit(held,needed,materials,new Set(),false,recalls),null);
 const recipe={ID:1,CraftType:0,FusionType:3,Grade:1,MinTier:0,MaxTier:0,RequireCubeLevel:0,FusionCount:9};
 let task=c.subject.fusionTasks(c.subject.fusionPlans([gems,stored],[recipe],1),1)[0];assert.equal(task.withdraw.info.uid,stored.info.uid);
 stored.place='inventory';task=c.subject.fusionTasks(c.subject.fusionPlans([gems,stored],[recipe],1),0)[0];assert.equal(task.ready,true);
});
test('no safe held item or only the target recipe leaves staging blocked',()=>{
 assert.equal(c.subject.stagingDeposit([],new Set(),new Set(),new Set(),true,[]),null);
 const gem=entry('gem',4,16);assert.equal(c.subject.stagingDeposit([gem],new Set(['gem']),new Set(['gem']),new Set(),true,[{entries:[gem],priority:103}]),null);
});


test('staging keeps ready materials, retirees and immediate equipment upgrades in the backpack',()=>{
 const held=[entry('recipe'),entry('retire'),entry('equip')];
 assert.equal(c.subject.stagingDeposit(held,new Set(['equip']),new Set(['recipe']),new Set(['retire']),true,[],new Set(['equip'])),null);
});
test('ordinary idle items stage before protected items',()=>{
 const trade={...entry('trade',1,16),consumable:false},plain={...entry('plain'),consumable:true};
 assert.equal(c.subject.stagingDeposit([trade,plain],new Set(),new Set(),new Set(),false,[]).info.uid,'plain');
});
function planningFixture(entries,capacity=2,storageCapacity=1,recipes=[]){
 const storage={get_TabCount:()=>1,IsTabUnlocked:()=>true,get_OccupiedCount:()=>entries.filter(e=>e.place==='storage').length,get_SlotCountPerTab:()=>storageCapacity,get_IsFull:()=>entries.filter(e=>e.place==='storage').length>=storageCapacity};
 const im={get_Storage:()=>storage,get_Cube:()=>({get_Level:()=>1,get_Capacity:()=>9}),GetEquipment:()=>({get_Has:()=>[]})};
 const ctx={call:(o,n,args=[])=>o[n](...args),list:x=>x,itemInfo:p=>p.info,read:(o,n)=>o[n],isTradable:p=>p.info.tradable===true,protectedItem:(_,p)=>!!p.protected,canMoveStoredItem:(_,p)=>!p.blocked,workshopCapacity:()=>9,canRecycleItem:(_,p)=>!p.protected,protectedEquipped:()=>false,containerEntries:()=>entries,keyHash:x=>x,
  fixtureCatalogue:{recipes,tiers:[{tier:1,min:1}],normalMax:100,towerMax:100,maxCharacterLevel:100}};
 vm.createContext(ctx);vm.runInContext(fs.readFileSync('bridge/planner.js','utf8')+'\ncatalogueCache=fixtureCatalogue;equipmentPlans=()=>[];globalThis.run=inventoryOpportunities;',ctx);
 return {scan(){const snapshot={characters:[{id:1,level:1}],squad:[1],inventory:{count:entries.filter(e=>e.place==='inventory').length,capacity}},actions=[],issues=[];
  ctx.run(snapshot,{},im,(kind,key,label,priority,data)=>actions.push({kind,key,priority,...data}),issues);return {snapshot,actions:actions.sort((a,b)=>b.priority-a.priority),issues};}};
}
const planningEntry=(uid,kind=1,count=1,place='inventory',protection={})=>{const e=entry(uid,count,kind,place);e.item={info:e.info,...protection};return e;};
const gemRecipe={ID:1,CraftType:0,FusionType:3,Grade:1,MinTier:0,MaxTier:0,RequireCubeLevel:0,FusionCount:9};
test('protected movable inventory can stage, but it never enters a consumption recipe',()=>{
 const p=planningEntry('trade',1,1,'inventory',{protected:true});p.info.tradable=true;
 const {actions,snapshot}=planningFixture([p],1,2).scan();
 assert.equal(actions[0].kind,'deposit');assert.equal(actions[0].uid,'trade');
 assert.equal(snapshot.inventoryFlow.protectedMaterials,1);assert.equal(snapshot.inventoryFlow.blockedTransfers,0);
 assert.ok(!actions.some(a=>['combine','forge','decompose','refine'].includes(a.kind)));
});
test('immovable inventory reports a blocked flow instead of pretending to organize it',()=>{
 const {actions,snapshot,issues}=planningFixture([planningEntry('locked',1,1,'inventory',{protected:true,blocked:true})],1,2).scan();
 assert.equal(actions.length,0);assert.equal(snapshot.inventoryFlow.blocked,true);assert.equal(snapshot.inventoryFlow.blockedTransfers,1);assert.match(issues[0],/没有可安全转仓/);
});
test('ready consumption has priority over depositing more idle items',()=>{
 const entries=[planningEntry('gems',16,9),planningEntry('trade',1,1,'inventory',{protected:true})];
 const {actions}=planningFixture(entries,2,2,[gemRecipe]).scan();assert.equal(actions[0].kind,'combine');
 const deposit=actions.find(a=>a.kind==='deposit');assert.ok(deposit);assert.ok(actions[0].priority>deposit.priority);
});
test('two full containers exchange an idle item, finish the recipe and never recall the protected item as material',()=>{
 const bag=planningEntry('bag',16,4),stored=planningEntry('stored',16,5,'storage'),trade=planningEntry('spare',1,1,'inventory',{protected:true});
 const entries=[bag,trade,stored],f=planningFixture(entries,2,1,[gemRecipe]);
 let {actions}=f.scan();assert.equal(actions[0].kind,'withdraw');assert.equal(actions[0].uid,'stored');assert.equal(actions[0].swapUid,'spare');
 stored.place='inventory';trade.place='storage';
 actions=f.scan().actions;assert.equal(actions[0].kind,'combine');assert.deepEqual(Array.from(actions[0].allowed),['bag','stored']);assert.ok(!actions.some(a=>a.swapUid||a.kind==='deposit'));
 entries.splice(0,entries.length,trade);actions=f.scan().actions;assert.ok(!actions.some(a=>a.kind==='withdraw'));
});
test('full containers without a safe exchange wait and never consume protected stock',()=>{
 const bag=planningEntry('bag',16,4),stored=planningEntry('stored',16,5,'storage'),locked=planningEntry('locked',1,1,'inventory',{protected:true,blocked:true});
 const {actions,snapshot,issues}=planningFixture([bag,locked,stored],2,1,[gemRecipe]).scan();
 assert.equal(actions.length,0);assert.equal(snapshot.inventoryFlow.blocked,true);assert.match(issues[0],/没有可安全整理/);
});


test('pressure cleanup retires idle current-tier ordinary equipment before filling storage',()=>{
 const entries=[planningEntry('idle'),planningEntry('protected',1,1,'inventory',{protected:true})];
 const {actions}=planningFixture(entries,2,2).scan();assert.equal(actions[0].kind,'decompose');assert.deepEqual(Array.from(actions[0].allowed),['idle']);
 assert.ok(!actions.some(a=>a.kind==='deposit'&&a.uid==='idle'));
});


test('full containers prioritize one pending recipe instead of deadlocking on materials for other recipes',()=>{
 const gearRecipe={ID:2,CraftType:0,FusionType:0,Grade:1,MinTier:1,MaxTier:1,RequireCubeLevel:0,FusionCount:9};
 const gear=planningEntry('gear',1,1),gems=planningEntry('gems',16,4),storedGear=planningEntry('stored-gear',1,8,'storage'),storedGems=planningEntry('stored-gems',16,5,'storage');
 const entries=[gear,gems,storedGear,storedGems],f=planningFixture(entries,2,2,[gearRecipe,gemRecipe]);
 let {actions}=f.scan();assert.equal(actions[0].kind,'withdraw');assert.equal(actions[0].uid,'stored-gear');assert.equal(actions[0].swapUid,'gems');
 storedGear.place='inventory';gems.place='storage';actions=f.scan().actions;assert.equal(actions[0].kind,'combine');assert.deepEqual(Array.from(actions[0].allowed),['gear','stored-gear']);
});

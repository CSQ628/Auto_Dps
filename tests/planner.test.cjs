const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');
const context={};vm.createContext(context);
vm.runInContext(fs.readFileSync('bridge/planner.js','utf8')+'\nglobalThis.subject={tierForLevel,materialBatch,fusionPlans,retirementPlans,popupPolicy,entranceStatus};',context);
const {tierForLevel,materialBatch,fusionPlans,popupPolicy,entranceStatus}=context.subject;
const tiers=[1,5,10,15,20,30,40,50,65,80].map((min,i)=>({tier:i+1,min}));
const entry=(uid,count,place='inventory')=>({place,info:{uid,count,tier:2,grade:1,kind:1}});
test('retirement reclaims warehouse and held obsolete gear without fullness or duplicate gates',()=>{
 const old=entry('old',1),stored=entry('warehouse',1,'storage'),upgrade=entry('upgrade',1),future=entry('future',1);
 const current={...entry('current',1),info:{...entry('current',1).info,tier:5,grade:2}};
 const high={...entry('high',1),info:{...entry('high',1).info,tier:2,grade:5}};
 assert.deepEqual(Array.from(context.subject.retirementPlans([old,stored,upgrade,future,current,high],new Set(['upgrade','future']),5),e=>e.info.uid),['old','warehouse']);
});
test('forge tier follows native level boundaries',()=>{
 for(const [level,expected]of [[1,1],[5,2],[14,3],[15,4],[29,5],[50,8],[65,9],[80,10]])assert.equal(tierForLevel(level,tiers),expected);
});

test('level 21 planning keeps the tier 3 recipe selector for tier 3..5 materials',()=>{
 const material={info:{id:510401,uid:'ore',count:1,kind:32,grade:1,tier:0}};
 const equipment={info:{tier:3,grade:4}};
 const storage={get_TabCount:()=>1,IsTabUnlocked:()=>true,get_OccupiedCount:()=>0,get_SlotCountPerTab:()=>49,get_IsFull:()=>false};
 const im={get_Storage:()=>storage,get_Cube:()=>({get_Level:()=>10}),GetEquipment:()=>({get_Has:()=>[null,null,null,null,equipment]})};
 const recipes=[{ID:50205,CraftType:1,RequireCubeLevel:10,MinTier:3,MaxTier:5,CraftPart:5,MaterialID:[510401],MaterialCount:[1]},
  {ID:50305,CraftType:1,RequireCubeLevel:20,MinTier:5,MaxTier:6,CraftPart:5,MaterialID:[510501],MaterialCount:[1]}];
 const c={call:(o,n,a=[])=>o[n](...a),list:x=>x,itemInfo:x=>x.info,isTradable:()=>false,protectedItem:()=>false,canMoveStoredItem:()=>true,
  containerEntries:()=>[{item:material,place:'inventory'}],keyHash:()=>'',fixtureCatalogue:{recipes,tiers,normalMax:160,towerMax:100,maxCharacterLevel:100}};
 equipment.get_IsLocked=()=>false;
 vm.createContext(c);vm.runInContext(fs.readFileSync('bridge/planner.js','utf8')+'\ncatalogueCache=fixtureCatalogue;equipmentPlans=()=>[];globalThis.run=inventoryOpportunities;',c);
 const actions=[];c.run({characters:[{id:400001,level:21}],squad:[400001],inventory:{count:1,capacity:46}},{},im,(kind,key,label,priority,data)=>actions.push({kind,...data}),[]);
 const forge=actions.find(x=>x.kind==='forge');assert.ok(forge);assert.equal(forge.recipe,50205);assert.equal(forge.tier,3);
 assert.deepEqual(Array.from(forge.allowed),['ore']);
});
test('material reservation uses held materials first and only takes one batch',()=>{
 const batch=materialBatch([entry('warehouse',8,'storage'),entry('held',5),entry('extra',10)],9);
 assert.deepEqual(Array.from(batch,x=>x.info.uid),['held','extra']);
 assert.equal(materialBatch([entry('insufficient',2)],9).length,0);
});
test('fusion uses the actual count, grade and unlocked recipe range',()=>{
 const recipe={CraftType:0,FusionType:0,Grade:1,MinTier:1,MaxTier:2,RequireCubeLevel:5,FusionCount:4};
 const items=[entry('one',3),entry('two',1,'storage')];
 assert.equal(fusionPlans(items,[recipe],4).length,0);
 assert.equal(fusionPlans(items,[{...recipe,Grade:2}],10).length,0);
 assert.equal(fusionPlans(items,[{...recipe,MinTier:3}],10).length,0);
 const plans=fusionPlans(items,[recipe],5);assert.equal(plans.length,1);assert.equal(plans[0].entries.length,2);
 assert.equal(fusionPlans(items,[{...recipe,FusionCount:9}],5).length,0);
});

test('confirmation and unknown dialogs block cleanup even alongside a normal panel',()=>{
 for(const modal of ['DG.UI.ConfirmPopup','DG.UI.Popup.UnknownPopup']){
  const policy=popupPolicy(['DG.UI.Popup.HeroPopup',modal]);
  assert.deepEqual(Array.from(policy.blocked),[modal]);assert.equal(policy.cleanup,null);
 }
});

test('only known ordinary panels can be cleaned up while mail and trade remain untouched',()=>{
 const policy=popupPolicy(['DG.UI.Popup.MailPopup','DG.UI.Popup.TradePopup','DG.UI.Popup.SteamInventoryPopup']);
 assert.equal(policy.cleanup,null);assert.equal(policy.blocked.length,0);
 assert.equal(popupPolicy(['DG.UI.Popup.HeroPopup']).cleanup,'DG.UI.Popup.HeroPopup');
});

test('offline reward display has a dedicated route and never enters generic cleanup',()=>{
 const policy=popupPolicy(['DG.UI.Popup.OfflineRewardPopup']);assert.equal(policy.offline,true);assert.equal(policy.cleanup,null);
 const mixed=popupPolicy(['DG.UI.Popup.OfflineRewardPopup','DG.UI.ConfirmPopup']);assert.equal(mixed.offline,false);
});

test('entry checks the exact native consumption target instead of another safe stack',()=>{
 const protectedTarget={protected:true},safeTarget={protected:false};let target=protectedTarget,ticket=690100;
 context.call=(_,name)=>name==='GetRequireItemID'?ticket:target;
 context.isTradable=p=>p.protected;context.protectedItem=(_,p)=>p.protected;
 context.itemInfo=p=>({id:0,tradable:p.protected});context.read=()=>0;
 assert.equal(entranceStatus({}, {},0,20).safe,false);
 target=null;assert.equal(entranceStatus({}, {},0,20).reason,'ticket_missing');
 target=safeTarget;assert.equal(entranceStatus({}, {},0,20).safe,true);
 ticket=0;target=protectedTarget;assert.equal(entranceStatus({}, {},0,19).safe,true);
});


test('pressure cleanup is configurable and keeps reserved, future-tier and rare gear',()=>{
 const plain=entry('plain',1),stored=entry('stored',1,'storage'),reserved=entry('reserved',1),future=entry('future',1),rare=entry('rare',1);
 future.info.tier=3;rare.info.grade=3;
 const options=context.subject.retirementPlans;const all=[plain,stored,reserved,future,rare];
 assert.equal(options(all,new Set(['reserved']),2,undefined,false).length,0);
 assert.deepEqual(Array.from(options(all,new Set(['reserved']),2,undefined,true),e=>e.info.uid),['plain','stored']);
 assert.equal(options(all,new Set(['reserved']),2,{recycle_normal_tier_gap:1,recycle_rare_tier_gap:2,recycle_pressure_cleanup:false},true).length,0);
});

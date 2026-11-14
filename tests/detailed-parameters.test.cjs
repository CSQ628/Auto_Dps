const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');
const c={call:(o,n,a=[])=>o[n](...a),list:x=>x,protectedEquipped:()=>false};vm.createContext(c);vm.runInContext(fs.readFileSync('bridge/planner.js','utf8'),c);
const entry=(uid,kind,count=9,place='inventory',grade=1,tier=kind===16?0:1)=>{
 const e={place,info:{uid,id:1000+kind,count,kind,grade,tier}};e.item={info:e.info};return e;
};
const recipe=(category,id=category+1)=>({ID:id,CraftType:0,FusionType:[0,1,3,4][category],Grade:1,MinTier:category===2?0:1,MaxTier:2,RequireCubeLevel:0,FusionCount:9});
function workshop(entries,recipes,options={},equipped=[]){
 const storage={get_TabCount:()=>1,IsTabUnlocked:()=>true,get_OccupiedCount:()=>entries.filter(e=>e.place==='storage').length,get_SlotCountPerTab:()=>49,get_IsFull:()=>false};
 const im={get_Storage:()=>storage,get_Cube:()=>({get_Level:()=>20}),GetEquipment:()=>({get_Has:()=>equipped})};
 const ctx={call:(o,n,args=[])=>o[n](...args),list:x=>x,read:(o,n)=>o[n],itemInfo:p=>p.info,isTradable:()=>false,
  protectedItem:()=>false,canMoveStoredItem:()=>true,workshopCapacity:()=>9,canRecycleItem:(_,p)=>[1,2,4].includes(p.info.kind),protectedEquipped:()=>true,
  containerEntries:()=>entries,keyHash:x=>x,hasAttachmentSpace:()=>true,equipmentRevision:()=> 'gear-revision',fixtureCatalogue:{recipes,tiers:[{tier:1,min:1}],normalMax:160,towerMax:20,maxCharacterLevel:101}};
 vm.createContext(ctx);vm.runInContext(fs.readFileSync('bridge/planner.js','utf8')+'\ncatalogueCache=fixtureCatalogue;equipmentPlans=()=>[];',ctx);
 const s={characters:[{id:1,level:10}],squad:[1],record:{maxCleared:9},inventory:{count:entries.filter(e=>e.place==='inventory').length,capacity:50}},actions=[];
 ctx.inventoryOpportunities(s,{},im,(kind,key,label,priority,data)=>actions.push({kind,key,label,priority,...data}),[],ctx.bridgeStrategy(options));
 return {s,actions};
}
test('every fusion category can be disabled before any reservation or warehouse recall',()=>{
 const names=['equipment','accessory','refinement','craft'],kinds=[1,4,16,8];
 for(let off=0;off<4;off++){
  const inputs=kinds.map((k,i)=>entry('input-'+i,k)),r=workshop(inputs,[0,1,2,3].map(i=>recipe(i)),{['combine_'+names[off]]:false,modules:{refine:false,decompose:false}});
  assert.deepEqual(r.actions.filter(a=>a.kind==='combine').map(a=>a.category).sort(),[0,1,2,3].filter(i=>i!==off));
  assert.equal(r.s.inventoryFlow.recipeReserved,3);
  const stored=workshop([entry('stored',kinds[off],9,'storage')],[recipe(off)],{['combine_'+names[off]]:false,modules:{refine:false,decompose:false}});
  assert.equal(stored.s.inventoryFlow.recipeReserved,0);assert.equal(stored.actions.length,0);
 }
});
test('fusion quality and tier bounds apply to actual ingredients and reject inverted ranges',()=>{
 for(const category of [0,1,2,3]){
  const name=['equipment','accessory','refinement','craft'][category],kind=[1,4,16,8][category],p='combine_'+name;
  const e=entry('material',kind),r=recipe(category),opts=c.bridgeStrategy({[p+'_min_grade']:2});
  assert.equal(c.fusionPlans([e],[r],20,[],opts).length,0);
  assert.equal(c.fusionPlans([e],[r],20,[],c.bridgeStrategy({[p+'_min_grade']:3,[p+'_max_grade']:2})).length,0);
  assert.equal(c.fusionPlans([e],[r],20,[],c.bridgeStrategy({[p+'_min_tier']:3})).length,0);
 }
 const r=recipe(0),mixed=[entry('low',1,4,'inventory',1,1),entry('high',2,5,'inventory',1,2)];
 assert.equal(c.fusionPlans(mixed,[r],20).length,1);
 assert.equal(c.fusionPlans(mixed,[r],20,[],c.bridgeStrategy({combine_equipment_max_tier:1})).length,0);
});
test('category priorities change ordering only when explicitly different',()=>{
 const entries=[entry('equipment',1),entry('accessory',4)],recipes=[recipe(0),recipe(1)];
 assert.deepEqual(Array.from(c.fusionPlans(entries,recipes,20),p=>p.category),[0,1]);
 assert.deepEqual(Array.from(c.fusionPlans(entries,recipes,20,[],c.bridgeStrategy({combine_equipment_priority:2})),p=>p.category),[1,0]);
});
test('disabled material synthesis immediately releases the batch to authorized equipment refinement',()=>{
 const gear={get_Uid:()=> 'gear',get_IsLocked:()=>false};
 const enabled=workshop([entry('material',16)],[recipe(2)],{},[gear]);
 assert.equal(enabled.s.combining.refinementMaterials.reservedForSynthesis,9);assert.equal(enabled.s.refining.planned,0);
 const disabled=workshop([entry('material',16)],[recipe(2)],{combine_refinement:false},[gear]);
 assert.equal(disabled.s.combining.refinementMaterials.status,'disabled');assert.equal(disabled.s.combining.refinementMaterials.reservedForSynthesis,0);
 assert.equal(disabled.actions.filter(a=>a.kind==='refine').length,1);
 const filtered=workshop([entry('material',16)],[recipe(2)],{combine_refinement_min_grade:2},[gear]);assert.equal(filtered.s.refining.planned,1);
});
test('each warehouse material purpose can stop recalls without reserving inaccessible items',()=>{
 for(const options of [{storage_withdraw:false},{storage_withdraw_combine:false},{combine_use_storage:false},{modules:{storage:false}}]){
  const r=workshop([entry('stored',16,9,'storage')],[recipe(2)],{...options,modules:{refine:false,...options.modules}});
  assert.equal(r.actions.filter(a=>a.kind==='withdraw').length,0);assert.equal(r.s.inventoryFlow.recipeReserved,0);
 }
 const r=workshop([entry('stored',16,9,'storage')],[recipe(2)],{modules:{refine:false}});
 assert.equal(r.actions[0].kind,'withdraw');assert.equal(r.actions[0].purpose,'combine');
});
test('forge part filters and demand thresholds remove the recipe and all retention',()=>{
 const im={GetEquipment:()=>({get_Has:()=>[null]})},r={ID:10,CraftType:1,CraftPart:1,MinTier:1,MaxTier:2,RequireCubeLevel:0,MaterialID:[1001],MaterialCount:[1]};
 const args=[im,[{id:1,level:10}],[r],20,1,[entry('input',1)],[]];
 assert.ok(c.forgePlanning(...args,c.bridgeStrategy()));
 assert.equal(c.forgePlanning(...args,c.bridgeStrategy({forge_part_main_weapon:false})),null);
 assert.equal(c.forgePlanning(...args,c.bridgeStrategy({forge_min_need:101})),null);
});
test('refinement quality, equipment part and native tier remain independent',()=>{
 const gear={get_Uid:()=> 'gear',get_IsLocked:()=>false,info:{tier:3}},im={GetEquipment:()=>({get_Has:()=>[gear]})};
 const q={call:(o,n,a=[])=>o[n](...a),list:x=>x,itemInfo:p=>p.info,isTradable:()=>false,hasAttachmentSpace:()=>true,equipmentRevision:()=> 'revision'};
 vm.createContext(q);vm.runInContext(fs.readFileSync('bridge/planner.js','utf8'),q);
 const rows=[entry('low',16,2,'inventory',1),entry('high',16,2,'inventory',3)];
 const run=options=>q.refinementPlanning(im,[{id:1}],rows,q.bridgeStrategy(options)).plans;
 assert.equal(run({})[0].material.info.uid,'high');assert.equal(run({refine_material_order:'lowest'})[0].material.info.uid,'low');
 assert.equal(run({refine_min_grade:4}).length,0);assert.equal(run({refine_max_tier:2}).length,0);assert.equal(run({refine_part_main_weapon:false}).length,0);
});
const rune=(id,header,extra={})=>({id,header,level:0,max:5,requires:[],values:[1,2,3,4,5],goods:[201],prices:[100],canLearn:true,...extra});
test('disabled rune classes block unlearned prerequisites without starving independent paths',()=>{
 const rows=[rune(1,'OfflineExpGain'),rune(2,'KillExpGain',{requires:[1],canLearn:false}),rune(3,'BaseAttackPoint')];
 const options=c.bridgeStrategy({rune_offline:false}),plans=c.planRuneInvestment(rows,{soul:10000,premium:100,controls:options});
 assert.deepEqual(Array.from(plans,p=>p.id),[3]);
 rows[0].level=1;rows[1].canLearn=true;
 assert.ok(c.planRuneInvestment(rows,{soul:10000,controls:options}).some(p=>p.id===2));
});
test('rune cost and node limits still permit lower-cost independent investments',()=>{
 const rows=[rune(1,'KillExpGain',{prices:[1000]}),rune(2,'BaseAttackPoint',{prices:[50]}),rune(3,'SkillHaste',{level:2})];
 assert.deepEqual(Array.from(c.planRuneInvestment(rows,{soul:10000,controls:c.bridgeStrategy({rune_soul_cost_limit:100,rune_max_level:2})}),p=>p.id),[2]);
 assert.equal(c.planRuneInvestment(rows,{soul:10000,controls:c.bridgeStrategy({rune_learn:false,rune_upgrade:false})}).length,0);
});
test('partial skill controls never refund a category that cannot refill its point plan',()=>{
 const a=[{uid:'core',type:'BrandBurst',learned:3,max:10,unlock:1,canLearn:true,canRefund:true,increments:[1]}],p=[{uid:'passive',index:0,ability:'S_Skill_Rate',learned:2,max:10,unlock:1,canLearn:true,canRefund:true,requires:[],requireLevels:[],factor:1,increment:1}],build={desired:['core']};
 for(const options of [{active_upgrade:false},{active_learn:false}]){
  const r=c.planSkillReallocation(a,p,build,30,2,{arranged:true,positionKnown:true},c.bridgeStrategy(options));
  assert.equal(r.repair.controls.active,false);assert.notEqual(r.repair.refund?.kind,'active');
 }
 const r=c.planSkillReallocation(a,p,build,30,2,{arranged:true,positionKnown:true},c.bridgeStrategy({passive_learn:false,passive_upgrade:false}));assert.equal(r.repair.controls.passive,false);
});
test('selective panel retention waits only for conflicting actions',()=>{
 const options=c.bridgeStrategy({cleanup_storage:false});
 const r=c.popupPolicy(['DG.UI.Popup.StoragePopup','DG.UI.Popup.HeroPopup'],false,false,options);
 assert.deepEqual(Array.from(r.manual),['DG.UI.Popup.StoragePopup']);assert.equal(r.cleanup,'DG.UI.Popup.HeroPopup');
 assert.equal(c.panelActionBlocked('passive',r.manual),false);assert.equal(c.panelActionBlocked('withdraw',r.manual),true);
});
test('main-story limits cannot be bypassed by free recovery or final dispatch',()=>{
 for(const [action,options] of [[{kind:'progress',mode:'boss',level:60},{progress_boss_tickets:false}], [{kind:'progress',mode:'push',level:61},{progress_max_stage:60}], [{kind:'tower',level:6,ticket:0},{tower_max_level:5}], [{kind:'progress',mode:'farm'},{progress_farm:false}]])assert.equal(c.detailedActionAllowed(action,c.bridgeStrategy(options)),false);
 assert.equal(c.detailedActionAllowed({kind:'progress',mode:'guard'},c.bridgeStrategy({progress_push:false,progress_farm:false})),true);
});

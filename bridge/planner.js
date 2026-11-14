// Read-only observation of the game's applied server results. No network calls or game state writes.
let mailClaimJournal=null;
function mailClaimObservation(){
 if(!mailClaimJournal){
  const journal={available:false,observer:Date.now().toString(36)+':'+Math.random().toString(36).slice(2),sequence:0,receipts:[]};
  mailClaimJournal=journal;
  try{
   journal.hook=Interceptor.attach(method(klass('DG.UI.Popup.MailPopup'),'ApplyClaimResults',1).readPointer(),{
    onEnter(args){
     this.receipt=null;
     try{
      const account=stat('DG.Save.InGame.SaveEnvironment','get_Directory').replaceAll('\\','/').split('/').pop();
      const results=list(args[1]).filter(p=>p&&!p.isNull()).map(p=>({id:read(p,'mailId'),status:read(p,'status')}));
      this.receipt={account,results};
     }catch(e){journal.readError=true;}
    },
    onLeave(){
     if(!this.receipt)return;
     journal.receipts.push({...this.receipt,at:Date.now()/1000,sequence:++journal.sequence});
     journal.receipts=journal.receipts.slice(-32);
    }
   });
   journal.available=true;
  }catch(e){journal.readError=true;}
 }
 const {available,observer,sequence,receipts,readError}=mailClaimJournal;
 return {available,observer,sequence,receipts,readError:!!readError};
}
function bridgeStrategy(input={}){
 input=input&&typeof input==='object'?input:{};
 const out={},numbers={farm_level_offset:[0,0,20],farm_candidate_count:[10,1,10],inventory_pressure_percent:[80,40,100],storage_pressure_percent:[80,40,100],recycle_pressure_max_grade:[4,1,4],sort_cooldown_seconds:[30,5,300],recycle_batch:[12,1,12],forge_priority_main_weapon:[1,1,7],forge_priority_accessory:[1,1,7],forge_priority_sub_weapon:[1,1,7],forge_priority_helmet:[1,1,7],forge_priority_armor:[1,1,7],forge_priority_gloves:[1,1,7],forge_priority_boots:[1,1,7],recycle_normal_tier_gap:[1,1,10],recycle_rare_tier_gap:[2,1,10],skill_point_reserve:[0,0,100],farm_retry_finish_seconds:[180,30,600],equipment_min_gain_percent:[0,0,100]};
 for(const [key,[fallback,min,max]] of Object.entries(numbers))out[key]=typeof input[key]==='number'&&Number.isFinite(input[key])&&input[key]>=min&&input[key]<=max&&(key==='equipment_min_gain_percent'||Number.isInteger(input[key]))?input[key]:fallback;
 for(const key of ['recommended_actives','allow_active_refund','allow_passive_refund','recycle_pressure_cleanup','auto_sort_items'])out[key]=typeof input[key]==='boolean'?input[key]:true;
 out.preserve_open_panels=input.preserve_open_panels===true;
 out.pause_on_manual_panels=input.pause_on_manual_panels===true;
 out.recycle_socketed_equipment=input.recycle_socketed_equipment===true;
 out.rune_priority=['growth','balanced','combat'].includes(input.rune_priority)?input.rune_priority:'growth';
  out.pet_mode=['auto','growth','combat','keep'].includes(input.pet_mode)?input.pet_mode:'auto';
  out.budget=input.budget&&typeof input.budget==='object'?input.budget:{};
  out.modules=Object.fromEntries(['active','passive','combine','decompose','forge','refine','storage'].map(key=>[key,input.modules?.[key]!==false]));return out;
}
function isOfflineRuneHeader(header){return typeof header==='string'&&header.startsWith('Offline');}
function runeProgress(rows){
 const result={learned:0,total:0,maxed:0,onlineLearned:0,onlineTotal:0,offlineLearned:0,offlineTotal:0,offlineNodes:0,offlineDeferred:0,progressKnown:true};
 if(!Array.isArray(rows))rows=null;
 if(!rows||!rows.length||rows.some(r=>!r||typeof r.header!=='string'||!r.header.length||!Number.isSafeInteger(r.level)||!Number.isSafeInteger(r.max)||r.level<0||r.max<=0||r.level>r.max)){
  return {...result,learned:null,total:null,onlineLearned:null,onlineTotal:null,offlineLearned:null,offlineTotal:null,progressKnown:false};
 }
 for(const r of rows){
  result.learned+=r.level;result.total+=r.max;if(r.level===r.max)result.maxed++;
  if(isOfflineRuneHeader(r.header)){
   result.offlineNodes++;result.offlineLearned+=r.level;result.offlineTotal+=r.max;if(r.level<r.max)result.offlineDeferred++;
  }else{result.onlineLearned+=r.level;result.onlineTotal+=r.max;}
 }
 return result;
}
function runePriorityBonus(header,mode){
 const combat=['BaseAttackPoint','NormalAttack','HealthPoint','Defense','AttackSpeed','Skill','DamageReduction','SkillHaste'].includes(header);
 const growth=['KillExpGain','KillGoods','BoxAutoOpenNormal','BoxAutoOpenStage'].includes(header);
 return mode==='combat'?(combat?15:growth?-10:0):mode==='balanced'?(combat?6:growth?-3:0):0;
}
let catalogueCache=null,catalogueSourcesRetryAt=0;
function catalogue(dm){
 const now=Date.now();
 if(catalogueCache){
  if(catalogueCache.materialSources?.known===false&&now>=catalogueSourcesRetryAt){
   catalogueSourcesRetryAt=now+60000;
   catalogueCache.materialSources=readCraftSources(dm,catalogueCache.recipes);
  }
  return catalogueCache;
 }
 const recipes=recipeRows(dm).map(r=>Object.fromEntries(['ID','CraftType','FusionType','CraftPart','Grade','FusionCount','MinTier','MaxTier','RequireCubeLevel','RandomBagID'].map(n=>[n,read(r,n)]).concat(['MaterialID','MaterialCount'].map(n=>[n,list(read(r,n))]))));
 const stages=list(call(read(dm,'_stageConfigTable'),'get_Datas')).map(p=>read(p,'Level'));
 const tower=list(call(read(dm,'_contentStageTable'),'get_Datas')).filter(p=>read(p,'Category')===1).map(p=>read(p,'Level'));
 const tiers=Array.from({length:10},(_,i)=>({tier:i+1,min:stat('DG.UI.Popup.CubeBasePopupView','TierMinLevel',[i+1]),max:stat('DG.UI.Popup.CubeBasePopupView','TierMaxLevel',[i+1])}));
 catalogueSourcesRetryAt=now+60000;
 catalogueCache={recipes,tiers,materialSources:readCraftSources(dm,recipes),normalMax:Math.max(...stages),towerMax:Math.max(0,...tower),maxCharacterLevel:call(dm,'GetCharacterExpMaxLevel')};
 return catalogueCache;
}
function tierForLevel(level,tiers){return tiers.filter(t=>t.min<=level).reduce((best,t)=>Math.max(best,t.tier),1);}
function materialBatch(entries,count){
 const result=[];let remaining=count;
 for(const e of [...entries].sort((a,b)=>(a.place==='storage')-(b.place==='storage')||a.info.tier-b.info.tier)){
  if(remaining<=0)break;result.push(e);remaining-=e.info.count;
 }return remaining<=0?result:[];
}
function materialQuantities(entries,count){
 const quantities={};let remaining=count;
 for(const e of entries){const n=Math.min(e.info.count,remaining);if(n>0){quantities[e.info.uid]=n;remaining-=n;}}
 return quantities;
}
function fusionPlans(entries,recipes,cubeLevel,diagnostics=[]){
 const used=new Set(),plans=[];
 // Equipment/accessories accept an inclusive native recipe band; materials use exact tiers.
 for(const recipe of recipes.filter(r=>r.CraftType===0&&r.RequireCubeLevel<=cubeLevel&&r.FusionCount>0).sort((a,b)=>b.MinTier-a.MinTier||a.ID-b.ID)){
  const category=({0:0,1:1,3:2,4:3})[recipe.FusionType];if(category===undefined)continue;
  const rows=entries.filter(e=>!used.has(e.info.uid)&&({1:0,2:0,4:1,16:2,8:3})[e.info.kind]===category&&e.info.grade===recipe.Grade&&
    (category<=1?e.info.tier>=recipe.MinTier&&e.info.tier<=recipe.MaxTier:e.info.tier===recipe.MinTier));
  const available=rows.reduce((n,e)=>n+e.info.count,0);if(!available)continue;
  const batch=materialBatch(rows,recipe.FusionCount);
  diagnostics.push({category,minTier:recipe.MinTier,maxTier:category<=1?recipe.MaxTier:recipe.MinTier,grade:recipe.Grade,available,required:recipe.FusionCount,ready:batch.length>0});
  if(!batch.length)continue;
  for(const e of batch)used.add(e.info.uid);
  plans.push({category,tier:batch[0].info.tier,grade:recipe.Grade,entries:batch,recipe,materialMinTier:recipe.MinTier,materialMaxTier:category<=1?recipe.MaxTier:recipe.MinTier});
 }
 return plans;
}
function fusionTasks(groups,free){
 return groups.map(group=>{
  const current=group.entries.filter(e=>e.place==='inventory');
  const ready=current.reduce((n,e)=>n+e.info.count,0)>=group.recipe.FusionCount;
  return {group,current,ready,withdraw:!ready&&free>0?group.entries.find(e=>e.place==='storage'):null};
 });
}
function stagingDeposit(held,needed,materials,retiring,full,recalls,equipping=new Set(),readyMaterials=materials){
 const rank=rows=>[...rows].sort((a,b)=>Number(a.consumable===false)-Number(b.consumable===false)||((b.info.kind>=8?10:0)+b.info.grade)-((a.info.kind>=8?10:0)+a.info.grade)||String(a.info.uid).localeCompare(String(b.info.uid)))[0];
 const ordinary=rank(held.filter(e=>!needed.has(e.info.uid)&&!materials.has(e.info.uid)&&!retiring.has(e.info.uid)));
 if(ordinary||!full)return ordinary||null;
 // Retention forbids consumption, not moving an otherwise safe item into storage.
 // Keep the first pending recipe's held ingredients in place to avoid a withdraw/deposit loop.
 const target=[...recalls].sort((a,b)=>b.priority-a.priority)[0];
 const targetIds=new Set((target?.entries||[]).map(e=>e.info.uid));
 return rank(held.filter(e=>!targetIds.has(e.info.uid)&&!equipping.has(e.info.uid)&&!readyMaterials.has(e.info.uid)&&!retiring.has(e.info.uid)))||null;
}
function retirementPlans(entries,reserved,tier,options=bridgeStrategy(),underPressure=false){
 // Equipment useful to any managed character (including the next level) is excluded upstream.
 return entries.filter(e=>!reserved.has(e.info.uid)&&[1,2,4].includes(e.info.kind)&&
  ((e.info.grade<=2&&e.info.tier<=tier-options.recycle_normal_tier_gap)||(e.info.grade<=4&&e.info.tier<=tier-options.recycle_rare_tier_gap)||
    (underPressure&&options.recycle_pressure_cleanup&&e.info.grade<=(options.recycle_pressure_max_grade??4)&&e.info.tier<=tier)))
  .sort((a,b)=>a.info.tier-b.info.tier||a.info.grade-b.info.grade||(a.place==='storage')-(b.place==='storage'));
}
function forgeNeed(im,characters,part,tier){
 let best=0;
 for(const c of characters){
  const set=list(call(call(im,'GetEquipment',[c.id]),'get_Has'));
  const indexes=part===7?[6,7,8,9]:[part-1];
  for(const index of indexes){
   const p=set[index];if(protectedEquipped(im,p))continue;
   if(!p)best=Math.max(best,100);else{
    const info=itemInfo(p);if(info.tier<tier)best=Math.max(best,20+(tier-info.tier)*5+6-info.grade);
    else if(info.tier===tier&&info.grade<4)best=Math.max(best,4-info.grade);
   }
  }
 }return best;
}
// Native tables are read once. The pure source graph below never rolls rewards or moves items.
function readCraftSources(dm,recipes){
 try{
  const vals=(p,fields)=>Object.fromEntries(fields.map(n=>[n,read(p,n)]));
  const items=list(call(read(dm,'_itemConfigTable'),'get_Datas')).map(p=>vals(p,['ID','Tier','Grade','ItemType','RandomBagID']));
  const bags=list(call(read(dm,'_itemRandombagTable'),'get_Datas')).map(p=>({...vals(p,['ID','Weight']),reward:vals(read(p,'Reward'),['ID','Count'])}));
  const craftRewards=list(call(read(dm,'_craftRandombagTable'),'get_Datas')).map(p=>({bag:read(p,'ID'),weight:read(p,'Weight'),id:read(read(p,'Reward'),'ID'),count:read(read(p,'Reward'),'Count')}));
  const waveCounts=new Map();
  for(const p of list(call(read(dm,'_stageTable'),'get_Datas'))){
   const level=read(p,'Level'),counts=list(read(p,'SpawnCount')),row=waveCounts.get(level)||[0,0,0];
   counts.slice(0,3).forEach((n,i)=>row[i]+=Math.max(0,n));waveCounts.set(level,row);
  }
  const stages=list(call(read(dm,'_stageConfigTable'),'get_Datas')).map(p=>{
   const level=read(p,'Level'),counts=waveCounts.get(level)||[];
   return {level,free:read(p,'RequireItemID')<=0,normal:counts[0]||0,elite:counts[1]||0,boss:counts[2]||0};
  });
  const drops=list(call(read(dm,'_stageDropConfig'),'get_Datas')).map(p=>({...vals(p,['Level','NormalBoxRate','NormalWeaponRate','NormalBoxID','BossBoxRate','BossWeaponRate','BossBoxID']),NormalWeaponBoxID:list(read(p,'NormalWeaponBoxID')),BossWeaponBoxID:list(read(p,'BossWeaponBoxID'))}));
  return buildCraftSources({items,bags,craftRewards,stages,drops,recipes});
 }catch(error){return {known:false,materials:{}};}
}
function buildCraftSources({items,bags,craftRewards,stages,drops,recipes}){
 const wanted=new Set(recipes.filter(r=>r.CraftType===1).flatMap(r=>r.MaterialID));
 const materials=Object.fromEntries([...wanted].map(id=>[id,{firstStage:null,firstFreeStage:null,fusion:[]}]));
 const boxBags=new Map(items.filter(i=>i.RandomBagID>0).map(i=>[i.ID,i.RandomBagID])),bagItems=new Map();
 for(const b of bags)if(b.Weight>0&&b.reward.Count>0&&wanted.has(b.reward.ID)){
  if(!bagItems.has(b.ID))bagItems.set(b.ID,new Set());bagItems.get(b.ID).add(b.reward.ID);
 }
 const byLevel=new Map(stages.map(s=>[s.level,s]));
 for(const drop of drops){
  const stage=byLevel.get(drop.Level);if(!stage)continue;
  const boxes=[];
  for(const [prefix,count] of [['Normal',stage.normal],['Boss',stage.elite+stage.boss]]){
   if(count<=0||!(drop[prefix+'BoxRate']>0))continue;
   if(drop[prefix+'WeaponRate']<100)boxes.push(drop[prefix+'BoxID']);
   if(drop[prefix+'WeaponRate']>0)boxes.push(...(drop[prefix+'WeaponBoxID']||[]));
  }
  for(const box of boxes)for(const id of bagItems.get(boxBags.get(box))||[]){
   const row=materials[id];row.firstStage=Math.min(row.firstStage??Infinity,stage.level);
   if(stage.free)row.firstFreeStage=Math.min(row.firstFreeStage??Infinity,stage.level);
  }
 }
 const rewards=new Map();
 for(const r of craftRewards)if(r.weight>0){if(!rewards.has(r.bag))rewards.set(r.bag,[]);rewards.get(r.bag).push(r);}
 for(const recipe of recipes.filter(r=>r.CraftType===0&&r.FusionType===4&&r.FusionCount>0)){
  const inputs=items.filter(i=>i.ItemType===4&&i.Tier===recipe.MinTier&&i.Grade===recipe.Grade).map(i=>i.ID);
  const rows=rewards.get(recipe.RandomBagID)||[],total=rows.reduce((n,r)=>n+r.weight,0);
  if(!inputs.length||total<=0)continue;
  for(const r of rows)if(wanted.has(r.id)&&r.count>0)materials[r.id].fusion.push({recipe:recipe.ID,cubeLevel:recipe.RequireCubeLevel,inputs,count:recipe.FusionCount,probability:r.weight/total});
 }
 return {known:true,materials};
}
function reachableCraftMaterials(sources,cubeLevel,frontier){
 const reachable=new Map();
 if(!sources?.known)return reachable;
 for(const [id,row] of Object.entries(sources.materials))if(row.firstFreeStage>0&&row.firstFreeStage<=frontier)reachable.set(Number(id),0);
 // Only farmable inputs seed repeatable supply. A finite stack is not infinite material.
 for(let pass=0;pass<Object.keys(sources.materials).length;pass++){
  let changed=false;
  for(const [id,row] of Object.entries(sources.materials))for(const r of row.fusion){
   if(r.cubeLevel>cubeLevel)continue;
   const steps=r.inputs.filter(i=>reachable.has(i)).map(i=>reachable.get(i)+1);
   if(!steps.length)continue;const step=Math.min(...steps),key=Number(id);
   if(!reachable.has(key)||reachable.get(key)>step){reachable.set(key,step);changed=true;}
  }
  if(!changed)break;
 }
 return reachable;
}
function materialSupply(id,stock,cubeLevel,frontier,sources,reachable,combine=true){
 if(!sources?.known||!sources.materials?.[id])return {source:'unknown',rank:3,firstStage:null,firstFreeStage:null,fusion:[]};
 const row=sources.materials[id],fusion=combine?row.fusion.filter(r=>r.cubeLevel<=cubeLevel):[];
 const ready=fusion.some(r=>r.inputs.reduce((n,id)=>n+(stock.get(id)||0),0)>=r.count);
 const collect=fusion.some(r=>r.inputs.some(id=>reachable.has(id)));
 const source=row.firstFreeStage>0&&row.firstFreeStage<=frontier?'drop':ready?'fusion_ready':collect?'fusion':'future';
 return {...row,fusion,source,fusionSteps:combine?(reachable.get(id)??null):null,rank:({drop:0,fusion_ready:1,fusion:2,future:4})[source]};
}
function forgePlanning(im,characters,recipes,cubeLevel,tier,entries,all,options=bridgeStrategy(),context={}){
 const priorityKeys={1:'main_weapon',2:'sub_weapon',3:'helmet',4:'armor',5:'gloves',6:'boots',7:'accessory'};
 const stock=new Map(),held=new Map(),total=new Map(),combine=options.modules?.combine!==false;
 const reachable=combine?reachableCraftMaterials(context.sources,cubeLevel,context.frontier):new Map();
 for(const e of entries){stock.set(e.info.id,(stock.get(e.info.id)||0)+e.info.count);if(e.place==='inventory')held.set(e.info.id,(held.get(e.info.id)||0)+e.info.count);}
 for(const e of all)total.set(e.info.id,(total.get(e.info.id)||0)+e.info.count);
 const plans=recipes.filter(r=>r.CraftType===1&&r.RequireCubeLevel<=cubeLevel&&r.MinTier<=tier&&r.MaterialID.length&&r.MaterialID.every((id,i)=>id>0&&r.MaterialCount[i]>0))
  .map(r=>({...r,need:forgeNeed(im,characters,r.CraftPart,Math.min(tier,r.MaxTier)),craftPriority:options['forge_priority_'+priorityKeys[r.CraftPart]]??7,
   materials:r.MaterialID.map((id,i)=>({id,required:r.MaterialCount[i],available:stock.get(id)||0,inventory:held.get(id)||0,protected:(total.get(id)||0)-(stock.get(id)||0),
    ...materialSupply(id,stock,cubeLevel,context.frontier,context.sources,reachable,combine)}))}))
  .filter(r=>r.need>0).map(r=>{
   const missing=r.materials.filter(m=>m.available<m.required),sourceRank=missing.length?Math.max(...missing.map(m=>m.rank)):-1;
   return {...r,complete:!missing.length,sourceRank,source:missing.length?missing.find(m=>m.rank===sourceRank).source:'inventory'};
  }).sort((a,b)=>Number(b.complete)-Number(a.complete)||a.sourceRank-b.sourceRank||a.craftPriority-b.craftPriority||b.MinTier-a.MinTier||b.need-a.need||a.ID-b.ID);
 const selected=plans[0];if(!selected)return null;
 // Keep one batch for each useful current part, using max shared demand, not seven copies.
 // A complete higher recipe can still run immediately; it must not erase lower upgrade paths.
 const retained=new Map(),parts=new Set();
 function retain(plan){for(const m of plan.materials){const old=retained.get(m.id);if(!old||old.required<m.required)retained.set(m.id,m);}}
 retain(selected);
 for(const p of plans)if(p.sourceRank<=0&&!parts.has(p.CraftPart)){parts.add(p.CraftPart);retain(p);}
 return {...selected,retention:[...retained.values()],sourceKnown:context.sources?.known===true,
  alternatives:plans.length-1,retainedParts:parts.size};
}
function managedEquipmentCharacters(characters,squad){const active=new Set((squad||[]).filter(id=>id>0).slice(0,3));return characters.filter(c=>active.has(c.id));}
function inventoryOpportunities(s,dm,im,add,issues,options=bridgeStrategy()){
 const managed=managedEquipmentCharacters(s.characters,s.squad);
 const enabled={combine:true,decompose:true,forge:true,refine:true,storage:true,...options.modules};
 const all=containerEntries(im).map(e=>({...e,info:itemInfo(e.item),consumable:!protectedItem(im,e.item)}));
 const safe=all.filter(e=>e.consumable),movable=all.filter(e=>canMoveStoredItem(im,e.item)),held=safe.filter(e=>e.place==='inventory'),catalog=catalogue(dm);
 const stamp=keyHash(all.map(e=>e.info.uid+':'+e.info.count+':'+e.place).join('|'));
 const storage=call(im,'get_Storage'),perTab=call(storage,'get_SlotCountPerTab'),tabs=Array.from({length:call(storage,'get_TabCount')},(_,i)=>({id:i,open:call(storage,'IsTabUnlocked',[i]),count:all.filter(e=>e.place==='storage'&&Math.floor(e.index/perTab)===i).length,capacity:perTab}));
 const tradable=all.filter(e=>isTradable(e.item));
 s.storage={count:call(storage,'get_OccupiedCount'),capacity:tabs.filter(t=>t.open).length*perTab,tabs,safeItems:safe.filter(e=>e.place==='storage').length,tradable:tradable.filter(e=>e.place==='storage').length};
 s.storage.pressure=s.storage.capacity>0&&s.storage.count>=s.storage.capacity*options.storage_pressure_percent/100;
 const protectedGear=s.characters.flatMap(c=>list(call(call(im,'GetEquipment',[c.id]),'get_Has')).filter(p=>p&&isTradable(p)));
 s.protection={tradable:tradable.length+protectedGear.length,rule:'equip_and_store_preserve_trade_attributes'};
 s.catalogue={normalMax:catalog.normalMax,towerMax:catalog.towerMax,characterMax:catalog.maxCharacterLevel,recipes:catalog.recipes.length,fusionRecipes:catalog.recipes.filter(r=>r.CraftType===0).length,forgeRecipes:catalog.recipes.filter(r=>r.CraftType===1).length};
 const needed=new Set();s.equipmentPlanning=[];
 const equipment=equipmentPlans(im,managed,s.squad,s.equipmentPlanning,needed,options.equipment_min_gain_percent);
 for(const c of s.characters)if(!managed.some(a=>a.id===c.id))s.equipmentPlanning.push({id:c.id,status:'not_arranged',planned:0,slotDetails:[]});
 for(const plan of equipment){needed.add(plan.uid);add('equipment','equip:'+plan.id+':'+plan.uid+':'+plan.slot,'为角色 '+plan.id+' 装备'+(plan.source==='storage'?'仓库':'背包')+'优选装备',99,plan);}
 const cube=call(im,'get_Cube'),cubeLevel=call(cube,'get_Level'),nativeCapacity=workshopCapacity('decompose');
 // Recycle by actual native slots, counting stack units as separate reservations.
 const recycleLimit=Number.isSafeInteger(nativeCapacity)&&nativeCapacity>0?Math.min(options.recycle_batch,nativeCapacity):0;
 const candidates=safe.filter(e=>!needed.has(e.info.uid));
 const needItems=new Set(),forgeHolds=new Map(),readyItems=new Set(),recalls=[],free=s.inventory.capacity-s.inventory.count;
 const accessible=candidates.filter(e=>e.place==='inventory'||enabled.storage);let workshopReady=false;
 function recall(entries,reason,priority){
  for(const e of entries)needItems.add(e.info.uid);
  const item=entries.find(e=>e.place==='storage');
   if(item&&enabled.storage)recalls.push({entries,priority,purpose:reason==='合成配方'?'combine':reason==='锻造材料'?'forge':'workshop'});
   if(item&&free>0&&enabled.storage)add('withdraw','withdraw:'+item.info.uid+':'+stamp,'取用仓库物品 · '+reason,priority,{uid:item.info.uid,purpose:reason==='合成配方'?'combine':reason==='锻造材料'?'forge':'workshop'});
 }
 const tier=tierForLevel(Math.max(1,...managed.map(c=>c.level)),catalog.tiers);
 const retireTier=managed.length?tierForLevel(Math.min(...managed.map(c=>c.level)),catalog.tiers):null;
 const forge=enabled.forge?forgePlanning(im,managed,catalog.recipes,cubeLevel,tier,accessible,all,options,{sources:catalog.materialSources,frontier:s.record?.maxCleared}):null;
 s.forging={status:!enabled.forge?'disabled':forge?'materials_missing':'no_need',cubeLevel,tier,recipe:forge?.ID??null,part:forge?.CraftPart??null,priority:forge?.craftPriority??null,materials:forge?.materials||[],source:forge?.source??null,sourceKnown:forge?.sourceKnown??false,retainedParts:forge?.retainedParts??0,alternatives:forge?.alternatives??0,ready:false};
 if(forge){
  s.forging.minLevel=catalog.tiers.find(t=>t.tier===forge.MinTier)?.min;
  s.forging.maxLevel=catalog.tiers.find(t=>t.tier===forge.MaxTier)?.min;
  // Retain the exact forge demand while another ingredient is missing.
  const materials=(forge.retention||forge.materials).flatMap(m=>{
   const count=Math.min(m.required,m.available),batch=materialBatch(accessible.filter(e=>e.info.id===m.id),count);
   for(const [uid,quantity] of Object.entries(materialQuantities(batch,count)))forgeHolds.set(uid,(forgeHolds.get(uid)||0)+quantity);
   return batch;
  });
  for(const e of materials)needItems.add(e.info.uid);
  const ready=forge.complete&&forge.materials.every(m=>m.inventory>=m.required);
  s.forging.ready=ready;s.forging.status=ready?'ready':forge.complete?'storage_pending':'materials_missing';
  if(ready){workshopReady=true;materials.forEach(e=>readyItems.add(e.info.uid));
   add('forge','forge:'+forge.ID+':'+forge.MinTier+':'+materials.map(e=>e.info.uid+':'+e.info.count).join(','),'锻造可用配方范围内的成长装备',109,{recipe:forge.ID,part:forge.CraftPart,tier:forge.MinTier,allowed:materials.filter(e=>e.place==='inventory'&&forge.MaterialID.includes(e.info.id)).map(e=>e.info.uid)});
  }else if(forge.complete)recall(materials.filter(e=>forge.MaterialID.includes(e.info.id)),'锻造材料',109);
 }
 const attachments=accessible.filter(e=>e.info.kind===16&&!needItems.has(e.info.uid));
 for(const c of enabled.refine?managed:[]){
  const equipped=list(call(call(im,'GetEquipment',[c.id]),'get_Has')).filter(p=>p&&!isTradable(p)&&!call(p,'get_IsLocked'));
   const target=equipped.find(p=>attachments.some(e=>!needItems.has(e.info.uid)&&hasAttachmentSpace(im,p,e.item)));
  if(!target)continue;
   const materials=attachments.filter(e=>!needItems.has(e.info.uid)&&hasAttachmentSpace(im,target,e.item)).sort((a,b)=>b.info.grade-a.info.grade||b.info.tier-a.info.tier).slice(0,1),current=materials.filter(e=>e.place==='inventory');
  for(const e of materials)needItems.add(e.info.uid);
   if(current.length)workshopReady=true;current.forEach(e=>readyItems.add(e.info.uid));
  if(current.length)add('refine','refine:'+call(target,'get_Uid')+':'+list(call(target,'get_Sockets')).length+':'+stamp,'为角色 '+c.id+' 镶嵌可用材料',90,{id:c.id,uid:call(target,'get_Uid'),allowed:current.map(e=>e.info.uid)});
  else recall(materials,'装备镶嵌',91);
 }
 // Ready forging owns its stacks. Only an incomplete forge can release surplus units to synthesis.
 const fusionDiagnostics=[];
 const fusionMaterials=accessible.flatMap(e=>{
  if(!needItems.has(e.info.uid))return [e];
  if(!forge||forge.complete||!forgeHolds.has(e.info.uid))return [];
  const count=e.info.count-forgeHolds.get(e.info.uid);
  return count>0?[{...e,info:{...e.info,count}}]:[];
 });
 const combineGroups=enabled.combine?fusionPlans(fusionMaterials,catalog.recipes,cubeLevel,fusionDiagnostics):[];
 for(const plan of combineGroups)for(const e of plan.entries)needItems.add(e.info.uid);
 const tasks=fusionTasks(combineGroups,free);
 s.combining={status:!enabled.combine?'disabled':tasks.length?'planned':'materials_missing',waitingGroups:fusionDiagnostics.filter(p=>!p.ready).length,nearest:fusionDiagnostics.filter(p=>!p.ready).sort((a,b)=>(a.required-a.available)-(b.required-b.available)||b.minTier-a.minTier).slice(0,3),groups:tasks.length,ready:tasks.filter(t=>t.ready).length,warehousePending:tasks.filter(t=>!t.ready).length,needSpace:free<=0&&tasks.some(t=>!t.ready),
   warehouseMaterials:accessible.filter(e=>e.place==='storage'&&[8,16].includes(e.info.kind)).reduce((n,e)=>n+e.info.count,0)};
 for(const {group,current,ready} of tasks){
   if(ready)current.forEach(e=>readyItems.add(e.info.uid));
   if(ready)add('combine','combine:'+group.recipe.ID+':'+current.map(e=>e.info.uid+':'+e.info.count).join(','),'优先合成闲置材料并释放空间',108,
    {recipe:group.recipe.ID,category:group.category,tier:group.recipe.MinTier,materialTier:group.tier,materialMinTier:group.materialMinTier,materialMaxTier:group.materialMaxTier,maxGrade:group.grade,allowed:current.map(e=>e.info.uid),materialCounts:materialQuantities(current,group.recipe.FusionCount),batchSize:group.recipe.FusionCount});
   else recall(group.entries,'合成配方',107);
 }
 const pressure=s.inventory.count>=s.inventory.capacity*options.inventory_pressure_percent/100,full=free<=0,storageFull=call(storage,'get_IsFull');
 const storagePressure=enabled.storage&&(s.storage.pressure||storageFull);
 const obsolete=enabled.decompose&&managed.length?retirementPlans(all.filter(e=>canRecycleItem(im,e.item,options.recycle_socketed_equipment)&&(e.place==='inventory'||enabled.storage)),new Set([...needed,...needItems]),retireTier,options,pressure||storagePressure):[];
 const materialCounts=materialQuantities(obsolete.filter(e=>e.place==='inventory').slice(0,recycleLimit),recycleLimit);
 const reclaim=obsolete.filter(e=>materialCounts[e.info.uid]>0),batchSize=Object.values(materialCounts).reduce((n,count)=>n+count,0);
 s.recycling={pressureCleanup:options.recycle_pressure_cleanup&&(pressure||storagePressure),reservedEquipment:needed.size,obsolete:obsolete.length,inventory:obsolete.filter(e=>e.place==='inventory').length,storage:obsolete.filter(e=>e.place==='storage').length,planned:batchSize,nativeCapacity:recycleLimit?nativeCapacity:null,batchLimit:recycleLimit,socketedAllowed:options.recycle_socketed_equipment,locked:all.filter(e=>[1,2,4].includes(e.info.kind)&&e.info.locked).length,socketedRetained:all.filter(e=>[1,2,4].includes(e.info.kind)&&e.info.sockets>0&&!options.recycle_socketed_equipment).length,highGradeRetained:all.filter(e=>[1,2,4].includes(e.info.kind)&&e.info.grade>=5).length,retireTier,policy:'roster_upgrades_then_fusion_then_retirement'};
 if(batchSize){
  add('decompose','decompose:'+reclaim.map(e=>e.info.uid+':'+materialCounts[e.info.uid]).join(','),'分解闲置或淘汰装备，回收灵魂',102,{recycleSocketed:options.recycle_socketed_equipment,tier:Math.min(...reclaim.map(e=>e.info.tier)),maxGrade:Math.max(...reclaim.map(e=>e.info.grade)),allowed:reclaim.map(e=>e.info.uid),materialCounts,batchSize});}
 else if(recycleLimit&&obsolete.length)recall(obsolete.slice(0,1),'淘汰装备回收',102);
 else if(enabled.decompose&&!recycleLimit)issues.push('原生方块容量不可用，保留回收物品并等待容量恢复');
 const retiring=new Set(obsolete.map(e=>e.info.uid)),equipping=new Set(equipment.map(p=>p.uid)),movableHeld=movable.filter(e=>e.place==='inventory');
 const consumeReady=workshopReady||tasks.some(t=>t.ready)||reclaim.length>0;
 let stash=null,swap=null;
 if(enabled.storage&&pressure&&!storageFull){
  stash=stagingDeposit(movableHeld,needed,needItems,retiring,full,recalls,equipping,readyItems);
  if(stash)add('deposit','deposit:'+stash.info.uid+':'+stamp,full?'背包已满，临时存仓以接续取料和开箱':'自动存仓，预留战利品空间',full&&recalls.length&&!consumeReady?105:101,{uid:stash.info.uid});
 }
 // A native slot exchange can bring recipe materials in even when both containers are full.
 if(enabled.storage&&full&&storageFull&&!consumeReady){
  const target=[...recalls].sort((a,b)=>b.priority-a.priority)[0],stored=target?.entries.find(e=>e.place==='storage');
  swap=stored&&stagingDeposit(movableHeld,needed,needItems,retiring,true,[target],equipping,readyItems);
  if(swap)add('withdraw','withdraw:'+stored.info.uid+':swap:'+swap.info.uid+':'+stamp,'背包与仓库已满，交换闲置物品以取用材料',target.priority,{uid:stored.info.uid,swapUid:swap.info.uid,purpose:target.purpose});
 }
 const blocked=full&&!stash&&!swap&&!consumeReady&&!equipment.length;
 s.inventoryFlow={recipeReserved:needItems.size,movable:movable.length,consumable:safe.length,protectedMaterials:all.filter(e=>!e.consumable&&!canRecycleItem(im,e.item,options.recycle_socketed_equipment)).length,blockedTransfers:all.length-movable.length,reservedEquipment:needed.size,storageFull,staging:!!stash,swapping:!!swap,blocked};
 if(blocked)issues.push(storageFull?'背包与仓库已满：没有可安全整理的组合，保留受保护物品并等待配方或容量条件':'背包已满：没有可安全转仓的闲置物品，等待装备、配方或扩容条件');
 else if(full)issues.push('背包已满，正在安排存仓、合成、回收与扩容');
 s.inventoryFlow.waitingConditions=candidates.filter(e=>!needItems.has(e.info.uid)&&!retiring.has(e.info.uid)).length;
 s.inventoryFlow.recipeReserved=needItems.size;
}
// Only the native maintenance handler can authorize the game's own exit callback.
// Never infer maintenance or confirm an arbitrary dialog from its displayed text.
function maintenanceStatus(){
 const result={known:false,active:false,canExit:false};
 try{result.active=stat('DG.UI.MaintenanceHandler','get_IsActive')===true;result.known=true;}catch(error){return result;}
 if(!result.active)return result;
 try{
  const p=sceneObject('DG.UI.ConfirmPopup');
  if(!p||!call(call(p,'get_gameObject'),'get_activeInHierarchy'))return result;
  const declaring=api('method_get_class','pointer',['pointer']);
  function exitCallback(name){
   const d=read(p,name);if(!d||d.isNull()||!read(d,'m_target').isNull())return false;
   const m=read(d,'method');
   return !m.isNull()&&utf(A.methodName(m))==='Exit'&&fullname(declaring(m))==='.AppQuitHandler'&&list(read(d,'delegates')).length===0;
  }
  const button=read(p,'_confirmButton');
  result.canExit=exitCallback('_confirmed')&&exitCallback('_cancelled')&&!!button&&!button.isNull()&&
   call(call(button,'get_gameObject'),'get_activeInHierarchy')===true&&call(button,'get_interactable')===true;
 }catch(error){result.canExit=false;}
 return result;
}
function openPopups(){return list(invoke(external('UnityEngine','Resources'),nil,'FindObjectsOfTypeAll',[ref(typeObject(classType(klass('DG.UI.OutGamePopup'))))],'System.Type')).filter(p=>call(call(p,'get_gameObject'),'get_activeInHierarchy'));}
const cleanupPopupTypes=new Set(['DG.UI.Popup.HeroPopup','DG.UI.Popup.HeroInfoPopup','DG.UI.Popup.SkillTreePopup','DG.UI.Popup.StoragePopup','DG.UI.Popup.CubePopup','DG.UI.Rune.RuneTreePopup']);
// Keep inspection windows open; only suspend actions that can change their contents.
function popupPolicy(open,preserveOpenPanels=true,pauseOnManualPanels=false){
 const known=new Set([...cleanupPopupTypes,'DG.UI.Popup.MailPopup','DG.UI.Popup.TradePopup','DG.UI.Popup.SteamInventoryPopup','DG.UI.Popup.OfflineRewardPopup']);
 const manual=preserveOpenPanels?open.filter(name=>cleanupPopupTypes.has(name)):[];
 const blocked=open.filter(name=>!known.has(name)||pauseOnManualPanels&&manual.includes(name));
 return {blocked,manual,cleanup:blocked.length||preserveOpenPanels?null:open.find(name=>cleanupPopupTypes.has(name))||null,
  offline:!blocked.length&&!manual.length&&open.includes('DG.UI.Popup.OfflineRewardPopup')};
}
function panelActionBlocked(kind,panels=[]){
 if(!panels.length)return false;
 if(['ui_cleanup','sort','tower','tower_return','progress','battle_recover','mail_open','mail_close','mail_claim','offline_close','formation'].includes(kind))return true;
 // Native workshop views borrow the shared popup layout and item-input container.
 if(['combine','decompose','forge','refine'].includes(kind))return true;
 if(panels.some(n=>n.endsWith('HeroPopup')||n.endsWith('HeroInfoPopup'))&&['equipment','active','passive','skill_equip','skill_refund','passive_refund','skill_unequip','unlock'].includes(kind))return true;
 if(panels.includes('DG.UI.Popup.SkillTreePopup')&&['active','passive','skill_equip','skill_refund','passive_refund','skill_unequip','unlock'].includes(kind))return true;
 if(panels.some(n=>n.endsWith('StoragePopup')||n.endsWith('CubePopup'))&&['equipment','deposit','withdraw'].includes(kind))return true;
 return false;
}
// Stable role templates use native types and unlocks, never combat-time scores.
// Gula keeps a stack generator plus its spender before kill-triggered fallback, so Boss
// attempts do not depend on four kills occurring first. No repeated farming/Boss respec.
function planActives(rows,slots,level,points,recommended=true){
 const available=rows.filter(r=>r.unlock<=level),types=new Set(rows.map(r=>r.type)),desired=[];
 // Identify the role from its complete native catalogue, including skills unlocked later.
 const roles=recommended?(types.has('HitShield')&&types.has('Berserk')?['HitShield','Berserk','PowerAttack']:
  types.has('AttackSpeedStack')?['AttackSpeedStack','Barrage','CriticalBuff','ParabolaShot']:
  types.has('GluttonyKill')?['GluttonyStrike','FollowField','GluttonyBurst','GluttonyKill']:
  types.has('ShapeShiftSlash')?['ShapeShiftSlash','ShapeShiftRampage','SelfHeal','AreaBurstAttackSpeed']:
  types.has('BrandBurst')?['BrandBurst','HealAlly','TeamAttackBuff','SignatureTeamShield']:[]):[];
 function add(uid){if(uid&&desired.length<slots.length&&!desired.includes(uid)&&available.some(r=>r.uid===uid))desired.push(uid);}
 for(const type of roles){const candidate=available.filter(r=>r.type===type).sort((a,b)=>b.unlock-a.unlock||b.learned-a.learned||String(a.uid).localeCompare(String(b.uid)))[0];if(candidate)add(candidate.uid);}
 slots.forEach(add);available.forEach(r=>add(r.uid));
 const wanted=new Set(desired),equipped=new Set(slots.filter(Boolean)),used=new Set(),swaps=[];
 for(const uid of desired){
  if(equipped.has(uid)||!rows.find(r=>r.uid===uid&&r.learned>0))continue;
  let slot=slots.findIndex((x,i)=>!x&&!used.has(i));
  if(slot<0)slot=slots.findIndex((x,i)=>!wanted.has(x)&&!used.has(i));
  if(slot>=0){used.add(slot);swaps.push({uid,slot,previous:slots[slot]||null});}
 }
 const missing=desired.filter(uid=>!rows.find(r=>r.uid===uid&&r.learned>0));
 const refund=rows.filter(r=>r.learned>0&&!wanted.has(r.uid)&&!equipped.has(r.uid)).map(r=>r.uid);
 const retire=points<=0&&missing.length&&!swaps.length&&!refund.length?slots.findIndex(uid=>uid&&!wanted.has(uid)):-1;
 return {desired,missing,learn:desired,refund,swaps,unequip:retire>=0?{slot:retire,uid:slots[retire],target:missing[0]}:null};
}
function towerRepeatGuard(stage){
 if(stage?.category!==1||stage.repeat!==true)return null;
 return {mode:'guard',repeat:false,freeEntry:true};
}
function nextTowerLevel(record,max){
 const cleared=record?.towerMaxCleared;
 return Number.isInteger(cleared)&&cleared>=0&&Number.isInteger(max)&&max>cleared?cleared+1:null;
}
function contentGoal(rows){
 const known=rows.every(r=>typeof r.eligible==='boolean');
 return {total:rows.length,eligibleTotal:known?rows.filter(r=>r.eligible).length:null,
  eligibleUnlocked:known?rows.filter(r=>r.eligible&&r.unlocked).length:null,
  excludedDlc:rows.filter(r=>r.condition==='DLC'&&r.eligible===false).length,requirements:rows};
}
function isFarmingStage(stage){return stage?.category===0&&stage.repeat===true;}
function petPreference(ability,factor,farming){
 if(!Number.isFinite(factor))return {group:-2,value:0};
 const growth=/KillExpGain/.test(ability)?3:/KillGoods/.test(ability)?2:0;
 const combat=/Critical|AttackSpeed|BaseAttackPoint|BossMonster/.test(ability)?3:/Defense|ReviveHaste/.test(ability)?2:1;
 return {group:/OfflineReward/.test(ability)?-1:farming?(growth||1):growth?0:1,value:factor*combat};
}
function planPetFollower(rows,current,mode='auto'){
 if(mode==='keep')return null;
 if(mode==='auto'&&rows.some(p=>p.id===current))return current;
 const ordered=[...rows].sort((a,b)=>{
  if(mode==='auto')return a.id.localeCompare(b.id);
  const x=petPreference(a.ability,a.factor,mode==='growth'),y=petPreference(b.ability,b.factor,mode==='growth');
  return y.group-x.group||y.value-x.value||(b.id===current)-(a.id===current)||a.id.localeCompare(b.id);
 });
 return ordered[0]?.id??null;
}
function boxOpportunities(s,drop,add){
 const counts=[0,1,2].map(grade=>call(drop,'Count',[grade]));
 s.boxes={counts,total:counts.reduce((n,count)=>n+count,0),freeSlots:Math.max(0,s.inventory.capacity-s.inventory.count)};
 for(const [grade,count] of counts.entries())if(count>0&&s.boxes.freeSlots>0)
  add('box','box:'+grade+':'+s.record.boxes,'开启战利品宝箱',99,{grade,count});
}
function auxiliaryOpportunities(s,dm,im,add,issues,options=bridgeStrategy()){
 const popups=openPopups(),open=popups.map(p=>fullname(A.objectClass(p)));
 const policy=popupPolicy(open,options.preserve_open_panels,options.pause_on_manual_panels);s.automationBlocked=policy.blocked;
 s.manualPanels=policy.manual;s.manualPanelOpen=policy.manual.length>0;
 s.manualBlockedKinds=['box','equipment','active','passive','skill_equip','skill_refund','passive_refund','skill_unequip','unlock','rune','combine','decompose','forge','refine','deposit','withdraw','sort','tower','tower_return','progress','battle_recover','formation','mail_open','mail_close','mail_claim','offline_close'].filter(kind=>panelActionBlocked(kind,policy.manual));
 if(s.manualPanelOpen&&!policy.blocked.length)issues.push('手动窗口已保留：不冲突的成长继续，窗口内物品与切场操作等待关闭后恢复');
 const holding=call(call(im,'get_Input'),'get_IsHolding'),cubeBusy=!call(call(im,'get_Cube'),'get_IsEmpty');
 s.itemInputHolding=holding;s.cubeBusy=cubeBusy;
 if(holding){s.automationBlocked.push('item_drag_active');issues.push('正在拖拽物品，放下后自动恢复');}
 // Native TryOpen only appends a new inventory item; it never reserves input/cube materials.
 if(cubeBusy){s.manualBlockedKinds.push('equipment','combine','decompose','forge','refine','deposit','withdraw','sort','tower','tower_return','progress','battle_recover');issues.push('合成方块中仍有手动物品，工坊与切场等待取回；背包有空位时继续单次开箱');}
 s.experienceBlocked=open.length>0||holding;
 if(policy.blocked.length)issues.push(s.manualPanelOpen?'手动面板已保留：关闭背包、仓库或成长窗口后自动恢复':'确认或未知面板正在等待处理，自动化保留窗口并暂停提交');
 const trade=open.some(n=>n.endsWith('TradePopup')||n.endsWith('SteamInventoryPopup'));
 s.trading=trade;
 if(trade){s.manualBlockedKinds.push('box','equipment','combine','decompose','forge','refine','deposit','withdraw','sort','tower','tower_return','progress','battle_recover','mail_open','mail_claim','mail_close');issues.push('交易面板正在使用，物品与切场操作等待面板关闭');}
 const ordinary=popups.find(p=>fullname(A.objectClass(p))===policy.cleanup);
 const offline=popups.find(p=>fullname(A.objectClass(p))==='DG.UI.Popup.OfflineRewardPopup');
 if(policy.offline&&offline&&!read(offline,'_opening'))add('offline_close','offline_close','完成离线收益展示，接续游戏加载',115);
 if(ordinary&&call(call(im,'get_Cube'),'get_IsEmpty')&&!call(call(im,'get_Input'),'get_IsHolding'))add('ui_cleanup','close:'+fullname(A.objectClass(ordinary)),'收起面板，接续自动成长',110,{type:fullname(A.objectClass(ordinary))});
 const server=single('DG.Network.ServerManager'),unread=call(server,'get_MailUnreadCount'),mail=sceneObject('DG.UI.Popup.MailPopup');
 s.mail={unread,loading:mail?read(mail,'_isLoading'):false,claiming:mail?read(mail,'_isClaiming'):false,claims:mailClaimObservation()};
 if(mail&&!trade&&s.inventory.count<s.inventory.capacity){
  const active=open.includes('DG.UI.Popup.MailPopup');
  if(unread>0&&!active)add('mail_open','mail_open:'+unread,'读取待领取邮件',77);
  if(active&&!s.mail.loading&&!s.mail.claiming){
   const mails=list(read(mail,'_slots')).map(p=>call(p,'get_Mail')).filter(p=>p&&read(p,'state')==='unread');
   if(mails.length&&s.mail.claims.available&&call(mail,'IsReceivable'))add('mail_claim','mail_claim:'+mails.map(p=>read(p,'mailId')).sort().join(','),'领取邮件附件',98,{ids:mails.map(p=>read(p,'mailId'))});
   else if(!mails.length)add('mail_close','mail_close','收起已处理的邮箱',76);
  }
 }
 const gm=single('DG.Manager.GameManager'),tower=nextTowerLevel(s.record,s.catalogue.towerMax);
 const repeatGuard=towerRepeatGuard(s.stage);
 if(repeatGuard)add('progress','tower_repeat_off','无限塔单次挑战，关闭继承的重复开关',131,repeatGuard);
 s.tower={level:tower,max:s.catalogue.towerMax,cleared:s.record.towerMaxCleared,complete:s.record.towerMaxCleared>=s.catalogue.towerMax};
 const ending=call(gm,'IsStageEnding');
 s.stage.ending=ending;
 if(s.stage.category===1&&!s.stage.running&&ending){
  const returnLevel=read(gm,'_returnLevel'),returnDifficulty=read(gm,'_returnDifficulty');
  if(returnLevel>0&&call(gm,'CanEnterStage',[0,returnLevel]))add('tower_return','tower_return:'+returnLevel+':'+returnDifficulty,'无限塔结束，返回主线继续成长',112,{level:returnLevel,difficulty:returnDifficulty,freeEntry:call(gm,'GetRequireItemID',[0,returnLevel])<=0});
  else issues.push('无限塔已结束，原生返回关卡暂不可进入，等待同步完成');
 }
 if(s.stage.category===0&&s.stage.running===false&&ending&&Number.isInteger(s.stage.level)&&
    Number.isInteger(s.record.maxCleared)&&s.stage.level<=s.record.maxCleared&&
    Number.isInteger(s.catalogue.normalMax)&&s.catalogue.normalMax>0&&s.record.maxCleared>=s.catalogue.normalMax&&
    call(gm,'GetRequireItemID',[0,s.stage.level])<=0&&tower>0&&tower<=s.catalogue.towerMax&&call(gm,'CanEnterStage',[1,tower])){
  const ticket=call(gm,'GetRequireItemID',[1,tower]),target=ticket>0?call(im,'FindOccupyTarget',[ticket]):null;
  if(ticket<=0||(target&&!protectedItem(im,target)))add('tower','tower:'+tower+':'+(target?call(target,'get_Uid'):'free'),'挑战无限塔第 '+tower+' 层',79,{level:tower,ticket,freeEntry:ticket<=0,clearedBefore:s.record.towerMaxCleared});
 }
}

function entranceStatus(gm,im,category,level){
 const ticket=call(gm,'GetRequireItemID',[category,level]);
 if(ticket<=0)return {level,ticket,safe:true};
 const target=call(im,'FindOccupyTarget',[ticket]);
 if(!target)return {level,ticket,safe:false,reason:'ticket_missing'};
 if(!protectedItem(im,target))return {level,ticket,safe:true,uid:call(target,'get_Uid'),count:call(target,'get_Count')};
 // Main-story entry tickets are consumables for boss clears, never crafting or trading materials.
 const info=itemInfo(target),config=call(target,'get_Config');
 const approved=category===0&&[690100,690200,690300,690400].includes(ticket)&&info.id===ticket&&
  info.kind===32&&read(config,'ItemType')===6&&info.tradable===true&&info.confirmed===true&&
  info.locked===false&&info.count>0&&info.sockets===0&&!call(im,'IsInUse',[ref(target)])&&
  !call(im,'IsEquipped',[ref(target)])&&list(call(im,'FindRegistrations',[ref(target)])).length===0;
 return {level,ticket,safe:approved,uid:info.uid,count:info.count,consumeOnClear:approved,
  reason:approved?'boss_entry_ticket':info.tradable?'protected_ticket':'unavailable_ticket'};
}
function battleReadiness(s){
 try{
  const gm=single(names.game),bm=single('DG.InGame.Battle.Manager.BattleManager'),arrange=call(bm,'get_Arrange');
  const owned=new Set(s.characters.map(c=>c.id)),ids=s.squad.filter(id=>id>0);
  if(new Set(ids).size!==ids.length||ids.some(id=>!owned.has(id)))return {known:false,reason:'squad_not_ready'};
  const missing=ids.filter(id=>{const model=call(arrange,'GetArrangedCharacter',[id]);return !model||model.isNull();});
  return {known:true,charactersInitialized:call(single(names.chars),'get_IsInitialized'),expected:ids.length,missing,
   arrangedCount:call(arrange,'GetArrangedCharactersCount'),squadArranged:read(gm,'_squadArranged'),
   syncRunning:read(gm,'_squadSyncRunning'),syncPending:read(gm,'_squadSyncPending'),
   enterSequence:read(gm,'_enterSequence'),ending:call(gm,'IsStageEnding'),pendingSpawn:call(call(bm,'get_Stage'),'get_HasPendingSpawn'),timeScale:invoke(external('UnityEngine','Time'),nil,'get_timeScale')};
 }catch(error){return {known:false,reason:'native_readiness_unavailable'};}
}
function battleRecoveryCase(s){
 const r=s.battleReadiness,stage=s.stage;
 if(!r?.known||!r.charactersInitialized||r.expected<=0||r.syncRunning!==false||r.syncPending!==false||stage.category!==0||r.timeScale===0)return null;
 if(r.missing.length&&r.arrangedCount===0&&stage.alivePlayers===0)return 'missing_party';
 if(!r.missing.length&&r.arrangedCount>0&&stage.running===false&&stage.wave>0&&stage.aliveMonsters===0&&r.pendingSpawn===false)return 'stalled_end';
 return null;
}
function battleRecoveryPlans(s){
 const r=s.battleReadiness,stage=s.stage,reason=battleRecoveryCase(s);
 if(!reason)return [];
 const base={kind:'battle_recover',priority:145,level:stage.level,difficulty:stage.difficulty,category:stage.category,freeEntry:true};
 const suffix=[stage.category,stage.level,stage.difficulty,r.enterSequence,s.squad.join('-')].join(':');
 const plans=reason==='missing_party'?[{...base,mode:'sync',reason,key:'battle_recover:sync:'+suffix,label:'重新同步已保存编队，恢复缺失英雄'}]:[];
 const gm=single(names.game);let target=stage.level;
 const cleared=s.combat?.available&&s.combat.current?.result==='Cleared'&&s.combat.current.level===stage.level&&s.combat.current.difficulty===stage.difficulty&&stage.level<=s.record.maxCleared;
 if(reason==='stalled_end'&&cleared&&!stage.repeat&&call(gm,'HasStageData',[stage.level+1,stage.difficulty])&&call(gm,'GetRequireItemID',[0,stage.level+1])<=0&&call(gm,'CanEnterStage',[0,stage.level+1]))target=stage.level+1;
 if(call(gm,'GetRequireItemID',[stage.category,target])<=0&&call(gm,'CanEnterStage',[stage.category,target]))plans.push({...base,level:target,mode:'stage',reason,key:'battle_recover:stage:'+suffix+':'+target,label:target===stage.level?'重新进入当前免费关卡，接续战斗':'已确认通关，接续下一免费关卡'});
 return plans;
}
function activeFrontierBattle(s){
 const stage=s.stage||{},raw=s.combat||{},current=raw.current||{},frontier=s.record?.maxCleared;
 if(stage.category!==0||stage.running!==true||raw.available!==true||!Number.isInteger(frontier)||frontier<0||
  !Number.isInteger(stage.level)||stage.level<=frontier||!Number.isInteger(stage.difficulty)||stage.difficulty<0||
  !Number.isInteger(current.sequence)||current.sequence<0||current.result!=='InProgress'||
  current.level!==stage.level||current.difficulty!==stage.difficulty||!Number.isFinite(current.elapsed)||current.elapsed<0)return null;
 return {level:stage.level,difficulty:stage.difficulty,sequence:current.sequence,elapsed:current.elapsed};
}
function frontierFarmReturnAllowed(s,action,cmd,options){
 if(action.kind!=='progress'||action.mode!=='farm'||action.phase!=='travel')return true;
 const battle=activeFrontierBattle(s);if(!battle)return true;
 const proof=cmd.frontierReturn;
 return !!proof&&['level','difficulty','sequence'].every(k=>proof[k]===battle[k])&&
  Number.isFinite(proof.elapsed)&&proof.elapsed>=0&&battle.elapsed>=proof.elapsed&&
  Number.isFinite(proof.waited)&&proof.waited>=options.farm_retry_finish_seconds;
}
function progressionOpportunities(s,dm,im,add,issues,options=bridgeStrategy()){
 if(s.stage.category!==0){s.progression={mode:'content',gate:null};return;}
 const gm=single(names.game),levels=list(call(read(dm,'_stageConfigTable'),'get_Datas')).map(p=>read(p,'Level'));
 const frontier=Number.isInteger(s.record.maxCleared)?Math.max(0,s.record.maxCleared):0,next=frontier+1;
 const stages=list(call(read(dm,'_stageTable'),'get_Datas'));
 const stageByLevel=new Map();for(const row of stages){const level=read(row,'Level');if(!stageByLevel.has(level))stageByLevel.set(level,row);}
 const challenge=stageByLevel.get(next);
 const entry=levels.includes(next)?entranceStatus(gm,im,0,next):null;
 // Return directly to the frontier. Disabling repeat on an old map replays cleared Bosses.
 const gate=s.stage.level!==next&&entry&&!entry.safe?entry:null;
 s.progression={mode:s.stage.repeat?'repeat':'push',gate,boss:entry&&entry.ticket>0?entry:null,
  nextChallenge:challenge?{level:next,difficulty:read(challenge,'Difficulty'),ticket:entry?.ticket||0}:null};
 s.entryTickets=containerEntries(im).map(e=>({place:e.place,...itemInfo(e.item)})).filter(p=>[690100,690200,690300,690400].includes(p.id));
 if(challenge&&entry?.safe&&s.stage.level<next&&call(gm,'CanEnterStage',[0,next])){
   if(entry.ticket>0)add('progress','boss:'+next+':'+entry.uid,'挑战主线前沿第 '+next+' 关 Boss',108,
    {mode:'boss',phase:'travel',repeat:false,level:next,difficulty:read(challenge,'Difficulty'),ticket:entry.ticket,ticketUid:entry.uid,ticketBefore:entry.count});
  else add('progress','push:'+next,'直接挑战最高已通关后的第 '+next+' 关',108,
   {mode:'push',phase:'travel',repeat:false,level:next,difficulty:read(challenge,'Difficulty'),freeEntry:true});
 }
 if(gate){
  issues.push(gate.reason==='protected_ticket'?'主线前沿入场物品受保护，继续免费练级与成长':'主线前沿缺少可用入场物品，继续免费练级与成长');
  if(!s.stage.repeat&&s.stage.level<=frontier&&call(gm,'GetRequireItemID',[0,s.stage.level])<=0)
   add('progress','guard_gate:'+next+':'+gate.reason,'保留入场物品，当前免费关卡继续成长',130,{mode:'guard',repeat:true,freeEntry:true});
 }else if(s.stage.repeat&&activeFrontierBattle(s))add('progress','frontier_repeat_off','当前前沿完成后继续自动推进',130,{mode:'guard',repeat:false,freeEntry:true,requiresProgress:true});
 else if(s.stage.repeat&&s.stage.level>=next)add('progress','repeat_off','恢复主线自动推进',106,{mode:'push',repeat:false});
 // Anchor the band to the highest cleared record, not the highest currently enterable map.
 const chapterNumber=frontier>0?Math.ceil(frontier/10):1;
 const chapterStart=(chapterNumber-1)*10+1,chapterEnd=chapterNumber*10;
 const frontierStage=stageByLevel.get(frontier);
 const newestDifficulty=frontierStage?read(frontierStage,'Difficulty'):null;
 let targets=[...new Set(levels)].filter(level=>Number.isInteger(level)&&level>0&&level<=frontier
  &&level>=chapterStart&&level<=chapterEnd&&stageByLevel.has(level))
  .sort((a,b)=>b-a).filter(level=>call(gm,'GetRequireItemID',[0,level])<=0&&entranceStatus(gm,im,0,level).safe&&call(gm,'CanEnterStage',[0,level])&&call(gm,'CanRepeat',[0,level]));
 const highest=targets[0],spacing=Math.max(1,options.farm_level_offset);
 const rangeMinimum=highest?Math.max(chapterStart,highest-options.farm_candidate_count+1):chapterStart;
 // Keep the full ten-level chapter even when native difficulty changes inside it.
 // Each candidate and action still carries that stage's own native difficulty.
 targets=targets.filter(level=>level>=rangeMinimum&&(highest-level)%spacing===0);
 const minimum=targets.length?Math.min(...targets):rangeMinimum;
 s.progression.farmBand={start:chapterStart,end:Math.min(frontier,chapterEnd),minLevel:minimum,
  maxLevel:highest||frontier,chapter:chapterNumber,difficulty:newestDifficulty,policy:'chapter_exp_efficiency'};
 s.progression.farmCandidates=targets.map(level=>{const stage=stageByLevel.get(level);return stage?{level,difficulty:read(stage,'Difficulty')}:null;}).filter(Boolean);

 for(const target of targets)if(!s.stage.repeat||s.stage.level!==target){
  const stage=stageByLevel.get(target);
  const phase=s.stage.level===target?'repeat':'travel';
  if(stage)add('progress','farm:'+target+':'+phase,phase==='travel'?'返回已通关关卡，准备自动练级':'重复已通关关卡，积累等级与材料',107,{mode:'farm',phase,repeat:true,level:target,difficulty:read(stage,'Difficulty'),freeEntry:call(gm,'GetRequireItemID',[0,target])<=0});
 }
}

// Mechanism-based priorities are a stable policy, not a claim of optimal simulated DPS.
function skillPartyPosition(squad,characters){
 const ranges={};
 if(!Array.isArray(squad)||squad.some(id=>!Number.isInteger(id))||!Array.isArray(characters))
  return {known:false,frontline:null,ranges,reason:'invalid_squad'};
 const ids=squad.filter(id=>id>0);
 if(!ids.length||new Set(ids).size!==ids.length)return {known:false,frontline:null,ranges,reason:'invalid_squad'};
 for(const id of ids){
  const rows=(characters||[]).filter(c=>c.id===id),range=rows.length===1?rows[0].baseRange:null;
  if(!Number.isFinite(range)||range<=0)return {known:false,frontline:null,ranges,reason:'range_unavailable'};
  ranges[id]=range;
 }
 const minimum=Math.min(...Object.values(ranges)),front=ids.filter(id=>ranges[id]===minimum);
 if(front.length!==1)return {known:false,frontline:null,ranges,reason:'range_tied'};
 return {known:true,frontline:front[0],ranges,reason:'native_base_range'};
}
function skillProfile(rows){
 const types=new Set(rows.map(r=>r.type));
 return types.has('HitShield')?'guardian':types.has('AttackSpeedStack')?'ranger':types.has('GluttonyStrike')?'gluttony':types.has('ShapeShiftSlash')?'shifter':types.has('BrandBurst')?'support':'general';
}
function passiveUtility(row,actives,context={}){
 const name=row.ability||'',profile=skillProfile(actives),types=new Set(actives.map(r=>r.type));
 let weight=/BasicDamageBonus|BaseAttackPoint/.test(name)?92:/AttackSpeed/.test(name)?87:/SkillHaste/.test(name)?85:/Skill_Rate/.test(name)?84:/HealthPoint|DamageReduction/.test(name)?82:/Critical|NormalAttack/.test(name)?80:72;
 if(profile==='guardian'&&/HealthPoint|Defense|ShieldBonus|DamageReduction/.test(name))weight=context.frontline?108:90;
 if(profile==='ranger'&&/AttackSpeed|Critical/.test(name))weight=106;
 if(profile==='gluttony'&&/Skill_Rate|SkillHaste|BaseAttackPoint|BossMonster/.test(name))weight=104;
 if(profile==='shifter'&&/AttackSpeed|BasicDamageBonus/.test(name))weight=103;
 if(profile==='shifter'&&types.has('SelfHeal')&&/Evasion/.test(name))weight=107;
 if(profile==='support'&&/BaseAttackPoint|SkillHaste|ShieldBonus/.test(name))weight=105;
 if(row.apply===1&&context.arranged)weight+=8; // Wiki: team passives require the hero in the squad.
 if(/SkillHaste/.test(name)&&!actives.some(r=>r.cooldown>0))weight-=18;
 if(/ShieldBonus/.test(name)&&!actives.some(r=>/Shield/.test(r.type)))weight-=18;
 if(row.trigger&&row.trigger!=='Always')weight-=10;
 const delta=row.learned?row.increment:row.factor;
 return Number.isFinite(delta)&&delta>0?weight/(1+row.learned*.14):0;
}
function planSkillPoints(actives,passives,build,level,context={},modules={}){
 const selected=actives.filter(r=>build.desired.includes(r.uid)),byIndex=new Map(passives.map(r=>[r.index,r])),candidates=[];
 if(modules.active!==false)for(const r of selected)if(r.canLearn&&r.learned<r.max){
  const grows=(r.increments||[]).some(x=>Number.isFinite(x)&&x>0)||(r.subIncrements||[]).some(x=>Number.isFinite(x)&&x>0)||r.cooldownIncrement<0;
  if(r.learned&&!grows)continue;
  candidates.push({kind:'active',skill:r.uid,target:r.uid,reason:r.learned?'core_upgrade':'core_unlock',score:r.learned?108/(1+r.learned*.32):1000,steps:1});
 }
 if(modules.passive!==false)for(const target of passives.filter(p=>p.unlock<=level&&p.learned<p.max)){
  const demand=new Map();let valid=true;
  function require(index,count,path=new Set()){
   if(index<0)return;
   const p=byIndex.get(index);
   if(!p||path.has(index)||p.unlock>level||count>p.max){valid=false;return;}
   if(p.learned>=count)return;
   const previous=demand.get(index)||0;if(previous>=count)return;
   demand.set(index,count);path=new Set(path);path.add(index);
   p.requires.forEach((parent,i)=>require(parent,p.requireLevels[i],path));
  }
  require(target.index,target.learned+1);
  if(!valid)continue;
  const next=[...demand.keys()].map(i=>byIndex.get(i)).filter(p=>p.canLearn&&p.learned<demand.get(p.index))
   .sort((a,b)=>Number(a.uid===target.uid)-Number(b.uid===target.uid)||a.index-b.index)[0];
  if(!next)continue;
  const steps=[...demand].reduce((n,[i,count])=>n+count-byIndex.get(i).learned,0);
  candidates.push({kind:'passive',skill:next.uid,target:target.uid,reason:next.uid===target.uid?'role_passive':'passive_prerequisite',steps,
   score:passiveUtility(target,selected,context)/Math.sqrt(steps)});
 }
 candidates.sort((a,b)=>b.score-a.score||a.steps-b.steps||a.skill.localeCompare(b.skill)||a.target.localeCompare(b.target));
 const seen=new Set(),ranked=candidates.filter(c=>{const key=c.kind+':'+c.skill;if(seen.has(key))return false;seen.add(key);return c.score>0;});
 return {profile:skillProfile(selected),next:ranked[0]||null,candidates:ranked};
}

// Rebuild from the finite point pool, not native CanLearn (which is false at zero points).
// Selected actives retain their first level; authorized upgrades and passive points share the pool.
// The pool survives each one-point refund/learn and bridge restart without a saved reset job.
function planSkillReallocation(actives,passives,build,level,points,context={},options={}){
 const modules=options.modules||{},incremental=()=>planSkillPoints(actives,passives,build,level,context,modules);
 // Do not refund or spend position-sensitive passive points on an unknown role.
 // Core active growth and every other automation module remain available.
 if(modules.passive!==false&&context.arranged&&context.positionKnown===false
  &&skillProfile(actives.filter(a=>build.desired.includes(a.uid)))==='guardian')
  return {...planSkillPoints(actives,passives,build,level,context,{...modules,passive:false}),repair:{reason:'position_unknown'}};
 const repairPassive=modules.passive!==false&&options.allow_passive_refund!==false;
 const repairActive=modules.active!==false&&options.allow_active_refund===true;
 if(!repairPassive&&!repairActive)return {...incremental(),repair:null};
 const selected=actives.filter(a=>build.desired.includes(a.uid));
 const controls={active:repairActive,passive:repairPassive};
 const byIndex=new Map(passives.map(p=>[p.index,p]));
 const valid=p=>typeof p.uid==='string'&&Number.isInteger(p.index)&&Number.isInteger(p.learned)&&p.learned>=0&&Number.isInteger(p.max)&&p.max>=p.learned
  &&Number.isInteger(p.unlock)&&Array.isArray(p.requires)&&Array.isArray(p.requireLevels)&&p.requires.length===p.requireLevels.length
  &&p.requires.every((index,i)=>Number.isInteger(index)&&(index<0||byIndex.has(index)&&Number.isInteger(p.requireLevels[i])&&p.requireLevels[i]>=0&&p.requireLevels[i]<=byIndex.get(index).max));
 const seen=new Set(),path=new Set();
 function acyclic(p){if(path.has(p.index))return false;if(seen.has(p.index))return true;path.add(p.index);
  for(const i of p.requires)if(i>=0&&!acyclic(byIndex.get(i)))return false;
  path.delete(p.index);seen.add(p.index);return true;}
 const activeValid=!repairActive||(new Set(selected.map(a=>a.uid)).size===selected.length&&selected.every(a=>
  typeof a.uid==='string'&&Number.isInteger(a.learned)&&a.learned>=0&&Number.isInteger(a.max)&&a.max>=a.learned&&Number.isInteger(a.unlock)));
 const pool=points+(repairPassive?passives.reduce((n,p)=>n+p.learned,0):0)
  +(repairActive?selected.reduce((n,a)=>n+Math.max(0,a.learned-1),0):0),reserve=options.skill_point_reserve||0;
 if(!activeValid||!passives.every(valid)||byIndex.size!==passives.length||new Set(passives.map(p=>p.uid)).size!==passives.length
  ||!Number.isInteger(points)||points<0||!Number.isInteger(pool)||pool>100||!passives.every(acyclic))return {...incremental(),repair:{reason:'skill_catalogue_invalid',controls}};
 const simulated=passives.map(p=>({...p,learned:repairPassive?0:p.learned})),simIndex=new Map(simulated.map(p=>[p.index,p]));
 const as=actives.map(a=>({...a,learned:repairActive&&build.desired.includes(a.uid)?Math.min(1,a.learned):a.learned}));
 let remaining=Math.max(0,pool-reserve);const route=[];
 while(remaining>0){
  for(const p of simulated)p.canLearn=p.unlock<=level&&p.learned<p.max&&p.requires.every((i,n)=>i<0||simIndex.get(i).learned>=p.requireLevels[n]);
  for(const a of as)a.canLearn=a.unlock<=level&&a.learned<a.max;
  const next=planSkillPoints(as,simulated,build,level,context,modules).candidates.find(c=>c.steps<=remaining);
  if(!next)break;
  (next.kind==='active'?as:simulated).find(p=>p.uid===next.skill).learned++;remaining--;route.push(next);
 }
 const target=Object.fromEntries(simulated.map(p=>[p.uid,p.learned]));
 const activeTarget=Object.fromEntries(as.filter(a=>build.desired.includes(a.uid)).map(a=>[a.uid,a.learned]));
 const excess=repairPassive?passives.filter(p=>p.learned>target[p.uid]):[];
 const activeExcess=repairActive?selected.filter(a=>a.learned>activeTarget[a.uid]):[];
 // Keep shared parents at the maximum requirement of every still learned child.
 const refundable=excess.filter(p=>p.canRefund===true&&passives.every(child=>child.learned<=0||child.requires.every((i,n)=>i!==p.index||p.learned-1>=child.requireLevels[n])))
  .sort((a,b)=>a.uid.localeCompare(b.uid));
 const activeRefundable=activeExcess.filter(a=>a.canRefund===true&&a.learned>1&&activeTarget[a.uid]>=1)
  .sort((a,b)=>a.uid.localeCompare(b.uid));
 const passiveRefund=refundable[0],activeRefund=activeRefundable[0];
 const refund=passiveRefund?{kind:'passive',skill:passiveRefund.uid,level:passiveRefund.learned,targetLevel:target[passiveRefund.uid]}:
  activeRefund?{kind:'active',skill:activeRefund.uid,level:activeRefund.learned,targetLevel:activeTarget[activeRefund.uid]}:null;
 const totalExcess=excess.reduce((n,p)=>n+p.learned-target[p.uid],0)+activeExcess.reduce((n,a)=>n+a.learned-activeTarget[a.uid],0);
 const next=totalExcess?null:route.find(step=>{
  const actual=(step.kind==='active'?actives:passives).find(p=>p.uid===step.skill);
  const desired=(step.kind==='active'?as:simulated).find(p=>p.uid===step.skill);
  return actual.canLearn===true&&actual.learned<desired.learned;
 })||null;
 return {profile:skillProfile(actives.filter(a=>build.desired.includes(a.uid))),next,candidates:next?[next]:[],
  repair:{pool,reserve,target,activeTarget,controls,remaining,excess:totalExcess,
   passiveExcess:excess.reduce((n,p)=>n+p.learned-target[p.uid],0),
   activeExcess:activeExcess.reduce((n,a)=>n+a.learned-activeTarget[a.uid],0),refund,
   reason:totalExcess?(refund?'refund_branch':'native_refund_blocked'):next?'fill_target':'aligned'}};
}

function skillReallocationPending(snapshot,options={}){
 return (snapshot.characters||[]).some(c=>{
  if(!(snapshot.squad||[]).includes(c.id))return false;
  const r=c.skillPlanning?.repair,controls=r?.controls||{passive:true};
  if(!(controls.passive&&options.modules?.passive!==false&&options.allow_passive_refund!==false||
       controls.active&&options.modules?.active!==false&&options.allow_active_refund===true))return false;
  if(r?.reason==='native_refund_blocked'&&!r.refund)return false;
  return (r?.excess||0)>0||r?.reason==='fill_target'&&c.points>(options.skill_point_reserve||0);
 });
}
function runeUtility(row,context){
 const h=row.header,party=context.characters||[],levelling=party.some(c=>c.level<(context.characterMax||101));
 const economy=/KillExpGain|KillGoods|NormalBoxDropRate|BossBoxDropRate/.test(h);
 const convenience=/Box|MoveSpeed|WaveSkip|ReviveHaste|InventorySlot|StorageTab|SquadSlot/.test(h);
 const combat=!economy&&!convenience;
 let weight=economy?(context.mode==='combat'?75:context.mode==='balanced'?91:98):combat?(context.mode==='combat'?104:context.mode==='balanced'?94:89):80;
 if(h==='SquadSlot'&&(context.squadCount||0)<3)weight=160;
 if(h==='InventorySlot'&&context.inventoryPressure||h==='StorageTab'&&context.storagePressure)weight=150;
 if(h==='KillExpGain'&&!levelling)weight=20;
 if(h==='SkillHaste'&&context.hasCooldown)weight+=8;
 if(h==='AttackSpeed'||h==='BaseAttackPoint'||h==='DamageReduction'||h==='BossMonster')weight+=5;
 if(h==='ShieldBonus'&&!context.hasShield)weight-=20;
 const previous=row.level>0?row.values[row.level-1]||0:0,delta=(row.values[row.level]??previous)-previous;
 return delta>0?weight+Math.min(8,Math.log1p(delta)*2):0;
}
function planRuneInvestment(rows,context={}){
 const byId=new Map(rows.map(r=>[r.id,r])),choices=new Map(),budget=context.budget||{};
 const wallet={201:Math.max(0,(context.soul??Infinity)-(budget.soul_reserve||0)),202:Math.max(0,(context.premium??Infinity)-(budget.premium_reserve??0))};
 const allowed=(goods,amount)=>[201,202].includes(goods)&&Number.isFinite(amount)&&amount>=0&&amount<=wallet[goods]&&(goods!==202||budget.permanent_runes!==false);
 for(const target of rows){
  if(target.level>=target.max)continue;
  const chain=new Map();let valid=true;
  function require(id,path=new Set()){
   if(id<0)return;
   const r=byId.get(id);if(!r||path.has(id)){valid=false;return;}
   if(r.level>0&&id!==target.id)return;
   if(chain.has(id))return;
   chain.set(id,r);path=new Set(path);path.add(id);r.requires.forEach(parent=>require(parent,path));
  }
  require(target.id);if(!valid)continue;
  const cost={201:0,202:0};
  for(const r of chain.values()){
   const goods=r.goods[Math.min(r.level,r.goods.length-1)],price=r.prices[Math.min(r.level,r.prices.length-1)];
   if(![201,202].includes(goods)||!Number.isFinite(price)||price<0||goods===202&&(budget.permanent_runes===false||price>wallet[202])){valid=false;break;}
   cost[goods]+=price;
  }
  if(!valid||cost[202]>wallet[202])continue;
  const utility=runeUtility(target,context);if(utility<=0)continue;
  // Costs stay in their own currency; there is no fabricated exchange rate.
  const score=utility/(1+Math.log1p(cost[201])/14+Math.log1p(cost[202])/5)/Math.sqrt(chain.size);
  for(const r of chain.values())if(r.canLearn){
   const goods=r.goods[Math.min(r.level,r.goods.length-1)],amount=r.prices[Math.min(r.level,r.prices.length-1)];
   if(!allowed(goods,amount))continue;
   const choice={id:r.id,target:target.id,offlineFallback:isOfflineRuneHeader(target.header),reason:r.id===target.id?'direct_benefit':'minimum_prerequisite',score,routeCost:cost,steps:chain.size};
   const previous=choices.get(r.id);
   if(!previous||previous.offlineFallback&&!choice.offlineFallback||previous.offlineFallback===choice.offlineFallback&&previous.score<score)choices.set(r.id,choice);
  }
 }
 return [...choices.values()].sort((a,b)=>Number(a.offlineFallback)-Number(b.offlineFallback)||b.score-a.score||a.steps-b.steps||a.id-b.id);
}

function runeWaiting(rows,context,onlineOnly=false){
 const byId=new Map(rows.map(r=>[r.id,r])),budget=context.budget||{};
 const unfinished=rows.filter(r=>r.level<r.max&&(!onlineOnly||!isOfflineRuneHeader(r.header)));
 // Include unfinished ancestors in the cost explanation, even when they are offline.
 const needed=new Map();
 function include(r,path=new Set()){if(!r||path.has(r.id))return;needed.set(r.id,r);path=new Set(path);path.add(r.id);for(const id of r.requires){const parent=byId.get(id);if(parent&&parent.level<=0)include(parent,path);}}
 unfinished.forEach(r=>include(r));
 const accessible=[...needed.values()].filter(r=>r.requires.every(id=>id<0||(byId.get(id)?.level||0)>0));
 const costs=accessible.map(r=>({goods:r.goods[Math.min(r.level,r.goods.length-1)],amount:r.prices[Math.min(r.level,r.prices.length-1)]}));
 const minimum=goods=>Math.min(Infinity,...costs.filter(c=>c.goods===goods&&Number.isFinite(c.amount)&&c.amount>=0).map(c=>c.amount));
 const soul=minimum(201),premium=minimum(202),soulSpendable=Math.max(0,context.soul-(budget.soul_reserve||0)),stoneSpendable=Math.max(0,context.premium-(budget.premium_reserve??0));
 return {reason:!unfinished.length?(onlineOnly?'online_complete':'runes_complete'):soul<=context.soul&&soul>soulSpendable?'soul_reserve':premium<=context.premium&&premium>stoneSpendable?'premium_reserve':budget.permanent_runes===false&&premium<Infinity?'premium_disabled':soul<Infinity&&soul>soulSpendable?'soul_missing':premium<Infinity&&premium>stoneSpendable?'premium_missing':'native_prerequisite',
  minimumSoul:Number.isFinite(soul)?soul:null,minimumPremium:Number.isFinite(premium)?premium:null,soulSpendable,premiumSpendable:stoneSpendable};
}

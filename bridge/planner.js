function bridgeStrategy(input={}){
 input=input&&typeof input==='object'?input:{};
 const out={},numbers={farm_candidate_count:[5,1,20],farm_level_offset:[1,1,20],inventory_pressure_percent:[80,40,100],recycle_batch:[12,1,12],recycle_normal_tier_gap:[1,1,10],recycle_rare_tier_gap:[2,1,10],skill_point_reserve:[0,0,100],equipment_min_gain_percent:[0,0,100]};
 for(const [key,[fallback,min,max]] of Object.entries(numbers))out[key]=typeof input[key]==='number'&&Number.isFinite(input[key])&&input[key]>=min&&input[key]<=max&&(key==='equipment_min_gain_percent'||Number.isInteger(input[key]))?input[key]:fallback;
 for(const key of ['recommended_actives','allow_active_refund'])out[key]=typeof input[key]==='boolean'?input[key]:true;
 out.rune_priority=['growth','balanced','combat'].includes(input.rune_priority)?input.rune_priority:'growth';
 out.pet_mode=['auto','growth','combat','keep'].includes(input.pet_mode)?input.pet_mode:'auto';return out;
}
function runePriorityBonus(header,mode){
 const combat=['BaseAttackPoint','NormalAttack','HealthPoint','Defense','AttackSpeed','Skill','DamageReduction','SkillHaste'].includes(header);
 const growth=['KillExpGain','KillGoods','BoxAutoOpenNormal','BoxAutoOpenStage'].includes(header);
 return mode==='combat'?(combat?15:growth?-10:0):mode==='balanced'?(combat?6:growth?-3:0):0;
}
let catalogueCache=null;
function catalogue(dm){
 if(catalogueCache)return catalogueCache;
 const recipes=recipeRows(dm).map(r=>Object.fromEntries(['ID','CraftType','FusionType','CraftPart','Grade','FusionCount','MinTier','MaxTier','RequireCubeLevel'].map(n=>[n,read(r,n)]).concat(['MaterialID','MaterialCount'].map(n=>[n,list(read(r,n))]))));
 const stages=list(call(read(dm,'_stageConfigTable'),'get_Datas')).map(p=>read(p,'Level'));
 const tower=list(call(read(dm,'_contentStageTable'),'get_Datas')).filter(p=>read(p,'Category')===1).map(p=>read(p,'Level'));
 const tiers=Array.from({length:10},(_,i)=>({tier:i+1,min:stat('DG.UI.Popup.CubeBasePopupView','TierMinLevel',[i+1]),max:stat('DG.UI.Popup.CubeBasePopupView','TierMaxLevel',[i+1])}));
 catalogueCache={recipes,tiers,normalMax:Math.max(...stages),towerMax:Math.max(0,...tower),maxCharacterLevel:call(dm,'GetCharacterExpMaxLevel')};
 return catalogueCache;
}
function tierForLevel(level,tiers){return tiers.filter(t=>t.min<=level).reduce((best,t)=>Math.max(best,t.tier),1);}
function materialBatch(entries,count){
 const result=[];let remaining=count;
 for(const e of [...entries].sort((a,b)=>(a.place==='storage')-(b.place==='storage')||a.info.tier-b.info.tier)){
  if(remaining<=0)break;result.push(e);remaining-=e.info.count;
 }return remaining<=0?result:[];
}
function fusionPlans(entries,recipes,cubeLevel){
 const groups=new Map();
 for(const e of entries){
  const category=({1:0,2:0,4:1,16:2,8:3})[e.info.kind];if(category===undefined)continue;
  const key=category+':'+e.info.tier+':'+e.info.grade;
  if(!groups.has(key))groups.set(key,{category,tier:e.info.tier,grade:e.info.grade,entries:[]});groups.get(key).entries.push(e);
 }
 return [...groups.values()].flatMap(g=>{
  const fusion=({0:0,1:1,2:3,3:4})[g.category];
  const recipe=recipes.find(r=>r.CraftType===0&&r.FusionType===fusion&&r.Grade===g.grade&&r.MinTier<=g.tier&&r.MaxTier>=g.tier&&r.RequireCubeLevel<=cubeLevel&&r.FusionCount>0);
  if(!recipe)return [];const batch=materialBatch(g.entries,recipe.FusionCount);return batch.length?[{...g,entries:batch,recipe}]:[];
 }).sort((a,b)=>b.entries.filter(e=>e.place==='inventory').length-a.entries.filter(e=>e.place==='inventory').length);
}
function retirementPlans(entries,reserved,tier,options=bridgeStrategy()){
 // Equipment useful to any managed character (including the next level) is excluded upstream.
 return entries.filter(e=>!reserved.has(e.info.uid)&&[1,2].includes(e.info.kind)&&
  ((e.info.grade<=2&&e.info.tier<=tier-options.recycle_normal_tier_gap)||(e.info.grade<=4&&e.info.tier<=tier-options.recycle_rare_tier_gap)))
  .sort((a,b)=>a.info.tier-b.info.tier||a.info.grade-b.info.grade||(a.place==='storage')-(b.place==='storage'));
}
function forgeNeed(im,characters,part,tier){
 let best=0;
 for(const c of characters){
  const set=list(call(call(im,'GetEquipment',[c.id]),'get_Has'));
  const indexes=part===7?[6,7,8,9]:[part-1];
  for(const index of indexes){
   const p=set[index];if(p&&(isTradable(p)||call(p,'get_IsLocked')))continue;
   if(!p)best=Math.max(best,100);else{
    const info=itemInfo(p);if(info.tier<tier)best=Math.max(best,20+(tier-info.tier)*5+6-info.grade);
    else if(info.tier===tier&&info.grade<4)best=Math.max(best,4-info.grade);
   }
  }
 }return best;
}
function inventoryOpportunities(s,dm,im,add,issues,options=bridgeStrategy()){
 const all=containerEntries(im),safe=all.filter(e=>!protectedItem(im,e.item)).map(e=>({...e,info:itemInfo(e.item)}));
 const held=safe.filter(e=>e.place==='inventory'),pool=safe.map(e=>e.info),catalog=catalogue(dm);
 const stamp=keyHash(safe.map(e=>e.info.uid+':'+e.info.count+':'+e.place).join('|'));
 const storage=call(im,'get_Storage'),tabs=Array.from({length:call(storage,'get_TabCount')},(_,i)=>({id:i,open:call(storage,'IsTabUnlocked',[i])}));
 const tradable=all.filter(e=>isTradable(e.item));
 s.storage={count:call(storage,'get_OccupiedCount'),capacity:tabs.filter(t=>t.open).length*call(storage,'get_SlotCountPerTab'),tabs,safeItems:safe.filter(e=>e.place==='storage').length,tradable:tradable.filter(e=>e.place==='storage').length};
 const protectedGear=s.characters.flatMap(c=>list(call(call(im,'GetEquipment',[c.id]),'get_Has')).filter(p=>p&&isTradable(p)));
 s.protection={tradable:tradable.length+protectedGear.length,rule:'immovable'};
 s.catalogue={normalMax:catalog.normalMax,towerMax:catalog.towerMax,characterMax:catalog.maxCharacterLevel,recipes:catalog.recipes.length,fusionRecipes:catalog.recipes.filter(r=>r.CraftType===0).length,forgeRecipes:catalog.recipes.filter(r=>r.CraftType===1).length};
 const needed=new Set();s.equipmentPlanning=[];
 const equipment=equipmentPlans(im,s.characters,s.squad,s.equipmentPlanning,needed,options.equipment_min_gain_percent);
 for(const plan of equipment){needed.add(plan.uid);add('equipment','equip:'+plan.id+':'+plan.uid+':'+plan.slot,'为角色 '+plan.id+' 装备'+(plan.source==='storage'?'仓库':'背包')+'优选装备',99,plan);}
 const cubeLevel=call(call(im,'get_Cube'),'get_Level');
 const candidates=safe.filter(e=>!needed.has(e.info.uid));
 const needItems=new Set(),free=s.inventory.capacity-s.inventory.count;
 function recall(entries,reason,priority){
  for(const e of entries)needItems.add(e.info.uid);
  const item=entries.find(e=>e.place==='storage');
  if(item&&free>0)add('withdraw','withdraw:'+item.info.uid+':'+stamp,'取用仓库物品 · '+reason,priority,{uid:item.info.uid});
 }
 const combineGroups=fusionPlans(candidates,catalog.recipes,cubeLevel);
 for(const plan of combineGroups)for(const e of plan.entries)needItems.add(e.info.uid);
 const group=combineGroups[0];
 if(group){
  const current=group.entries.filter(e=>e.place==='inventory');
  for(const e of group.entries)needItems.add(e.info.uid);
  if(current.reduce((n,e)=>n+e.info.count,0)>=group.recipe.FusionCount)add('combine','combine:'+group.recipe.ID+':'+current.map(e=>e.info.uid+':'+e.info.count).join(','),'合成闲置材料并释放背包',s.inventory.count>=s.inventory.capacity*options.inventory_pressure_percent/100?104:84,{recipe:group.recipe.ID,category:group.category,tier:group.tier,maxGrade:group.grade,allowed:current.map(e=>e.info.uid)});
  else recall(group.entries,'合成配方',103);
 }
 const tier=tierForLevel(Math.max(1,...s.characters.map(c=>c.level)),catalog.tiers);
 const retireTier=tierForLevel(Math.min(...s.characters.map(c=>c.level)),catalog.tiers);
 const forge=catalog.recipes.filter(r=>r.CraftType===1&&r.RequireCubeLevel<=cubeLevel&&r.MinTier<=tier&&r.MaterialID.every((id,i)=>id>0&&safe.filter(e=>e.info.id===id).reduce((n,e)=>n+e.info.count,0)>=r.MaterialCount[i])).map(r=>({...r,need:forgeNeed(im,s.characters,r.CraftPart,Math.min(tier,r.MaxTier))})).filter(r=>r.need>0).sort((a,b)=>b.need-a.need||b.MinTier-a.MinTier||a.ID-b.ID)[0];
 if(forge){
  const materials=forge.MaterialID.flatMap((id,i)=>materialBatch(safe.filter(e=>e.info.id===id),forge.MaterialCount[i]));
  for(const e of materials)needItems.add(e.info.uid);
  const ready=forge.MaterialID.every((id,i)=>held.filter(e=>e.info.id===id).reduce((n,e)=>n+e.info.count,0)>=forge.MaterialCount[i]);
  // Native tier options select recipe bands, not the maximum output tier of a recipe.
  if(ready)add('forge','forge:'+forge.ID+':'+forge.MinTier+':'+materials.map(e=>e.info.uid+':'+e.info.count).join(','),'锻造可用配方范围内的成长装备',85,{recipe:forge.ID,part:forge.CraftPart,tier:forge.MinTier,allowed:materials.filter(e=>e.place==='inventory').map(e=>e.info.uid)});
  else recall(materials,'锻造材料',92);
 }
 const attachments=safe.filter(e=>e.info.kind===16);
 for(const c of s.characters){
  const equipped=list(call(call(im,'GetEquipment',[c.id]),'get_Has')).filter(p=>p&&!isTradable(p)&&!call(p,'get_IsLocked'));
  const target=equipped.find(p=>attachments.some(e=>hasAttachmentSpace(im,p,e.item)));
  if(!target)continue;
  const materials=attachments.filter(e=>hasAttachmentSpace(im,target,e.item)).sort((a,b)=>b.info.grade-a.info.grade||b.info.tier-a.info.tier).slice(0,1),current=materials.filter(e=>e.place==='inventory');
  for(const e of materials)needItems.add(e.info.uid);
  if(current.length)add('refine','refine:'+call(target,'get_Uid')+':'+list(call(target,'get_Sockets')).length+':'+stamp,'为角色 '+c.id+' 镶嵌可用材料',90,{id:c.id,uid:call(target,'get_Uid'),allowed:current.map(e=>e.info.uid)});
  else recall(materials,'装备镶嵌',91);
 }
 const obsolete=retirementPlans(candidates,new Set([...needed,...needItems]),retireTier,options);
 const reclaim=obsolete.filter(e=>e.place==='inventory').slice(0,options.recycle_batch);
 s.recycling={reservedEquipment:needed.size,obsolete:obsolete.length,inventory:obsolete.filter(e=>e.place==='inventory').length,storage:obsolete.filter(e=>e.place==='storage').length,planned:reclaim.length,policy:'three_character_upgrades_then_fusion_then_retirement'};
 if(reclaim.length)add('decompose','decompose:'+reclaim.map(e=>e.info.uid).join(','),'分解淘汰装备，回收材料与灵魂',102,{tier:Math.min(...reclaim.map(e=>e.info.tier)),maxGrade:Math.max(...reclaim.map(e=>e.info.grade)),allowed:reclaim.map(e=>e.info.uid)});
 else if(obsolete.length)recall(obsolete.slice(0,1),'淘汰装备回收',102);
 if(s.inventory.count>=s.inventory.capacity*options.inventory_pressure_percent/100&&!call(storage,'get_IsFull')){
  const retiring=new Set(obsolete.map(e=>e.info.uid));
  const stash=held.filter(e=>!needed.has(e.info.uid)&&!needItems.has(e.info.uid)&&!retiring.has(e.info.uid)).sort((a,b)=>(b.info.kind>=8?10:0)+b.info.grade-((a.info.kind>=8?10:0)+a.info.grade))[0];
  if(stash)add('deposit','deposit:'+stash.info.uid+':'+stamp,'自动存仓，预留战利品空间',101,{uid:stash.info.uid});
 }
 if(s.inventory.count>=s.inventory.capacity)issues.push('背包已满，正在安排存仓、合成、回收与扩容');
}
function openPopups(){return list(invoke(external('UnityEngine','Resources'),nil,'FindObjectsOfTypeAll',[ref(typeObject(classType(klass('DG.UI.OutGamePopup'))))],'System.Type')).filter(p=>call(call(p,'get_gameObject'),'get_activeInHierarchy'));}
const cleanupPopupTypes=new Set(['DG.UI.Popup.HeroPopup','DG.UI.Popup.HeroInfoPopup','DG.UI.Popup.StoragePopup','DG.UI.Popup.CubePopup','DG.UI.Rune.RuneTreePopup']);
function popupPolicy(open){
 const known=new Set([...cleanupPopupTypes,'DG.UI.Popup.MailPopup','DG.UI.Popup.TradePopup','DG.UI.Popup.SteamInventoryPopup','DG.UI.Popup.OfflineRewardPopup']);
 const blocked=open.filter(name=>!known.has(name));
 return {blocked,cleanup:blocked.length?null:open.find(name=>cleanupPopupTypes.has(name))||null,offline:!blocked.length&&open.includes('DG.UI.Popup.OfflineRewardPopup')};
}
// Stable role templates use native skill types and unlock levels, never combat-time scores.
function planActives(rows,slots,level,points,recommended=true){
 const available=rows.filter(r=>r.unlock<=level),types=new Set(available.map(r=>r.type)),desired=[];
 const roles=recommended?(types.has('HitShield')&&types.has('Berserk')?['HitShield','Berserk','PowerAttack']:
  types.has('AttackSpeedStack')?['AttackSpeedStack','Barrage','CriticalBuff','ParabolaShot']:
  types.has('GluttonyKill')?['GluttonyKill','FollowField','GluttonyStrike']:[]):[];
 function add(uid){if(uid&&desired.length<slots.length&&!desired.includes(uid)&&available.some(r=>r.uid===uid))desired.push(uid);}
 for(const type of roles){const candidate=available.find(r=>r.type===type);if(candidate)add(candidate.uid);}
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
function auxiliaryOpportunities(s,dm,im,add,issues){
 const popups=openPopups(),open=popups.map(p=>fullname(A.objectClass(p)));
 const policy=popupPolicy(open);s.automationBlocked=policy.blocked;
 if(policy.blocked.length)issues.push('确认或未知面板正在等待处理，自动化保留窗口并暂停提交');
 const trade=open.some(n=>n.endsWith('TradePopup')||n.endsWith('SteamInventoryPopup'));
 s.trading=trade;
 if(trade)issues.push('交易面板正在使用，物品自动化等待面板关闭');
 const ordinary=popups.find(p=>fullname(A.objectClass(p))===policy.cleanup);
 const offline=popups.find(p=>fullname(A.objectClass(p))==='DG.UI.Popup.OfflineRewardPopup');
 if(policy.offline&&offline&&!read(offline,'_opening'))add('offline_close','offline_close','完成离线收益展示，接续游戏加载',115);
 if(ordinary&&call(call(im,'get_Cube'),'get_IsEmpty')&&!call(call(im,'get_Input'),'get_IsHolding'))add('ui_cleanup','close:'+fullname(A.objectClass(ordinary)),'收起面板，接续自动成长',110,{type:fullname(A.objectClass(ordinary))});
 const server=single('DG.Network.ServerManager'),unread=call(server,'get_MailUnreadCount'),mail=sceneObject('DG.UI.Popup.MailPopup');
 s.mail={unread,loading:mail?read(mail,'_isLoading'):false,claiming:mail?read(mail,'_isClaiming'):false};
 if(mail&&!trade&&s.inventory.count<s.inventory.capacity){
  const active=open.includes('DG.UI.Popup.MailPopup');
  if(unread>0&&!active)add('mail_open','mail_open:'+unread,'读取待领取邮件',77);
  if(active&&!s.mail.loading&&!s.mail.claiming){
   const mails=list(read(mail,'_slots')).map(p=>call(p,'get_Mail')).filter(p=>p&&read(p,'state')==='unread');
   if(mails.length&&call(mail,'IsReceivable'))add('mail_claim','mail_claim:'+mails.map(p=>read(p,'mailId')).sort().join(','),'领取邮件附件',98,{ids:mails.map(p=>read(p,'mailId'))});
   else if(!mails.length)add('mail_close','mail_close','收起已处理的邮箱',76);
  }
 }
 const gm=single('DG.Manager.GameManager'),tower=nextTowerLevel(s.record,s.catalogue.towerMax);
 s.tower={level:tower,max:s.catalogue.towerMax,cleared:s.record.towerMaxCleared,complete:s.record.towerMaxCleared>=s.catalogue.towerMax};
 const ending=call(gm,'IsStageEnding');
 if(s.stage.category===1&&!s.stage.running&&ending){
  const returnLevel=read(gm,'_returnLevel'),returnDifficulty=read(gm,'_returnDifficulty');
  if(returnLevel>0&&call(gm,'CanEnterStage',[0,returnLevel]))add('tower_return','tower_return:'+returnLevel+':'+returnDifficulty,'无限塔结束，返回主线继续成长',112,{level:returnLevel,difficulty:returnDifficulty,freeEntry:call(gm,'GetRequireItemID',[0,returnLevel])<=0});
  else issues.push('无限塔已结束，原生返回关卡暂不可进入，等待同步完成');
 }
 if(s.stage.category===0&&call(gm,'GetRequireItemID',[0,s.stage.level])<=0&&tower>0&&tower<=s.catalogue.towerMax&&call(gm,'CanEnterStage',[1,tower])){
  const ticket=call(gm,'GetRequireItemID',[1,tower]),target=ticket>0?call(im,'FindOccupyTarget',[ticket]):null;
  if(ticket<=0||(target&&!protectedItem(im,target)))add('tower','tower:'+tower+':'+(target?call(target,'get_Uid'):'free'),'挑战无限塔第 '+tower+' 层',79,{level:tower,ticket,clearedBefore:s.record.towerMaxCleared});
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
function progressionOpportunities(s,dm,im,add,issues,options=bridgeStrategy()){
 if(s.stage.category!==0){s.progression={mode:'content',gate:null};return;}
 const gm=single(names.game),levels=list(call(read(dm,'_stageConfigTable'),'get_Datas')).map(p=>read(p,'Level'));
 const next=s.stage.level+1,gate=levels.includes(next)?entranceStatus(gm,im,0,next):null;
 const frontier=s.record.maxCleared||0,bossLevel=frontier+1;
 const boss=levels.includes(bossLevel)?entranceStatus(gm,im,0,bossLevel):null;
 s.progression={mode:s.stage.repeat?'repeat':'push',gate:gate&&!gate.safe?gate:null,boss:boss&&boss.ticket>0?boss:null};
 s.entryTickets=containerEntries(im).map(e=>({place:e.place,...itemInfo(e.item)})).filter(p=>[690100,690200,690300,690400].includes(p.id));
 if(boss&&boss.ticket>0&&boss.safe&&s.stage.level<=frontier&&call(gm,'CanEnterStage',[0,bossLevel])){
  const stage=list(call(read(dm,'_stageTable'),'get_Datas')).find(p=>read(p,'Level')===bossLevel);
  if(stage)add('progress','boss:'+bossLevel+':'+boss.uid,'挑战第 '+bossLevel+' 关 Boss，通关后使用入场券',108,
   {mode:'boss',phase:'travel',level:bossLevel,difficulty:read(stage,'Difficulty'),ticket:boss.ticket,ticketUid:boss.uid,ticketBefore:boss.count});
 }
 if(s.progression.gate){
  issues.push(gate.reason==='protected_ticket'?'下一关的原生入场目标属于受保护物品，当前关练级，保持物品原位':'下一关暂无可用的已确认入场物品，继续积累战力');
  if(!s.stage.repeat)add('progress','guard_gate:'+next+':'+gate.reason,'保留入场物品，当前关继续成长',130,{mode:'guard',repeat:true,freeEntry:true});
 }else if(s.stage.repeat)add('progress','repeat_off','练级完成，恢复主线推进',106,{mode:'push',repeat:false});
 // Farming never spends an entry item, including a native-approved Boss ticket.
 const targets=[...new Set(levels)].filter(level=>Number.isInteger(level)&&level>0&&level<=Math.max(1,s.record.maxCleared-options.farm_level_offset)&&level<=s.record.maxCleared)
  .sort((a,b)=>b-a).filter(level=>call(gm,'GetRequireItemID',[0,level])<=0&&entranceStatus(gm,im,0,level).safe&&call(gm,'CanEnterStage',[0,level])&&call(gm,'CanRepeat',[0,level])).slice(0,options.farm_candidate_count);
 const stages=list(call(read(dm,'_stageTable'),'get_Datas'));
 s.progression.farmCandidates=targets.map(level=>{const stage=stages.find(p=>read(p,'Level')===level);return stage?{level,difficulty:read(stage,'Difficulty')}:null;}).filter(Boolean);
 for(const target of targets)if(!s.stage.repeat||s.stage.level!==target){
  const stage=list(call(read(dm,'_stageTable'),'get_Datas')).find(p=>read(p,'Level')===target);
  const phase=s.stage.level===target?'repeat':'travel';
  if(stage)add('progress','farm:'+target+':'+phase,phase==='travel'?'返回已通关关卡，准备自动练级':'重复已通关关卡，积累等级与材料',107,{mode:'farm',phase,repeat:true,level:target,difficulty:read(stage,'Difficulty'),freeEntry:call(gm,'GetRequireItemID',[0,target])<=0});
 }
}

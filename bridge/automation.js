// A closed action vocabulary. Recompute native prerequisites on the main thread before each action.
const names={data:'DG.Manager.DataManager',items:'DG.Item.Manager.ItemManager',game:'DG.Manager.GameManager',chars:'DG.Manager.CharacterManager',pets:'DG.Manager.PetManager',currency:'DG.Manager.CurrencyManager',drop:'DG.Manager.DropManager',record:'DG.Manager.RecordManager',squad:'DG.Manager.SquadManager',active:'DG.Entity.ActiveSaveStateProvider',passive:'DG.Entity.PassiveSaveStateProvider'};
function enumValueMap(name){return withManagedThread(()=>{const out={};for(const f of iter(A.fields,klass(name))){if(!(A.fieldFlags(f)&64))continue;const v=Memory.alloc(8);A.staticGet(f,v);out[v.readS32()]=utf(A.fieldName(f));}return out;});}
const runeHeaders=enumValueMap('DG.CoreLib.Table.RuneHeader');
const itemKinds=enumValueMap('DG.Item.Enums.ItemKind');
const abilityNames=enumValueMap('DG.Common.Enums.AbilityType');
const activeTypeNames=enumValueMap('DG.InGame.Battle.Enums.Skill.ActiveType');
const recordConditionNames=enumValueMap('DG.Common.Enums.Record.Category');
const contentTypeNames=enumValueMap('DG.Steam.Enums.DLCContentType');
function growthContentRow(manager,config,kind,signature){
 const id=read(config,'ID'),condition=recordConditionNames[read(config,'Condition')],values=list(read(config,'ConditionValue'));
 const unlocked=call(manager,'IsUnlocked',[id],signature);let eligible=condition?condition!=='DLC':null;
 if(condition==='DLC'){
  try{const type=Number(Object.keys(contentTypeNames).find(k=>contentTypeNames[k]===kind));
   eligible=unlocked||call(call(single('DG.Manager.SteamManager'),'get_Dlc'),'IsOpened',[type,String(id)])===true;
  }catch(e){eligible=null;}
 }
 return {id,condition,values,unlocked,eligible};
}
function passiveWeight(name){
 if(/BaseAttackPoint|AttackSpeed/.test(name))return 87;
 if(/SkillHaste|Skill_Rate/.test(name))return 85;
 if(/NormalAttack|Critical/.test(name))return 83;
 if(/HealthPoint|Defense|DamageReduction|Shield/.test(name))return 82;
 return 80;
}
function keyHash(value){let h=2166136261;for(let i=0;i<value.length;i++)h=Math.imul(h^value.charCodeAt(i),16777619);return (h>>>0).toString(16);}
function runeCost(r,level){const ids=list(read(r,'GoodsIDs')),prices=list(read(r,'Price'));return {goods:ids[Math.min(level,ids.length-1)],amount:prices[Math.min(level,prices.length-1)]};}
function equipped(im,id){return list(call(call(im,'GetEquipment',[id]),'get_Has')).flatMap((x,slot)=>x&&!x.isNull()?[{id:call(x,'get_ConfigID'),uid:call(x,'get_Uid'),slot,sockets:list(call(x,'get_Sockets')).length}]:[]);}
function equipmentKey(im,id){return JSON.stringify(equipped(im,id));}
function combatSnapshot(s){
 try{
  const kind='DG.InGame.Battle.Statistics.BattleStatistics',manager=stat(kind,'get_Default'),recording=stat(kind,'get_IsRecording');
  if(!recording)return {available:false,reason:'native_statistics_disabled'};
  function record(p){if(!p||p.isNull())return null;
   const result=call(p,'get_Result'),row={sequence:call(p,'get_Sequence'),level:call(p,'get_Level'),difficulty:call(p,'get_Difficulty'),
    result:({0:'InProgress',1:'Cleared',2:'Failed',3:'Aborted'})[result]||'Unknown',elapsed:call(p,'get_ElapsedSeconds'),
    characters:list(call(p,'get_Records')).map(c=>({id:read(c,'CharacterID'),dealt:read(c,'DamageDealt'),taken:read(c,'DamageTaken'),blocked:read(c,'DamageBlocked'),healed:read(c,'HealDealt')}))};
   if(row.result==='InProgress'&&row.level===s.stage.level&&row.difficulty===s.stage.difficulty)row.elapsed=s.stage.elapsed;
   return row;
  }
  const current=record(call(manager,'get_Current')),count=Math.min(10,call(manager,'get_Count'));
  const records=Array.from({length:count},(_,i)=>record(call(manager,'GetAt',[i]))).filter(Boolean);
  if(current&&!records.some(r=>r.sequence===current.sequence))records.push(current);
  const bm=single('DG.InGame.Battle.Manager.BattleManager');
  const players=list(call(bm,'get_AlivePlayers')).map(p=>({id:call(p,'get_DataID'),
   hp:list(read(call(p,'get_ActualStats'),'_values'))[1],maxHp:read(call(p,'get_BattleNode'),'HealthPoint')}));
  return {available:true,current:current?.level===s.stage.level&&current?.difficulty===s.stage.difficulty?current:null,records,players};
 }catch(error){return {available:false,reason:'native_statistics_unavailable'};}
}

function opportunityScan(input={}){
 const options=bridgeStrategy(input);
 const s=snapshot();s.squad=list(s.squad);s.combat=combatSnapshot(s);
 const dm=single(names.data),im=single(names.items),cm=single(names.chars),pm=single(names.pets),rp=runesProvider(),drop=single(names.drop);
 s.battleReadiness=battleReadiness(s);
 if(s.battleReadiness.known&&!s.battleReadiness.charactersInitialized)return jsonSafe({snapshot:s,actions:[],issues:['等待原生角色与存档初始化，暂缓成长操作']});
 const actions=[],issues=[];const add=(kind,key,label,priority,detail={})=>actions.push({kind,key,label,priority,...detail});
 const roster=list(call(cm,'GetAllCharacters'));
 for(const t of roster){const id=read(t,'ID');if(call(cm,'CanUnlock',[id],'System.Int32'))add('unlock','character:'+id,'解锁角色 '+id,100,{id});}
 s.roster=contentGoal(roster.map(p=>growthContentRow(cm,p,'Character','System.Int32')));
 for(const c of s.characters){
   if(!stat(names.squad,'IsArranged',[c.id])&&stat(names.squad,'GetEmptySlotIndex')>=0)add('formation','arrange:'+c.id,'补齐编队 '+c.id,s.squad.some(id=>id>0)?98:142,{id:c.id});
   const activeSlots=list(call(dm,'GetEquippedActives',[c.id])),equippedActives=new Set(activeSlots.filter(Boolean));
   const activeConfigs=list(call(dm,'GetActiveSkills',[c.id]));
   const activeRows=activeConfigs.map(p=>({uid:read(p,'UniqueID'),type:activeTypeNames[read(p,'Type')]||'Unknown',unlock:read(p,'UnlockLevel'),learned:call(dm,'GetActiveLearnedLevel',[c.id,read(p,'UniqueID')])}));
   const build=planActives(activeRows,activeSlots,c.level,c.points,options.recommended_actives);
   c.activeLoadout=[...equippedActives];c.activePlanning={desired:build.desired,missing:build.missing};c.skills=[];
   if(build.unequip&&options.allow_active_refund){const old=activeConfigs.find(p=>read(p,'UniqueID')===build.unequip.uid);
    if(old&&stat(names.active,'CanRefund',[c.id,ref(old)]))add('skill_unequip','skill_unequip:'+c.id+':'+build.unequip.slot+':'+build.unequip.uid,'为新解锁技能释放可回收的旧技能槽',98,{id:c.id,slot:build.unequip.slot,skill:build.unequip.uid,target:build.unequip.target});
   }
   for(const swap of build.swaps){const config=activeConfigs.find(p=>read(p,'UniqueID')===swap.uid);
    if(stat(names.active,'CanEquip',[c.id,ref(config),swap.slot]))add('skill_equip','skill_equip:'+c.id+':'+swap.slot+':'+swap.uid,'按角色机制更新主动技能组合',102,{id:c.id,skill:swap.uid,slot:swap.slot});
   }
   const passiveConfigs=list(call(dm,'GetPassiveSkills',[c.id])),passiveByIndex=new Map(passiveConfigs.map(p=>[read(p,'Index'),p])),funding=new Map();
   function fundPassive(index,target,weight,path=new Set()){
    if(index<0||path.has(index)||!passiveByIndex.has(index))return;
    path=new Set(path);path.add(index);const p=passiveByIndex.get(index),current=call(dm,'GetPassiveLearnedLevel',[c.id,read(p,'UniqueID')]);
    if(current>=target)return;funding.set(index,Math.max(funding.get(index)||0,weight));
    const levels=list(read(p,'RequireLevel'));list(read(p,'RequireIndex')).forEach((parent,i)=>fundPassive(parent,levels[i],weight+1,path));
   }
   for(const p of passiveConfigs)if(read(p,'UnlockLevel')<=c.level)fundPassive(read(p,'Index'),Math.min(read(p,'MaxLevel'),Math.max(1,Math.ceil(c.level/10))),passiveWeight(abilityNames[read(p,'Ability')]||''));
   for(const type of ['active','passive']){
     const configs=type==='active'?activeConfigs:passiveConfigs;
     for(const config of configs){
       const skill=read(config,'UniqueID'),level=call(dm,type==='active'?'GetActiveLearnedLevel':'GetPassiveLearnedLevel',[c.id,skill]);
       if(level>0)c.skills.push({kind:type,skill,level});
       if(type==='active'&&options.allow_active_refund&&build.refund.includes(skill)&&stat(names.active,'CanRefund',[c.id,ref(config)]))add('skill_refund','skill_refund:'+c.id+':'+skill+':'+level,'回收未装配主动技能点，联动被动成长',97,{id:c.id,skill,level});
       if(c.points>options.skill_point_reserve&&(type==='passive'||build.learn.includes(skill))&&stat(names[type],'CanLearn',[c.id,ref(config)])){
        const priority=type==='active'?(level===0?100:82-level*2):Math.max(passiveWeight(abilityNames[read(config,'Ability')]||'')-level*2,funding.get(read(config,'Index'))||0);
        add(type,type+':'+c.id+':'+skill+':'+level,'学习'+(type==='active'?'主动':'被动')+' '+skill,priority,{id:c.id,skill,level});
       }

     }
   }
 }
 for(const grade of [0,1,2]){
   const count=call(drop,'Count',[grade]);
   if(count>0&&s.inventory.count<s.inventory.capacity)add('box','box:'+grade+':'+s.record.boxes,'开启战利品宝箱',99,{grade,count});
 }
 inventoryOpportunities(s,dm,im,add,issues,options);
 const allRunes=list(call(dm,'GetAllRunes'));
 const byRune=new Map(allRunes.map(r=>[read(r,'ID'),r])),investment=new Map(),runeLevels=new Map(allRunes.map(r=>[read(r,'ID'),call(rp,'GetLevel',[read(r,'ID')])]));
 // Invest in the real prerequisite graph so useful unlocks do not wait forever behind cheap leaves.
 function fund(id,weight,path=new Set()){
   if(path.has(id)||!byRune.has(id))return;path=new Set(path);path.add(id);
   const r=byRune.get(id);if(runeLevels.get(id)>=read(r,'MaxLevel')||(investment.get(id)||0)>=weight)return;
   investment.set(id,Math.max(investment.get(id)||0,weight));
   for(const parent of list(read(r,'NeedRune')))fund(parent,weight-1,path);
 }
 for(const r of allRunes){const header=runeHeaders[read(r,'Header')];if(['SquadSlot','KillExpGain','KillGoods','BoxAutoOpenNormal','InventorySlot'].includes(header))fund(read(r,'ID'),header==='SquadSlot'?96:header==='InventorySlot'?89:87);}
 s.runes={learned:0,total:0,maxed:0,available:0};
 for(const r of allRunes){
   const id=read(r,'ID'),level=runeLevels.get(id),max=read(r,'MaxLevel');s.runes.learned+=level;s.runes.total+=max;if(level>=max)s.runes.maxed++;
   if(!call(rp,'CanLearn',[ref(r)]))continue;
   const cost=runeCost(r,level),header=runeHeaders[read(r,'Header')]||'Rune';s.runes.available++;
   // Both currencies can buy permanent rune progression; the scheduler enforces separate reserves.
   if(![201,202].includes(cost.goods)||!Number.isFinite(cost.amount)||cost.amount<0)continue;
   const weights={SquadSlot:97,BoxAutoOpenNormal:93,BoxAutoOpenStage:92,BoxOpenAll:91,InventorySlot:90,KillExpGain:89,KillGoods:88,ReviveHaste:78,BoxMaxCountNormal:75,BoxMaxCountStage:75,BaseAttackPoint:73,NormalAttack:72,AttackSpeed:72,HealthPoint:71,Defense:69,Skill:70};
   let priority=Math.max(weights[header]||60,investment.get(id)||0);
   if(cost.goods===202)priority=['BaseAttackPoint','NormalAttack','HealthPoint','Defense','AttackSpeed','Skill','DamageReduction','SkillHaste'].includes(header)?94:['SquadSlot','InventorySlot'].includes(header)?95:70;
   priority+=runePriorityBonus(header,options.rune_priority);
   if(s.inventory.count>=s.inventory.capacity*options.inventory_pressure_percent/100&&header==='InventorySlot')priority=100;
   add('rune','rune:'+id+':'+level,'符文成长 · '+header,priority,{id,level,max,header,cost,permanent:true});
 }
 const allPets=list(call(pm,'GetAllPets'));
 for(const p of allPets){const id=read(p,'ID');if(call(pm,'CanUnlock',[id],'System.String'))add('pet_unlock','pet:'+id,'解锁宠物 '+id,91,{id});}
 const unlockedPets=list(call(pm,'get_UnlockedPets')),currentPet=call(pm,'get_EquippedPetID');
 const petWeight=p=>petPreference(abilityNames[read(p,'Ability')]||'',read(p,'Factor'),options.pet_mode==='growth'||options.pet_mode==='auto'&&isFarmingStage(s.stage));
 const preferred=unlockedPets.sort((a,b)=>{const x=petWeight(a),y=petWeight(b);return y.group-x.group||y.value-x.value||(read(b,'ID')===currentPet)-(read(a,'ID')===currentPet)||read(a,'ID').localeCompare(read(b,'ID'));})[0];
 if(options.pet_mode!=='keep'&&preferred&&read(preferred,'ID')!==currentPet)add('pet_equip','pet_equip:'+read(preferred,'ID'),'按当前成长阶段配置已解锁宠物',90,{id:read(preferred,'ID')});
 s.pets={...contentGoal(allPets.map(p=>growthContentRow(pm,p,'Pet','System.String'))),unlocked:call(pm,'get_UnlockedCount'),equipped:call(pm,'get_EquippedPetID')};
 s.achievements={cleared:call(single('DG.Manager.AchievementManager'),'get_ClearedCount'),total:list(call(dm,'get_AchievementConfigs')).length};
 s.characters=s.characters.map(c=>({...c,equipment:equipped(im,c.id),equipmentPlanning:s.equipmentPlanning.find(p=>p.id===c.id)}));
 const squadOrder=new Map(s.squad.map((id,index)=>[id,index]));
 s.characters.sort((a,b)=>(squadOrder.get(a.id)??s.squad.length)-(squadOrder.get(b.id)??s.squad.length)||a.id-b.id);
 auxiliaryOpportunities(s,dm,im,add,issues);
 progressionOpportunities(s,dm,im,add,issues,options);
 for(const action of battleRecoveryPlans(s))add(action.kind,action.key,action.label,action.priority,action);
 if(s.inventory.count>=s.inventory.capacity)issues.push('背包已满：优先合成、扩容与回收后继续开箱');
 const server=single('DG.Network.ServerManager'),reach=read(server,'_reachability');
 s.connection={online:reach&&!reach.isNull()?call(reach,'get_IsOnline'):false,loggedIn:call(server,'get_IsLoggedIn'),trustBlocked:call(server,'get_IsTrustBlocked')};
 if(!s.connection.online)issues.push('游戏原生网络探测为离线：免费练级继续，成长消费等待连接恢复');
 const sync=single('DG.Network.SyncManager');s.sync={busy:call(sync,'get_IsBusy'),queue:call(sync,'get_QueueCount'),blocked:call(sync,'get_IsGrantBlocked'),nextFlushSeconds:Math.max(0,call(sync,'get_SecondsUntilNextFlush'))};
 s.sync.backlogged=s.sync.queue>100;
 if(s.sync.backlogged)issues.push('原生同步积压 '+s.sync.queue+' 条：成长消费等待同步，免费练级与入场保护继续');
 if(s.sync.blocked)issues.push('原生同步当前阻止奖励结算，等待游戏恢复');
 return jsonSafe({snapshot:s,actions:actions.sort((a,b)=>b.priority-a.priority),issues});
}
function executeAction(cmd){
 const options=bridgeStrategy(cmd.strategy),scan=opportunityScan(options);
 if(scan.snapshot.account!==cmd.account)throw Error('account_changed');
 if(scan.snapshot.automationBlocked?.length)return {status:'waiting',reason:'native_modal_active'};
 const action=scan.actions.find(a=>a.key===cmd.key&&a.kind===cmd.kind);
 if(!action)return {status:'stale',reason:'native_prerequisite_changed'};
 if(['tower','progress'].includes(action.kind)&&scan.snapshot.battleReadiness?.known&&(scan.snapshot.battleReadiness.syncRunning||scan.snapshot.battleReadiness.syncPending))return {status:'waiting',reason:'native_squad_transition_active'};
 if(scan.snapshot.sync.blocked)return {status:'waiting',reason:'native_sync_blocked'};
 const recovery=action.freeEntry===true&&(['tower_return','battle_recover'].includes(action.kind)||action.kind==='progress'&&['guard','farm'].includes(action.mode));
 if(scan.snapshot.connection?.online===false&&!recovery)return {status:'waiting',reason:'native_offline'};
 if(scan.snapshot.sync.backlogged&&!recovery)return {status:'waiting',reason:'native_sync_backlog'};
 if(scan.snapshot.trading&&(['equipment','combine','decompose','forge','refine','deposit','withdraw','tower','battle_recover'].includes(action.kind)||action.kind==='progress'&&action.mode==='boss'))return {status:'waiting',reason:'trade_panel_active'};
 if(action.cost){
  const cost=action.cost,allowed=cost.goods===201?scan.snapshot.currencies.soul-cost.amount>=(cmd.soulReserve||0):cost.goods===202&&action.kind==='rune'&&action.permanent&&cmd.permanentRunes===true&&scan.snapshot.currencies.premium-cost.amount>=Math.max(0,cmd.premiumReserve??2);
  if(!Number.isFinite(cost.amount)||cost.amount<0||!allowed)return {status:'waiting',reason:'budget_changed'};
 }
 const dm=single(names.data),im=single(names.items);let ok=false,before,after;
 switch(action.kind){
 case 'offline_close':{const p=sceneObject('DG.UI.Popup.OfflineRewardPopup');if(!p||read(p,'_opening'))return {status:'waiting',reason:'offline_display_not_ready'};call(p,'Hide');return {status:call(call(p,'get_gameObject'),'get_activeInHierarchy')?'pending':'confirmed',source:'settled_offline_display'};}
 case 'ui_cleanup':{if(!cleanupPopupTypes.has(action.type))return {status:'waiting',reason:'popup_not_approved_for_cleanup'};const p=sceneObject(action.type);if(p)call(p,'OnClickClose');return {status:p?'confirmed':'stale',type:action.type};}
 case 'mail_open':{const p=sceneObject('DG.UI.Popup.MailPopup');call(p,'Show');return {status:'confirmed',unread:scan.snapshot.mail.unread};}
 case 'mail_claim':{const p=sceneObject('DG.UI.Popup.MailPopup');call(p,'OnClickReceiveAll');return {status:'pending',ids:action.ids};}
 case 'mail_close':{call(sceneObject('DG.UI.Popup.MailPopup'),'OnClickClose');return {status:'confirmed'};}
 case 'tower':{
  const gm=single(names.game);
  if(scan.snapshot.stage.category!==0||action.level!==nextTowerLevel(scan.snapshot.record,scan.snapshot.catalogue?.towerMax)||!call(gm,'CanEnterStage',[1,action.level]))return {status:'stale',reason:'tower_frontier_changed'};
  const target=action.ticket>0?call(im,'FindOccupyTarget',[action.ticket]):null;
  if(action.ticket>0&&(!target||protectedItem(im,target)))return {status:'waiting',reason:'protected_entrance_ticket'};
  // RepeatStage belongs to the main-stage farming loop. Never inherit it into the tower.
  if(call(gm,'get_RepeatStage'))call(gm,'set_RepeatStage',[false]);
  if(call(gm,'get_RepeatStage')!==false)return {status:'waiting',reason:'tower_repeat_not_disabled'};
  call(gm,'GoToStage',[1,action.level,0]);return {status:'pending',level:action.level};
 }
 case 'tower_return':{
  const gm=single(names.game),level=read(gm,'_returnLevel'),difficulty=read(gm,'_returnDifficulty');
  if(level!==action.level||difficulty!==action.difficulty||!call(gm,'IsStageEnding'))return {status:'stale',reason:'stage_return_state_changed'};
  if(!call(gm,'CanEnterStage',[0,level])||!entranceStatus(gm,im,0,level).safe)return {status:'waiting',reason:'main_stage_not_ready'};
  call(gm,'GoToStage',[0,level,difficulty]);return {status:'pending',level,difficulty};
 }
 case 'deposit':case 'withdraw':return {...guardedStorageAction(action,scan.snapshot.characters),action};
 case 'forge':return {...guardedItemAction(()=>forgeAction(action),scan.snapshot.characters),action};
 case 'refine':return {...guardedItemAction(()=>refineAction(action),scan.snapshot.characters),action};
 case 'combine':case 'decompose':return {...guardedItemAction(()=>cubeAction(action),scan.snapshot.characters),action};
 case 'unlock':ok=call(single(names.chars),'TryUnlock',[action.id]);after=call(single(names.chars),'IsUnlocked',[action.id],'System.Int32');break;
 case 'formation':ok=stat(names.squad,'TryArrange',[action.id]);after=stat(names.squad,'IsArranged',[action.id]);break;
 case 'battle_recover':{
  const gm=single(names.game);
  if(!battleRecoveryPlans(scan.snapshot).some(a=>a.key===action.key))return {status:'stale',reason:'battle_readiness_changed'};
  if(action.mode==='sync')call(gm,'OnSquadChanged');
  else {
   if(call(gm,'GetRequireItemID',[action.category,action.level])>0||!call(gm,'CanEnterStage',[action.category,action.level]))return {status:'waiting',reason:'recovery_entry_not_free'};
   call(gm,'GoToStage',[action.category,action.level,action.difficulty]);
  }
  return {status:'pending',mode:action.mode,source:'native_squad_recovery'};
 }
 case 'box':before=call(single(names.record),'get_BoxOpenCount');ok=call(single(names.drop),'TryOpen',[action.grade]);after=call(single(names.record),'get_BoxOpenCount')>before;break;
 case 'equipment':return {...guardedEquipmentAction(action,scan.snapshot.characters,options.equipment_min_gain_percent),action};
 case 'active':case 'passive':{
   const config=call(dm,action.kind==='active'?'GetActiveByUniqueID':'GetPassiveByUniqueID',[action.skill]);
   ok=stat(names[action.kind],'Learn',[action.id,ref(config)]);
   after=call(dm,action.kind==='active'?'GetActiveLearnedLevel':'GetPassiveLearnedLevel',[action.id,action.skill])>action.level;break;
 }
 case 'skill_unequip':{
   const character=scan.snapshot.characters.find(c=>c.id===action.id),current=call(dm,'GetEquippedActiveAt',[action.id,action.slot]);
   if(current!==action.skill||character?.points>0||character?.activePlanning?.desired.includes(action.skill)||!character?.activePlanning?.missing.includes(action.target))return {status:'stale',reason:'skill_build_changed'};
   const old=call(dm,'GetActiveByUniqueID',[action.skill]);
   if(!stat(names.active,'CanRefund',[action.id,ref(old)]))return {status:'waiting',reason:'skill_points_not_recoverable'};
   ok=stat(names.active,'Unequip',[action.id,action.slot]);after=!call(dm,'GetEquippedActiveAt',[action.id,action.slot]);
   return {status:ok&&after?'confirmed':ok?'pending':'rejected',action,previousSkill:current};
 }
 case 'skill_refund':{
   const config=call(dm,'GetActiveByUniqueID',[action.skill]);
   if(call(dm,'IsActiveEquipped',[action.id,action.skill]))return {status:'stale',reason:'skill_now_equipped'};
   const character=scan.snapshot.characters.find(c=>c.id===action.id);
   if(character?.activePlanning?.desired.includes(action.skill))return {status:'stale',reason:'skill_is_planned'};
   before=character.points;
   ok=stat(names.active,'Refund',[action.id,ref(config)]);
   const level=call(dm,'GetActiveLearnedLevel',[action.id,action.skill]),afterPoints=snapshot().characters.find(c=>c.id===action.id).points;
   return {status:ok&&level<action.level&&afterPoints>before?'confirmed':ok?'pending':'rejected',action,beforePoints:before,afterPoints,afterLevel:level};
 }
 case 'skill_equip':{
   const config=call(dm,'GetActiveByUniqueID',[action.skill]);ok=stat(names.active,'Equip',[action.id,ref(config),action.slot]);after=call(dm,'GetEquippedActiveAt',[action.id,action.slot])===action.skill;break;
 }
 case 'rune':{
   const r=call(dm,'GetRune',[action.id]),rp=runesProvider();ok=call(rp,'Learn',[ref(r)]);after=call(rp,'GetLevel',[action.id])>action.level;break;
 }
 case 'pet_unlock':ok=call(single(names.pets),'TryUnlock',[action.id]);after=call(single(names.pets),'IsUnlocked',[action.id],'System.String');break;
 case 'pet_equip':ok=call(single(names.pets),'Equip',[action.id]);after=call(single(names.pets),'get_EquippedPetID')===action.id;break;
 case 'progress':{
  const gm=single(names.game);
  if(action.mode==='boss'){
   const frontier=scan.snapshot.record.maxCleared||0,entry=entranceStatus(gm,im,0,action.level);
   if(action.level!==frontier+1||action.level<=scan.snapshot.stage.level||!entry.safe||entry.uid!==action.ticketUid||
      entry.ticket!==action.ticket||!call(gm,'CanEnterStage',[0,action.level]))return {status:'stale',reason:'boss_entry_changed'};
   call(gm,'GoToStage',[0,action.level,action.difficulty]);
   return {status:'pending',level:action.level,ticket:entry.ticket,ticketUid:entry.uid,ticketBefore:entry.count,consumeOnClear:true};
  }
  if(action.mode==='farm'){
   if(!entranceStatus(gm,im,0,action.level).safe||!call(gm,'CanEnterStage',[0,action.level])||action.level>scan.snapshot.record.maxCleared)return {status:'stale',reason:'farm_stage_not_safe'};
   if(scan.snapshot.stage.level!==action.level){call(gm,'GoToStage',[0,action.level,action.difficulty]);return {status:'pending',level:action.level};}
   call(gm,'set_RepeatStage',[true]);
  }else call(gm,'set_RepeatStage',[action.repeat]);
  ok=true;after=call(gm,'get_RepeatStage')===action.repeat;break;
 }
 default:throw Error('unsupported_action');
 }
 return jsonSafe({status:ok&&after?'confirmed':ok?'pending':'rejected',action,after});
}
Object.assign(rpc.exports,{opportunities(options){return onMain(()=>opportunityScan(options));},execute(cmd){return onMain(()=>executeAction(cmd));}});

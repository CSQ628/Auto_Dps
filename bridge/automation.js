// A closed action vocabulary. Recompute native prerequisites on the main thread before each action.
const names={data:'DG.Manager.DataManager',items:'DG.Item.Manager.ItemManager',game:'DG.Manager.GameManager',chars:'DG.Manager.CharacterManager',pets:'DG.Manager.PetManager',currency:'DG.Manager.CurrencyManager',drop:'DG.Manager.DropManager',record:'DG.Manager.RecordManager',squad:'DG.Manager.SquadManager',active:'DG.Entity.ActiveSaveStateProvider',passive:'DG.Entity.PassiveSaveStateProvider'};
function enumValueMap(name){return withManagedThread(()=>{const out={};for(const f of iter(A.fields,klass(name))){if(!(A.fieldFlags(f)&64))continue;const v=Memory.alloc(8);A.staticGet(f,v);out[v.readS32()]=utf(A.fieldName(f));}return out;});}
const runeHeaders=enumValueMap('DG.CoreLib.Table.RuneHeader');
const itemKinds=enumValueMap('DG.Item.Enums.ItemKind');
const abilityNames=enumValueMap('DG.Common.Enums.AbilityType');
const activeTypeNames=enumValueMap('DG.InGame.Battle.Enums.Skill.ActiveType');
const skillTriggerNames=enumValueMap('DG.InGame.Battle.Enums.Skill.SkillTriggerType');
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
let runePointCatalogue=null;
function runePointRows(allRunes,rp){
 if(!runePointCatalogue)runePointCatalogue=allRunes.map(r=>({config:r,id:read(r,'ID'),header:runeHeaders[read(r,'Header')]||'Rune',max:read(r,'MaxLevel'),
  requires:list(read(r,'NeedRune')),values:list(read(r,'Values')),goods:list(read(r,'GoodsIDs')),prices:list(read(r,'Price'))}));
 return runePointCatalogue.map(({config,...row})=>({...row,level:call(rp,'GetLevel',[row.id]),canLearn:call(rp,'CanLearn',[ref(config)])}));
}
function runeCost(r,level){const ids=list(read(r,'GoodsIDs')),prices=list(read(r,'Price'));return {goods:ids[Math.min(level,ids.length-1)],amount:prices[Math.min(level,prices.length-1)]};}
function equipped(im,id){return list(call(call(im,'GetEquipment',[id]),'get_Has')).flatMap((x,slot)=>x&&!x.isNull()?[{id:call(x,'get_ConfigID'),uid:call(x,'get_Uid'),slot,sockets:list(call(x,'get_Sockets')).length,revision:equipmentRevision(x)}]:[]);}
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
 const scan=typeof withReadOnlyScan==='function'?withReadOnlyScan(()=>opportunityScanFresh(input)):opportunityScanFresh(input);
 scan.boxFastPath=1;
 if(typeof lastScanPerformance!=='undefined'&&lastScanPerformance&&scan.snapshot)scan.snapshot.bridgePerformance={...lastScanPerformance};
 return scan;
}
function opportunityScanFresh(input={}){
 const options=bridgeStrategy(input);
 const maintenance=maintenanceStatus(),runtime={ready:false,maintenance};
 if(maintenance.active)return {snapshot:null,runtime,actions:[],issues:['服务器维护中，暂停自动成长并等待重连']};
 try{
  const data=single(names.data);
  runtime.ready=call(data,'get_IsSaveLoaded')===true&&call(data,'get_IsMasterTableLoaded')===true;
 }catch(error){runtime.ready=false;}
 if(!runtime.ready)return {snapshot:null,runtime,actions:[],issues:['等待游戏登录与存档加载']};
 const s=snapshot();s.squad=list(s.squad);s.combat=combatSnapshot(s);
 const dm=single(names.data),im=single(names.items);
 let rp,runeProviderError;try{rp=refreshRunesProvider();}catch(error){runeProviderError=error;}
 s.battleReadiness=battleReadiness(s);
 s.entryState=stageEntryState(s);
 if(s.battleReadiness.known&&!s.battleReadiness.charactersInitialized)return jsonSafe({snapshot:s,runtime,actions:[],issues:['等待原生角色与存档初始化，暂缓成长操作']});
 const actions=[],issues=[];const add=(kind,key,label,priority,detail={})=>{const a={kind,key,label,priority,...detail};if(detailedActionAllowed(a,options))actions.push(a);};
 const section=(name,fn,dependencies=[])=>collectOpportunitySection(s,add,issues,name,fn,dependencies);
 section('characters',(s,add,issues)=>{
 const cm=single(names.chars);
 const roster=list(call(cm,'GetAllCharacters'));
 for(const t of roster){const id=read(t,'ID');if(call(cm,'CanUnlock',[id],'System.Int32'))add('unlock','character:'+id,'解锁角色 '+id,100,{id});}
 s.roster=contentGoal(roster.map(p=>growthContentRow(cm,p,'Character','System.Int32')));
 // Stable catalogue range determines frontline role, never list order or who is alive.
 const positions=skillPartyPosition(s.squad,s.characters.map(c=>{
  try{const config=roster.find(p=>read(p,'ID')===c.id),stats=config?call(dm,'GetBaseStat',[read(config,'BaseStat')]):null;
   return {id:c.id,baseRange:stats?read(stats,'Range'):null};
  }catch(error){return {id:c.id,baseRange:null};}
 }));
 for(const c of s.characters){
   if(!stat(names.squad,'IsArranged',[c.id])&&stat(names.squad,'GetEmptySlotIndex')>=0)add('formation','arrange:'+c.id,'补齐编队 '+c.id,s.squad.some(id=>id>0)?98:142,{id:c.id});
   const activeSlots=list(call(dm,'GetEquippedActives',[c.id])),equippedActives=new Set(activeSlots.filter(Boolean));
   const activeConfigs=list(call(dm,'GetActiveSkills',[c.id]));
   const activeRows=activeConfigs.map(p=>({uid:read(p,'UniqueID'),type:activeTypeNames[read(p,'Type')]||'Unknown',trigger:skillTriggerNames[read(p,'TriggerType')]||'Unknown',triggerValue:read(p,'TriggerValue'),cooldown:read(p,'Cooldown'),cooldownIncrement:read(p,'LevelUpCooldown'),max:read(p,'MaxLevel'),increments:list(read(p,'LevelUpFactor')),subIncrements:list(read(p,'LevelUpSubFactor')),canLearn:stat(names.active,'CanLearn',[c.id,ref(p)]),canRefund:stat(names.active,'CanRefund',[c.id,ref(p)]),unlock:read(p,'UnlockLevel'),learned:call(dm,'GetActiveLearnedLevel',[c.id,read(p,'UniqueID')])}));
   const learnableRows=options.active_learn?activeRows:activeRows.filter(r=>r.learned>0);
   const build=options.active_equip?planActives(learnableRows,activeSlots,c.level,c.points,options.recommended_actives&&options.modules.active!==false):{desired:activeSlots.filter(Boolean),missing:[],refund:[],swaps:[],unequip:null};
   c.activeLoadout=[...equippedActives];c.activePlanning={desired:build.desired,missing:build.missing,triggers:build.desired.map(uid=>{const row=activeRows.find(r=>r.uid===uid);return {skill:uid,type:row.type,trigger:row.trigger,value:row.triggerValue};})};c.skills=[];
   if(build.unequip&&options.allow_active_refund){const old=activeConfigs.find(p=>read(p,'UniqueID')===build.unequip.uid);
    if(old&&stat(names.active,'CanRefund',[c.id,ref(old)]))add('skill_unequip','skill_unequip:'+c.id+':'+build.unequip.slot+':'+build.unequip.uid,'为新解锁技能释放可回收的旧技能槽',98,{id:c.id,slot:build.unequip.slot,skill:build.unequip.uid,target:build.unequip.target});
   }
   for(const swap of build.swaps){const config=activeConfigs.find(p=>read(p,'UniqueID')===swap.uid);
    if(stat(names.active,'CanEquip',[c.id,ref(config),swap.slot]))add('skill_equip','skill_equip:'+c.id+':'+swap.slot+':'+swap.uid,'按角色机制更新主动技能组合',102,{id:c.id,skill:swap.uid,slot:swap.slot});
   }
   const passiveConfigs=list(call(dm,'GetPassiveSkills',[c.id]));
   const passiveRows=passiveConfigs.map(p=>({uid:read(p,'UniqueID'),index:read(p,'Index'),unlock:read(p,'UnlockLevel'),max:read(p,'MaxLevel'),
    learned:call(dm,'GetPassiveLearnedLevel',[c.id,read(p,'UniqueID')]),ability:abilityNames[read(p,'Ability')]||'',trigger:skillTriggerNames[read(p,'TriggerType')],
    apply:read(p,'ApplyType'),factor:read(p,'Factor'),increment:read(p,'LevelUpFactor'),requires:list(read(p,'RequireIndex')),requireLevels:list(read(p,'RequireLevel')),canLearn:stat(names.passive,'CanLearn',[c.id,ref(p)]),canRefund:stat(names.passive,'CanRefund',[c.id,ref(p)])}));
   const position={known:positions.known,frontline:positions.known?positions.frontline===c.id:null,range:positions.ranges[c.id]??null,reason:positions.reason};
   const skillPlan=planSkillReallocation(activeRows,passiveRows,build,c.level,c.points,{arranged:s.squad.includes(c.id),frontline:position.frontline,positionKnown:position.known},options);
   c.skillPlanning={profile:skillPlan.profile,next:skillPlan.next,pointReserve:options.skill_point_reserve,policy:'finite_role_allocation',position,repair:skillPlan.repair};
   if(skillPlan.repair?.reason==='position_unknown')issues.push('等待角色站位数据，继续当前战斗与其他成长');
   if(skillPlan.repair?.refund){const r=skillPlan.repair.refund,kind=r.kind==='active'?'skill_refund':'passive_refund';
    add(kind,kind+':'+c.id+':'+r.skill+':'+r.level,r.kind==='active'?'保留核心技能，回收超出职业目标的主动升级点':'从末端回收偏离职业路线的被动点',109,{id:c.id,skill:r.skill,level:r.level,targetLevel:r.targetLevel,repair:true});}
   for(const type of ['active','passive']){
     const configs=type==='active'?activeConfigs:passiveConfigs;
     for(const config of configs){
       const skill=read(config,'UniqueID'),level=call(dm,type==='active'?'GetActiveLearnedLevel':'GetPassiveLearnedLevel',[c.id,skill]);
       if(level>0)c.skills.push({kind:type,skill,level});
       if(type==='active'&&options.allow_active_refund&&build.refund.includes(skill)&&stat(names.active,'CanRefund',[c.id,ref(config)]))add('skill_refund','skill_refund:'+c.id+':'+skill+':'+level,'回收未装配主动技能点，联动被动成长',97,{id:c.id,skill,level});
       if(c.points>options.skill_point_reserve&&skillPlan.next?.kind===type&&skillPlan.next.skill===skill){
        add(type,type+':'+c.id+':'+skill+':'+level,'学习'+(type==='active'?'核心主动':'职业被动')+' '+skill,skillPlan.repair?.reason==='fill_target'?109:skillPlan.next.reason==='core_unlock'?100:86,
         {id:c.id,skill,level,planningReason:skillPlan.next.reason,targetSkill:skillPlan.next.target});
       }

     }
   }
 }
 });
 section('boxes',(s,add)=>boxOpportunities(s,single(names.drop),add,options));
 section('workshop',(s,add,issues)=>inventoryOpportunities(s,dm,im,add,issues,options),['characters']);
 section('sorting',(s,add)=>{
 if(options.auto_sort_items)for(const plan of itemSortPlans(im,options.modules.storage,options.sort_cooldown_seconds))if(options[plan.place==='inventory'?'sort_inventory':'sort_storage'])add('sort',plan.key,'物品处理完成，使用系统排序整理'+(plan.place==='inventory'?'背包':'仓库第 '+(plan.tab+1)+' 页'),20,plan);
 });
 section('runes',(s,add)=>{
 if(runeProviderError)throw runeProviderError;
 const allRunes=list(call(dm,'GetAllRunes'));
 const runeRows=runePointRows(allRunes,rp);
 const party=s.characters.filter(c=>s.squad.includes(c.id)),selected=party.flatMap(c=>c.activePlanning?.triggers||[]);
 const runeContext={mode:options.rune_priority,characters:party,characterMax:s.catalogue?.characterMax,squadCount:s.squad.filter(id=>id>0).length,
  inventoryPressure:s.inventory.count>=s.inventory.capacity*options.inventory_pressure_percent/100,storagePressure:s.storage?.pressure===true,
  hasCooldown:party.some(c=>list(call(dm,'GetActiveSkills',[c.id])).some(p=>c.activePlanning?.desired.includes(read(p,'UniqueID'))&&read(p,'Cooldown')>0)),
  hasShield:selected.some(r=>/Shield/.test(r.type)),soul:s.currencies.soul,premium:s.currencies.premium,budget:options.budget,controls:options};
 const runePlan=planRuneInvestment(runeRows,runeContext),runeRanks=new Map(runePlan.map((p,i)=>[p.id,{...p,priority:p.offlineFallback?1:94-Math.min(40,i)*.1}]));
 s.runes={...runeProgress(runeRows),available:runeRows.filter(r=>r.canLearn).length,availableOnline:runeRows.filter(r=>!isOfflineRuneHeader(r.header)&&r.canLearn).length,
  planning:{mode:options.rune_priority,policy:'online_then_offline_fallback',onlineWaiting:runeWaiting(runeRows,runeContext,true),next:runePlan[0]||null,candidates:runePlan.length,waiting:runePlan.length?null:runeWaiting(runeRows,runeContext)}};
 for(const r of runeRows){
  const planned=runeRanks.get(r.id);if(!planned)continue;
  const cost={goods:r.goods[Math.min(r.level,r.goods.length-1)],amount:r.prices[Math.min(r.level,r.prices.length-1)]};
  add('rune','rune:'+r.id+':'+r.level,'刻印成长 · '+r.header,planned.priority,
   {id:r.id,level:r.level,max:r.max,header:r.header,cost,permanent:true,planningReason:planned.reason,targetRune:planned.target,offlineFallback:planned.offlineFallback,runeGroup:runeGroup(r.header)});
 }
 },['characters']);
 section('pets',(s,add)=>{
 const pm=single(names.pets);
 const allPets=list(call(pm,'GetAllPets'));
 for(const p of allPets){const id=read(p,'ID');if(call(pm,'CanUnlock',[id],'System.String'))add('pet_unlock','pet:'+id,'解锁宠物 '+id,91,{id});}
 const unlockedPets=list(call(pm,'get_UnlockedPets')),currentPet=call(pm,'get_EquippedPetID');
 const ownedEffects=unlockedPets.map(p=>({id:read(p,'ID'),ability:abilityNames[read(p,'Ability')]||String(read(p,'Ability')),factor:read(p,'Factor')})).sort((a,b)=>a.id.localeCompare(b.id));
 const preferred=planPetFollower(ownedEffects,currentPet,options.pet_mode);
 if(preferred&&preferred!==currentPet)add('pet_equip','pet_equip:'+preferred,'选择已解锁的跟随宠物（全部拥有加成已生效）',70,{id:preferred});
 s.pets={...contentGoal(allPets.map(p=>growthContentRow(pm,p,'Pet','System.String'))),unlocked:call(pm,'get_UnlockedCount'),equipped:currentPet,ownedEffects,effectsPolicy:'all_owned'};
 });
 section('achievements',s=>{
 s.achievements={cleared:call(single('DG.Manager.AchievementManager'),'get_ClearedCount'),total:list(call(dm,'get_AchievementConfigs')).length};
 });
 section('equipment',s=>{
 s.characters=s.characters.map(c=>({...c,equipment:equipped(im,c.id),equipmentPlanning:s.equipmentPlanning?.find(p=>p.id===c.id)}));
 s.equipmentContext=equipmentContext(s);
 });
 const squadOrder=new Map(s.squad.map((id,index)=>[id,index]));
 s.characters.sort((a,b)=>(squadOrder.get(a.id)??s.squad.length)-(squadOrder.get(b.id)??s.squad.length)||a.id-b.id);
 if(!section('auxiliary',(s,add,issues)=>auxiliaryOpportunities(s,dm,im,add,issues,options))){
  s.automationBlocked=['native_panel_state_unavailable'];s.experienceBlocked=true;s.manualBlockedKinds=[];
 }
 section('progression',(s,add,issues)=>progressionOpportunities(s,dm,im,add,issues,options));
 section('recovery',(s,add)=>{for(const action of battleRecoveryPlans(s,options))add(action.kind,action.key,action.label,action.priority,action);});
 if(s.inventory.count>=s.inventory.capacity&&!issues.some(message=>/^背包(?:与仓库)?已满/.test(message)))issues.push('背包已满（'+s.inventory.count+'/'+s.inventory.capacity+'格）：正在重试读取整理条件，其他成长继续');
 const server=single('DG.Network.ServerManager'),reach=read(server,'_reachability');
 s.connection={online:reach&&!reach.isNull()?call(reach,'get_IsOnline'):false,loggedIn:call(server,'get_IsLoggedIn'),trustBlocked:call(server,'get_IsTrustBlocked')};
 if(!s.connection.online)issues.push('游戏原生网络探测为离线：免费练级继续，成长消费等待连接恢复');
 const sync=single('DG.Network.SyncManager');s.sync={busy:call(sync,'get_IsBusy'),queue:call(sync,'get_QueueCount'),blocked:call(sync,'get_IsGrantBlocked'),nextFlushSeconds:Math.max(0,call(sync,'get_SecondsUntilNextFlush'))};
 s.sync.backlogged=s.sync.queue>100;
 if(s.sync.backlogged)issues.push('原生同步积压 '+s.sync.queue+' 条：成长消费等待同步，免费练级与入场保护继续');
 if(s.sync.blocked)issues.push('原生同步当前阻止奖励结算，等待游戏恢复');
 return jsonSafe({snapshot:s,runtime,storageRecoveryBarrier:1,actions:actions.filter(a=>!(s.manualBlockedKinds||[]).includes(a.kind)&&planningActionAllowed(s,a)).sort((a,b)=>b.priority-a.priority),issues});
}
function executeAction(cmd){
 if(cmd.kind==='maintenance_exit'){
  const maintenance=maintenanceStatus();
  if(!maintenance.active||!maintenance.canExit)return {status:'waiting',reason:'maintenance_exit_not_authorized'};
  call(sceneObject('DG.UI.ConfirmPopup'),'OnClickConfirm');
  return {status:'submitted',source:'native_maintenance_exit'};
 }
 const options=bridgeStrategy(cmd.strategy),scan=opportunityScan(options);
 if(scan.runtime?.maintenance?.active)return {status:'waiting',reason:'native_maintenance_active'};
 if(!scan.snapshot)return {status:'waiting',reason:'native_data_loading'};
 if(scan.snapshot.account!==cmd.account)throw Error('account_changed');
 if(scan.snapshot.automationBlocked?.length)return {status:'waiting',reason:'native_modal_active'};
 const action=scan.actions.find(a=>a.key===cmd.key&&a.kind===cmd.kind);
 if(!action)return {status:'stale',reason:'native_prerequisite_changed'};
 if(action.kind==='progress'&&action.mode==='farm'&&action.phase==='travel'&&!frontierFarmReturnAllowed(scan.snapshot,action,cmd,options))return {status:'waiting',reason:'frontier_battle_in_progress'};
 if(action.kind==='equipment'&&!equipmentContextMatches(cmd,action,scan.snapshot))return {status:'stale',reason:'equipment_context_changed'};
 if(scan.snapshot.manualBlockedKinds?.includes(action.kind)||panelActionBlocked(action.kind,scan.snapshot.manualPanels))return {status:'waiting',reason:'manual_panel_conflict'};
 if(['tower','progress'].includes(action.kind)&&scan.snapshot.battleReadiness?.known&&(scan.snapshot.battleReadiness.syncRunning||scan.snapshot.battleReadiness.syncPending))return {status:'waiting',reason:'native_squad_transition_active'};
 if(skillReallocationPending(scan.snapshot,options)&&(action.kind==='tower'||action.kind==='progress'&&['push','boss'].includes(action.mode)))return {status:'waiting',reason:'skills_reallocating'};
 if(scan.snapshot.sync.blocked)return {status:'waiting',reason:'native_sync_blocked'};
 const recovery=action.freeEntry===true&&(['tower_return','battle_recover'].includes(action.kind)||action.kind==='progress'&&['guard','farm'].includes(action.mode));
 if(scan.snapshot.connection?.online===false&&!recovery)return {status:'waiting',reason:'native_offline'};
 if(scan.snapshot.sync.backlogged&&!recovery)return {status:'waiting',reason:'native_sync_backlog'};
 if(scan.snapshot.trading&&(['equipment','combine','decompose','forge','refine','deposit','withdraw','sort','tower','battle_recover'].includes(action.kind)||action.kind==='progress'&&action.mode==='boss'))return {status:'waiting',reason:'trade_panel_active'};
 if(action.cost){
  const cost=action.cost,allowed=cost.goods===201?scan.snapshot.currencies.soul-cost.amount>=(cmd.soulReserve||0):cost.goods===202&&action.kind==='rune'&&action.permanent&&cmd.permanentRunes===true&&scan.snapshot.currencies.premium-cost.amount>=Math.max(0,cmd.premiumReserve??0);
  if(!Number.isFinite(cost.amount)||cost.amount<0||!allowed)return {status:'waiting',reason:'budget_changed'};
 }
 const dm=single(names.data),im=single(names.items);let ok=false,before,after;
 switch(action.kind){
 case 'offline_close':{const p=sceneObject('DG.UI.Popup.OfflineRewardPopup');if(!p||read(p,'_opening'))return {status:'waiting',reason:'offline_display_not_ready'};call(p,'Hide');return {status:call(call(p,'get_gameObject'),'get_activeInHierarchy')?'pending':'confirmed',source:'settled_offline_display'};}
 case 'ui_cleanup':{
  if(options.preserve_open_panels)return {status:'waiting',reason:'user_popup_open'};
  if(!cleanupPopupTypes.has(action.type))return {status:'waiting',reason:'popup_not_approved_for_cleanup'};
  const p=sceneObject(action.type);
  if(!p||!call(call(p,'get_gameObject'),'get_activeInHierarchy'))return {status:'stale',reason:'popup_already_closed',type:action.type};
  call(p,'OnClickClose');
  return call(call(p,'get_gameObject'),'get_activeInHierarchy')
   ?{status:'waiting',reason:'popup_close_not_complete',type:action.type}
   :{status:'confirmed',type:action.type};
 }
 case 'mail_open':{const p=sceneObject('DG.UI.Popup.MailPopup');call(p,'Show');return {status:'confirmed',unread:scan.snapshot.mail.unread};}
 case 'mail_claim':{
  const p=sceneObject('DG.UI.Popup.MailPopup'),claims=mailClaimObservation();
  if(!claims.available)return {status:'waiting',reason:'native_mail_observer_unavailable'};
  if(!p||read(p,'_isLoading')||read(p,'_isClaiming')||!call(p,'IsReceivable'))return {status:'waiting',reason:'native_mail_busy'};
  const ids=list(read(p,'_slots')).map(p=>call(p,'get_Mail')).filter(p=>p&&read(p,'state')==='unread').map(p=>read(p,'mailId')).sort();
  if(JSON.stringify(ids)!==JSON.stringify([...action.ids].sort()))return {status:'stale',reason:'native_mail_list_changed'};
  call(p,'OnClickReceiveAll');return {status:'pending',ids:action.ids};
 }
 case 'mail_close':{call(sceneObject('DG.UI.Popup.MailPopup'),'OnClickClose');return {status:'confirmed'};}
 case 'tower':{
  const gm=single(names.game);
   const stage=scan.snapshot.stage,frontier=scan.snapshot.record.maxCleared;
   const normalMax=scan.snapshot.catalogue?.normalMax;
  if(stage.category!==0||stage.running!==false||!call(gm,'IsStageEnding')||!Number.isInteger(stage.level)||
      !Number.isInteger(frontier)||!Number.isInteger(normalMax)||normalMax<=0||frontier<normalMax||stage.level>frontier||
      action.level!==nextTowerLevel(scan.snapshot.record,scan.snapshot.catalogue?.towerMax)||
     !call(gm,'CanEnterStage',[1,action.level]))return {status:'stale',reason:'tower_frontier_changed'};
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
 case 'sort':return {...sortItemsAction(action,scan.snapshot.characters),action};
 case 'forge':return {...guardedItemAction(()=>forgeAction(action),scan.snapshot.characters),action};
 case 'refine':return {...guardedItemAction(()=>refineAction(action),scan.snapshot.characters,[],[action.uid],[],action.uid,action.allowTradableTarget),action};
 case 'combine':return {...guardedItemAction(()=>cubeAction(action),scan.snapshot.characters),action};
 case 'decompose':return {...guardedRecycleAction(action,scan.snapshot.characters),action};
 case 'unlock':ok=call(single(names.chars),'TryUnlock',[action.id]);after=call(single(names.chars),'IsUnlocked',[action.id],'System.Int32');break;
 case 'formation':ok=stat(names.squad,'TryArrange',[action.id]);after=stat(names.squad,'IsArranged',[action.id]);break;
 case 'battle_recover':{
  const gm=single(names.game);
  if(!battleRecoveryPlans(scan.snapshot,options).some(a=>a.key===action.key))return {status:'stale',reason:'battle_readiness_changed'};
  if(action.mode==='sync')call(gm,'OnSquadChanged');
  else {
   if(call(gm,'GetRequireItemID',[action.category,action.level])>0||!call(gm,'CanEnterStage',[action.category,action.level]))return {status:'waiting',reason:'recovery_entry_not_free'};
   call(gm,'GoToStage',[action.category,action.level,action.difficulty]);
  }
  return {status:'pending',mode:action.mode,source:'native_squad_recovery'};
 }
 case 'box':{
  const drop=single(names.drop),record=single(names.record);
  const queueBefore=call(drop,'Count',[action.grade]),recordBefore=call(record,'get_BoxOpenCount');
  if(queueBefore<=0)return {status:'stale',reason:'box_queue_changed'};
  if(scan.snapshot.inventory.count>=scan.snapshot.inventory.capacity)return {status:'waiting',reason:'inventory_full'};
  const accepted=call(drop,'TryOpen',[action.grade]);
  const queueAfter=call(drop,'Count',[action.grade]),recordAfter=call(record,'get_BoxOpenCount');
  const status=accepted===true&&recordAfter>recordBefore?'confirmed':accepted===true?'pending':'rejected';
  return {status,reason:status==='confirmed'?null:accepted===true?'box_result_unconfirmed':'native_box_rejected',
   grade:action.grade,accepted,queueBefore,queueAfter,recordBefore,recordAfter};
 }
 case 'equipment':return {...guardedEquipmentAction(action,scan.snapshot.characters,options.equipment_min_gain_percent),action};
 case 'active':case 'passive':{
   const config=call(dm,action.kind==='active'?'GetActiveByUniqueID':'GetPassiveByUniqueID',[action.skill]);
   const getter=action.kind==='active'?'GetActiveLearnedLevel':'GetPassiveLearnedLevel',beforeLevel=call(dm,getter,[action.id,action.skill]);
   const character=scan.snapshot.characters.find(c=>c.id===action.id),beforePoints=character.points;
   if(beforeLevel!==action.level||beforePoints<=options.skill_point_reserve)return {status:'stale',reason:'skill_level_changed'};
   const accepted=stat(names[action.kind],'Learn',[action.id,ref(config)]),afterLevel=call(dm,getter,[action.id,action.skill]);
   const afterPoints=snapshot().characters.find(c=>c.id===action.id).points,exact=afterLevel===beforeLevel+1&&afterPoints===beforePoints-1;
   return {status:exact?'confirmed':accepted?'pending':'rejected',reason:exact?null:'skill_learn_unconfirmed',action,accepted,beforeLevel,afterLevel,beforePoints,afterPoints};
 }
 case 'skill_unequip':{
   const character=scan.snapshot.characters.find(c=>c.id===action.id),current=call(dm,'GetEquippedActiveAt',[action.id,action.slot]);
   if(current!==action.skill||character?.points>0||character?.activePlanning?.desired.includes(action.skill)||!character?.activePlanning?.missing.includes(action.target))return {status:'stale',reason:'skill_build_changed'};
   const old=call(dm,'GetActiveByUniqueID',[action.skill]);
   if(!stat(names.active,'CanRefund',[action.id,ref(old)]))return {status:'waiting',reason:'skill_points_not_recoverable'};
   ok=stat(names.active,'Unequip',[action.id,action.slot]);after=!call(dm,'GetEquippedActiveAt',[action.id,action.slot]);
   return {status:ok&&after?'confirmed':ok?'pending':'rejected',action,previousSkill:current};
 }
 case 'passive_refund':{
   const character=scan.snapshot.characters.find(c=>c.id===action.id),repair=character?.skillPlanning?.repair;
   if(options.modules.passive===false||!options.allow_passive_refund||repair?.refund?.skill!==action.skill||repair.refund.level!==action.level||repair.target[action.skill]>=action.level)return {status:'stale',reason:'skill_build_changed'};
   const config=call(dm,'GetPassiveByUniqueID',[action.skill]),beforeLevel=call(dm,'GetPassiveLearnedLevel',[action.id,action.skill]),beforePoints=character.points;
   if(beforeLevel!==action.level)return {status:'stale',reason:'skill_level_changed'};
   if(!stat(names.passive,'CanRefund',[action.id,ref(config)]))return {status:'waiting',reason:'native_refund_blocked'};
   const accepted=stat(names.passive,'Refund',[action.id,ref(config)]),afterLevel=call(dm,'GetPassiveLearnedLevel',[action.id,action.skill]);
   const afterPoints=snapshot().characters.find(c=>c.id===action.id).points;
   const exact=afterLevel===beforeLevel-1&&afterPoints===beforePoints+1;
   return {status:exact?'confirmed':accepted?'pending':'rejected',reason:exact?null:'skill_refund_unconfirmed',action,accepted,beforeLevel,afterLevel,beforePoints,afterPoints};
 }
 case 'skill_refund':{
   if(options.modules.active===false||!options.allow_active_refund)return {status:'stale',reason:'skill_build_changed'};
   const config=call(dm,'GetActiveByUniqueID',[action.skill]),character=scan.snapshot.characters.find(c=>c.id===action.id);
   const beforeLevel=call(dm,'GetActiveLearnedLevel',[action.id,action.skill]),beforePoints=character.points;
   if(action.repair){
    const repair=character?.skillPlanning?.repair,r=repair?.refund;
    if(r?.kind!=='active'||r.skill!==action.skill||r.level!==beforeLevel||beforeLevel<=1||
       repair.activeTarget?.[action.skill]<1||!(repair.activeTarget?.[action.skill]<beforeLevel))return {status:'stale',reason:'skill_build_changed'};
   }else{
    if(call(dm,'IsActiveEquipped',[action.id,action.skill]))return {status:'stale',reason:'skill_now_equipped'};
    if(character?.activePlanning?.desired.includes(action.skill))return {status:'stale',reason:'skill_is_planned'};
   }
   if(beforeLevel!==action.level)return {status:'stale',reason:'skill_level_changed'};
   if(!stat(names.active,'CanRefund',[action.id,ref(config)]))return {status:'waiting',reason:'native_refund_blocked'};
   const accepted=stat(names.active,'Refund',[action.id,ref(config)]),afterLevel=call(dm,'GetActiveLearnedLevel',[action.id,action.skill]);
   const afterPoints=snapshot().characters.find(c=>c.id===action.id).points;
   const exact=afterLevel===beforeLevel-1&&afterPoints===beforePoints+1;
   return {status:exact?'confirmed':accepted?'pending':'rejected',reason:exact?null:'skill_refund_unconfirmed',action,accepted,beforeLevel,afterLevel,beforePoints,afterPoints};
 }
 case 'skill_equip':{
   const config=call(dm,'GetActiveByUniqueID',[action.skill]);ok=stat(names.active,'Equip',[action.id,ref(config),action.slot]);after=call(dm,'GetEquippedActiveAt',[action.id,action.slot])===action.skill;break;
 }
 case 'rune':{
   // Use the save provider from this execution's fresh scan, never a UI cache.
   const rp=runesProvider(),r=call(dm,'GetRune',[action.id]);
   const beforeLevel=call(rp,'GetLevel',[action.id]);
   if(beforeLevel!==action.level||beforeLevel>=read(r,'MaxLevel'))return {status:'stale',reason:'rune_level_changed'};
   if(!call(rp,'CanLearn',[ref(r)]))return {status:'waiting',reason:'native_rune_not_ready'};
   const cost=runeCost(r,beforeLevel),currency=single(names.currency);
   if(!action.cost||cost.goods!==action.cost.goods||cost.amount!==action.cost.amount)return {status:'stale',reason:'rune_cost_changed'};
   const currencyBefore=call(currency,'Get',[cost.goods]);
   ok=call(rp,'Learn',[ref(r)]);
   // An independent provider verifies persistence, not just Learn's own cache.
   const observed=refreshRunesProvider(),afterLevel=call(observed,'GetLevel',[action.id]),currencyAfter=call(currency,'Get',[cost.goods]);
   after=afterLevel===beforeLevel+1;
   let uiRefresh='unavailable';
   if(after){
    try{
     const popup=sceneObject('DG.UI.Rune.RuneTreePopup'),view=popup&&!popup.isNull()?read(popup,'_view'):null;
     if(view&&!view.isNull()){
      const current=call(view,'get_State');
      if(current&&!current.isNull()&&fullname(A.objectClass(current))==='DG.UI.Rune.RuneSaveStateProvider'){
       call(view,'SetStateProvider',[ref(observed)]);call(popup,'Refresh');uiRefresh='refreshed';
      }else uiRefresh='incompatible';
     }
    }catch(error){uiRefresh='failed';}
   }
   return jsonSafe({status:ok===true&&after?'confirmed':ok===true?'pending':after?'no_change':'rejected',
    action,after,beforeLevel,afterLevel,goods:cost.goods,currencyBefore,currencyAfter,uiRefresh,learnAccepted:ok});
 }
 case 'pet_unlock':ok=call(single(names.pets),'TryUnlock',[action.id]);after=call(single(names.pets),'IsUnlocked',[action.id],'System.String');break;
 case 'pet_equip':ok=call(single(names.pets),'Equip',[action.id]);after=call(single(names.pets),'get_EquippedPetID')===action.id;break;
 case 'progress':{
  const gm=single(names.game);
  if(action.mode==='boss'){
   const frontier=scan.snapshot.record.maxCleared||0,entry=entranceStatus(gm,im,0,action.level);
   if(action.level!==frontier+1||action.level<=scan.snapshot.stage.level||!entry.safe||entry.uid!==action.ticketUid||
      entry.ticket!==action.ticket||!call(gm,'CanEnterStage',[0,action.level]))return {status:'stale',reason:'boss_entry_changed'};
   call(gm,'GoToStage',[0,action.level,action.difficulty]);call(gm,'set_RepeatStage',[false]);
   return {status:'pending',level:action.level,ticket:entry.ticket,ticketUid:entry.uid,ticketBefore:entry.count,consumeOnClear:true};
  }
  if(action.mode==='push'&&action.phase==='travel'){
   if(action.level!==scan.snapshot.record.maxCleared+1||action.level<=scan.snapshot.stage.level||
      call(gm,'GetRequireItemID',[0,action.level])>0||!entranceStatus(gm,im,0,action.level).safe||
      !call(gm,'CanEnterStage',[0,action.level]))return {status:'stale',reason:'push_frontier_changed'};
   call(gm,'GoToStage',[0,action.level,action.difficulty]);call(gm,'set_RepeatStage',[false]);
   return {status:'pending',level:action.level};
  }
  if(action.mode==='farm'){
   const frontier=scan.snapshot.record.maxCleared||0,chapterStart=frontier>0?Math.floor((frontier-1)/10)*10+1:1;
   const candidate=(scan.snapshot.progression?.farmCandidates||[]).find(p=>p.level===action.level&&p.difficulty===action.difficulty);
   if(scan.snapshot.stage.category!==0)return {status:'stale',reason:'farm_not_in_main_story'};
   if(action.level<chapterStart||action.level>frontier)return {status:'stale',reason:'farm_stage_outside_current_chapter'};
   if(!candidate)return {status:'stale',reason:'farm_candidate_changed'};
   if(call(gm,'GetRequireItemID',[0,action.level])>0)return {status:'stale',reason:'farm_stage_requires_ticket'};
   if(!entranceStatus(gm,im,0,action.level).safe||!call(gm,'CanEnterStage',[0,action.level])||!call(gm,'CanRepeat',[0,action.level]))return {status:'stale',reason:'farm_stage_not_safe'};
   if(scan.snapshot.stage.level!==action.level){call(gm,'GoToStage',[0,action.level,action.difficulty]);return {status:'pending',level:action.level};}
   call(gm,'set_RepeatStage',[true]);
  }else call(gm,'set_RepeatStage',[action.repeat]);
  ok=true;after=call(gm,'get_RepeatStage')===action.repeat;break;
 }
 default:throw Error('unsupported_action');
 }
 return jsonSafe({status:ok&&after?'confirmed':ok?'pending':'rejected',action,after});
}
// This lane deliberately avoids character, recipe and rune enumeration. Never use
// the full-scan read cache across a mutation, even within one opening batch.
const boxReceipts=new Map();
const restoredBoxRequests=new Set();
function restoreBoxReceipts(rows){
 if(!Array.isArray(rows)||rows.length>256)throw Error('invalid_box_receipt_store');
 for(const row of rows){
  if(!row||typeof row.requestId!=='string'||!row.requestId.length||row.requestId.length>120||
     typeof row.account!=='string'||!row.account.length||row.account.length>256||
     !Number.isSafeInteger(row.openedCount)||row.openedCount<0||row.openedCount>8||
     !['confirmed','pending','waiting','rejected','unresolved'].includes(row.status)||
     row.status==='unresolved'&&(row.sealed?.schema!==1||row.sealed?.source!=='native_main_thread_fence'||
      !Number.isSafeInteger(row.sealed.record)||row.sealed.record<0||!Array.isArray(row.sealed.counts)||row.sealed.counts.length!==3||
      row.sealed.counts.some(n=>!Number.isSafeInteger(n)||n<0))||
     row.status==='pending'&&(!Number.isSafeInteger(row.pendingRecord)||row.pendingRecord<0))throw Error('invalid_box_receipt');
 }
 for(const row of rows){if(boxReceipts.has(row.requestId))continue;
  boxReceipts.set(row.requestId,JSON.parse(JSON.stringify(row)));restoredBoxRequests.add(row.requestId);
 }
 return rows.length;
}
function boxReceiptResult(receipt){
 return receipt?{...receipt,...(restoredBoxRequests.has(receipt.requestId)?{source:'durable_bridge_receipt'}:{})}:null;
}
function boxScanFresh(input={}){
 const started=Date.now(),maintenance=maintenanceStatus(),runtime={ready:false,maintenance};
 if(maintenance.active)return {snapshot:null,runtime,actions:[],issues:[],scanMs:Date.now()-started};
 const dm=single(names.data),im=single(names.items);
 runtime.ready=call(dm,'get_IsSaveLoaded')===true&&call(dm,'get_IsMasterTableLoaded')===true&&call(im,'get_IsLoaded')===true;
 if(!runtime.ready)return {snapshot:null,runtime,actions:[],issues:[],scanMs:Date.now()-started};
 const options=bridgeStrategy(input.strategy),bag=call(im,'get_Inventory');
 const account=stat('DG.Save.InGame.SaveEnvironment','get_Directory').replaceAll('\\','/').split('/').pop();
 const open=openPopups().map(p=>fullname(A.objectClass(p))),policy=popupPolicy(open,options.preserve_open_panels,options.pause_on_manual_panels,options);
 const server=single('DG.Network.ServerManager'),reach=read(server,'_reachability'),sync=single('DG.Network.SyncManager');
 const s={account,loaded:true,inventory:{count:call(bag,'get_OccupiedCount'),capacity:call(bag,'get_Capacity')},
  record:{boxes:call(single(names.record),'get_BoxOpenCount')},automationBlocked:[...policy.blocked],
  itemInputHolding:call(call(im,'get_Input'),'get_IsHolding'),manualPanels:policy.manual,
  manualBlockedKinds:panelActionBlocked('box',policy.manual)?['box']:[],
  trading:open.some(n=>n.endsWith('TradePopup')||n.endsWith('SteamInventoryPopup')),
  connection:{online:!!reach&&!reach.isNull()&&call(reach,'get_IsOnline'),loggedIn:call(server,'get_IsLoggedIn'),trustBlocked:call(server,'get_IsTrustBlocked')},
  sync:{blocked:call(sync,'get_IsGrantBlocked'),queue:call(sync,'get_QueueCount')}};
 s.sync.backlogged=s.sync.queue>100;
 const actions=[];boxOpportunities(s,single(names.drop),(kind,key,label,priority,detail)=>actions.push({kind,key,label,priority,...detail}),options);
 const receipt=boxReceipts.get(input.requestId);
 // An accepted single open may finish on a later frame. Observe it; do not call
 // TryOpen again or credit earlier successful members of a partial batch twice.
 if(receipt&&receipt.account===account&&receipt.status==='pending'&&s.record.boxes>receipt.pendingRecord){
  receipt.openedCount++;receipt.status='confirmed';receipt.reason=null;receipt.stopReason='pending_settled';
  receipt.recordAfter=s.record.boxes;delete receipt.pendingRecord;checkpointBoxReceipt(receipt);
 }
 let resolved=receipt,prefixReceipt=null;
 // This callback runs on the same native main thread as TryOpen. Earlier calls
 // have returned. Sealing the request ID also prevents any late queued callback
 // from calling TryOpen. The outcome stays unknown; only a NEW current queue
 // operation can follow. Neither time nor record growth fabricates success.
 if(input.sealPending===true&&input.account===account&&typeof input.requestId==='string'&&input.requestId.length>0&&input.requestId.length<=120&&
    (!resolved||resolved.account===account&&resolved.status==='pending')&&Number.isSafeInteger(s.record.boxes)&&s.record.boxes>=0&&
    s.boxes.counts.every(n=>Number.isSafeInteger(n)&&n>=0)&&[...boxReceipts.values()].filter(r=>r.status==='unresolved'||r.status==='pending').length<224){
  if(resolved)prefixReceipt=boxReceiptResult(resolved);
  resolved={...(resolved||{requestId:input.requestId,account,openedCount:0,observations:[]}),status:'unresolved',reason:'box_request_sealed',
   sealed:{schema:1,source:'native_main_thread_fence',record:s.record.boxes,counts:s.boxes.counts.slice()}};
  boxReceipts.set(input.requestId,resolved);checkpointBoxReceipt(resolved);
 }
 const pendingReceipt=[...boxReceipts.values()].find(r=>r.account===account&&r.status==='pending');
 return {snapshot:s,runtime,actions,issues:[],boxRecoveryBarrier:1,receipt:resolved?.account===account?boxReceiptResult(resolved):null,prefixReceipt,
  pendingReceipt:pendingReceipt?boxReceiptResult(pendingReceipt):null,scanMs:Math.max(0,Date.now()-started)};
}
function boxScanGuard(scan,account){
 if(scan.runtime.maintenance.active)return 'native_maintenance_active';
 const s=scan.snapshot;if(!s)return 'native_data_loading';
 if(s.account!==account)throw Error('account_changed');
 if(s.automationBlocked.length)return 'native_modal_active';
 if(s.itemInputHolding)return 'item_drag_active';
 if(s.trading)return 'trade_panel_active';
 if(s.manualBlockedKinds.includes('box'))return 'manual_panel_conflict';
 if(s.connection.online!==true||s.connection.loggedIn!==true||s.connection.trustBlocked)return 'native_offline';
 if(s.boxes.relief?.active&&!s.boxes.relief.blocked)return 'inventory_relief';
 if(s.boxes.freeSlots>0&&s.boxes.openableSlots<=0)return 'inventory_reserved_slots';
 if(s.sync.blocked)return 'native_sync_blocked';
 if(s.sync.backlogged)return 'native_sync_backlog';
 if(!Number.isSafeInteger(s.inventory.capacity)||!Number.isSafeInteger(s.inventory.count)||s.inventory.count<0||s.inventory.capacity<=s.inventory.count)return 'inventory_full';
 if(!Number.isSafeInteger(s.record.boxes)||s.record.boxes<0||s.boxes.counts.some(n=>!Number.isSafeInteger(n)||n<0))return 'native_box_waiting';
 return null;
}
function openBoxBatch(cmd){
 if(typeof cmd.requestId!=='string'||!cmd.requestId.length||cmd.requestId.length>120)throw Error('invalid_box_request');
 if(boxReceipts.has(cmd.requestId)){
  const cached=boxReceipts.get(cmd.requestId);if(cached.account!==cmd.account)throw Error('account_changed');return boxReceiptResult(cached);
 }
 if([...boxReceipts.values()].some(r=>r.account===cmd.account&&r.status==='pending'))return {status:'waiting',reason:'box_result_unconfirmed',openedCount:0};
 let scan=boxScanFresh(cmd),reason=boxScanGuard(scan,cmd.account);
 const receipt={requestId:cmd.requestId,account:cmd.account,status:'waiting',reason,openedCount:0,recordBefore:scan.snapshot?.record.boxes,recordAfter:scan.snapshot?.record.boxes,observations:[]};
 boxReceipts.set(cmd.requestId,receipt);
 // Finished receipts are only a transport recovery cache, not an endless log.
 if(boxReceipts.size>32)for(const [key,value] of boxReceipts){if(key!==cmd.requestId&&!['pending','unresolved'].includes(value.status)){boxReceipts.delete(key);restoredBoxRequests.delete(key);break;}}
 const started=Date.now(),drop=single(names.drop),record=single(names.record),freeBefore=scan.snapshot?scan.snapshot.boxes.openableSlots:0,options=bridgeStrategy(cmd.strategy);
 const limitReason=scan.snapshot&&freeBefore<scan.snapshot.boxes.freeSlots?
  scan.snapshot.boxes.relief?.enabled&&freeBefore===scan.snapshot.boxes.relief.high-scan.snapshot.inventory.count?'inventory_relief':'inventory_reserved_slots':'inventory_full';
 for(let index=0;!reason&&index<options.box_batch_limit;index++){
  if(index>=freeBefore){reason=limitReason;break;}
  if(index){if(Date.now()-started>=25){reason='box_batch_yield';break;}scan=boxScanFresh(cmd);reason=boxScanGuard(scan,cmd.account);if(reason)break;}
  const counts=scan.snapshot.boxes.counts,first=scan.snapshot.record.boxes%3;
  const grade=[first,(first+1)%3,(first+2)%3].find(g=>counts[g]>0&&scan.snapshot.boxes.enabledGrades[g]);
  if(grade===undefined){reason='box_empty';break;}
  const before=scan.snapshot.record.boxes,queueBefore=counts[grade];
  // Install uncertainty before calling native code. Exceptions and lost replies
  // cannot authorize a second consumption, including after a confirmed prefix.
  receipt.status='pending';receipt.reason='box_result_unconfirmed';receipt.pendingRecord=before;checkpointBoxReceipt(receipt);
  try{
   const accepted=call(drop,'TryOpen',[grade]);
   const queueAfter=call(drop,'Count',[grade]),after=call(record,'get_BoxOpenCount');
   receipt.observations.push({grade,accepted,queueBefore,queueAfter,recordBefore:before,recordAfter:after});receipt.recordAfter=after;
   if(accepted===true&&after>before){receipt.openedCount++;receipt.status='confirmed';receipt.reason=null;delete receipt.pendingRecord;}
   else if(accepted===true){reason='box_result_unconfirmed';break;}
   else{receipt.status=receipt.openedCount?'confirmed':'rejected';delete receipt.pendingRecord;reason='native_box_rejected';break;}
  }catch(error){reason='box_result_unconfirmed';break;}
 }
 receipt.stopReason=reason||'box_batch_limit';
 if(receipt.status!=='pending')receipt.reason=receipt.openedCount?null:reason;
 checkpointBoxReceipt(receipt);return {...receipt};
}
function checkpointBoxReceipt(receipt){
 try{send({channel:'box_receipt',receipt:JSON.parse(JSON.stringify(receipt))});}catch(error){}
}
function boxNotStarted(cmd){
 if(typeof cmd?.requestId!=='string'||!cmd.requestId.length||cmd.requestId.length>120||
    typeof cmd.account!=='string'||!cmd.account||cmd.account.length>256)throw Error('invalid_box_request');
 const previous=boxReceipts.get(cmd.requestId);
 if(previous){if(previous.account!==cmd.account)throw Error('account_changed');return boxReceiptResult(previous);}
 const receipt={requestId:cmd.requestId,account:cmd.account,status:'waiting',reason:'native_request_not_started',
  executionState:'not_started',openedCount:0,observations:[]};
 boxReceipts.set(cmd.requestId,receipt);
 while(boxReceipts.size>32){const done=[...boxReceipts].find(([key,r])=>key!==cmd.requestId&&!['pending','unresolved'].includes(r.status));if(!done)break;boxReceipts.delete(done[0]);restoredBoxRequests.delete(done[0]);}
 checkpointBoxReceipt(receipt);return {...receipt};
}
function openBoxRequest(cmd){
 try{return openBoxBatch(cmd);}catch(error){
  // No receipt means the prerequisite scan failed before native consumption.
  // Once registered, its exact outcome remains authoritative, including pending.
  if(boxReceipts.has(cmd?.requestId))throw error;
  return boxNotStarted(cmd);
 }
}
function onMainRequest(fn,onNotStarted){
 const result=onMain(fn);
 return result&&typeof result.catch==='function'?result.catch(error=>{
  if(!isMainNotStarted(error))throw error;
  return onNotStarted(error);
 }):result;
}
function executeNotStarted(cmd){
 return executeWorkshopRequest(cmd,()=>({status:'waiting',reason:'native_request_not_started',executionState:'not_started'}));
}
const workshopReceipts=new Map(),workshopKinds=new Set(['combine','forge','refine','decompose','deposit','withdraw']);
const workshopTerminal=new Set(['confirmed','rejected','waiting','stale','no_change']);
function stableWorkshopCommand(value){
 if(Array.isArray(value))return value.map(stableWorkshopCommand);
 if(value&&typeof value==='object')return Object.fromEntries(Object.keys(value).sort().map(k=>[k,stableWorkshopCommand(value[k])]));
 return value;
}
function validWorkshopReceipt(r){
 return r&&workshopKinds.has(r.kind)&&typeof r.requestId==='string'&&/^[A-Za-z0-9:_-]{1,120}$/.test(r.requestId)&&
  typeof r.account==='string'&&r.account.length>0&&r.account.length<=256&&typeof r.key==='string'&&r.key.length>0&&r.key.length<=2048&&
  typeof r.signature==='string'&&/^[0-9a-f]{64}$/.test(r.signature)&&Number.isFinite(r.at)&&r.at>0&&
  r.result&&typeof r.result==='object'&&!Array.isArray(r.result)&&(r.result.status==='pending'||workshopTerminal.has(r.result.status));
}
function restoreWorkshopReceipts(rows){
 if(!Array.isArray(rows)||rows.length>256||rows.some(r=>!validWorkshopReceipt(r))||new Set(rows.map(r=>r.requestId)).size!==rows.length)throw Error('invalid_workshop_receipt_store');
 for(const r of rows){const old=workshopReceipts.get(r.requestId);if(old&&JSON.stringify(old)!==JSON.stringify(r))throw Error('workshop_receipt_conflict');}
 for(const r of rows)workshopReceipts.set(r.requestId,JSON.parse(JSON.stringify(r)));
 return workshopReceipts.size;
}
function workshopReceipt(query){
 const r=workshopReceipts.get(query?.requestId);
 if(!r||r.account!==query.account||r.kind!==query.kind||r.key!==query.key)return null;
 if(r.kind==='refine'&&r.result.status==='pending'&&r.result.reason==='refine_result_unconfirmed'){
  try{const recovered=revalidateRefineReceipt(r);if(recovered){r.result=recovered;checkpointWorkshopReceipt(r);}}catch(error){}
 }
 return JSON.parse(JSON.stringify(r));
}
function checkpointWorkshopReceipt(receipt){
 // Message delivery and the host's synchronous return checkpoint both precede
 // HTTP delivery. A crash between native execution and either remains unknown.
 try{send({channel:'workshop_receipt',receipt:JSON.parse(JSON.stringify(receipt))});}catch(error){}
}
function executeWorkshopRequest(cmd,invokeAction=executeAction){
 if(cmd.kind==='box')return {status:'waiting',reason:'legacy_box_request_blocked',executionState:'not_started'};
 // Late commands from legacy clients must not cross the recovery barrier.
 if(['deposit','withdraw'].includes(cmd.kind)&&cmd.requestId===undefined)return {status:'waiting',reason:'storage_request_id_required',executionState:'not_started'};
 if(!workshopKinds.has(cmd.kind)||cmd.requestId===undefined)return invokeAction(cmd);
 if(typeof cmd.requestId!=='string'||!/^[A-Za-z0-9:_-]{1,120}$/.test(cmd.requestId)||
    typeof cmd.account!=='string'||!cmd.account||cmd.account.length>256||typeof cmd.key!=='string'||!cmd.key||cmd.key.length>2048)throw Error('invalid_workshop_request');
 const {requestId,...command}=cmd;
 const signature=Checksum.compute('sha256',JSON.stringify(stableWorkshopCommand(command))),previous=workshopReceipts.get(cmd.requestId);
 if(previous){
  if(previous.signature!==signature||previous.account!==cmd.account||previous.kind!==cmd.kind||previous.key!==cmd.key)throw Error('workshop_request_conflict');
  return {...JSON.parse(JSON.stringify(previous.result)),workshopReceipt:JSON.parse(JSON.stringify(previous)),source:'cached_workshop_receipt'};
 }
 while(workshopReceipts.size>=32){
  const done=[...workshopReceipts].find(([key,r])=>workshopTerminal.has(r.result.status));if(!done)break;workshopReceipts.delete(done[0]);
 }
 if(workshopReceipts.size>=256)return {status:'waiting',reason:'workshop_receipt_capacity'};
 const receipt={requestId:cmd.requestId,account:cmd.account,kind:cmd.kind,key:cmd.key,signature,at:Date.now()/1000,
  result:{status:'pending',reason:'workshop_result_unconfirmed'}};
 workshopReceipts.set(cmd.requestId,receipt);checkpointWorkshopReceipt(receipt);
 try{
  const result=invokeAction(cmd);
  if(!result||!(result.status==='pending'||workshopTerminal.has(result.status)))throw Error('invalid_workshop_result');
  receipt.result=jsonSafe(result);checkpointWorkshopReceipt(receipt);
  return {...result,workshopReceipt:JSON.parse(JSON.stringify(receipt))};
 }catch(error){checkpointWorkshopReceipt(receipt);throw error;}
}
Object.assign(rpc.exports,{restoreworkshopreceipts(rows){return restoreWorkshopReceipts(rows);},workshopreceipt(query){return onMain(()=>workshopReceipt(query));},restoreboxreceipts(rows){return restoreBoxReceipts(rows);},boxscan(input){return onMain(()=>boxScanFresh(input));},openboxes(cmd){return onMainRequest(()=>openBoxRequest(cmd),()=>boxNotStarted(cmd));},opportunities(options){return onMain(()=>opportunityScan(options));},execute(cmd){return onMainRequest(()=>{const result=executeWorkshopRequest(cmd);if(typeof lastScanPerformance!=='undefined'&&lastScanPerformance)result.bridgePerformance={...lastScanPerformance};return result;},()=>executeNotStarted(cmd));}});

// UI controllers keep material rules, prerequisite checks, and sync accounting in the game.
const classFromName=api('class_from_name','pointer',['pointer','pointer','pointer']);
const classType=api('class_get_type','pointer',['pointer']);
const typeObject=api('type_get_object','pointer',['pointer']);
const externalTypes=new Map();
function external(ns,name){
 const key=ns+'.'+name;if(externalTypes.has(key))return externalTypes.get(key);
 for(let i=0;i<size.readU64().toNumber();i++){
  const k=classFromName(A.image(asms.add(i*PS).readPointer()),Memory.allocUtf8String(ns),Memory.allocUtf8String(name));
  if(!k.isNull()){externalTypes.set(key,k);return k;}
 }throw Error('external_missing:'+key);
}
function sceneObject(name){
 if(!types.has(name))return null;
 const objects=list(invoke(external('UnityEngine','Resources'),nil,'FindObjectsOfTypeAll',[ref(typeObject(classType(klass(name))))],'System.Type'));
 return objects.length===1?objects[0]:null;
}
function itemInfo(p){
 const config=call(p,'get_Config');
 return {id:call(p,'get_ConfigID'),uid:call(p,'get_Uid'),count:call(p,'get_Count'),kind:call(p,'get_Kind'),
  grade:read(config,'Grade'),tier:read(config,'Tier'),tradable:read(config,'Tradable'),locked:call(p,'get_IsLocked'),confirmed:call(p,'get_IsServerConfirmed'),sockets:list(call(p,'get_Sockets')).length};
}
function inventoryItems(im){return list(call(call(im,'get_Inventory'),'get_Has')).filter(p=>p&&!p.isNull());}
function containerEntries(im,withStorage=true){
 const result=[],inventory=call(im,'get_Inventory');
 list(call(inventory,'get_Has')).forEach((item,index)=>{if(item&&!item.isNull())result.push({item,index,container:inventory,place:'inventory'});});
 if(withStorage){
  const storage=call(im,'get_Storage'),perTab=call(storage,'get_SlotCountPerTab');
  list(call(storage,'get_Has')).forEach((item,index)=>{if(item&&!item.isNull()&&call(storage,'IsTabUnlocked',[Math.floor(index/perTab)]))result.push({item,index,container:storage,place:'storage'});});
 }
 return result;
}
const equipmentArrayNew=api('array_new','pointer',['pointer','uint64']);
const equipmentValueSize=api('class_value_size','int',['pointer','pointer']);
function equipmentScorer(im,id,set,has){
 const basis=Memory.alloc(equipmentValueSize(klass('DG.Item.Manager.ItemManager.EquipScoreBasis'),Memory.alloc(4)));
 if(!call(im,'TryBuildScoreBasis',[id,ref(basis)]))return null;
 // A rooted scratch array is passed to the native scorer; real equipment slots are never written here.
 const scratch=equipmentArrayNew(klass('DG.Item.ItemEntity'),set.length),handle=gcNew(scratch,0);
 try{
  const score=(slot,item)=>{
   set.forEach((p,i)=>scratch.add(32+i*PS).writePointer(i===slot?item:(p||nil)));
   return call(im,'CalculateEquipScore',[id,ref(scratch),ref(basis)]);
  };
  const base=call(im,'CalculateEquipScore',[id,ref(has),ref(basis)]),copy=score(-1,nil);
  if(!Number.isFinite(base)||!Number.isFinite(copy)||Math.abs(copy-base)>Math.max(1,Math.abs(base))*1e-9){gcFree(handle);return null;}
  return {base,score,close:()=>gcFree(handle)};
 }catch(e){gcFree(handle);throw e;}
}
function protectedEquipped(im,p){
 return !!p&&(typeof read(call(p,'get_Config'),'Tradable')!=='boolean'||call(p,'get_IsLocked')||call(im,'IsInUse',[ref(p)])||!call(p,'get_IsServerConfirmed'));
}
function allocateEquipment(options){
 const usedItems=new Set(),usedSlots=new Set();
 return [...options].sort((a,b)=>Number(b.empty)-Number(a.empty)||b.gain-a.gain||a.order-b.order||a.slot-b.slot||a.uid.localeCompare(b.uid)).filter(plan=>{
  const key=plan.id+':'+plan.slot;if(usedItems.has(plan.uid)||usedSlots.has(key))return false;
  usedItems.add(plan.uid);usedSlots.add(key);return true;
 });
}
function equipmentPlans(im,characters,squad=[],diagnostics=[],reserved=new Set(),minGainPercent=0){
 const available=containerEntries(im).filter(e=>call(e.item,'get_EquipmentConfig')!==null);
 const candidates=available.filter(e=>!protectedEquipmentCandidate(im,e.item)),options=[];
 const order=new Map(squad.filter(id=>id>0).map((id,i)=>[id,i]));
 const roster=[...characters].sort((a,b)=>(order.get(a.id)??squad.length)-(order.get(b.id)??squad.length)||a.id-b.id);
 for(const [index,character] of roster.entries()){
  const equipment=call(im,'GetEquipment',[character.id]),has=call(equipment,'get_Has'),set=list(has);
  const detail={id:character.id,slots:set.length,equipped:set.filter(Boolean).length,empty:set.filter(p=>!p).length,protectedSlots:0,accepted:0,upgrades:0,planned:0,status:'no_upgrade',slotDetails:[]};
  diagnostics.push(detail);
  const scorer=equipmentScorer(im,character.id,set,has);
  if(!scorer){detail.status='score_unavailable';candidates.forEach(e=>reserved.add(call(e.item,'get_Uid')));continue;}
  detail.score=scorer.base;
  try{
   for(let slot=0;slot<set.length;slot++){
    const current=set[slot],matching=available.filter(e=>read(call(e.item,'get_EquipmentConfig'),'EquipPart')===slot);
    const slotDetail={slot,empty:!current,candidates:matching.length,protectedCandidates:matching.filter(e=>protectedEquipmentCandidate(im,e.item)).length,accepted:0,upgrades:0,bestScore:null,status:'no_candidate'};
    detail.slotDetails.push(slotDetail);
    if(protectedEquipped(im,current)){detail.protectedSlots++;slotDetail.status='protected_equipped';continue;}
    const future=[];
    for(const candidate of candidates){
     if(call(equipment,'IsUnderRequireLevel',[ref(candidate.item)])&&!call(equipment,'IsWrongClass',[ref(candidate.item)])){
      const config=call(candidate.item,'get_EquipmentConfig');
      if(read(config,'EquipPart')!==slot)continue;
      const requireLevel=read(config,'RequireLevel'),uid=call(candidate.item,'get_Uid');
      if(!Number.isInteger(requireLevel)||!Number.isFinite(character.level)||requireLevel<=character.level)reserved.add(uid);
      else future.push({uid,requireLevel,score:scorer.score(slot,candidate.item)});
      continue;
     }
     if(!call(equipment,'CanAccept',[slot,ref(candidate.item)]))continue;detail.accepted++;slotDetail.accepted++;
     const score=scorer.score(slot,candidate.item),base=scorer.base;
     if(Number.isFinite(score)&&(slotDetail.bestScore===null||score>slotDetail.bestScore))slotDetail.bestScore=score;
     if(!Number.isFinite(score)){reserved.add(call(candidate.item,'get_Uid'));continue;}
     if(score-base<=Math.max(1,Math.abs(base))*1e-6)continue;
     reserved.add(call(candidate.item,'get_Uid'));
     if(current&&(score-base)/Math.max(1,Math.abs(base))*100<minGainPercent)continue;
     detail.upgrades++;slotDetail.upgrades++;
     options.push({uid:call(candidate.item,'get_Uid'),id:character.id,slot,score,base,gain:(score-base)/Math.max(1,Math.abs(base)),source:candidate.place,previousUid:current?call(current,'get_Uid'):null,empty:!current,order:index,scoring:'native_set'});
    }
    if(future.length){
     const nearest=Math.min(...future.map(p=>p.requireLevel)),next=future.filter(p=>p.requireLevel===nearest);
     if(next.some(p=>!Number.isFinite(p.score)))next.forEach(p=>reserved.add(p.uid));
     else reserved.add(next.sort((a,b)=>b.score-a.score||a.uid.localeCompare(b.uid))[0].uid);
     slotDetail.futureLevel=nearest;slotDetail.futureReserved=next.filter(p=>reserved.has(p.uid)).length;
    }
    slotDetail.status=slotDetail.upgrades?'upgrade_ready':slotDetail.accepted?'no_upgrade':matching.length===0?'no_candidate':slotDetail.protectedCandidates===matching.length?'protected_candidates':'native_rejected';
   }
  }finally{scorer.close();}
 }
 const plans=allocateEquipment(options);
 for(const detail of diagnostics){
  detail.planned=plans.filter(p=>p.id===detail.id).length;
  if(detail.planned)detail.status='upgrade_ready';else if(detail.upgrades)detail.status='shared_candidate_assigned';
  for(const slot of detail.slotDetails){if(slot.upgrades)slot.status=plans.some(p=>p.id===detail.id&&p.slot===slot.slot)?'upgrade_ready':'shared_candidate_assigned';}
 }
 return plans;
}
function equipAction(action,minGainPercent=0){
 const im=single('DG.Item.Manager.ItemManager'),entry=containerEntries(im).find(e=>call(e.item,'get_Uid')===action.uid),equipment=call(im,'GetEquipment',[action.id]);
 if(!entry||protectedEquipmentCandidate(im,entry.item))return {status:'stale',reason:'protected_or_missing_item'};
 const old=list(call(equipment,'get_Has'))[action.slot];
 if(protectedEquipped(im,old))return {status:'waiting',reason:'protected_equipped_item'};
 if((old?call(old,'get_Uid'):null)!==action.previousUid)return {status:'stale',reason:'equipped_item_changed'};
 if(!call(equipment,'CanAccept',[action.slot,ref(entry.item)]))return {status:'stale',reason:'equipment_no_longer_accepted'};
 const has=call(equipment,'get_Has'),scorer=equipmentScorer(im,action.id,list(has),has);
 if(!scorer)return {status:'waiting',reason:'equipment_score_unavailable'};
 let score,base;
 try{base=scorer.base;score=scorer.score(action.slot,entry.item);}finally{scorer.close();}
 if(!Number.isFinite(score)||score-base<=Math.max(1,Math.abs(base))*1e-6||old&&(score-base)/Math.max(1,Math.abs(base))*100<minGainPercent)return {status:'stale',reason:'equipment_no_longer_upgrade'};
 const ok=call(im,'TryExchange',[ref(entry.container),entry.index,ref(equipment),action.slot]);
 const after=list(call(equipment,'get_Has'))[action.slot];
 return {status:ok&&after&&call(after,'get_Uid')===action.uid?'confirmed':ok?'pending':'rejected',uid:action.uid,id:action.id,slot:action.slot,previousUid:action.previousUid,source:entry.place,score,previousScore:base,scoring:'native_set'};
}
function storageEmptyIndex(storage){
 const perTab=call(storage,'get_SlotCountPerTab');
 return list(call(storage,'get_Has')).findIndex((p,index)=>(!p||p.isNull())&&call(storage,'IsTabUnlocked',[Math.floor(index/perTab)]));
}
function storageAction(action){
 const im=single('DG.Item.Manager.ItemManager'),entry=containerEntries(im).find(e=>call(e.item,'get_Uid')===action.uid);
 if(!entry||!canMoveStoredItem(im,entry.item))return {status:'stale',reason:'protected_or_missing_item'};
 const destination=({deposit:'storage',withdraw:'inventory'})[action.kind];
 if(!destination||entry.place===destination)return {status:'stale',reason:'storage_source_changed'};
 if(call(call(im,'get_Input'),'get_IsHolding'))return {status:'waiting',reason:'user_item_operation'};
 let ok=false,swap=null;
 if(action.swapUid){
  swap=containerEntries(im).find(e=>call(e.item,'get_Uid')===action.swapUid&&e.place==='inventory');
  if(action.kind!=='withdraw'||!swap||!canMoveStoredItem(im,swap.item))return {status:'stale',reason:'storage_swap_changed'};
 }
 if(action.kind==='deposit'&&entry.place==='inventory'){
  const storage=call(im,'get_Storage'),index=storageEmptyIndex(storage);
  if(index<0)return {status:'waiting',reason:'storage_full'};
  // TryMoveToStorage can merge stacks and retire a UID. Explicit empty-slot exchange preserves identity.
  ok=call(im,'TryExchange',[ref(entry.container),entry.index,ref(storage),index]);
 }
 if(action.kind==='withdraw'&&entry.place==='storage'){
  const inventory=call(im,'get_Inventory'),index=swap?swap.index:call(inventory,'FindEmptyIndex');
  if(index<0)return {status:'waiting',reason:'inventory_full'};
  ok=call(im,'TryExchange',[ref(entry.container),entry.index,ref(inventory),index]);
 }
 const entries=containerEntries(im),after=entries.find(e=>call(e.item,'get_Uid')===action.uid),swapped=swap&&entries.find(e=>call(e.item,'get_Uid')===action.swapUid);
 return {status:ok&&after?.place===destination&&(!swap||swapped?.place==='storage')?'confirmed':ok?'pending':'rejected',uid:action.uid,from:entry.place,to:after?.place,tradable:read(call(entry.item,'get_Config'),'Tradable'),...(swap?{swapUid:action.swapUid,swapTo:swapped?.place}: {})};
}
function protectedPositions(im,characters,watched=[]){
 const watch=new Set(watched);
 const fingerprint=(p,place,index)=>({tradable:read(call(p,'get_Config'),'Tradable'),uid:call(p,'get_Uid'),id:call(p,'get_ConfigID'),place,index,count:call(p,'get_Count'),locked:call(p,'get_IsLocked'),sockets:list(call(p,'get_Sockets')).map(s=>({index:call(s,'get_Index'),id:call(s,'get_ConfigID'),ability:call(s,'get_Ability'),value:call(s,'get_Value')}))});
 const result=containerEntries(im).filter(e=>isTradable(e.item)||watch.has(call(e.item,'get_Uid'))).map(e=>fingerprint(e.item,e.place,e.index));
 for(const c of characters)list(call(call(im,'GetEquipment',[c.id]),'get_Has')).forEach((p,index)=>{if(p&&isTradable(p))result.push(fingerprint(p,'equipment:'+c.id,index));});
 return result;
}
function checkPreserved(before,after,moves=[]){
 const positions=new Map(after.map(x=>[x.uid,x])),allowed=new Map(moves.map(m=>[m.uid,m]));
 return before.filter(x=>{
  const actual=positions.get(x.uid);if(!actual||after.filter(p=>p.uid===x.uid).length!==1)return true;
  if(JSON.stringify(actual)===JSON.stringify(x))return false;
  const move=allowed.get(x.uid);
  if(!move||!Number.isInteger(actual.index)||actual.index<0)return true;
  const index=move.index;
  return JSON.stringify(actual)!==JSON.stringify({...x,place:move.place,index});
 });
}
function guardedItemAction(fn,characters,moves=[],watched=[]){
 const im=single('DG.Item.Manager.ItemManager'),before=protectedPositions(im,characters,watched);let result,error;
 try{result=fn();}catch(e){error=e;}
 const changed=checkPreserved(before,protectedPositions(im,characters,watched),moves);
 if(error&&!changed.length)throw error;
 if(error)result={status:'waiting',reason:'protected_state_changed_after_error',error:String(error)};
 return {...result,protectedChecked:before.length,protectedChanged:changed};
}
function guardedStorageAction(action,characters){
 const im=single('DG.Item.Manager.ItemManager'),entries=containerEntries(im),entry=entries.find(e=>call(e.item,'get_Uid')===action.uid),moves=[];
 const watched=entries.filter(e=>protectedItem(im,e.item)||call(e.item,'get_Uid')===action.uid||call(e.item,'get_Uid')===action.swapUid).map(e=>call(e.item,'get_Uid'));
 if(entry&&action.kind==='deposit'&&entry.place==='inventory')moves.push({uid:action.uid,place:'storage',index:storageEmptyIndex(call(im,'get_Storage'))});
 if(entry&&action.kind==='withdraw'&&entry.place==='storage'){
  if(action.swapUid){
   const swap=entries.find(e=>call(e.item,'get_Uid')===action.swapUid&&e.place==='inventory');
   if(swap){moves.push({uid:action.uid,place:'inventory',index:swap.index});moves.push({uid:action.swapUid,place:'storage',index:entry.index});}
  }else moves.push({uid:action.uid,place:'inventory',index:call(call(im,'get_Inventory'),'FindEmptyIndex')});
 }
 return guardedItemAction(()=>storageAction(action),characters,moves,watched);
}
function guardedEquipmentAction(action,characters,minGainPercent=0){
 const im=single('DG.Item.Manager.ItemManager'),entry=containerEntries(im).find(e=>call(e.item,'get_Uid')===action.uid),moves=[];
 if(entry){
  moves.push({uid:action.uid,place:'equipment:'+action.id,index:action.slot});
  if(action.previousUid)moves.push({uid:action.previousUid,place:entry.place,index:entry.index});
 }
 return guardedItemAction(()=>equipAction(action,minGainPercent),characters,moves);
}
function approvedMaterials(im,ids){
 if(!Array.isArray(ids)||!ids.length||new Set(ids).size!==ids.length)return null;
 const entries=containerEntries(im,false).filter(e=>ids.includes(call(e.item,'get_Uid')));
 return entries.length===ids.length&&entries.every(e=>!protectedItem(im,e.item))?entries.map(e=>e.item):null;
}
function recipeRows(dm){return list(call(read(dm,'_craftConfigTable'),'get_Datas'));}
function forgeAction(cmd){
 const im=single('DG.Item.Manager.ItemManager'),cube=call(im,'get_Cube'),view=sceneObject('DG.UI.Popup.CubeAssembleView');
 const approved=approvedMaterials(im,cmd.allowed);
 if(!approved)return {status:'stale',reason:'protected_or_missing_material'};
 if(!view||!call(cube,'get_IsEmpty')||call(call(im,'get_Input'),'get_IsHolding'))return {status:'waiting',reason:'cube_in_use'};
 const oldTier=call(view,'get_SelectedTier'),toggle=call(view,'get_IncludeStorageToggle'),oldStorage=call(toggle,'get_isOn');
 const before=inventoryItems(im).map(itemInfo);let selected=[],ok=false,popup;
 try{
  call(toggle,'set_isOn',[false]);popup=activateCubeView(view);call(view,'CollectSlots');call(view,'SetSelectedTier',[cmd.tier]);
  const part=list(read(view,'_partSlots')).find(p=>call(p,'get_Part')===cmd.part);
  if(!part)return {status:'stale',reason:'craft_part_unavailable'};
  call(view,'SelectPart',[ref(part)]);
  call(view,'ApplyRequirements');call(view,'RebuildRules');
  const recipe=call(view,'get_CurrentConfig');
  if(!recipe||read(recipe,'ID')!==cmd.recipe)return {status:'stale',reason:'craft_recipe_changed'};
  for(const item of approved){
   for(let n=0;n<32&&call(cube,'CanReserveMore',[ref(item)]);n++)if(!call(im,'TryMoveToCube',[ref(item)]))break;
  }
  const materials=list(call(cube,'get_Has')).filter(p=>p&&!p.isNull());selected=materials.map(itemInfo);
  if(!selected.length||materials.some(p=>isTradable(p)||call(p,'get_IsLocked'))||selected.some(p=>!cmd.allowed.includes(p.uid)))return {status:'waiting',reason:'protected_craft_material'};
  if(!call(view,'get_IsReady'))return {status:'waiting',reason:'native_recipe_not_ready'};
  ok=call(view,'TryExecute');
 }finally{call(view,'ReleaseAll');if(popup)call(popup,'OnClickClose');call(view,'SetSelectedTier',[oldTier]);call(toggle,'set_isOn',[oldStorage]);}
 const after=inventoryItems(im).map(itemInfo),old=new Map(before.map(x=>[x.uid,x.count]));
 const produced=after.filter(x=>!old.has(x.uid)||x.count>old.get(x.uid));
 return {status:ok&&produced.length?'confirmed':ok?'pending':'rejected',recipe:cmd.recipe,materials:selected,produced};
}
function hasAttachmentSpace(im,equipment,item){
 if(!call(im,'CanAttach',[ref(equipment),ref(item)]))return false;
 const config=call(equipment,'get_EquipmentConfig'),attachment=call(item,'get_AttachmentConfig');
 if(!config||!attachment)return false;
 const type=read(attachment,'ItemType'),capacity=call(im,'GetSocketCount',[ref(config),type]);
 const used=list(call(equipment,'get_Sockets')).filter(s=>read(call(s,'get_Config'),'ItemType')===type).length;
 return Number.isInteger(capacity)&&capacity>used;
}
function refineAction(cmd){
 const im=single('DG.Item.Manager.ItemManager'),cube=call(im,'get_Cube'),view=sceneObject('DG.UI.Popup.CubeRefineView');
 const approved=approvedMaterials(im,cmd.allowed);
 if(!approved)return {status:'stale',reason:'protected_or_missing_material'};
 if(!view||!call(cube,'get_IsEmpty')||call(call(im,'get_Input'),'get_IsHolding'))return {status:'waiting',reason:'cube_in_use'};
 const equipment=list(call(call(im,'GetEquipment',[cmd.id]),'get_Has')).find(p=>p&&call(p,'get_Uid')===cmd.uid);
 if(!equipment||isTradable(equipment)||call(equipment,'get_IsLocked'))return {status:'stale',reason:'protected_equipment'};
 const before=list(call(equipment,'get_Sockets')).length,toggle=call(view,'get_IncludeStorageToggle'),storage=call(toggle,'get_isOn');let ok=false,selected=[],popup;
 try{
  call(toggle,'set_isOn',[false]);popup=activateCubeView(view);call(view,'CollectSlots');call(view,'SetMode',[0]);call(view,'RebuildRules');
  if(!call(im,'TryMoveToCube',[ref(equipment)]))return {status:'waiting',reason:'equipment_not_accepted'};
  for(const item of approved)if(hasAttachmentSpace(im,equipment,item))call(im,'TryMoveToCube',[ref(item)]);
  const materials=list(call(cube,'get_Has')).filter(p=>p&&!p.isNull());selected=materials.map(itemInfo);
  if(!selected.some(p=>cmd.allowed.includes(p.uid)))return {status:'waiting',reason:'native_attachment_not_ready'};
  if(materials.some(isTradable)||selected.some(p=>p.uid!==cmd.uid&&!cmd.allowed.includes(p.uid)))return {status:'waiting',reason:'protected_refine_material'};
  ok=call(view,'TryExecute');
 }finally{call(view,'ReleaseAll');if(popup)call(popup,'OnClickClose');call(toggle,'set_isOn',[storage]);}
 const after=list(call(equipment,'get_Sockets')).length;
 return {status:ok&&after>before?'confirmed':ok?'pending':'rejected',uid:cmd.uid,before,after,materials:selected};
}
function activateCubeView(view){
 const popup=sceneObject('DG.UI.Popup.CubePopup');
 const views=list(read(popup,'_views')),index=views.findIndex(p=>p.equals(view));
 if(index<0)throw Error('cube_view_not_registered');
 call(popup,'Show');call(popup,'SelectTab',[index]);
 const current=read(popup,'_currentView');
 if(!current||current.isNull()||!current.equals(view))call(popup,'OnViewChanged',[index]);
 return popup;
}
function isTradable(p){return read(call(p,'get_Config'),'Tradable')!==false;}
function protectedEquipmentCandidate(im,p){return typeof read(call(p,'get_Config'),'Tradable')!=='boolean'||call(p,'get_IsLocked')||call(im,'IsInUse',[ref(p)])||call(im,'IsEquipped',[ref(p)])||list(call(im,'FindRegistrations',[ref(p)])).length>0||!call(p,'get_IsServerConfirmed');}
// Storage transfers retain trade flags and sockets; only inactive, confirmed items may move.
function canMoveStoredItem(im,p){return !protectedEquipmentCandidate(im,p);}
// Existing sockets are retained on an equipment swap, but never consumed as craft materials.
function protectedItem(im,p){return isTradable(p)||protectedEquipmentCandidate(im,p)||list(call(p,'get_Sockets')).length>0;}
function materialReceipt(before,after,selected){
 const old=new Map(before.map(p=>[p.uid,p])),now=new Map(after.map(p=>[p.uid,p]));
 const reserved=new Map();for(const p of selected)reserved.set(p.uid,(reserved.get(p.uid)||0)+1);
 const consumed=[...reserved].flatMap(([uid,count])=>{const item=old.get(uid);if(!item)return [];const quantity=item.count-(now.get(uid)?.count||0);return quantity>0?[{...item,count:quantity,reserved:count}]:[];});
 const produced=after.filter(p=>!old.has(p.uid)||p.count>old.get(p.uid).count).map(p=>({...p,count:p.count-(old.get(p.uid)?.count||0)}));
 return {consumed,produced};
}
function cubeAction(cmd){
 const im=single('DG.Item.Manager.ItemManager'),cube=call(im,'get_Cube');
 const approved=approvedMaterials(im,cmd.allowed);
 if(!approved)return {status:'stale',reason:'protected_or_missing_material'};
 if(!call(cube,'get_IsEmpty')||call(call(im,'get_Input'),'get_IsHolding'))return {status:'waiting',reason:'user_item_operation'};
 if(call(single('DG.UI.PopupLayoutHandler'),'get_AnyPopupOpen'))return {status:'waiting',reason:'user_popup_open'};
 const view=sceneObject(cmd.kind==='combine'?'DG.UI.Popup.CubeCombineView':'DG.UI.Popup.CubeDecomposeView');
 if(!view)return {status:'waiting',reason:'view_not_ready'};
 const tier=call(view,'get_SelectedTier'),toggle=call(view,'get_IncludeStorageToggle'),storage=call(toggle,'get_isOn');
 const category=cmd.kind==='combine'?call(view,'get_SelectedCategory'):null;
 const before=inventoryItems(im).map(itemInfo),soulBefore=call(single('DG.Manager.CurrencyManager'),'Get',[201]);
 let selected=[],ok=false,popup,submitted=false,touched=false,result,executionError,step='native_ready';const cleanupIssues=[];
 try{
  result=(()=>{
  if(!call(view,'CanStartExecute'))return {status:'waiting',reason:'native_cube_busy'};
  // Combine/decompose use the base view's Show/SetSlots; CollectSlots exists only on assemble/refine.
  touched=true;call(toggle,'set_isOn',[false]);popup=sceneObject('DG.UI.Popup.CubePopup');activateCubeView(view);
  step='configure';
  if(category!==null){
   call(view,'SetCategory',[cmd.category]);call(view,'RefreshLevelRangeOptions');call(view,'SetSelectedTier',[cmd.tier]);
   if(call(view,'get_SelectedTier')!==cmd.tier)return {status:'waiting',reason:'native_tier_not_ready'};
  }
  // Decompose has no tier dropdown in the native view; an empty options list is valid.
  call(view,'RebuildRules');step='reserve';
  for(const item of approved){
   for(let n=0;n<32&&call(cube,'CanReserveMore',[ref(item)]);n++)if(!call(im,'TryMoveToCube',[ref(item)]))break;
  }
  const materials=list(call(cube,'get_Has')).filter(p=>p&&!p.isNull());selected=materials.map(itemInfo);
  // Check the native reservation against the exact approved materials before consumption.
  if(!materials.length)return {status:'waiting',reason:'native_material_not_reserved'};
  if(materials.some(p=>protectedItem(im,p))||selected.some(p=>!cmd.allowed.includes(p.uid)||p.grade>cmd.maxGrade))return {status:'waiting',reason:'autofill_contains_protected_material'};
  if(!call(view,'get_CanExecute'))return {status:'waiting',reason:'native_recipe_not_ready'};
  step='execute';submitted=true;
  ok=call(view,'TryExecute');
  return null;
  })();
 }catch(error){
  // Never replay an uncertain consumption just because its response or cleanup failed.
  if(submitted)executionError=error;
  else result={status:'waiting',reason:'native_preparation_failed',step};
 }finally{
  const cleanup=(name,fn)=>{if(!touched)return;try{fn();}catch(error){cleanupIssues.push(name);}};
  cleanup('release',()=>call(view,'ReleaseAll'));
  if(popup)cleanup('close',()=>call(popup,'OnClickClose'));
  if(category!==null){
   cleanup('category',()=>{call(view,'SetCategory',[category]);call(view,'RefreshLevelRangeOptions');});
   cleanup('tier',()=>call(view,'SetSelectedTier',[tier]));
  }
  cleanup('storage',()=>call(toggle,'set_isOn',[storage]));
 }
 if(executionError)throw executionError;
 if(result)return {...result,...(cleanupIssues.length?{cleanupIssues}: {})};
 const after=inventoryItems(im).map(itemInfo),receipt=materialReceipt(before,after,selected);
 return {status:ok&&receipt.consumed.length?'confirmed':ok?'pending':'rejected',
  ...(cleanupIssues.length?{reason:'native_cleanup_incomplete',cleanupIssues}: {}),
  materials:selected,...receipt,beforeCount:before.length,afterCount:after.length,soulBefore,soulAfter:call(single('DG.Manager.CurrencyManager'),'Get',[201])};
}

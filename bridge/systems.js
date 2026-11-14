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
 return !!p&&(call(p,'get_IsLocked')||call(im,'IsInUse',[ref(p)]));
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
 const active=new Set(squad.filter(id=>id>0).slice(0,3));
 const roster=characters.filter(c=>!squad.length||active.has(c.id)).sort((a,b)=>(order.get(a.id)??squad.length)-(order.get(b.id)??squad.length)||a.id-b.id);
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
      else{const score=scorer.score(slot,candidate.item);if(!Number.isFinite(score)||score-scorer.base>Math.max(1,Math.abs(scorer.base))*1e-6)future.push({uid,requireLevel,score});}
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
 for(const plan of plans)plan.itemRevision=equipmentRevision(available.find(e=>call(e.item,'get_Uid')===plan.uid).item);
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
function storageEmptyIndex(storage,item=null){
 const perTab=call(storage,'get_SlotCountPerTab');
 return list(call(storage,'get_Has')).findIndex((p,index)=>(!p||p.isNull())&&call(storage,'IsTabUnlocked',[Math.floor(index/perTab)])&&(!item||call(storage,'CanAccept',[index,ref(item)])));
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
  const storage=call(im,'get_Storage'),index=storageEmptyIndex(storage,entry.item);
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
function socketState(p){return list(call(p,'get_Sockets')).map(s=>({index:call(s,'get_Index'),id:call(s,'get_ConfigID'),ability:call(s,'get_Ability'),value:call(s,'get_Value')}));}
function equipmentRevision(p){
 const sockets=socketState(p).sort((a,b)=>a.index-b.index||a.id-b.id||String(a.ability).localeCompare(String(b.ability))||a.value-b.value);
 return JSON.stringify([call(p,'get_Uid'),call(p,'get_ConfigID'),sockets]);
}
function equipmentContext(snapshot){
 const active=new Set((snapshot.squad||[]).filter(id=>id>0));
 return JSON.stringify(snapshot.characters.filter(c=>active.has(c.id)).flatMap(c=>(c.equipment||[]).map(e=>[c.id,e.slot,e.revision])).sort((a,b)=>a[0]-b[0]||a[1]-b[1]));
}
function equipmentContextMatches(cmd,action,snapshot){
 return !cmd.equipmentStability||(cmd.equipmentStability.schema===1&&cmd.equipmentStability.context===snapshot.equipmentContext&&cmd.itemRevision===action.itemRevision&&cmd.previousUid===action.previousUid);
}
function protectedPositions(im,characters,watched=[]){
 const watch=new Set(watched);
 const fingerprint=(p,place,index)=>({tradable:read(call(p,'get_Config'),'Tradable'),uid:call(p,'get_Uid'),id:call(p,'get_ConfigID'),place,index,count:call(p,'get_Count'),locked:call(p,'get_IsLocked'),confirmed:call(p,'get_IsServerConfirmed'),sockets:socketState(p)});
 const result=containerEntries(im).filter(e=>protectedItem(im,e.item)||watch.has(call(e.item,'get_Uid'))).map(e=>fingerprint(e.item,e.place,e.index));
 for(const c of characters)list(call(call(im,'GetEquipment',[c.id]),'get_Has')).forEach((p,index)=>{if(p&&(protectedItem(im,p)||watch.has(call(p,'get_Uid'))))result.push(fingerprint(p,'equipment:'+c.id,index));});
 return result;
}
function checkPreserved(before,after,moves=[],appends=[]){
 const positions=new Map(after.map(x=>[x.uid,x])),allowed=new Map(moves.map(m=>[m.uid,m]));
 return before.filter(x=>{
  const actual=positions.get(x.uid);if(!actual||after.filter(p=>p.uid===x.uid).length!==1)return true;
  if(JSON.stringify(actual)===JSON.stringify(x))return false;
  const append=appends.find(p=>p.uid===x.uid);
  if(append&&x.tradable===false&&!x.locked&&append.sockets.length>x.sockets.length
   &&JSON.stringify(append.sockets.slice(0,x.sockets.length))===JSON.stringify(x.sockets)
   &&JSON.stringify(actual)===JSON.stringify({...x,sockets:append.sockets}))return false;
  const move=allowed.get(x.uid);
  if(!move||!Number.isInteger(actual.index)||actual.index<0)return true;
  const index=move.index;
  return JSON.stringify(actual)!==JSON.stringify({...x,place:move.place,index});
 });
}
// Trade value is independent of container order, confirmation flags and stack UIDs.
function checkTradePreserved(before,after){
 const changed=[],positions=new Map(after.map(p=>[p.uid,p]));
 const key=p=>JSON.stringify([p.id,p.sockets]);
 const totals=rows=>{const sums=new Map();for(const p of rows)if(p.tradable===true)sums.set(key(p),(sums.get(key(p))||0)+p.count);return sums;};
 const old=totals(before),now=totals(after);
 for(const p of before.filter(p=>p.tradable===true)){
  const actual=positions.get(p.uid);
  if(actual&&actual.tradable===false)changed.push({uid:p.uid,reason:'trade_flag_lost'});
 }
 for(const [id,count] of old)if((now.get(id)||0)<count)changed.push({reason:'tradable_quantity_lost',before:count,after:now.get(id)||0});
 return changed;
}
function guardedItemAction(fn,characters,moves=[],watched=[],consuming=[],socketTarget=null){
 const im=single('DG.Item.Manager.ItemManager'),before=protectedPositions(im,characters,watched).filter(p=>!consuming.includes(p.uid));let result,error;
 try{result=fn();}catch(e){error=e;}
 const after=protectedPositions(im,characters,[...watched,...before.map(p=>p.uid)]),changed=checkPreserved(before,after,moves,!error&&result?.status==='confirmed'&&socketTarget===result.uid&&result.socketAppend?[{uid:socketTarget,sockets:result.socketAppend}]:[]),tradeChanged=checkTradePreserved(before,after);
 if(error&&!changed.length)throw error;
 if(error)result={status:'waiting',reason:'protected_state_changed_after_error',error:String(error)};
 return {...result,protectedChecked:before.length,protectedChanged:changed,tradeChanged};
}
function guardedRecycleAction(action,characters){
 const im=single('DG.Item.Manager.ItemManager');
 // Only exact, revalidated, unlocked retirement targets may lose their sockets.
 const consuming=action.kind==='decompose'&&action.recycleSocketed===true?containerEntries(im,false).filter(e=>action.allowed.includes(call(e.item,'get_Uid'))&&canRecycleItem(im,e.item,true)).map(e=>call(e.item,'get_Uid')):[];
 return guardedItemAction(()=>cubeAction(action),characters,[],[],consuming);
}
function guardedStorageAction(action,characters){
 const im=single('DG.Item.Manager.ItemManager'),entries=containerEntries(im),entry=entries.find(e=>call(e.item,'get_Uid')===action.uid),moves=[];
 const watched=entries.filter(e=>protectedItem(im,e.item)||call(e.item,'get_Uid')===action.uid||call(e.item,'get_Uid')===action.swapUid).map(e=>call(e.item,'get_Uid'));
 if(entry&&action.kind==='deposit'&&entry.place==='inventory')moves.push({uid:action.uid,place:'storage',index:storageEmptyIndex(call(im,'get_Storage'),entry.item)});
 if(entry&&action.kind==='withdraw'&&entry.place==='storage'){
  if(action.swapUid){
   const swap=entries.find(e=>call(e.item,'get_Uid')===action.swapUid&&e.place==='inventory');
   if(swap){moves.push({uid:action.uid,place:'inventory',index:swap.index});moves.push({uid:action.swapUid,place:'storage',index:entry.index});}
  }else moves.push({uid:action.uid,place:'inventory',index:call(call(im,'get_Inventory'),'FindEmptyIndex')});
 }
 return guardedItemAction(()=>storageAction(action),characters,moves,watched);
}
// Sort one native container/page at a time, after useful inventory work. No tab switching.
const itemSortMarks=new Map();
function itemSortPlans(im,withStorage=true,cooldown=30){
 const entries=containerEntries(im,withStorage),storage=call(im,'get_Storage'),perTab=call(storage,'get_SlotCountPerTab');
 const buckets=[{place:'inventory',tab:null},...(!withStorage?[]:Array.from({length:call(storage,'get_TabCount')},(_,tab)=>({place:'storage',tab})).filter(p=>call(storage,'IsTabUnlocked',[p.tab])))];
 return buckets.flatMap(p=>{
  const rows=entries.filter(e=>e.place===p.place&&(p.tab===null||Math.floor(e.index/perTab)===p.tab));
  if(!rows.length)return [];
  const signature=keyHash(rows.map(e=>e.index+':'+call(e.item,'get_Uid')+':'+call(e.item,'get_Count')).join('|'));
  const bucket=p.place+':'+p.tab,mark=itemSortMarks.get(bucket);
  return mark&&(mark.signature===signature||Date.now()-mark.at<cooldown*1000)?[]:[{...p,signature,bucket,key:'sort:'+bucket+':'+signature}];
 });
}
function sortItemsAction(action,characters=[]){
 const im=single('DG.Item.Manager.ItemManager');
 if(call(call(im,'get_Input'),'get_IsHolding')||!call(call(im,'get_Cube'),'get_IsEmpty'))return {status:'waiting',reason:'user_item_operation'};
 if(call(single('DG.UI.PopupLayoutHandler'),'get_AnyPopupOpen'))return {status:'waiting',reason:'user_popup_open'};
 const storage=call(im,'get_Storage'),perTab=call(storage,'get_SlotCountPerTab');
 if(action.place!=='inventory'&&(action.place!=='storage'||!Number.isInteger(action.tab)||action.tab<0||action.tab>=call(storage,'get_TabCount')||!call(storage,'IsTabUnlocked',[action.tab])))return {status:'stale',reason:'storage_source_changed'};
 const entries=containerEntries(im),watched=entries.map(e=>call(e.item,'get_Uid'));
 const scope=entries.filter(e=>e.place===action.place&&(action.place==='inventory'||Math.floor(e.index/perTab)===action.tab));
 const strict=new Set(entries.filter(e=>call(e.item,'get_MaxCount')<=1).map(e=>call(e.item,'get_Uid')));
 // Native stack merges are allowed when quantity, lock and trade attributes survive.
 const before=protectedPositions(im,characters,watched),positionsBefore=new Map(before.map(p=>[p.uid,p]));
 function totals(rows){
  const sums=new Map();for(const p of rows){
   if(!Number.isSafeInteger(p.count)||p.count<=0)throw Error('invalid_stack_count');
   const key=JSON.stringify([p.place,p.place==='storage'?Math.floor(p.index/perTab):null,p.id,p.tradable,p.locked,p.sockets]);
   const count=(sums.get(key)||0)+p.count;if(!Number.isSafeInteger(count))throw Error('invalid_stack_total');sums.set(key,count);
  }return JSON.stringify([...sums].sort((a,b)=>a[0].localeCompare(b[0])));
 }
 const expectedTotals=totals(before);let error;
 try{
  if(action.place==='inventory'){const inventory=call(im,'get_Inventory');call(inventory,'Sort');call(inventory,'Draw');}
  else{call(storage,'SortTab',[action.tab]);call(storage,'Draw');}
 }catch(e){error=e;}
 // Include newly created UIDs so an unexpected addition cannot evade the conservation check.
 const afterEntries=containerEntries(im),after=protectedPositions(im,characters,afterEntries.map(e=>call(e.item,'get_Uid'))),positions=new Map(after.map(e=>[e.uid,e]));
 const moves=before.flatMap(p=>{
  const next=positions.get(p.uid),inScope=p.place===action.place&&(action.place==='inventory'||Math.floor(p.index/perTab)===action.tab);
  return next&&inScope&&next.place===p.place&&(action.place==='inventory'||Math.floor(next.index/perTab)===action.tab)?[{uid:p.uid,place:p.place,index:next.index}]:[];
 });
 const strictBefore=before.filter(p=>strict.has(p.uid)||!positionsBefore.has(p.uid)||p.place.startsWith('equipment:')||p.place!==action.place||(action.place==='storage'&&Math.floor(p.index/perTab)!==action.tab));
 // Server acknowledgements may change during a legitimate sort.
 const changed=checkPreserved(strictBefore,after.map(p=>({...p,confirmed:positionsBefore.get(p.uid)?.confirmed??p.confirmed})),moves),tradeChanged=checkTradePreserved(before,after);
 if(expectedTotals!==totals(after))changed.push({reason:'item_totals_changed'});
 if(error&&!changed.length)throw error;
 if(changed.length)return {status:'waiting',reason:'sort_conservation_failed',protectedChecked:strictBefore.length,protectedChanged:changed,tradeChanged};
 // Store the post-sort layout so an unchanged container never sorts every scan.
 const rows=containerEntries(im).filter(e=>e.place===action.place&&(action.place==='inventory'||Math.floor(e.index/perTab)===action.tab));
 const signature=keyHash(rows.map(e=>e.index+':'+call(e.item,'get_Uid')+':'+call(e.item,'get_Count')).join('|'));
 itemSortMarks.set(action.bucket,{signature,at:Date.now()});
 return {status:'confirmed',source:'native_system_sort',place:action.place,tab:action.tab,protectedChecked:strictBefore.length,protectedChanged:[],tradeChanged,mergedStacks:before.length-after.length,moved:moves.filter(p=>before.find(b=>b.uid===p.uid)?.index!==p.index).length};
}
function guardedEquipmentAction(action,characters,minGainPercent=0){
 const im=single('DG.Item.Manager.ItemManager'),entry=containerEntries(im).find(e=>call(e.item,'get_Uid')===action.uid),moves=[];
 if(entry){
  moves.push({uid:action.uid,place:'equipment:'+action.id,index:action.slot});
  if(action.previousUid)moves.push({uid:action.previousUid,place:entry.place,index:entry.index});
 }
 return guardedItemAction(()=>equipAction(action,minGainPercent),characters,moves);
}
function approvedMaterials(im,ids,recycleSocketed=false){
 if(!Array.isArray(ids)||!ids.length||new Set(ids).size!==ids.length)return null;
 const entries=containerEntries(im,false).filter(e=>ids.includes(call(e.item,'get_Uid')));
 return entries.length===ids.length&&entries.every(e=>recycleSocketed?canRecycleItem(im,e.item,true):!protectedItem(im,e.item))?entries.map(e=>e.item):null;
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
 const beforeSockets=socketState(equipment),before=beforeSockets.length,toggle=call(view,'get_IncludeStorageToggle'),storage=call(toggle,'get_isOn');let ok=false,selected=[],popup;
 try{
  call(toggle,'set_isOn',[false]);popup=activateCubeView(view);call(view,'CollectSlots');call(view,'SetMode',[0]);call(view,'RebuildRules');
  if(!call(im,'TryMoveToCube',[ref(equipment)]))return {status:'waiting',reason:'equipment_not_accepted'};
  for(const item of approved)if(hasAttachmentSpace(im,equipment,item))call(im,'TryMoveToCube',[ref(item)]);
  const materials=list(call(cube,'get_Has')).filter(p=>p&&!p.isNull());selected=materials.map(itemInfo);
  if(!selected.some(p=>cmd.allowed.includes(p.uid)))return {status:'waiting',reason:'native_attachment_not_ready'};
  if(materials.some(isTradable)||selected.some(p=>p.uid!==cmd.uid&&!cmd.allowed.includes(p.uid)))return {status:'waiting',reason:'protected_refine_material'};
  ok=call(view,'TryExecute');
 }finally{call(view,'ReleaseAll');if(popup)call(popup,'OnClickClose');call(toggle,'set_isOn',[storage]);}
 const sockets=socketState(equipment),after=sockets.length,added=sockets.slice(before),counts=new Map();
 for(const p of selected.filter(p=>p.uid!==cmd.uid&&cmd.allowed.includes(p.uid)))counts.set(p.id,(counts.get(p.id)||0)+p.count);
 const valid=ok&&after>before&&JSON.stringify(sockets.slice(0,before))===JSON.stringify(beforeSockets)
  &&new Set(sockets.map(s=>s.index)).size===sockets.length&&added.every(s=>{
   const count=counts.get(s.id)||0;counts.set(s.id,count-1);
   return count>0&&Number.isInteger(s.index)&&s.index>=0&&Number.isInteger(s.ability)&&Number.isFinite(s.value);
  });
 return {status:valid?'confirmed':ok?'pending':'rejected',uid:cmd.uid,before,after,materials:selected,...(valid?{socketAppend:sockets}:{})};
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
// Native CanAccept/TryExchange decides lossless moves. Reservations still prevent conflicts.
function canMoveStoredItem(im,p){return !call(im,'IsInUse',[ref(p)])&&!call(im,'IsEquipped',[ref(p)])&&list(call(im,'FindRegistrations',[ref(p)])).length===0;}
function protectedEquipmentCandidate(im,p){return call(p,'get_IsLocked')||!canMoveStoredItem(im,p);}
// Consuming materials has stricter requirements than moving or wearing them.
function protectedConsumptionCandidate(im,p){return !canMoveStoredItem(im,p)||call(p,'get_IsLocked')||!call(p,'get_IsServerConfirmed');}
function canRecycleItem(im,p,allowSocketed=false){return [1,2,4].includes(call(p,'get_Kind'))&&!isTradable(p)&&!protectedConsumptionCandidate(im,p)&&(allowSocketed||list(call(p,'get_Sockets')).length===0);}
// The shared cube is resized by the last opened view. Read the target view's slots.
function workshopCapacity(kind){
 try{const view=sceneObject(kind==='decompose'?'DG.UI.Popup.CubeDecomposeView':'DG.UI.Popup.CubeCombineView');const count=view?list(read(view,'_slots')).length:0;return Number.isSafeInteger(count)&&count>0?count:null;}catch(error){return null;}
}
// Existing sockets are retained on an equipment swap, but never consumed as craft materials.
function protectedItem(im,p){return isTradable(p)||protectedConsumptionCandidate(im,p)||list(call(p,'get_Sockets')).length>0;}
function materialReceipt(before,after,selected){
 const old=new Map(before.map(p=>[p.uid,p])),now=new Map(after.map(p=>[p.uid,p]));
 const reserved=new Map();for(const p of selected)reserved.set(p.uid,(reserved.get(p.uid)||0)+1);
 const consumed=[...reserved].flatMap(([uid,count])=>{const item=old.get(uid);if(!item)return [];const quantity=item.count-(now.get(uid)?.count||0);return quantity>0?[{...item,count:quantity,reserved:count}]:[];});
 const produced=after.filter(p=>!old.has(p.uid)||p.count>old.get(p.uid).count).map(p=>({...p,count:p.count-(old.get(p.uid)?.count||0)}));
 return {consumed,produced};
}
function cubeAction(cmd){
 const im=single('DG.Item.Manager.ItemManager'),cube=call(im,'get_Cube');
 const recycleSocketed=cmd.kind==='decompose'&&cmd.recycleSocketed===true;
 const approved=approvedMaterials(im,cmd.allowed,recycleSocketed);
 if(!approved)return {status:'stale',reason:'protected_or_missing_material'};
 const limits=cmd.materialCounts;
 if(limits!==undefined&&(!limits||typeof limits!=='object'||Array.isArray(limits)||
   Object.keys(limits).length!==cmd.allowed.length||cmd.allowed.some(uid=>!Number.isInteger(limits[uid])||limits[uid]<=0)||
   !Number.isInteger(cmd.batchSize)||cmd.batchSize<=0||cmd.batchSize!==Object.values(limits).reduce((n,count)=>n+count,0)||
   approved.some(item=>limits[call(item,'get_Uid')]>call(item,'get_Count'))))return {status:'stale',reason:'material_quantity_changed'};
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
    const limit=limits?limits[call(item,'get_Uid')]:32;
    for(let n=0;n<limit&&call(cube,'CanReserveMore',[ref(item)]);n++)if(!call(im,'TryMoveToCube',[ref(item)]))break;
  }
  const materials=list(call(cube,'get_Has')).filter(p=>p&&!p.isNull());selected=materials.map(itemInfo);
  // Check the native reservation against the exact approved materials before consumption.
  if(!materials.length)return {status:'waiting',reason:'native_material_not_reserved'};
  if(materials.some(p=>recycleSocketed?!canRecycleItem(im,p,true):protectedItem(im,p))||selected.some(p=>!cmd.allowed.includes(p.uid)||p.grade>cmd.maxGrade))return {status:'waiting',reason:'autofill_contains_protected_material'};
   if(limits){
    const counts={};for(const item of selected)counts[item.uid]=(counts[item.uid]||0)+1;
    if(selected.length!==cmd.batchSize||cmd.allowed.some(uid=>counts[uid]!==limits[uid]))return {status:'waiting',reason:'material_quantity_changed'};
    const categories={1:0,2:0,4:1,16:2,8:3};
    if(selected.some(p=>cmd.kind==='combine'?(categories[p.kind]!==cmd.category||(p.tier<(cmd.materialMinTier??cmd.materialTier??cmd.tier)||p.tier>(cmd.materialMaxTier??cmd.materialTier??cmd.tier))||p.grade!==cmd.maxGrade):![1,2,4].includes(p.kind)))return {status:'stale',reason:'material_recipe_changed'};
   }
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

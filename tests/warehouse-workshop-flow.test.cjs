const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');

// Run the production scanner, UID lookup, transfers, reservations and receipts together.
// Only the native game and popup boundaries are modeled; no live player items are changed.
function fixture({category=2,forge=false,refine=false,capacity=6,open=[0,1,2],perTab=3}={}){
 const inventory={items:Array(capacity).fill(null),get_Has(){return this.items;},FindEmptyIndex(){return this.items.findIndex(p=>!p);}};
 const storage={items:Array(perTab*4).fill(null),get_Has(){return this.items;},get_SlotCountPerTab:()=>perTab,get_TabCount:()=>4,
  IsTabUnlocked:i=>open.includes(i),get_OccupiedCount(){return this.items.filter(Boolean).length;},
  get_IsFull(){return open.every(tab=>this.items.slice(tab*perTab,(tab+1)*perTab).every(Boolean));},
  CanAccept:(index)=>open.includes(Math.floor(index/perTab))};
 const moves=[],selected=[],equipped=[],calls=[];let soul=0,include=true,tier=1,selectedCategory=0,executed=0;
 function item(uid,{id=1001,kind=16,count=3,grade=1,tier=kind===16?0:1,tradable=false,locked=false}={}){
  const p={uid,id,kind,count,grade,tier,tradable,locked,sockets:[],isNull:()=>false,
   get_Uid(){return this.uid;},get_ConfigID(){return this.id;},get_Kind(){return this.kind;},get_Count(){return this.count;},get_MaxCount:()=>999,
   get_Config(){return {Tradable:this.tradable,Grade:this.grade,Tier:this.tier};},get_IsLocked(){return this.locked;},get_IsServerConfirmed:()=>true,
   get_Sockets(){return this.sockets;},get_EquipmentConfig:()=>({}),get_AttachmentConfig:()=>({ItemType:1})};return p;
 }
 const recipe=forge?{ID:501,CraftType:1,CraftPart:1,MinTier:1,MaxTier:1,MaterialID:[501,502,503],MaterialCount:[1,1,1],RequireCubeLevel:0}:
  {ID:601,CraftType:0,FusionType:[0,1,3,4][category],Grade:1,MinTier:category===2?0:1,MaxTier:category===2?0:1,RequireCubeLevel:0,FusionCount:9};
 const cube={get_Level:()=>50,get_IsEmpty:()=>selected.length===0,get_Has:()=>selected,
  CanReserveMore:p=>selected.length<9&&selected.filter(x=>x===p).length<p.count};
 const toggle={get_isOn:()=>include,set_isOn:x=>{include=x;}};
 function consume(p,count){
  p.count-=count;
  if(!p.count){const i=inventory.items.indexOf(p);if(i>=0)inventory.items[i]=null;}
 }
 const view={_partSlots:[{get_Part:()=>1}],get_SelectedTier:()=>tier,SetSelectedTier:x=>{tier=x;},get_SelectedCategory:()=>selectedCategory,SetCategory:x=>{selectedCategory=x;},
  get_IncludeStorageToggle:()=>toggle,RefreshLevelRangeOptions:()=>{},RebuildRules:()=>{},CollectSlots:()=>{},SelectPart:()=>{},ApplyRequirements:()=>{},get_CurrentConfig:()=>({ID:recipe.ID}),SetMode:()=>{},
  CanStartExecute:()=>true,get_CanExecute:()=>true,get_IsReady:()=>true,ReleaseAll:()=>{selected.length=0;},
  TryExecute:()=>{
   executed++;calls.push('execute');
   if(refine){const target=selected.find(p=>equipped.includes(p)),mat=selected.find(p=>!equipped.includes(p));consume(mat,1);
    target.sockets.push({get_Index:()=>0,get_ConfigID:()=>mat.id,get_Ability:()=>1,get_Value:()=>5,get_Config:()=>({ItemType:1})});return true;}
   const quantities=new Map();for(const p of selected)quantities.set(p,(quantities.get(p)||0)+1);
   for(const [p,n] of quantities)consume(p,n);
   if(view.operation==='decompose'){soul+=10;return true;}
   const index=inventory.FindEmptyIndex();assert.ok(index>=0,'modeled output must fit');
   inventory.items[index]=item('product-'+executed,{id:9001,kind:forge?1:[1,4,16,8][category],count:1,grade:2});return true;
  }};
 const im={get_Inventory:()=>inventory,get_Storage:()=>storage,get_Cube:()=>cube,get_Input:()=>({get_IsHolding:()=>false}),GetEquipment:()=>({get_Has:()=>equipped}),
  IsInUse:()=>false,IsEquipped:p=>equipped.includes(p),FindRegistrations:()=>[],CanAttach:()=>true,GetSocketCount:()=>1,
  TryMoveToCube:p=>{selected.push(p);return true;},
  TryExchange:(from,i,to,j)=>{if(to===storage&&!storage.CanAccept(j))return false;
   const p=from.items[i],old=to.items[j];moves.push({uid:p.uid,from:from===storage?'storage':'inventory',index:i,to:to===storage?'storage':'inventory',destination:j});
   from.items[i]=old;to.items[j]=p;return true;}};
 const c={api:()=>()=>0,call:(o,n,args=[])=>{if(typeof o?.[n]!=='function')throw Error('unexpected native method '+n);return o[n](...args);},read:(o,n)=>o[n],list:x=>x,ref:x=>x,keyHash:x=>x,
  single:n=>n==='DG.Manager.CurrencyManager'?{Get:()=>soul}:n==='DG.UI.PopupLayoutHandler'?{get_AnyPopupOpen:()=>false}:im};
 vm.createContext(c);vm.runInContext(fs.readFileSync(process.env.SOCKET_SYSTEMS_SOURCE||'bridge/systems.js','utf8')+'\n'+fs.readFileSync('bridge/planner.js','utf8'),c);
 c.sceneObject=()=>view;c.activateCubeView=()=>({OnClickClose:()=>{calls.push('close');}});c.workshopCapacity=()=>9;
 // Equipment scoring is independent of warehouse routing and requires native combat data.
 c.equipmentPlans=()=>[];
 c.fixtureCatalogue={recipes:refine?[]:[recipe],tiers:[{tier:1,min:1}],normalMax:160,towerMax:20,maxCharacterLevel:101};
 vm.runInContext('catalogueCache=fixtureCatalogue;',c);
 const base={modules:{forge,combine:!forge&&!refine,refine,decompose:false}};
 function scan(options={}){
  const s={characters:[{id:1,level:10}],squad:[1],record:{maxCleared:9},inventory:{count:inventory.items.filter(Boolean).length,capacity}},actions=[],issues=[];
  c.inventoryOpportunities(s,{},im,(kind,key,label,priority,data)=>actions.push({kind,key,label,priority,...data}),issues,c.bridgeStrategy({...base,...options,modules:{...base.modules,...options.modules}}));
  return {s,actions,issues};
 }
 function execute(action){
  if(['withdraw','deposit'].includes(action.kind))return c.guardedStorageAction(action,[{id:1}]);
  if(action.kind==='forge')return c.guardedItemAction(()=>c.forgeAction(action),[{id:1}]);
  if(action.kind==='refine')return c.guardedItemAction(()=>c.refineAction(action),[{id:1}],[],[],[],action.uid,action.allowTradableTarget);
  view.operation=action.kind;return c.guardedRecycleAction(action,[{id:1}]);
 }
 return {c,item,inventory,storage,recipe,moves,selected,equipped,view,calls,scan,execute,executed:()=>executed,include:()=>include};
}

function preparedConsumption(kind){
 const f=fixture({forge:kind==='forge',refine:kind==='refine'});
 if(kind==='forge'){
  for(let i=0;i<3;i++)f.inventory.items[i]=f.item('ore-'+i,{id:501+i,kind:8,count:1});
 }else if(kind==='refine'){
  f.inventory.items[0]=f.item('attachment',{count:2});f.equipped.push(f.item('target',{kind:1,count:1}));
 }else if(kind==='decompose'){
  f.inventory.items[0]=f.item('obsolete',{kind:1,count:1});f.c.fixtureCatalogue.tiers.push({tier:2,min:10});
 }else f.inventory.items[0]=f.item('material',{count:9});
 const options=kind==='decompose'?{modules:{combine:false,decompose:true}}:{};
 const action=f.scan(options).actions.find(a=>a.kind===kind);assert.ok(action);
 return {f,action};
}

for(const kind of ['combine','forge','refine','decompose']){
 test(kind+' retains a pending receipt when native false contradicts observed mutation',()=>{
  const {f,action}=preparedConsumption(kind),execute=f.view.TryExecute;
  f.view.TryExecute=()=>{execute();return false;};
  const r=f.execute(action);assert.equal(r.status,'pending');assert.equal(r.reason,kind+'_result_unconfirmed');
  assert.ok(r.consumed.length);assert.equal(f.selected.length,0);assert.equal(f.include(),true);
 });
 test(kind+' releases an explicit native rejection without inventory mutation',()=>{
  const {f,action}=preparedConsumption(kind);f.view.TryExecute=()=>false;
  const r=f.execute(action);assert.equal(r.status,'rejected');assert.equal(r.consumed.length,0);
  assert.equal(f.selected.length,0);assert.equal(f.include(),true);
 });
}

for(const [category,name] of ['equipment','accessory','refinement materials','craft materials'].entries())test(name+' gathers a batch from three unlocked warehouse pages and executes once',()=>{
 const f=fixture({category}),kind=[1,4,16,8][category];
 for(const [n,index] of [0,4,8].entries())f.storage.items[index]=f.item('input-'+n,{kind});
 f.storage.items[10]=f.item('locked-page',{kind,count:9});
 let result;
 for(let step=0;step<6;step++){
  const {s,actions}=f.scan();assert.equal(s.storage.capacity,9);
  assert.ok(!actions.some(a=>(a.allowed||[]).includes('locked-page')||a.uid==='locked-page'));
  const action=actions.find(a=>a.kind==='combine')||actions.find(a=>a.kind==='withdraw');assert.ok(action);
  result=f.execute(action);assert.equal(result.status,'confirmed');assert.deepEqual(Array.from(result.protectedChanged),[]);assert.deepEqual(Array.from(result.tradeChanged),[]);
  if(action.kind==='combine')break;
 }
 assert.equal(f.executed(),1);assert.equal(result.consumed.reduce((n,p)=>n+p.count,0),9);assert.equal(result.produced.length,1);
 assert.deepEqual(f.moves.filter(m=>m.from==='storage').map(m=>m.index).sort((a,b)=>a-b),[0,4,8]);
 assert.equal(f.storage.items[10].count,9);assert.equal(f.selected.length,0);assert.equal(f.include(),true);
});

test('forge gathers each distinct ingredient from its warehouse page and preserves other recipes',()=>{
 const f=fixture({forge:true});for(const [n,index] of [0,4,8].entries())f.storage.items[index]=f.item('ore-'+n,{id:501+n,kind:8,count:1});
 f.storage.items[9]=f.item('locked-ore',{id:501,kind:8,count:99});
 let receipt;
 for(let step=0;step<6;step++){
  const {actions}=f.scan(),action=actions.find(a=>a.kind==='forge')||actions.find(a=>a.kind==='withdraw');assert.ok(action);
  const r=f.execute(action);assert.equal(r.status,'confirmed');if(action.kind==='forge'){receipt=r;break;}
 }
 assert.equal(f.executed(),1);assert.equal(receipt.consumed.length,3);assert.equal(receipt.produced.length,1);
 assert.deepEqual(f.moves.map(m=>m.index).sort((a,b)=>a-b),[0,4,8]);assert.equal(f.storage.items[9].count,99);
});

test('refinement recalls a later-page attachment and appends exactly one socket',()=>{
 const f=fixture({refine:true});f.storage.items[8]=f.item('attachment',{count:2});f.equipped.push(f.item('target',{kind:1,count:1}));
 let action=f.scan().actions.find(a=>a.kind==='withdraw');assert.ok(action);assert.equal(action.purpose,'refine');assert.equal(f.execute(action).status,'confirmed');
 action=f.scan().actions.find(a=>a.kind==='refine');assert.ok(action);const r=f.execute(action);
 assert.equal(r.status,'confirmed');assert.equal(r.consumed[0].count,1);assert.equal(f.equipped[0].sockets.length,1);assert.deepEqual(Array.from(r.protectedChanged),[]);
 assert.equal(f.moves[0].index,8);assert.equal(f.include(),true);
});

test('retirement recalls a later-page obsolete item without consuming crafting stock',()=>{
 const f=fixture(),old=f.item('obsolete',{kind:1,count:1}),material=f.item('craft-stock',{kind:8,count:2});f.storage.items[8]=old;f.storage.items[4]=material;
 f.c.fixtureCatalogue.tiers.push({tier:2,min:10});
 const options={modules:{combine:false,decompose:true}};
 let action=f.scan(options).actions.find(a=>a.kind==='withdraw');assert.equal(action.uid,'obsolete');assert.equal(action.purpose,'recycle');assert.equal(f.execute(action).status,'confirmed');
 action=f.scan(options).actions.find(a=>a.kind==='decompose');assert.ok(action);assert.equal(f.execute(action).status,'confirmed');assert.equal(material.count,2);
});

test('deposits skip full and locked pages; UID lookup follows a reordered later-page item',()=>{
 const f=fixture({open:[0,2]});for(let i=0;i<3;i++)f.storage.items[i]=f.item('full-'+i);
 f.inventory.items[0]=f.item('move',{tradable:true});let r=f.execute({kind:'deposit',uid:'move'});assert.equal(r.status,'confirmed');assert.equal(f.moves[0].destination,6);
 f.storage.items[8]=f.storage.items[6];f.storage.items[6]=null;
 r=f.execute({kind:'withdraw',uid:'move'});assert.equal(r.status,'confirmed');assert.equal(f.moves[1].index,8);assert.deepEqual(Array.from(r.protectedChanged),[]);
});

test('full containers exchange a protected idle item for a later-page batch and finish synthesis',()=>{
 const f=fixture({capacity:2,perTab:1});f.inventory.items[0]=f.item('held',{count:4});f.inventory.items[1]=f.item('trade',{kind:1,count:1,tradable:true});
 f.storage.items[0]=f.item('safe-other',{kind:8,count:1});f.storage.items[1]=f.item('protected-other',{kind:1,count:1,locked:true});f.storage.items[2]=f.item('batch',{count:5});
 let action=f.scan().actions.find(a=>a.kind==='withdraw');assert.equal(action.uid,'batch');assert.equal(action.swapUid,'trade');let r=f.execute(action);assert.equal(r.status,'confirmed');assert.deepEqual(Array.from(r.protectedChanged),[]);
 action=f.scan().actions.find(a=>a.kind==='combine');assert.ok(action);r=f.execute(action);assert.equal(r.status,'confirmed');assert.equal(f.storage.items[2].uid,'trade');assert.equal(f.storage.items[2].tradable,true);
});

for(const options of [{storage_withdraw:false},{storage_withdraw_combine:false},{combine_use_storage:false},{modules:{storage:false}}])test('disabled warehouse route cannot reserve or recall later-page fusion materials: '+JSON.stringify(options),()=>{
 const f=fixture();f.storage.items[8]=f.item('later',{count:9});const r=f.scan(options);
 assert.equal(r.s.inventoryFlow.recipeReserved,0);assert.ok(!r.actions.some(a=>['combine','withdraw'].includes(a.kind)));assert.equal(f.moves.length,0);
});

for(const kind of ['combine','decompose'])for(const amount of [1,8,10])test(kind+' does not confirm partial or excessive consumption '+amount,()=>{
 const f=fixture(),p=f.item('stack',{count:20,kind:kind==='combine'?16:1});f.inventory.items[0]=p;
 f.view.TryExecute=()=>{p.count-=amount;f.inventory.items[1]=f.item('result',{count:1});return true;};
 const cmd={kind,category:2,tier:0,maxGrade:1,allowed:['stack'],materialCounts:{stack:9},batchSize:9};
 const r=f.execute(cmd);assert.equal(r.status,'pending');assert.equal(r.reason,kind+'_result_unconfirmed');assert.equal(p.count,20-amount);assert.equal(f.selected.length,0);assert.equal(f.include(),true);
});

test('synthesis waits for its product even when all approved materials disappeared',()=>{
 const f=fixture(),p=f.item('stack',{count:9});f.inventory.items[0]=p;f.view.TryExecute=()=>{f.inventory.items[0]=null;return true;};
 const r=f.execute({kind:'combine',category:2,tier:0,maxGrade:1,allowed:['stack'],materialCounts:{stack:9},batchSize:9});
 assert.equal(r.status,'pending');assert.equal(r.reason,'combine_result_unconfirmed');assert.equal(r.produced.length,0);
});


function socket(id,type=2,index=0,value=6){return {get_Index:()=>index,get_ConfigID:()=>id,get_Ability:()=>2,get_Value:()=>value,get_Config:()=>({ItemType:type})};}
function mixedRefine(){
 const f=fixture({refine:true});f.inventory.items[0]=f.item('attachment',{id:410301,count:2});
 const target=f.item('target',{id:1050605,kind:1,count:1});target.sockets=[socket(420401)];f.equipped.push(target);
 const action=f.scan().actions.find(a=>a.kind==='refine');assert.ok(action);return {f,target,action};
}
test('refine confirms category-local index zero and preserves old sockets after native reordering',()=>{
 const {f,target,action}=mixedRefine(),execute=f.view.TryExecute;
 f.view.TryExecute=()=>{const ok=execute();target.sockets.reverse();return ok;};
 const r=f.execute(action);assert.equal(r.status,'confirmed');assert.equal(f.executed(),1);
 assert.equal(r.consumed[0].count,1);assert.deepEqual(Array.from(r.protectedChanged),[]);
 assert.deepEqual(Array.from(r.tradeChanged),[]);assert.equal(target.sockets.length,2);
});
for(const [name,mutate] of [
 ['same category and index',({target})=>{target.sockets[0]=socket(420401,1);}],
 ['old socket value changed',({target})=>{target.sockets[0]=socket(420401,2,0,99);}],
 ['old socket removed',({target})=>{target.sockets.shift();}],
 ['wrong new material',({target})=>{target.sockets[1]=socket(999,1);}],
 ['extra material consumed',({f})=>{f.inventory.items[0]=null;}],
 ['unexpected product',({f})=>{f.inventory.items[1]=f.item('unexpected',{count:1});}],
 ['socket type unavailable',({target})=>{target.sockets[1].get_Config=()=>{throw Error('native type unavailable');};}]
])test('refine keeps native mutation pending when '+name,()=>{
 const setup=mixedRefine(),{f}=setup,execute=f.view.TryExecute;
 f.view.TryExecute=()=>{const ok=execute();mutate(setup);return ok;};
 const r=f.execute(setup.action);assert.equal(r.status,'pending');assert.equal(r.reason,'refine_result_unconfirmed');assert.equal(f.executed(),1);
});

function pendingSocketReceipt(){
 const setup=mixedRefine(),{f,target,action}=setup,validate=f.c.refineSocketsConfirmed,execute=f.view.TryExecute;
 f.c.refineSocketsConfirmed=()=>false;f.view.TryExecute=()=>{const ok=execute();target.sockets.reverse();return ok;};
 const result={...f.execute(action),action};f.c.refineSocketsConfirmed=validate;
 assert.equal(result.status,'pending');assert.equal(result.protectedChanged.length,1);
 return {...setup,receipt:{kind:'refine',requestId:'old-native-request',account:'fixture',key:action.key,signature:'a'.repeat(64),at:100,result}};
}
function restoredSocketJournal(setup){
 const next=fixture({refine:true}),messages=[];next.equipped.push(setup.target);
 Object.assign(next.c,{rpc:{exports:{}},withManagedThread:()=>({}),onMain:fn=>fn(),jsonSafe:x=>JSON.parse(JSON.stringify(x)),
  Checksum:{compute:()=> 'a'.repeat(64)},send:m=>messages.push(JSON.parse(JSON.stringify(m))),stat:()=> 'C:\\saves\\fixture'});
 const native=next.c.call;next.c.call=(o,n,args)=>{assert.match(n,/^(get_|GetEquipment$)/,'receipt query must only read native state');return native(o,n,args);};
 vm.runInContext(fs.readFileSync('bridge/automation.js','utf8'),next.c);
 next.c.executeAction=()=>{throw Error('must not execute a native action during recovery');};
 const api=next.c.rpc.exports;api.restoreworkshopreceipts([setup.receipt]);
 const query={requestId:setup.receipt.requestId,account:'fixture',kind:'refine',key:setup.receipt.key};
 return {next,api,query,messages};
}
test('restored pending refinement uses exact persisted consumption and read-only native socket evidence once',()=>{
 const setup=pendingSocketReceipt(),{api,query,messages}=restoredSocketJournal(setup);
 const r=api.workshopreceipt(query);assert.equal(r.result.status,'confirmed');assert.equal(messages.length,1);
 assert.equal(messages[0].receipt.result.status,'confirmed');assert.equal(r.result.recoveryEvidence.originalStatus,'pending');
 assert.equal(r.result.recoveryEvidence.originalProtectedChanged.length,1);assert.deepEqual(Array.from(r.result.protectedChanged),[]);
 assert.equal(api.workshopreceipt(query).result.status,'confirmed');assert.equal(messages.length,1);assert.equal(setup.f.executed(),1);
 const again=restoredSocketJournal({...setup,receipt:r});assert.equal(again.api.workshopreceipt(again.query).result.status,'confirmed');assert.equal(again.messages.length,0);
});
for(const [name,mutate] of [
 ['account changed',s=>{s.receipt.account='other';}],
 ['target uid changed',s=>{s.target.uid='other';}],
 ['equipment config changed',s=>{s.target.id=999;}],
 ['target slot changed',s=>{s.receipt.result.action.slot=1;}],
 ['target locked',s=>{s.target.locked=true;}],
 ['target tradable',s=>{s.target.tradable=true;}],
 ['target not confirmed',s=>{s.target.get_IsServerConfirmed=()=>false;}],
 ['old revision changed',s=>{const r=JSON.parse(s.receipt.result.action.itemRevision);r[2][0].value=99;s.receipt.result.action.itemRevision=JSON.stringify(r);}],
 ['wrong consumption uid',s=>{s.receipt.result.consumed[0].uid='other';}],
 ['double consumption',s=>{s.receipt.result.consumed[0].count=2;}],
 ['missing consumption protection',s=>{delete s.receipt.result.consumed[0].locked;}],
 ['unexpected product',s=>{s.receipt.result.produced.push({id:999});}],
 ['other protected difference',s=>{s.receipt.result.protectedChanged.push({uid:'other'});}],
 ['target protection changed',s=>{s.receipt.result.protectedChanged[0].count=2;}],
 ['trade difference',s=>{s.receipt.result.tradeChanged.push({reason:'trade_flag_lost'});}],
 ['selected material changed',s=>{s.receipt.result.materials[1].id=999;}],
 ['malformed allowed',s=>{s.receipt.result.action.allowed={length:1,0:'attachment'};}],
 ['malformed revision',s=>{s.receipt.result.action.itemRevision='{broken';}],
 ['malformed consumption',s=>{s.receipt.result.consumed=[null];}],
 ['missing original result',s=>{s.receipt.result={status:'pending',reason:'refine_result_unconfirmed'};}],
 ['unavailable socket type',s=>{s.target.sockets[0].get_Config=()=>{throw Error('unavailable');};}]
])test('pending refinement remains reserved when '+name,()=>{
 const setup=pendingSocketReceipt();mutate(setup);const {api,query,messages}=restoredSocketJournal(setup);
 // A mismatched query remains invisible, all other inconsistent evidence stays pending.
 const r=api.workshopreceipt(query);assert.ok(r===null||r.result.status==='pending');assert.equal(messages.length,0);assert.equal(setup.f.executed(),1);
});
test('socket preservation compares fields regardless of serialized property order',()=>{
 const f=fixture();assert.deepEqual(Array.from(f.c.remainingSockets([{index:0,id:1,ability:2,value:3}],[{value:3,ability:2,id:1,index:0}])),[]);
});


test('immortal equipment refines from later warehouse pages without changing its old sockets or trade flag',()=>{
 const f=fixture({refine:true}),old=socket(420401),target=f.item('immortal',{kind:1,count:1,grade:7,tradable:true});
 target.sockets=[old];f.equipped.push(target);f.storage.items[7]=f.item('attachment',{id:410301,count:1});
 const move=f.scan().actions.find(a=>a.kind==='withdraw');assert.ok(move);assert.equal(f.execute(move).status,'confirmed');
 const action=f.scan().actions.find(a=>a.kind==='refine');assert.ok(action);const r=f.execute(action);
 assert.equal(r.status,'confirmed');assert.equal(r.protectedChanged.length,0);assert.equal(r.tradeChanged.length,0);
 assert.equal(target.sockets[0],old);assert.equal(target.tradable,true);assert.equal(f.executed(),1);
});
function pendingTradableSocketReceipt(){
 const setup=mixedRefine();setup.target.grade=7;setup.target.tradable=true;
 setup.action=setup.f.scan().actions.find(a=>a.kind==='refine');assert.ok(setup.action?.allowTradableTarget);
 const validate=setup.f.c.refineSocketsConfirmed;setup.f.c.refineSocketsConfirmed=()=>false;
 const result={...setup.f.execute(setup.action),action:setup.action};setup.f.c.refineSocketsConfirmed=validate;
 assert.equal(result.status,'pending');assert.equal(result.protectedChanged.length,1);assert.equal(result.tradeChanged.length,0);
 return {...setup,receipt:{kind:'refine',requestId:'immortal-request',account:'fixture',key:setup.action.key,signature:'a'.repeat(64),at:100,result}};
}
test('pending immortal append resolves once from persisted authorization and read-only evidence',()=>{
 const setup=pendingTradableSocketReceipt(),{api,query,messages}=restoredSocketJournal(setup);
 const r=api.workshopreceipt(query);assert.equal(r.result.status,'confirmed');assert.equal(r.result.tradeChanged.length,0);
 assert.equal(api.workshopreceipt(query).result.status,'confirmed');assert.equal(messages.length,1);assert.equal(setup.f.executed(),1);
});
for(const [name,mutate] of [
 ['permission removed',s=>{s.receipt.result.action.allowTradableTarget=false;}],
 ['grade increased',s=>{s.target.grade=8;}],
 ['grade changed',s=>{s.target.grade=6;}],
 ['trade flag changed',s=>{s.target.tradable=false;}],
 ['selected grade changed',s=>{s.receipt.result.materials[0].grade=6;}],
 ['authorization evidence removed',s=>{delete s.receipt.result.tradableTargetAuthorized;}]
])test('immortal receipt stays pending when '+name,()=>{
 const setup=pendingTradableSocketReceipt();mutate(setup);const {api,query,messages}=restoredSocketJournal(setup);
 assert.equal(api.workshopreceipt(query).result.status,'pending');assert.equal(messages.length,0);assert.equal(setup.f.executed(),1);
});


test('relief keeps depositing below the pressure line and stops at the low-water target',()=>{
 const f=fixture({capacity:10});
 for(let i=0;i<8;i++)f.inventory.items[i]=f.item('held-'+i,{kind:8,count:1,tradable:true});
 const options={modules:{combine:false}};
 let scan=f.scan(options);assert.equal(scan.s.inventoryFlow.relief.active,true);
 for(const remaining of [7,6]){
  const deposit=scan.actions.find(a=>a.kind==='deposit');assert.ok(deposit);
  const r=f.execute(deposit);assert.equal(r.status,'confirmed');assert.equal(r.protectedChanged.length,0);assert.equal(r.tradeChanged.length,0);
  scan=f.scan(options);assert.equal(scan.s.inventory.count,remaining);
  assert.equal(scan.s.inventoryFlow.relief.active,remaining>6);
 }
 assert.ok(!scan.actions.some(a=>a.kind==='deposit'));assert.equal(f.storage.items.filter(Boolean).length,2);
 assert.equal(f.storage.items.filter(Boolean).every(p=>p.tradable),true);
});

test('an incomplete forge can stage its retained ingredients without discarding their reservation',()=>{
 const f=fixture({forge:true,capacity:3});
 f.inventory.items[0]=f.item('ore',{id:501,kind:8,count:1});
 f.inventory.items[1]=f.item('trade',{kind:1,count:1,tradable:true});
 let stagedOre=false;
 for(let step=0;step<3;step++){
  const scan=f.scan();assert.equal(scan.s.forging.status,'materials_missing');
  assert.equal(scan.s.inventoryFlow.relief.active,true);
  const a=scan.actions.find(a=>a.kind==='deposit');assert.ok(a);
  stagedOre ||= a.uid==='ore';assert.equal(f.execute(a).status,'confirmed');
  if(!f.inventory.items.some(Boolean))break;
 }
 assert.equal(stagedOre,true);assert.equal(f.storage.items.find(p=>p?.uid==='ore').count,1);
 assert.ok(!f.scan().actions.some(a=>['combine','decompose'].includes(a.kind)));
});

test('pressure recycling consumes only surplus gear after complete synthesis batches are reserved',()=>{
 const f=fixture({category:0,capacity:4});
 f.inventory.items[0]=f.item('fusion',{kind:1,count:9});
 f.inventory.items[1]=f.item('surplus',{kind:1,count:1});
 f.inventory.items[2]=f.item('trade',{kind:1,count:1,tradable:true});
 f.inventory.items[3]=f.item('locked',{kind:1,count:1,locked:true});
 let scan=f.scan({modules:{decompose:true}});
 const combine=scan.actions.find(a=>a.kind==='combine');assert.ok(combine);
 assert.deepEqual(Array.from(combine.allowed),['fusion']);
 const recycle=scan.actions.find(a=>a.kind==='decompose');assert.ok(recycle);
 assert.deepEqual(Array.from(recycle.allowed),['surplus']);
 assert.equal(f.execute(combine).status,'confirmed');
 scan=f.scan({modules:{decompose:true}});
 // This fixture has no equipment upgrades, so its ordinary output is idle too.
 const next=scan.actions.find(a=>a.kind==='decompose');assert.ok(next);assert.deepEqual(Array.from(next.allowed),['surplus','product-1']);
 assert.equal(f.execute(next).status,'confirmed');
 assert.equal(f.inventory.items.find(p=>p?.uid==='trade').tradable,true);
 assert.equal(f.inventory.items.find(p=>p?.uid==='locked').locked,true);
 const deposit=f.scan({modules:{decompose:true}}).actions.find(a=>a.kind==='deposit');assert.ok(deposit);
 assert.equal(f.execute(deposit).status,'confirmed');
 assert.ok(!f.scan({modules:{decompose:true}}).s.inventoryFlow.relief.active);
});


test('no cleanup route permits one box for missing ingredients and rechecks after occupancy changes',()=>{
 const f=fixture({capacity:10,open:[0],perTab:1});
 for(let i=0;i<8;i++)f.inventory.items[i]=f.item('kept-'+i,{kind:8,count:1,tradable:true});
 f.storage.items[0]=f.item('warehouse-full',{kind:8,count:1,tradable:true});
 const modules={forge:false,combine:false,refine:false,decompose:false},strategy=f.c.bridgeStrategy({modules});
 const scan=f.scan({modules});assert.equal(scan.s.inventoryFlow.relief.blocked,true);
 const boxes=s=>{const actions=[];f.c.boxOpportunities(s,{Count:()=>5},(...a)=>actions.push(a),strategy);return actions;};
 assert.equal(boxes(scan.s).length,3);assert.equal(scan.s.boxes.openableSlots,1);
 assert.equal(scan.s.boxes.relief.blocked,true);
 const changed={...scan.s,inventory:{count:9,capacity:10}};
 assert.equal(boxes(changed).length,0);assert.equal(changed.boxes.relief.blocked,false);
 f.inventory.items[8]=f.item('new-item',{kind:8,count:1,tradable:true});
 const next=f.scan({modules}).s;assert.ok(boxes(next).length);assert.equal(next.boxes.openableSlots,1);
 strategy.box_free_slots=1;assert.equal(boxes(next).length,0);
 assert.equal(f.moves.length,0);assert.equal(f.executed(),0);
});

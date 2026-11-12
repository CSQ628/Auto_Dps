const fs=require('node:fs');
const vm=require('node:vm');
const test=require('node:test');
const assert=require('node:assert/strict');

function fixture(){
 const mutations=[];
 const item=(uid,tradable=false)=>({isNull:()=>false,uid,config:{Tradable:tradable,Grade:1,Tier:1},
  get_Config(){return this.config;},get_Uid(){return uid;},get_IsLocked(){return !!this.locked;},get_IsServerConfirmed(){return this.confirmed!==false;},
  get_Sockets(){return this.sockets||[];},get_ConfigID(){return 1;},get_Count(){return this.count??1;},get_MaxCount(){return this.maxCount??1;},CanStackWith(other){return this.maxCount>1&&other.maxCount>1&&this.get_ConfigID()===other.get_ConfigID();},get_Kind(){return 1;}});
 const inventory={items:[],get_Has(){return this.items;},FindEmptyIndex(){return this.items.length;}};
 const storage={items:Array(49).fill(null),get_Has(){return this.items;},get_SlotCountPerTab:()=>49,get_TabCount(){return Math.ceil(this.items.length/49);},IsTabUnlocked:()=>true,CanAccept:()=>true};
 const equipment={items:[],get_Has(){return this.items;}};
 const popup={get_AnyPopupOpen:()=>false},clock={now:0};
 const im={get_Inventory:()=>inventory,get_Storage:()=>storage,GetEquipment:()=>equipment,get_Cube:()=>({get_IsEmpty:()=>true}),
  get_Input:()=>({get_IsHolding:()=>false}),IsInUse:p=>!!p.inUse,IsEquipped:p=>!!p.equipped,FindRegistrations:p=>p.registered?[1]:[],
  TryExchange:(from,i,to,j)=>{mutations.push('exchange');const old=to.items[j]||null;to.items[j]=from.items[i];from.items[i]=old;return true;},
  TryMoveToStorage:(from,i,p)=>{mutations.push('deposit');storage.items.push(p);from.items[i]=null;return true;}};
 const context={Date:{now:()=>clock.now},keyHash:x=>x,api:()=>()=>0,list:x=>x,read:(o,n)=>o[n],single:n=>n==='DG.UI.PopupLayoutHandler'?popup:im,ref:p=>p,sceneObject:()=>({}),
  call:(o,n,args=[])=>{if(typeof o[n]!=='function')throw Error('unexpected native call '+n);return o[n](...args);}};
 vm.createContext(context);
 vm.runInContext(fs.readFileSync('bridge/systems.js','utf8')+'\nglobalThis.sceneObject=()=>({});globalThis.subject={protectedItem,storageAction,equipAction,forgeAction,refineAction,cubeAction,approvedMaterials,checkPreserved,guardedItemAction,protectedEquipmentCandidate,protectedEquipped,canMoveStoredItem,guardedStorageAction,itemSortPlans,sortItemsAction};',context);
 return {item,inventory,storage,equipment,im,mutations,popup,clock,...context.subject};
}

test('tradable items transfer in both directions without authorizing consumption',()=>{
 const f=fixture(),p=f.item('sellable',true);f.inventory.items=[p];
 assert.equal(f.protectedItem(f.im,p),true);
 for(const kind of ['deposit','withdraw']){
  const result=f.guardedStorageAction({kind,uid:'sellable'},[]);
  assert.equal(result.status,'confirmed');assert.equal(result.tradable,true);assert.equal(result.protectedChanged.length,0);
  assert.equal(f.approvedMaterials(f.im,['sellable']),null);
 }
 assert.equal(p.config.Tradable,true);assert.equal(f.inventory.items[1],p);
});

test('tradable candidate is eligible for equipment while remaining a protected material',()=>{
 const f=fixture(),p=f.item('sellable',true);assert.equal(f.protectedEquipmentCandidate(f.im,p),false);assert.equal(f.protectedItem(f.im,p),true);
});

test('tradable equipped item can be exchanged without authorizing material consumption',()=>{
 const f=fixture(),p=f.item('sellable-equipped',true);assert.equal(f.protectedEquipped(f.im,p),false);assert.equal(f.protectedItem(f.im,p),true);
});

test('bulk auto equip is absent from the execution path',()=>{
 assert.doesNotMatch(fs.readFileSync('bridge/automation.js','utf8'),/['"]AutoEquip['"]/);
});

for(const kind of ['combine','decompose','forge','refine'])test(kind+' rejects trade materials before any reservation',()=>{
 const f=fixture();f.inventory.items=[f.item('trade',true)];
 const action={kind,allowed:['trade'],uid:'target',id:1};
 const result=kind==='forge'?f.forgeAction(action):kind==='refine'?f.refineAction(action):f.cubeAction(action);
 assert.equal(result.reason,'protected_or_missing_material');assert.deepEqual(f.mutations,[]);
});

test('unknown trade status is protected, and stale material lists fail closed',()=>{
 const f=fixture(),p=f.item('unknown');p.config.Tradable=undefined;f.inventory.items=[p,f.item('safe')];
 assert.equal(f.protectedItem(f.im,p),true);
 assert.equal(f.approvedMaterials(f.im,['unknown']),null);
 assert.equal(f.approvedMaterials(f.im,['safe','missing']),null);
 assert.equal(f.approvedMaterials(f.im,['safe','safe']),null);
});

test('preservation comparison catches location, count and disappearance',()=>{
 const f=fixture(),before=[{uid:'trade',place:'storage',index:3,count:2,sockets:0}];
 assert.equal(f.checkPreserved(before,[{...before[0]}]).length,0);
 for(const after of [[],[{...before[0],index:4}],[{...before[0],count:1}]])assert.equal(f.checkPreserved(before,after).length,1);
});

test('a native exception does not bypass the preservation check',()=>{
 const f=fixture(),p=f.item('trade',true);f.inventory.items=[p];
 const result=f.guardedItemAction(()=>{f.inventory.items=[];throw Error('native_failure');},[]);
 assert.equal(result.protectedChanged.length,1);assert.equal(result.reason,'protected_state_changed_after_error');
});

const socket=(id=10)=>({get_Index:()=>0,get_ConfigID:()=>id,get_Ability:()=>2,get_Value:()=>3});
test('socketed nontrade items transfer with sockets intact and remain protected materials',()=>{
 const f=fixture(),p=f.item('socketed');p.sockets=[socket()];f.inventory.items=[p];
 for(const kind of ['deposit','withdraw']){
  const result=f.guardedStorageAction({kind,uid:p.uid},[]);
  assert.equal(result.status,'confirmed');assert.equal(result.protectedChecked,1);assert.equal(result.protectedChanged.length,0);
  assert.equal(f.approvedMaterials(f.im,[p.uid]),null);
 }
});
test('storage transfer refuses locked, in-use, equipped, registered, unconfirmed or unknown items',()=>{
 for(const state of ['locked','inUse','equipped','registered','unconfirmed','unknown'])for(const kind of ['deposit','withdraw']){
  const f=fixture(),p=f.item('blocked',true);
  if(state==='unconfirmed')p.confirmed=false;else if(state==='unknown')delete p.config.Tradable;else p[state]=true;
  (kind==='deposit'?f.inventory:f.storage).items=[p];
  assert.equal(f.canMoveStoredItem(f.im,p),false);
  assert.equal(f.guardedStorageAction({kind,uid:p.uid},[]).status,'stale');assert.deepEqual(f.mutations,[]);
 }
});
test('transfer guard catches flag, count, socket, lock and unrelated location changes',()=>{
 for(const tamper of ['flag','count','socket','lock','other']){
  const f=fixture(),p=f.item('move',true),other=f.item('other');p.sockets=[socket()];other.sockets=[socket()];f.inventory.items=[p,other];
  const deposit=f.im.TryExchange;
  f.im.TryExchange=(...args)=>{const result=deposit(...args);
   if(tamper==='flag')p.config.Tradable=false;else if(tamper==='count')p.count=2;else if(tamper==='socket')p.sockets=[socket(20)];else if(tamper==='lock')p.locked=true;else {f.inventory.items[2]=other;f.inventory.items[1]=null;}
   return result;
  };
  assert.equal(f.guardedStorageAction({kind:'deposit',uid:p.uid},[]).protectedChanged.length,1,tamper);
 }
});
test('full containers exchange a protected idle item for a recipe material and check both positions',()=>{
 const f=fixture(),p=f.item('recipe'),spare=f.item('spare',true);spare.sockets=[socket()];
 f.storage.items=[null,null,p];f.inventory.items=[spare];f.inventory.FindEmptyIndex=()=>-1;
 const result=f.guardedStorageAction({kind:'withdraw',uid:p.uid,swapUid:spare.uid},[]);
 assert.equal(result.status,'confirmed');assert.equal(result.protectedChecked,2);assert.equal(result.protectedChanged.length,0);
 assert.equal(f.inventory.items[0],p);assert.equal(f.storage.items[2],spare);assert.equal(f.approvedMaterials(f.im,[spare.uid]),null);
});
test('a changed swap item and user drag state reject storage before mutation',()=>{
 for(const mutate of [f=>{f.inventory.items[0].locked=true;},f=>{f.inventory.items=[];},f=>{f.im.get_Input=()=>({get_IsHolding:()=>true});}]){
  const f=fixture();f.inventory.items=[f.item('spare',true)];f.storage.items=[f.item('recipe')];mutate(f);
  assert.notEqual(f.guardedStorageAction({kind:'withdraw',uid:'recipe',swapUid:'spare'},[]).status,'confirmed');assert.deepEqual(f.mutations,[]);
 }
});
test('a stale direction or full inventory never claims a storage move',()=>{
 const f=fixture();f.storage.items=[f.item('stored')];f.inventory.FindEmptyIndex=()=>-1;
 assert.equal(f.storageAction({kind:'deposit',uid:'stored'}).reason,'storage_source_changed');
 assert.equal(f.storageAction({kind:'withdraw',uid:'stored'}).reason,'inventory_full');assert.deepEqual(f.mutations,[]);
});


test('deposit uses an empty unlocked slot instead of native automatic stack merging',()=>{
 const f=fixture(),p=f.item('moving'),stack=f.item('existing');stack.count=3;f.inventory.items=[p];f.storage.items=[stack,null];
 f.im.TryMoveToStorage=()=>{throw Error('auto_merge_forbidden');};
 const result=f.guardedStorageAction({kind:'deposit',uid:p.uid},[]);
 assert.equal(result.status,'confirmed');assert.equal(result.protectedChanged.length,0);
 assert.equal(f.storage.items[0],stack);assert.equal(f.storage.items[1],p);assert.equal(stack.get_Count()+p.get_Count(),4);
});
test('empty slots in locked warehouse tabs are not deposit destinations',()=>{
 const f=fixture();f.inventory.items=[f.item('moving')];f.storage.items=Array(98).fill(null);
 for(let i=0;i<49;i++)f.storage.items[i]=f.item('held-'+i);f.storage.IsTabUnlocked=tab=>tab===0;
 const result=f.guardedStorageAction({kind:'deposit',uid:'moving'},[]);assert.equal(result.reason,'storage_full');assert.deepEqual(f.mutations,[]);
});

test('deposit skips a filtered first tab and finds a compatible empty slot on another unlocked tab',()=>{
 const f=fixture(),p=f.item('trade',true);f.inventory.items=[p];f.storage.items=Array(147).fill(null);
 f.storage.IsTabUnlocked=tab=>tab!==2;f.storage.CanAccept=index=>index>=49;
 const result=f.guardedStorageAction({kind:'deposit',uid:p.uid},[]);
 assert.equal(result.status,'confirmed');assert.equal(result.protectedChanged.length,0);assert.equal(f.storage.items[49],p);assert.equal(f.storage.items[0],null);
});

test('incompatible empty warehouse pages never receive an item',()=>{
 const f=fixture();f.inventory.items=[f.item('held')];f.storage.CanAccept=()=>false;
 assert.equal(f.guardedStorageAction({kind:'deposit',uid:'held'},[]).reason,'storage_full');assert.equal(f.mutations.length,0);
});

function sortingFixture(){
 const f=fixture();f.storage.items=Array(147).fill(null);f.storage.IsTabUnlocked=tab=>tab<2;
 f.storage.items[3]=f.item('page-one-trade',true);f.storage.items[51]=f.item('page-two');f.storage.items[100]=f.item('locked-page');
 f.inventory.items=[null,f.item('bag-trade',true)];f.inventory.items[1].sockets=[{get_Index:()=>0,get_ConfigID:()=>7,get_Ability:()=>2,get_Value:()=>3}];
 f.inventory.Sort=()=>{f.mutations.push('sort-inventory');f.inventory.items=[f.inventory.items[1],null];};f.inventory.Draw=()=>{};
 f.storage.SortTab=tab=>{f.mutations.push('sort-page-'+tab);const start=tab*49,rows=f.storage.items.slice(start,start+49).filter(Boolean);f.storage.items.splice(start,49,...rows,...Array(49-rows.length).fill(null));};f.storage.Draw=()=>{};
 return f;
}

test('native sorting covers all unlocked pages, conserves protected items and never changes page',()=>{
 const f=sortingFixture(),plans=Array.from(f.itemSortPlans(f.im));assert.equal(plans.length,3);
 for(const plan of plans){const result=f.sortItemsAction(plan,[]);assert.equal(result.status,'confirmed');assert.equal(result.protectedChanged.length,0);}
 assert.equal(f.storage.items[0].uid,'page-one-trade');assert.equal(f.storage.items[49].uid,'page-two');assert.equal(f.storage.items[100].uid,'locked-page');
 assert.equal(f.inventory.items[0].config.Tradable,true);assert.equal(f.inventory.items[0].sockets.length,1);assert.equal(f.itemSortPlans(f.im,true,0).length,0);
 f.inventory.items.push(f.item('new-loot'));assert.equal(f.itemSortPlans(f.im).length,0);f.clock.now=31000;
 assert.deepEqual(Array.from(f.itemSortPlans(f.im),p=>p.place),['inventory']);
});

test('sorting waits for manual windows, drag operations and native cube reservations',()=>{
 for(const block of ['window','drag','cube']){
  const f=sortingFixture(),plan=f.itemSortPlans(f.im)[0];
  if(block==='window')f.popup.get_AnyPopupOpen=()=>true;
  if(block==='drag')f.im.get_Input=()=>({get_IsHolding:()=>true});
  if(block==='cube')f.im.get_Cube=()=>({get_IsEmpty:()=>false});
  assert.equal(f.sortItemsAction(plan).status,'waiting');assert.equal(f.mutations.length,0);
 }
});

test('sorting detects count loss, cross-page moves and changed trade flags',()=>{
 for(const tamper of ['count','page','trade']){
  const f=sortingFixture(),plan=f.itemSortPlans(f.im).find(p=>p.place==='storage'&&p.tab===0);
  f.storage.SortTab=()=>{if(tamper==='count')f.storage.items[3].count=2;if(tamper==='page'){f.storage.items[49]=f.storage.items[3];f.storage.items[3]=null;}if(tamper==='trade')f.storage.items[3].config.Tradable=false;};
  assert.equal(f.sortItemsAction(plan).reason,'sort_conservation_failed');
 }
});

test('native stack merging conserves quantities while equipment UIDs remain stable',()=>{
 const f=sortingFixture();const a=f.item('stack-a'),b=f.item('stack-b');a.maxCount=b.maxCount=99;a.count=3;b.count=4;
 f.storage.items[52]=a;f.storage.items[54]=b;
 f.storage.SortTab=()=>{a.count=7;f.storage.items[54]=null;};
 const plan=f.itemSortPlans(f.im).find(p=>p.place==='storage'&&p.tab===1),result=f.sortItemsAction(plan);
 assert.equal(result.status,'confirmed');assert.equal(result.mergedStacks,1);assert.equal(result.protectedChanged.length,0);
});
test('sorting does not merge protected stack UIDs or accept an extra unaccounted item',()=>{
 const f=sortingFixture();const a=f.item('trade-stack-a',true),b=f.item('trade-stack-b',true);a.maxCount=b.maxCount=99;
 f.storage.items[52]=a;f.storage.items[54]=b;
 const plan=f.itemSortPlans(f.im).find(p=>p.place==='storage'&&p.tab===1);
 assert.equal(f.sortItemsAction(plan).reason,'sort_protected_stack');assert.equal(f.mutations.length,0);
 const g=sortingFixture();g.storage.SortTab=()=>{g.storage.items[8]=g.item('unexpected');};
 assert.equal(g.sortItemsAction(g.itemSortPlans(g.im).find(p=>p.place==='storage'&&p.tab===0)).reason,'sort_conservation_failed');
});

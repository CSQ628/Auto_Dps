const fs=require('node:fs');
const vm=require('node:vm');
const test=require('node:test');
const assert=require('node:assert/strict');

function fixture(){
 const mutations=[];
 const item=(uid,tradable=false)=>({isNull:()=>false,uid,config:{Tradable:tradable,Grade:1,Tier:1},
  get_Config(){return this.config;},get_Uid(){return uid;},get_IsLocked(){return false;},get_IsServerConfirmed(){return true;},
  get_Sockets(){return [];},get_ConfigID(){return 1;},get_Count(){return 1;},get_Kind(){return 1;}});
 const inventory={items:[],get_Has(){return this.items;},FindEmptyIndex:()=>1};
 const storage={items:[],get_Has(){return this.items;},get_SlotCountPerTab:()=>49,IsTabUnlocked:()=>true};
 const equipment={items:[],get_Has(){return this.items;}};
 const im={get_Inventory:()=>inventory,get_Storage:()=>storage,GetEquipment:()=>equipment,get_Cube:()=>({}),
  IsInUse:()=>false,IsEquipped:()=>false,FindRegistrations:()=>[],
  TryExchange:()=>{mutations.push('exchange');return true;},TryMoveToStorage:()=>{mutations.push('deposit');return true;}};
 const context={api:()=>()=>0,list:x=>x,read:(o,n)=>o[n],single:()=>im,ref:p=>p,sceneObject:()=>({}),
  call:(o,n,args=[])=>{if(typeof o[n]!=='function')throw Error('unexpected native call '+n);return o[n](...args);}};
 vm.createContext(context);
 vm.runInContext(fs.readFileSync('bridge/systems.js','utf8')+'\nglobalThis.sceneObject=()=>({});globalThis.subject={protectedItem,storageAction,equipAction,forgeAction,refineAction,cubeAction,approvedMaterials,checkPreserved,guardedItemAction};',context);
 return {item,inventory,storage,equipment,im,mutations,...context.subject};
}

test('tradable inventory and warehouse items never move',()=>{
 const f=fixture();
 f.inventory.items=[f.item('sellable',true)];
 assert.equal(f.protectedItem(f.im,f.inventory.items[0]),true);
 assert.equal(f.storageAction({kind:'deposit',uid:'sellable'}).status,'stale');
 f.storage.items=f.inventory.items;f.inventory.items=[];
 assert.equal(f.storageAction({kind:'withdraw',uid:'sellable'}).status,'stale');
 assert.deepEqual(f.mutations,[]);
});

test('tradable candidate cannot be equipped',()=>{
 const f=fixture();f.inventory.items=[f.item('sellable',true)];
 assert.equal(f.equipAction({id:1,slot:0,uid:'sellable'}).status,'stale');
 assert.deepEqual(f.mutations,[]);
});

test('tradable equipped item cannot be displaced',()=>{
 const f=fixture();f.inventory.items=[f.item('upgrade')];f.equipment.items=[f.item('sellable-equipped',true)];
 assert.equal(f.equipAction({id:1,slot:0,uid:'upgrade'}).reason,'protected_equipped_item');
 assert.deepEqual(f.mutations,[]);
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

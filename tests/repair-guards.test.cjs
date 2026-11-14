const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');

test('online wait retains learned offline parents and reports unlearned mixed route cost',()=>{
 const c={};vm.createContext(c);vm.runInContext(fs.readFileSync('bridge/planner.js','utf8'),c);
 const row=(id,header,extra={})=>({id,header,level:0,max:5,requires:[],goods:[201],prices:[10],...extra});
 const rows=[row(1,'OfflineExpGain',{level:1}),row(2,'AttackSpeed',{requires:[1],goods:[202],prices:[8]})];
 assert.equal(c.runeWaiting(rows,{soul:100,premium:0},true).reason,'premium_missing');
 rows[0].level=0;rows[0].prices=[200];assert.equal(c.runeWaiting(rows,{soul:100,premium:0},true).reason,'soul_missing');
 rows[1].level=5;assert.equal(c.runeWaiting(rows,{soul:0,premium:0},true).reason,'online_complete');
 assert.notEqual(c.runeWaiting(rows,{soul:0,premium:0}).reason,'runes_complete');
});

test('execution guard holds only arranged repair and releases when disabled or aligned',()=>{
 const c={};vm.createContext(c);vm.runInContext(fs.readFileSync('bridge/planner.js','utf8'),c);
 const snapshot={squad:[1],characters:[{id:1,points:0,skillPlanning:{repair:{excess:1,reason:'refund_branch'}}}]};
 assert.equal(c.skillReallocationPending(snapshot),true);
 assert.equal(c.skillReallocationPending(snapshot,{modules:{passive:false}}),false);
 assert.equal(c.skillReallocationPending(snapshot,{allow_passive_refund:false}),false);
 snapshot.squad=[];assert.equal(c.skillReallocationPending(snapshot),false);
 snapshot.squad=[1];snapshot.characters[0].skillPlanning.repair={reason:'fill_target',excess:0};snapshot.characters[0].points=1;
 assert.equal(c.skillReallocationPending(snapshot),true);
 assert.equal(c.skillReallocationPending(snapshot,{skill_point_reserve:1}),false);
 snapshot.characters[0].skillPlanning.repair.reason='aligned';assert.equal(c.skillReallocationPending(snapshot),false);
});

function fixture(tamper=()=>{}){
 const socket=(index,id=10,value=3)=>({get_Index:()=>index,get_ConfigID:()=>id,get_Ability:()=>2,get_Value:()=>value,get_Config:()=>({ItemType:1})});
 const item=(uid,id)=>({isNull:()=>false,uid,sockets:[],get_Uid:()=>uid,get_ConfigID:()=>id,get_Config:()=>({Tradable:false,Grade:1,Tier:1}),
  get_IsLocked(){return !!this.locked;},get_IsServerConfirmed:()=>true,get_Count(){return this.count||1;},get_Kind:()=>1,get_Sockets(){return this.sockets;},get_AttachmentConfig:()=>({ItemType:1}),get_EquipmentConfig:()=>({})});
 const gear=item('gear',1),material=item('gem',10),other=item('other',2);gear.sockets=[socket(0)];other.sockets=[socket(0)];
 const inventory={get_Has:()=>[material,other]},equipment={get_Has:()=>[gear]},cube={items:[],get_Has(){return this.items;},get_IsEmpty(){return !this.items.length;}};
 const toggle={get_isOn:()=>true,set_isOn:()=>{}};
 const view={get_IncludeStorageToggle:()=>toggle,CollectSlots(){},SetMode(){},RebuildRules(){},ReleaseAll(){cube.items=[];},TryExecute(){gear.sockets.push(socket(1));tamper({gear,other,socket});return true;}};
 const popup={OnClickClose(){}};
 const im={get_Inventory:()=>inventory,get_Storage:()=>({get_Has:()=>[],get_SlotCountPerTab:()=>49}),GetEquipment:()=>equipment,get_Cube:()=>cube,get_Input:()=>({get_IsHolding:()=>false}),
  IsInUse:()=>false,IsEquipped:()=>false,FindRegistrations:()=>[],CanAttach:()=>true,GetSocketCount:()=>4,TryMoveToCube:p=>{cube.items.push(p);return true;}};
 const c={api:()=>()=>0,list:x=>x,read:(o,n)=>o[n],single:()=>im,ref:x=>x,view,popup,call:(o,n,a=[])=>{if(typeof o[n]!=='function')throw Error(n);return o[n](...a);}};
 vm.createContext(c);vm.runInContext(fs.readFileSync('bridge/systems.js','utf8')+'\nsceneObject=()=>view;activateCubeView=()=>popup;globalThis.run=()=>guardedItemAction(()=>refineAction({id:1,uid:"gear",allowed:["gem"]}),[{id:1}],[],["gear"],[],"gear");',c);
 return {run:c.run,gear};
}

test('real refine receipt permits exactly the authorized socket append',()=>{
 const f=fixture(),r=f.run();assert.equal(r.status,'confirmed');assert.equal(r.protectedChanged.length,0);assert.equal(r.tradeChanged.length,0);assert.equal(r.socketAppend.length,2);
});
test('refine guard still detects old socket edits, extra materials, duplicate indices, flags and unrelated items',()=>{
 const mutations=[({gear,socket})=>gear.sockets[0]=socket(0,10,99),({gear,socket})=>gear.sockets.push(socket(2,88)),({gear,socket})=>gear.sockets.push(socket(1)),({gear})=>gear.locked=true,({other,socket})=>other.sockets[0]=socket(0,10,99)];
 for(const mutate of mutations){const r=fixture(mutate).run();assert.ok(r.protectedChanged.length>0);}
});
test('a failed or uncertain refine never authorizes a socket change',()=>{
 const f=fixture(()=>{throw Error('native_after_write');});const r=f.run();assert.equal(r.reason,'protected_state_changed_after_error');assert.equal(r.protectedChanged.length,1);
});

const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');
function fixture(){
 const mutations=[],freed=[];let rooted=0;
 const item=(uid,value,slots=[0],extra={})=>({uid,value,slots,config:{Tradable:false},isNull:()=>false,
  get_ConfigID(){return 100;},get_Count(){return 1;},get_Config(){return this.config;},get_EquipmentConfig(){return {EquipPart:this.slots[0]};},get_Uid(){return this.uid;},get_IsLocked(){return !!this.locked;},get_IsServerConfirmed(){return this.confirmed!==false;},get_Sockets(){return this.sockets||[];},...extra});
 const inv={items:[],get_Has(){return this.items;}},storage={items:[],get_Has(){return this.items;},get_SlotCountPerTab:()=>49,IsTabUnlocked:()=>true},gear=new Map();
 const character=(id,items)=>{const eq={items,get_Has(){return this.items;},CanAccept:(slot,p)=>p.slots.includes(slot),IsUnderRequireLevel:p=>!!p.underLevel,IsWrongClass:()=>false};gear.set(id,eq);return {id};};
 const im={get_Inventory:()=>inv,get_Storage:()=>storage,GetEquipment:id=>gear.get(id),IsInUse:p=>!!p.inUse,IsEquipped:()=>false,FindRegistrations:p=>p.registered?[1]:[],
  TryBuildScoreBasis:()=>true,CalculateEquipScore:(_id,set)=>set.reduce((v,p)=>v+(p?.value||0),0),
  IsBetterEquipment:()=>{throw Error('main-only comparison must not run');},
  TryExchange:(from,index,to,slot)=>{mutations.push({uid:from.items[index].uid,slot});[from.items[index],to.items[slot]]=[to.items[slot],from.items[index]];return true;}};
 const context={api:name=>name==='array_new'?(_klass,n)=>{const array=Array(n).fill(null);array.add=offset=>({writePointer:p=>{array[(offset-32)/8]=p;}});return array;}:()=>64,
  klass:x=>x,Memory:{alloc:n=>({n})},PS:8,nil:null,gcNew:p=>{rooted++;return p;},gcFree:p=>{rooted--;freed.push(p);},
  list:x=>x,read:(o,n)=>o[n],ref:p=>p,single:()=>im,call:(o,n,args=[])=>{if(typeof o[n]==='function')return o[n](...args);const key={get_Index:'index',get_ConfigID:'id',get_Ability:'ability',get_Value:'value'}[n];if(key)return o[key]??0;throw Error('unexpected native call '+n);}};
 vm.createContext(context);vm.runInContext(fs.readFileSync('bridge/systems.js','utf8')+'\nglobalThis.subject={equipmentPlans,equipAction,equipmentScorer,allocateEquipment,guardedEquipmentAction,protectedItem,approvedMaterials,equipmentRevision,equipmentContext,equipmentContextMatches};',context);
 return {item,character,gear,im,inv,storage,mutations,freed,rooted:()=>rooted,...context.subject};
}
test('all three characters and every slot receive independent upgrade plans',()=>{
 const f=fixture(),chars=[3,1,2].map(id=>f.character(id,[f.item('old-'+id,1,[id]),null]));
 f.inv.items=[1,2,3].flatMap(id=>[f.item('weapon-'+id,5,[id]),f.item('off-'+id,7,[1])]);
 // Give each character a distinct weapon class while off-hand slots accept the shared class.
 for(const [id,eq] of f.gear)eq.CanAccept=(slot,p)=>slot===0?p.uid==='weapon-'+id:p.uid.startsWith('off-');
 const details=[],plans=f.equipmentPlans(f.im,chars,[1,2,3],details);
 assert.equal(plans.length,6);assert.equal(new Set(plans.map(p=>p.uid)).size,6);
 for(const id of [1,2,3])assert.equal(plans.filter(p=>p.id===id).length,2);
 assert.deepEqual(Array.from(details,p=>p.id),[1,2,3]);assert.equal(f.rooted(),0);
});
test('shared UID goes to one character, with empty slots first',()=>{
 const f=fixture(),chars=[f.character(1,[f.item('old',1)]),f.character(2,[null]),f.character(3,[null])];
 f.inv.items=[f.item('shared',10)];const plans=f.equipmentPlans(f.im,chars,[3,2,1]);
 assert.equal(plans.length,1);assert.equal(plans[0].id,3);assert.equal(plans[0].uid,'shared');
});
test('recycling preserves all improvements and future-level equipment across the roster',()=>{
 const f=fixture(),chars=[f.character(1,[f.item('old',1)]),f.character(2,[null])];
 f.inv.items=[f.item('shared',10),f.item('alternative',8),f.item('future',20,[0],{underLevel:true})];
 for(const eq of f.gear.values())eq.CanAccept=(_slot,p)=>!p.underLevel;
 const reserved=new Set(),plans=f.equipmentPlans(f.im,chars,[1,2],[],reserved);
 assert.ok(plans.length>0);assert.deepEqual([...reserved].sort(),['alternative','future','shared']);
});
test('warehouse upgrade uses native whole-set score even if main-only comparison rejects it',()=>{
 const f=fixture(),chars=[f.character(2,[f.item('old',10)])];f.storage.items=[f.item('substat-upgrade',11)];
 const [plan]=f.equipmentPlans(f.im,chars);assert.equal(plan.source,'storage');
 assert.equal(plan.scoring,'native_set');assert.equal(f.equipAction(plan).status,'confirmed');
 assert.equal(f.gear.get(2).items[0].uid,'substat-upgrade');assert.equal(f.rooted(),0);
});

for(const source of ['inventory','storage'])test(source+' socketed gear upgrades a character without becoming crafting material',()=>{
 const f=fixture(),chars=[f.character(3,[f.item('old',1)])],sockets=[{id:410302,value:12}];
 const candidate=f.item('socketed-upgrade',10,[0],{sockets});
 (source==='inventory'?f.inv:f.storage).items=[candidate];
 assert.equal(f.protectedItem(f.im,candidate),true);
 assert.equal(f.approvedMaterials(f.im,['socketed-upgrade']),null);
 const [plan]=f.equipmentPlans(f.im,chars);assert.equal(plan.id,3);assert.equal(plan.source,source);
 assert.equal(f.equipAction(plan).status,'confirmed');
 assert.equal(f.gear.get(3).items[0],candidate);assert.deepEqual(candidate.sockets,sockets);
 assert.equal(f.protectedItem(f.im,f.gear.get(3).items[0]),true);
});

test('socketed and unknown-trade equipment can be worn without authorizing consumption',()=>{
 const f=fixture(),chars=[f.character(2,[null])];
 f.inv.items=[f.item('trade',100,[0],{config:{Tradable:true},sockets:[1]}),f.item('unknown',100,[0],{config:{},sockets:[1]})];
 const details=[];assert.equal(f.equipmentPlans(f.im,chars,[],details).length,1);
 assert.equal(details[0].slotDetails[0].status,'upgrade_ready');
 assert.equal(f.equipAction({id:2,slot:0,uid:'unknown',previousUid:null}).status,'confirmed');assert.equal(f.mutations.length,1);
 assert.equal(f.approvedMaterials(f.im,['trade']),null);
});

test('empty slots distinguish missing items, native rejection and shared assignments',()=>{
 const f=fixture(),chars=[f.character(1,[null,null]),f.character(2,[null,null]),f.character(3,[null,null])];
 f.inv.items=[f.item('shared',10,[0])];const details=[];
 f.gear.get(3).CanAccept=()=>false;
 const plans=f.equipmentPlans(f.im,chars,[1,2,3],details);
 assert.equal(plans.length,1);
 assert.equal(details[0].slotDetails[0].status,'upgrade_ready');
 assert.equal(details[1].slotDetails[0].status,'shared_candidate_assigned');
 assert.equal(details[2].slotDetails[0].status,'native_rejected');
 assert.equal(details[2].slotDetails[1].status,'no_candidate');
});
test('locked and registered candidates stay untouched',()=>{
 const f=fixture(),chars=[f.character(1,[null])];
 f.inv.items=[f.item('locked',100,undefined,{locked:true}),f.item('registered',100,undefined,{registered:true})];
 assert.equal(f.equipmentPlans(f.im,chars).length,0);assert.equal(f.mutations.length,0);
});
test('locked equipment slots cannot be replaced',()=>{
 const f=fixture(),chars=[f.character(1,[f.item('locked',1,undefined,{locked:true})])];
 f.inv.items=[f.item('upgrade',100,[0,1])];assert.equal(f.equipmentPlans(f.im,chars).length,0);
});
test('native score unavailable or nonfinite fails closed and releases roots',()=>{
 const f=fixture(),chars=[f.character(1,[null])];f.inv.items=[f.item('upgrade',10)];
 f.im.TryBuildScoreBasis=()=>false;const diagnostics=[];
 assert.equal(f.equipmentPlans(f.im,chars,[],diagnostics).length,0);assert.equal(diagnostics[0].status,'score_unavailable');
 f.im.TryBuildScoreBasis=()=>true;f.im.CalculateEquipScore=()=>NaN;
 assert.equal(f.equipmentPlans(f.im,chars).length,0);assert.equal(f.rooted(),0);
});
test('stale slot or lost improvement cannot cause a swap',()=>{
 const f=fixture(),chars=[f.character(1,[f.item('old',1)])];f.inv.items=[f.item('upgrade',10)];
 const [plan]=f.equipmentPlans(f.im,chars);f.gear.get(1).items[0]=f.item('manual-change',2);
 assert.equal(f.equipAction(plan).reason,'equipped_item_changed');
 f.gear.get(1).items[0]=f.item('old',20);
 assert.equal(f.equipAction(plan).reason,'equipment_no_longer_upgrade');assert.equal(f.mutations.length,0);
});
test('scratch scoring keeps actual equipment immutable and frees its GC handle on failure',()=>{
 const f=fixture(),items=[f.item('old',1)],has=items,score=f.equipmentScorer(f.im,1,items,has);
 assert.equal(score.score(0,f.item('candidate',10)),10);assert.equal(items[0].uid,'old');score.close();assert.equal(f.rooted(),0);
 f.im.CalculateEquipScore=()=>{throw Error('score_error');};
 assert.throws(()=>f.equipmentScorer(f.im,1,items,has),/score_error/);assert.equal(f.rooted(),0);
});


test('configured minimum gain applies to planning and same-call execution while preserving future upgrades',()=>{
 const f=fixture(),chars=[f.character(1,[f.item('old',100)])];f.inv.items=[f.item('upgrade',103)];
 const reserved=new Set();assert.equal(f.equipmentPlans(f.im,chars,[],[],reserved,4).length,0);assert.ok(reserved.has('upgrade'));
 const [plan]=f.equipmentPlans(f.im,chars,[],[],new Set(),2);assert.ok(plan);
 assert.equal(f.equipAction(plan,4).status,'stale');assert.equal(f.mutations.length,0);
 assert.equal(f.equipAction(plan,2).status,'confirmed');
});

test('empty equipment slots remain eligible under a high minimum gain',()=>{
 const f=fixture(),chars=[f.character(1,[null])];f.inv.items=[f.item('starter',1)];
 const [plan]=f.equipmentPlans(f.im,chars,[],[],new Set(),100);assert.ok(plan.empty);
 assert.equal(f.equipAction(plan,100).status,'confirmed');
});


test('tradable gear can be worn and replaced while trade materials remain protected',()=>{
 const f=fixture(),old=f.item('old-trade',1,[0],{config:{Tradable:true}}),upgrade=f.item('trade-upgrade',10,[0],{config:{Tradable:true}});
 const chars=[f.character(1,[old])];f.inv.items=[upgrade];
 const [plan]=f.equipmentPlans(f.im,chars);assert.ok(plan);assert.equal(plan.uid,'trade-upgrade');
 assert.equal(f.protectedItem(f.im,upgrade),true);assert.equal(f.approvedMaterials(f.im,['trade-upgrade']),null);
 assert.equal(f.equipAction(plan).status,'confirmed');assert.equal(f.gear.get(1).items[0],upgrade);
 assert.equal(f.inv.items[0],old);assert.equal(upgrade.config.Tradable,true);assert.equal(old.config.Tradable,true);
});

test('future reservations retain the best next-level item per slot instead of every future item',()=>{
 const f=fixture(),chars=[f.character(1,[f.item('old',1)])];
 const future=(uid,value,require)=>f.item(uid,value,[0],{underLevel:true,get_EquipmentConfig(){return {EquipPart:0,RequireLevel:require};}});
 chars[0].level=19;f.inv.items=[future('next-best',30,20),future('next-duplicate',10,20),future('far-future',50,30)];
 f.gear.get(1).CanAccept=()=>false;const reserved=new Set();f.equipmentPlans(f.im,chars,[],[],reserved);
 assert.deepEqual([...reserved],['next-best']);
});

test('future gear without an actual score improvement does not accumulate as reserved equipment',()=>{
 const f=fixture(),chars=[f.character(1,[f.item('current',50)])];chars[0].level=19;
 f.inv.items=[f.item('future-weaker',20,[0],{underLevel:true,get_EquipmentConfig(){return {EquipPart:0,RequireLevel:20};}})];
 f.gear.get(1).CanAccept=()=>false;const reserved=new Set();f.equipmentPlans(f.im,chars,[],[],reserved);
 assert.equal(reserved.size,0);
});


test('equipment guard permits only the two expected swap positions and preserves trade attributes',()=>{
 const f=fixture(),old=f.item('old-trade',1,[0],{config:{Tradable:true}}),upgrade=f.item('trade-upgrade',10,[0],{config:{Tradable:true}}),other=f.item('other-trade',1,[1],{config:{Tradable:true}});
 const chars=[f.character(1,[old])];f.inv.items=[upgrade,other];const [plan]=f.equipmentPlans(f.im,chars);
 const result=f.guardedEquipmentAction(plan,chars);assert.equal(result.status,'confirmed');assert.equal(result.protectedChanged.length,0);assert.equal(result.protectedChecked,3);
 assert.equal(f.inv.items[0],old);assert.equal(f.inv.items[1],other);assert.equal(f.gear.get(1).items[0],upgrade);
});

test('equipment guard detects a changed tradable flag or an unrelated item move',()=>{
 for(const tamper of ['flag','other']){
  const f=fixture(),chars=[f.character(1,[null])],upgrade=f.item('trade-upgrade',10,[0],{config:{Tradable:true}}),other=f.item('other-trade',1,[1],{config:{Tradable:true}});
  f.inv.items=[upgrade,other];const [plan]=f.equipmentPlans(f.im,chars),exchange=f.im.TryExchange;
  f.im.TryExchange=(...args)=>{const result=exchange(...args);if(tamper==='flag')upgrade.config.Tradable=false;else{f.inv.items[2]=f.inv.items[1];f.inv.items[1]=null;}return result;};
  assert.equal(f.guardedEquipmentAction(plan,chars).protectedChanged.length,1);
 }
});


test('unavailable native scoring preserves potential equipment from material consumption',()=>{
 const f=fixture(),chars=[f.character(1,[null])],p=f.item('candidate',10);f.inv.items=[p];f.im.TryBuildScoreBasis=()=>false;
 const reserved=new Set(),details=[];assert.equal(f.equipmentPlans(f.im,chars,[],details,reserved).length,0);
 assert.equal(details[0].status,'score_unavailable');assert.ok(reserved.has('candidate'));
});

test('only the three arranged heroes receive equipment plans when reserves are owned',()=>{
 const f=fixture(),chars=[1,2,3,4].map(id=>f.character(id,[null]));f.inv.items=[1,2,3,4].map(id=>f.item('item-'+id,10));
 const plans=f.equipmentPlans(f.im,chars,[3,1,2]);assert.equal(plans.length,3);assert.equal(plans.some(p=>p.id===4),false);
});

test('unconfirmed equipment and ordinary acknowledgement changes do not damage trade value',()=>{
 const f=fixture(),old=f.item('old',1,[0],{config:{Tradable:true},confirmed:false}),upgrade=f.item('upgrade',10,[0],{config:{Tradable:true},confirmed:false});
 const chars=[f.character(1,[old])];f.inv.items=[upgrade];
 const [plan]=f.equipmentPlans(f.im,chars,[1]);assert.ok(plan);
 const native=f.im.TryExchange;f.im.TryExchange=(...args)=>{const ok=native(...args);old.confirmed=true;return ok;};
 const r=f.guardedEquipmentAction(plan,chars);assert.equal(r.status,'confirmed');assert.equal(r.tradeChanged.length,0);
 assert.equal(old.config.Tradable,true);assert.equal(upgrade.config.Tradable,true);
 assert.equal(f.approvedMaterials(f.im,[old.uid]),null);
});


test('equipment revisions include full sockets with stable native collection order',()=>{
 const f=fixture(),first={index:0,id:10,ability:'Attack',value:1},second={index:1,id:11,ability:'Defense',value:2};
 const gear=f.item('same',1,[0],{sockets:[second,first]});
 const before=f.equipmentRevision(gear);gear.sockets.reverse();assert.equal(f.equipmentRevision(gear),before);
 gear.sockets[0]={...first,value:3};assert.notEqual(f.equipmentRevision(gear),before);
 const chars=[f.character(1,[gear])];f.inv.items=[f.item('new',10,[0],{sockets:[first]})];
 assert.equal(f.equipmentPlans(f.im,chars)[0].itemRevision,f.equipmentRevision(f.inv.items[0]));
});

test('party context is stable across roster order and ignores bench equipment',()=>{
 const f=fixture(),r=uid=>f.equipmentRevision(f.item(uid,1));
 const characters=[{id:2,equipment:[{slot:1,revision:r('B')},{slot:0,revision:r('A')}]},{id:1,equipment:[]},{id:9,equipment:[{slot:0,revision:r('bench')}]}];
 const snapshot={squad:[1,2],characters};const before=f.equipmentContext(snapshot);
 characters.reverse();characters.find(c=>c.id===2).equipment.reverse();characters[0].equipment[0].revision=r('bench-new');
 assert.equal(f.equipmentContext(snapshot),before);
 characters.find(c=>c.id===2).equipment[0].revision=r('manual');assert.notEqual(f.equipmentContext(snapshot),before);
});

test('real executor rejects any changed party or candidate revision before native mutation',()=>{
 const f=fixture(),base={kind:'equipment',key:'equip',id:1,slot:0,uid:'B',previousUid:'A',itemRevision:'B-revision'};
 const snapshot={account:'fixture',loaded:true,sync:{},equipmentContext:'original-party'};let current={...base},calls=0;
 const c={api:()=>()=>0,A:{fields:{}},iter:()=>[],klass:x=>x,withManagedThread:f=>f(),rpc:{exports:{}},equipmentContextMatches:f.equipmentContextMatches,scan:()=>({snapshot,actions:[current]}),bridgeStrategy:x=>x||{},maintenanceStatus:()=>({active:false}),panelActionBlocked:()=>false,skillReallocationPending:()=>false,single:()=>({}),names:{data:'data',items:'items'},guardedEquipmentAction:()=>{calls++;return {status:'confirmed'};}};
 vm.createContext(c);vm.runInContext(fs.readFileSync('bridge/automation.js','utf8')+'\nopportunityScan=scan;',c);
 const cmd={...base,account:'fixture',equipmentStability:{schema:1,context:'original-party'}};
 for(const mutate of [()=>snapshot.equipmentContext='manual-other-slot',()=>current.itemRevision='socket-changed',()=>current.previousUid='manual-target']){
  snapshot.equipmentContext='original-party';current={...base};mutate();
  assert.equal(c.executeAction(cmd).reason,'equipment_context_changed');assert.equal(calls,0);
 }
 snapshot.equipmentContext='original-party';current={...base};assert.equal(c.executeAction(cmd).status,'confirmed');assert.equal(calls,1);
});

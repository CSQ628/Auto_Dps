const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');

function fixture(){
 const calls=[];
 const ticket={config:{Tradable:true,ItemType:6,Grade:2,Tier:1},id:690100,uid:'ticket',count:3,locked:false,confirmed:true,sockets:[],
  get_Config(){return this.config;},get_ConfigID(){return this.id;},get_Uid(){return this.uid;},get_Count(){return this.count;},
  get_Kind:()=>32,get_IsLocked(){return this.locked;},get_IsServerConfirmed(){return this.confirmed;},get_Sockets(){return this.sockets;}};
 let target=ticket;
 const im={inUse:false,equipped:false,registered:[],IsInUse(){return this.inUse;},IsEquipped(){return this.equipped;},FindRegistrations(){return this.registered;},FindOccupyTarget:()=>target};
 const gm={required:690100,repeat:false,ending:true,GetRequireItemID(){return this.required;},CanEnterStage:()=>true,CanRepeat:()=>true,IsStageEnding(){return this.ending;},get_RepeatStage(){return this.repeat;},set_RepeatStage(value){this.repeat=value;},GoToStage:(...args)=>calls.push(args)};
 const action={kind:'progress',mode:'boss',key:'boss:20:ticket',level:20,difficulty:0,ticket:690100,ticketUid:'ticket',ticketBefore:3};
 const scan={snapshot:{account:'1001',automationBlocked:[],sync:{},connection:{online:true},stage:{level:19},record:{maxCleared:19}},actions:[action]};
 const c={api:()=>()=>0,A:{fields:{}},iter:()=>[],klass:x=>x,withManagedThread:fn=>fn(),rpc:{exports:{}},
  list:x=>x,read:(o,n)=>o[n],ref:p=>p,call:(o,n,a=[])=>o[n](...a),single:n=>n==='DG.Manager.GameManager'?gm:im,scan};
 vm.createContext(c);vm.runInContext(['systems','planner','automation'].map(n=>fs.readFileSync('bridge/'+n+'.js','utf8')).join('\n')+
  '\nopportunityScan=()=>scan;globalThis.entry=entranceStatus;globalThis.execute=executeAction;globalThis.protectedMaterial=protectedItem;',c);
 return {ticket,im,gm,action,scan,calls,entry:(category=0)=>c.entry(gm,im,category,20),execute:()=>c.execute({...action,account:'1001'}),protectedMaterial:()=>c.protectedMaterial(im,ticket),setTarget:p=>target=p};
}

test('confirmed main-story boss tickets may enter but remain protected crafting materials',()=>{
 const f=fixture();assert.equal(f.entry().safe,true);assert.equal(f.entry().consumeOnClear,true);assert.equal(f.entry().uid,'ticket');
 assert.equal(f.protectedMaterial(),true);assert.equal(f.entry(1).safe,false);
 for(const id of [690100,690200,690300,690400]){f.ticket.id=id;f.gm.required=id;assert.equal(f.entry().safe,true);}
 f.ticket.id=123;f.gm.required=123;assert.equal(f.entry().safe,false);
});

test('locked unconfirmed registered in-use and mismatched native targets stay protected',()=>{
 const cases=[f=>f.ticket.locked=true,f=>f.ticket.confirmed=false,f=>f.ticket.count=0,
  f=>f.ticket.id=690200,f=>f.ticket.config.Tradable=undefined,f=>f.ticket.config.ItemType=2,
  f=>f.im.registered=['preset'],f=>f.im.inUse=true,f=>f.im.equipped=true,f=>f.ticket.sockets=[{}]];
 for(const mutate of cases){const f=fixture();mutate(f);assert.equal(f.entry().safe,false);}
 const f=fixture();f.setTarget(null);assert.equal(f.entry().reason,'ticket_missing');
});

test('boss submission revalidates frontier UID and native entry before invoking stage travel',()=>{
 const f=fixture();f.gm.repeat=true;assert.equal(f.execute().status,'pending');assert.deepEqual(f.calls,[[0,20,0]]);assert.equal(f.gm.repeat,false);
 for(const mutate of [f=>f.scan.snapshot.record.maxCleared=18,f=>f.scan.snapshot.stage.level=20,
  f=>f.ticket.uid='changed',f=>f.ticket.locked=true,f=>f.gm.CanEnterStage=()=>false]){
  const g=fixture();mutate(g);assert.equal(g.execute().status,'stale');assert.deepEqual(g.calls,[]);
 }
});

test('offline sync and trading guards block boss submission even if a client claims free entry',()=>{
 for(const mutate of [f=>f.scan.snapshot.connection.online=false,f=>f.scan.snapshot.sync.blocked=true,
  f=>f.scan.snapshot.sync.backlogged=true,f=>f.scan.snapshot.trading=true]){
  const f=fixture();f.action.freeEntry=true;mutate(f);assert.equal(f.execute().status,'waiting');assert.deepEqual(f.calls,[]);
 }
});


test('tower submission rejects stale floors, missing native clearance and changed entry state',()=>{
 function tower(){const f=fixture();Object.assign(f.action,{kind:'tower',key:'tower:2:free',level:2,ticket:0});
  Object.assign(f.scan.snapshot.stage,{category:0,level:159,running:false});f.scan.snapshot.record.maxCleared=160;
  f.scan.snapshot.record.towerMaxCleared=1;f.scan.snapshot.catalogue={normalMax:160,towerMax:20};return f;}
 const f=tower();assert.equal(f.execute().status,'pending');assert.deepEqual(f.calls,[[1,2,0]]);
 for(const mutate of [f=>f.action.level=1,f=>f.action.level=3,f=>f.scan.snapshot.record.towerMaxCleared=2,
  f=>delete f.scan.snapshot.record.towerMaxCleared,f=>f.scan.snapshot.stage.category=1,f=>f.gm.CanEnterStage=()=>false,
  f=>f.scan.snapshot.stage.running=true,f=>f.scan.snapshot.stage.level=161,f=>f.gm.ending=false]){
  const g=tower();mutate(g);assert.equal(g.execute().reason,'tower_frontier_changed');assert.deepEqual(g.calls,[]);
 }
 for(const mutate of [f=>f.scan.snapshot.record.maxCleared=159,f=>f.scan.snapshot.catalogue.normalMax=161,
  f=>delete f.scan.snapshot.catalogue.normalMax]){
  const g=tower();mutate(g);assert.notEqual(g.execute().status,'pending');assert.deepEqual(g.calls,[]);
 }
});

test('free frontier travel bypasses cleared low bosses and disables repeat',()=>{
 const f=fixture();Object.assign(f.action,{mode:'push',phase:'travel',repeat:false,freeEntry:true});
 f.gm.required=0;f.gm.repeat=true;f.scan.snapshot.stage.level=3;
 assert.equal(f.execute().status,'pending');assert.deepEqual(f.calls,[[0,20,0]]);assert.equal(f.gm.repeat,false);
});
test('free frontier travel rechecks clearance, required item and current position',()=>{
 for(const mutate of [f=>f.scan.snapshot.record.maxCleared=18,f=>f.scan.snapshot.stage.level=20,
                     f=>f.gm.required=690100,f=>f.gm.CanEnterStage=()=>false]){
  const f=fixture();Object.assign(f.action,{mode:'push',phase:'travel',repeat:false,freeEntry:true});
  f.gm.required=0;mutate(f);assert.equal(f.execute().status,'stale');assert.deepEqual(f.calls,[]);
 }
});

test('farming rechecks the current chapter, fresh candidate set and free-repeat requirements',()=>{
 function farm(level,frontier,current,candidates,required=0,category=0){
  const f=fixture();
  Object.assign(f.action,{kind:'progress',mode:'farm',key:'farm:'+level+':travel',level,difficulty:0,phase:'travel',repeat:true,freeEntry:true});
  f.gm.required=required;
  f.scan.snapshot.stage={category,level:current,repeat:false};
  f.scan.snapshot.record.maxCleared=frontier;
  f.scan.snapshot.progression={farmCandidates:candidates};
  return f;
 }
 const oldChapter=farm(20,29,29,[{level:20,difficulty:0}]);
 assert.equal(oldChapter.execute().reason,'farm_stage_outside_current_chapter');
 assert.deepEqual(oldChapter.calls,[]);
 const paid=farm(31,39,39,[{level:31,difficulty:0}],690100);
 assert.equal(paid.execute().reason,'farm_stage_requires_ticket');
 assert.deepEqual(paid.calls,[]);
 const stale=farm(30,39,39,[{level:31,difficulty:0}]);
 assert.equal(stale.execute().reason,'farm_stage_outside_current_chapter');
 assert.deepEqual(stale.calls,[]);
 const wrongMode=farm(31,39,39,[{level:31,difficulty:0}],0,1);
 assert.equal(wrongMode.execute().reason,'farm_not_in_main_story');
 assert.deepEqual(wrongMode.calls,[]);
 const valid=farm(35,39,34,[{level:35,difficulty:0}]);
 assert.equal(valid.execute().status,'pending');
 assert.deepEqual(valid.calls,[[0,35,0]]);
});

const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');

function fixture(){
 const calls=[];
 const gm={repeat:true,CanEnterStage:()=>true,GetRequireItemID:()=>0,IsStageEnding:()=>true,
  get_RepeatStage(){return this.repeat;},set_RepeatStage(value){calls.push(['repeat',value]);this.repeat=value;},
  GoToStage(...args){calls.push(['travel',...args]);}};
 const im={FindOccupyTarget:()=>null};
 const action={kind:'tower',key:'tower:2:free',level:2,ticket:0};
 const scan={snapshot:{account:'fixture',loaded:true,automationBlocked:[],sync:{},connection:{online:true},
  stage:{category:0,level:9,repeat:true,running:false},record:{maxCleared:160,towerMaxCleared:1},catalogue:{normalMax:160,towerMax:20}},actions:[action]};
 const c={api:()=>()=>0,A:{fields:{}},iter:()=>[],klass:x=>x,withManagedThread:fn=>fn(),rpc:{exports:{}},
  jsonSafe:x=>x,list:x=>x,read:(o,n)=>o[n],ref:p=>p,call:(o,n,a=[])=>o[n](...a),
  single:n=>n==='DG.Manager.GameManager'?gm:im,scan};
 vm.createContext(c);vm.runInContext(['systems','planner','automation'].map(n=>fs.readFileSync('bridge/'+n+'.js','utf8')).join('\n')+
  '\nopportunityScan=()=>scan;globalThis.guard=towerRepeatGuard;globalThis.execute=executeAction;',c);
 return {gm,im,action,scan,calls,guard:stage=>c.guard(stage),execute:()=>c.execute({...scan.actions[0],account:'fixture'})};
}

test('tower entry disables inherited repeat before travel, preserving the main-stage repeat setting until entry is valid',()=>{
 const f=fixture();assert.equal(f.execute().status,'pending');
 assert.deepEqual(f.calls,[['repeat',false],['travel',1,2,0]]);
 const off=fixture();off.gm.repeat=false;off.execute();assert.deepEqual(off.calls,[['travel',1,2,0]]);
 for(const mutate of [f=>f.scan.snapshot.record.towerMaxCleared=2,f=>f.gm.CanEnterStage=()=>false,
  f=>f.scan.snapshot.connection.online=false,f=>f.action.ticket=123]){
  const g=fixture();mutate(g);assert.notEqual(g.execute().status,'pending');assert.deepEqual(g.calls,[]);
  assert.equal(g.gm.repeat,true);
 }
});

test('native refusal to disable repeat stops tower submission',()=>{
 const f=fixture();f.gm.set_RepeatStage=value=>f.calls.push(['repeat-refused',value]);
 assert.equal(f.execute().reason,'tower_repeat_not_disabled');
 assert.deepEqual(f.calls,[['repeat-refused',false]]);
});

test('existing tower sessions get a free repeat guard while main-stage farming remains enabled',()=>{
 const f=fixture();assert.equal(f.guard({category:0,repeat:true}),null);
 assert.equal(f.guard({category:1,repeat:false}),null);assert.equal(f.guard({category:1}),null);
 const guard=f.guard({category:1,repeat:true});assert.equal(guard.repeat,false);assert.equal(guard.freeEntry,true);
 f.scan.snapshot.stage.category=1;f.scan.snapshot.connection.online=false;f.scan.snapshot.sync.backlogged=true;
 f.scan.actions=[{kind:'progress',key:'tower_repeat_off',...guard}];
 assert.equal(f.execute().status,'confirmed');assert.deepEqual(f.calls,[['repeat',false]]);
});

const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');
function fixture(){
 const calls=[],gm={GetRequireItemID:()=>0,CanEnterStage:()=>true,CanRepeat:()=>true,GoToStage:(...a)=>calls.push(a)};
 const action={kind:'progress',mode:'farm',phase:'travel',key:'farm:49',level:49,difficulty:1,repeat:true,freeEntry:true};
 const snapshot={account:'fixture',sync:{},connection:{online:true},stage:{category:0,level:50,difficulty:1,running:true,repeat:true},record:{maxCleared:49},
  progression:{farmCandidates:[{level:49,difficulty:1}]},combat:{available:true,current:{level:50,difficulty:1,sequence:717,result:'InProgress',elapsed:12}}};
 const scan={snapshot,actions:[action]},c={jsonSafe:x=>x,api:()=>()=>0,A:{fields:{}},iter:()=>[],klass:x=>x,withManagedThread:fn=>fn(),rpc:{exports:{}},
  list:x=>x,read:(o,n)=>o[n],ref:p=>p,call:(o,n,a=[])=>o[n](...a),single:()=>gm,scan};
 vm.createContext(c);vm.runInContext(['systems','planner','automation'].map(n=>fs.readFileSync('bridge/'+n+'.js','utf8')).join('\n')+'\nopportunityScan=()=>scan;',c);
 return {snapshot,action,c,calls,execute:proof=>c.executeAction({...action,account:'fixture',frontierReturn:proof,strategy:{farm_retry_finish_seconds:90}})};
}
test('fresh native scan refuses an unapproved return after automatic frontier entry',()=>{
 const f=fixture();assert.equal(f.execute().reason,'frontier_battle_in_progress');assert.equal(f.calls.length,0);
});
test('bounded return needs the same battle and sufficient current timeout',()=>{
 const proof={level:50,difficulty:1,sequence:717,elapsed:11,waited:90};
 for(const override of [{sequence:718},{level:51},{difficulty:0},{elapsed:13},{waited:89},{waited:NaN}]){
  const f=fixture();assert.equal(f.execute({...proof,...override}).reason,'frontier_battle_in_progress');assert.equal(f.calls.length,0);
 }
 const f=fixture();assert.equal(f.execute(proof).status,'pending');assert.deepEqual(f.calls,[[0,49,1]]);
});
test('completed battles, ordinary farming and unavailable stats retain existing return behavior',()=>{
 for(const change of [f=>f.snapshot.combat.current.result='Failed',f=>f.snapshot.stage.running=false,
   f=>f.snapshot.record.maxCleared=50,f=>f.snapshot.combat.available=false]){
  const f=fixture();change(f);assert.equal(f.execute().status,'pending');assert.equal(f.calls.length,1);
 }
});
test('frontier repeat cleanup changes only the repeat flag while growth remains in farming',()=>{
 const f=fixture();f.action.mode='guard';delete f.action.phase;f.action.repeat=false;
 let repeat=true;f.c.call=(o,n,a=[])=>n==='set_RepeatStage'?(repeat=a[0]):n==='get_RepeatStage'?repeat:o[n](...a);
 assert.equal(f.execute().status,'confirmed');assert.equal(repeat,false);assert.equal(f.calls.length,0);
});

test('planner emits repeat cleanup on the already entered frontier without another entry',()=>{
 const f=fixture(),rows=Array.from({length:51},(_,i)=>({Level:i+1,Difficulty:1})),actions=[];
 f.c.containerEntries=()=>[];
 f.c.call=(o,n,a=[])=>n==='get_Datas'?o:o[n](...a);
 f.c.progressionOpportunities(f.snapshot,{_stageConfigTable:rows,_stageTable:rows},{},
  (kind,key,label,priority,detail)=>actions.push({kind,key,priority,...detail}),[],f.c.bridgeStrategy());
 const guard=actions.find(a=>a.key==='frontier_repeat_off');
 assert.equal(guard.requiresProgress,true);assert.equal(guard.mode,'guard');assert.equal(guard.repeat,false);assert.equal(guard.phase,undefined);
 assert.ok(!actions.some(a=>a.mode==='boss'||a.mode==='push'&&a.phase==='travel'));
});

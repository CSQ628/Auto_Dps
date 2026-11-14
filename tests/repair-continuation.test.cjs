const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');
function fixture(){
 const calls=[],gm={GetRequireItemID:()=>0,CanEnterStage:()=>true,GoToStage:(...a)=>calls.push(a),set_RepeatStage:()=>{}};
 const character={id:1,points:0,skillPlanning:{repair:{excess:2,reason:'native_refund_blocked',refund:null}}};
 const snapshot={account:'fixture',squad:[1],characters:[character],sync:{},connection:{online:true},
  stage:{category:0,level:38,difficulty:0,running:true,repeat:true},record:{maxCleared:39}};
 const action={kind:'progress',mode:'push',phase:'travel',key:'push:40',level:40,difficulty:0,repeat:false,freeEntry:true};
 const scan={snapshot,actions:[action]},c={jsonSafe:x=>x,api:()=>()=>0,A:{fields:{}},iter:()=>[],klass:x=>x,withManagedThread:fn=>fn(),rpc:{exports:{}},
  list:x=>x,read:(o,n)=>o[n],ref:p=>p,call:(o,n,a=[])=>o[n](...a),single:()=>gm,scan};
 vm.createContext(c);vm.runInContext(['systems','planner','automation'].map(n=>fs.readFileSync('bridge/'+n+'.js','utf8')).join('\n')+'\nopportunityScan=()=>scan;',c);
 return {character,snapshot,c,calls,execute:()=>c.executeAction({...action,account:'fixture'})};
}
test('fresh execution permits a retry when native repair cannot run',()=>{
 const f=fixture();assert.equal(f.c.skillReallocationPending(f.snapshot),false);
 assert.equal(f.execute().status,'pending');assert.deepEqual(f.calls,[[0,40,0]]);
 assert.equal(f.character.skillPlanning.repair.excess,2);
});
test('refund becoming available before submission still blocks a new challenge',()=>{
 const f=fixture();f.character.skillPlanning.repair.refund={skill:'wrong',level:4};
 assert.equal(f.execute().reason,'skills_reallocating');assert.equal(f.calls.length,0);
 f.character.skillPlanning.repair.reason='refund_branch';
 assert.equal(f.execute().reason,'skills_reallocating');assert.equal(f.calls.length,0);
});
test('waiting for reinvestment keeps the repair guard and native state remains authoritative',()=>{
 const f=fixture();f.character.points=1;f.character.skillPlanning.repair={reason:'fill_target',excess:0};
 assert.equal(f.execute().reason,'skills_reallocating');assert.equal(f.calls.length,0);
 f.character.skillPlanning.repair={reason:'native_refund_blocked',excess:2,refund:null};
 f.snapshot.connection.online=false;assert.equal(f.execute().reason,'native_offline');assert.equal(f.calls.length,0);
});
test('player messages explain the continuing challenge and distinguish invalid metadata',async()=>{
 const {skillStatus}=await import('../web/src/growth-plan.mjs'),{eventReason}=await import('../web/src/event-reasons.mjs');
 assert.match(skillStatus(fixture().character),/主线重试与其他成长继续/);
 assert.match(eventReason({result:{reason:'native_refund_blocked'}}),/继续主线重试/);
 assert.match(eventReason({result:{reason:'skill_catalogue_invalid'}}),/继续其他自动化/);
});

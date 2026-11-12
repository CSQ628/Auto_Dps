const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');
const c={};vm.createContext(c);vm.runInContext(fs.readFileSync('bridge/planner.js','utf8')+'\nglobalThis.subject={stagingDeposit,fusionPlans,fusionTasks};',c);
const entry=(uid,count=1,kind=1,place='inventory')=>({place,info:{uid,count,kind,grade:1,tier:kind===16?0:1}});
test('full inventory can stage retained gear without consuming it or moving the active recipe ingredients',()=>{
 const gems=entry('held-gems',4,16),stored=entry('warehouse-gems',5,16,'storage');
 const held=[gems,...Array.from({length:45},(_,i)=>entry('retained-'+i))];
 const needed=new Set(held.map(e=>e.info.uid)),materials=new Set([gems.info.uid,stored.info.uid]);
 const recalls=[{entries:[gems,stored],priority:103}];
 const stash=c.subject.stagingDeposit(held,needed,materials,new Set(),true,recalls);
 assert.ok(stash);assert.notEqual(stash.info.uid,gems.info.uid);assert.equal(stash.info.count,1);
 assert.equal(c.subject.stagingDeposit(held,needed,materials,new Set(),false,recalls),null);
 const recipe={ID:1,CraftType:0,FusionType:3,Grade:1,MinTier:0,MaxTier:0,RequireCubeLevel:0,FusionCount:9};
 let task=c.subject.fusionTasks(c.subject.fusionPlans([gems,stored],[recipe],1),1)[0];assert.equal(task.withdraw.info.uid,stored.info.uid);
 stored.place='inventory';task=c.subject.fusionTasks(c.subject.fusionPlans([gems,stored],[recipe],1),0)[0];assert.equal(task.ready,true);
});
test('no safe held item or only the target recipe leaves staging blocked',()=>{
 assert.equal(c.subject.stagingDeposit([],new Set(),new Set(),new Set(),true,[]),null);
 const gem=entry('gem',4,16);assert.equal(c.subject.stagingDeposit([gem],new Set(['gem']),new Set(['gem']),new Set(),true,[{entries:[gem],priority:103}]),null);
});

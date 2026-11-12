const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');
function scan({cleared=5,count=3,current=5,repeat=false}={}){
 const rows=Array.from({length:5},(_,i)=>({Level:i+1,Difficulty:0}));
 const gm={GetRequireItemID:(_,n)=>n===4?690100:0,CanEnterStage:()=>true,CanRepeat:()=>true};
 const c={names:{game:'gm'},single:()=>gm,list:p=>p,read:(p,n)=>p[n],containerEntries:()=>[],
  call:(p,n,args=[])=>n==='get_Datas'?p:p[n](...args)};
 vm.createContext(c);vm.runInContext(fs.readFileSync('bridge/planner.js','utf8')+'\nglobalThis.subject={progressionOpportunities,bridgeStrategy};',c);
 const snapshot={stage:{category:0,level:current,repeat},record:{maxCleared:cleared}},actions=[];
 c.subject.progressionOpportunities(snapshot,{_stageConfigTable:rows,_stageTable:rows},{FindOccupyTarget:()=>null},(kind,key,label,priority,detail)=>actions.push({kind,key,...detail}),[],c.subject.bridgeStrategy({farm_candidate_count:count}));
 return {snapshot,actions:actions.filter(a=>a.mode==='farm')};
}
test('farming enumerates only free cleared stages and honors editable candidate count',()=>{
 const r=scan();assert.deepEqual(Array.from(r.snapshot.progression.farmCandidates,p=>p.level),[3,2,1]);
 assert.equal(scan({count:1}).actions.length,1);
 assert.ok(r.actions.every(p=>p.freeEntry&&p.level<4));
 assert.equal(scan({cleared:0}).actions.length,0);
});
test('already repeating a selected level emits alternatives without restarting that level',()=>{
 const r=scan({current:3,repeat:true});assert.ok(r.snapshot.progression.farmCandidates.some(p=>p.level===3));
 assert.ok(!r.actions.some(p=>p.level===3));
});

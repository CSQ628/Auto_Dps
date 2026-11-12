const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');
function fixture(ticket=0){
 const c={names:{game:'gm'},single:()=>({GetRequireItemID:()=>ticket,CanEnterStage:()=>true,HasStageData:()=>true}),call:(p,n,args=[])=>p[n](...args)};
 vm.createContext(c);vm.runInContext(fs.readFileSync('bridge/planner.js','utf8')+'\nglobalThis.plans=battleRecoveryPlans;',c);
 return c.plans;
}
function snapshot(){return {stage:{level:1,category:0,difficulty:0,alivePlayers:0},squad:[400001],battleReadiness:{known:true,charactersInitialized:true,expected:1,missing:[400001],arrangedCount:0,syncRunning:false,syncPending:false,ending:false,enterSequence:1}};}
test('native recovery keeps current stage and never spends an entry ticket',()=>{
 const s=snapshot();s.stage.level=47;
 const plans=fixture()(s);assert.equal(plans.length,2);assert.ok(plans.every(p=>p.level===47&&p.category===0&&p.freeEntry));
 const paid=fixture(690100)(s);assert.equal(paid.length,1);assert.equal(paid[0].mode,'sync');
});
test('stalled clear advances only with matching native clear evidence and a free next stage',()=>{
 const s=snapshot();s.record={maxCleared:1};s.stage={level:1,category:0,difficulty:0,alivePlayers:1,aliveMonsters:0,wave:10,running:false,repeat:false};
 s.battleReadiness={...s.battleReadiness,missing:[],arrangedCount:1,pendingSpawn:false,timeScale:1};
 s.combat={available:true,current:{level:1,difficulty:0,result:'Cleared'}};
 const plans=fixture()(s);assert.equal(plans.length,1);assert.equal(plans[0].level,2);assert.equal(plans[0].mode,'stage');
 s.combat.current.result='Failed';assert.equal(fixture()(s)[0].level,1);
 s.combat.current.result='Cleared';s.stage.repeat=true;assert.equal(fixture()(s)[0].level,1);
 s.stage.repeat=false;assert.equal(fixture(690100)(s).length,0);
 s.battleReadiness.pendingSpawn=true;assert.equal(fixture()(s).length,0);
 s.battleReadiness.pendingSpawn=false;s.battleReadiness.timeScale=0;assert.equal(fixture()(s).length,0);
});
test('normal deaths, native squad sync, stage transitions and uninitialized saves have no recovery action',()=>{
 for(const [key,value] of [['known',false],['charactersInitialized',false],['expected',0],['arrangedCount',1],['syncRunning',true],['syncPending',true]]){
  const s=snapshot();s.battleReadiness[key]=value;assert.equal(fixture()(s).length,0,key);
 }
 const s=snapshot();s.stage.category=1;assert.equal(fixture()(s).length,0);
});

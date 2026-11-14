const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');
const c={};vm.createContext(c);vm.runInContext(fs.readFileSync('bridge/planner.js','utf8'),c);
const progress=rows=>JSON.parse(JSON.stringify(c.runeProgress(rows)));

test('raw rune totals retain offline investment while the online scope excludes it',()=>{
 const r=progress([{header:'HealthPoint',level:3,max:5},{header:'OfflineExpGain',level:2,max:4},
   {header:'OfflineGoodsGain',level:0,max:3},{header:'KillExpGain',level:1,max:1}]);
 assert.equal(r.learned,6);assert.equal(r.total,13);assert.equal(r.onlineLearned,4);assert.equal(r.onlineTotal,6);
 assert.equal(r.offlineLearned,2);assert.equal(r.offlineTotal,7);assert.equal(r.offlineNodes,2);assert.equal(r.offlineDeferred,2);
 assert.equal(r.maxed,1);assert.equal(r.progressKnown,true);
});

test('completing online nodes cannot fabricate the remaining offline levels',()=>{
 const r=progress([{header:'HealthPoint',level:5,max:5},{header:'OfflineReward',level:0,max:4}]);
 assert.equal(r.onlineLearned,r.onlineTotal);assert.notEqual(r.learned,r.total);assert.equal(r.offlineDeferred,1);
});

test('already completed offline nodes remain in the raw totals without requesting new investment',()=>{
 const r=progress([{header:'OfflineReward',level:4,max:4},{header:'KillGoods',level:0,max:3}]);
 assert.equal(r.offlineDeferred,0);assert.equal(r.offlineLearned,4);assert.equal(r.onlineLearned,0);assert.equal(r.maxed,1);
});

test('missing headers and malformed native levels cannot report a known complete scope',()=>{
 for(const rows of [[],null,[{header:'HealthPoint',level:NaN,max:2}],[{header:'HealthPoint',level:3,max:2}],
   [{header:'HealthPoint',level:true,max:2}],[{level:0,max:2}]]){
  const r=progress(rows);assert.equal(r.progressKnown,false);assert.equal(r.learned,null);assert.equal(r.onlineTotal,null);
 }
});

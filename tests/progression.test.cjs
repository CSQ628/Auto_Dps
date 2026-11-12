const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');
const context={};vm.createContext(context);
vm.runInContext(fs.readFileSync('bridge/planner.js','utf8')+'\nglobalThis.subject={nextTowerLevel,contentGoal,petPreference};',context);
const {nextTowerLevel,contentGoal,petPreference}=context.subject;

test('tower targets the next uncleared floor and stops at the native cap',()=>{
 assert.equal(nextTowerLevel({towerMaxCleared:0},20),1);
 assert.equal(nextTowerLevel({towerMaxCleared:1},20),2);
 assert.equal(nextTowerLevel({towerMaxCleared:19},20),20);
 for(const record of [{},{towerMaxCleared:-1},{towerMaxCleared:1.5},{towerMaxCleared:20},{towerMaxCleared:21}])assert.equal(nextTowerLevel(record,20),null);
 assert.equal(nextTowerLevel({towerMaxCleared:1},undefined),null);
});

test('content goals include owned DLC and free unlocks without treating unmet unlocks as unavailable',()=>{
 const goal=contentGoal([{id:'free',condition:'StageClear',eligible:true,unlocked:false},
  {id:'owned',condition:'DLC',eligible:true,unlocked:true},{id:'unowned',condition:'DLC',eligible:false,unlocked:false}]);
 assert.equal(goal.total,3);assert.equal(goal.eligibleTotal,2);assert.equal(goal.eligibleUnlocked,1);assert.equal(goal.excludedDlc,1);
 const unknown=contentGoal([{condition:'DLC',eligible:null,unlocked:false}]);
 assert.equal(unknown.eligibleTotal,null);assert.equal(unknown.eligibleUnlocked,null);
});

test('farming favors growth pets while pushing favors combat and keeps offline pets behind both',()=>{
 const ghost=petPreference('T_KillGoods_Rate',5,true),broom=petPreference('T_Critical_Rate',5,true);
 assert.ok(ghost.group>broom.group);
 assert.ok(petPreference('T_KillExpGain_Rate',5,true).group>ghost.group);
 assert.ok(petPreference('T_Critical_Rate',5,false).group>petPreference('T_KillGoods_Rate',5,false).group);
 assert.ok(petPreference('T_OfflineReward_Rate',1000,true).group<broom.group);
 assert.ok(petPreference('T_Critical_Rate',NaN,false).group<0);
});

const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');
const c={};vm.createContext(c);vm.runInContext(fs.readFileSync('bridge/planner.js','utf8')+'\nglobalThis.subject={bridgeStrategy,runePriorityBonus};',c);
const {bridgeStrategy,runePriorityBonus}=c.subject;
test('bridge accepts the same parameter bounds and falls back on malformed RPC options',()=>{
 for(const value of [null,undefined,{},[]])assert.equal(bridgeStrategy(value).recycle_batch,12);
 for(const value of [false,NaN,Infinity,1.5,0,13,'3'])assert.equal(bridgeStrategy({recycle_batch:value}).recycle_batch,12);
 const p=bridgeStrategy({recycle_batch:3,equipment_min_gain_percent:1.5,pet_mode:'keep',recommended_actives:false,allow_active_refund:false});
 assert.equal(p.recycle_batch,3);assert.equal(p.equipment_min_gain_percent,1.5);assert.equal(p.pet_mode,'keep');assert.equal(p.recommended_actives,false);assert.equal(p.allow_active_refund,false);
});
test('rune preference changes combat versus growth ordering',()=>{
 assert.ok(runePriorityBonus('BaseAttackPoint','combat')>runePriorityBonus('KillExpGain','combat'));
 assert.equal(runePriorityBonus('BaseAttackPoint','growth'),0);
 assert.ok(runePriorityBonus('BaseAttackPoint','balanced')<runePriorityBonus('BaseAttackPoint','combat'));
});

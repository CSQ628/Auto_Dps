const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');
const c={};vm.createContext(c);vm.runInContext(fs.readFileSync('bridge/planner.js','utf8'),c);
const pets=[{id:'ghost',ability:'T_KillGoods_Rate',factor:5},{id:'stone',ability:'T_Defense_Rate',factor:3}];
test('automatic following keeps the player choice across battle and farming; empty following is filled once',()=>{
 assert.equal(c.planPetFollower(pets,'stone','auto'),'stone');assert.equal(c.planPetFollower([...pets].reverse(),'stone','auto'),'stone');
 assert.equal(c.planPetFollower(pets,'missing','auto'),'ghost');assert.equal(c.planPetFollower([],'missing','auto'),null);
 assert.equal(c.planPetFollower(pets,'stone','keep'),null);
});
test('legacy explicit follower themes stay supported independently of battle phase',()=>{
 assert.equal(c.planPetFollower(pets,'stone','growth'),'ghost');assert.equal(c.planPetFollower(pets,'ghost','combat'),'stone');
 assert.equal(c.planPetFollower(pets,'stone','combat'),'stone');
});

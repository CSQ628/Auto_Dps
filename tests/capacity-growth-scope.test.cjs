const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');
const c={};vm.createContext(c);vm.runInContext(fs.readFileSync('bridge/planner.js','utf8'),c);
const rows=()=>[{id:1,header:'AttackSpeed',level:3,max:10},{id:2,header:'KillExpGain',level:2,max:5},
 {id:3,header:'InventorySlot',level:1,max:10},{id:4,header:'StorageTab',level:1,max:7},
 {id:5,header:'OfflineExpGain',level:2,max:3},{id:6,header:'MoveSpeed',level:0,max:10}];
test('capacity and offline investment keep battle scope while raw graduation totals increase',()=>{
 const r=rows(),before=c.runeProgress(r);assert.equal(before.battleScope.schema,1);
 assert.equal(before.battleScope.policy,'online_without_storage_capacity');
 for(const id of [3,4,5]){
  const next=rows();next.find(p=>p.id===id).level++;
  const after=c.runeProgress(next);assert.equal(after.learned,before.learned+1);
  assert.equal(after.battleScope.signature,before.battleScope.signature);
 }
});
test('attack, experience, movement, party and unknown effects still invalidate battle observations',()=>{
 for(const header of ['AttackSpeed','KillExpGain','MoveSpeed','SquadSlot','NewUnknownEffect']){
  const r=rows();r[0].header=header;const before=c.runeProgress(r);r[0].level++;
  assert.notEqual(c.runeProgress(r).battleScope.signature,before.battleScope.signature,header);
 }
});
test('native node identity and order are preserved independently of aggregate learned count',()=>{
 const r=rows(),before=c.runeProgress(r);r.reverse();
 assert.equal(c.runeProgress(r).battleScope.signature,before.battleScope.signature);
 r.find(p=>p.id===1).level--;r.find(p=>p.id===2).level++;
 assert.equal(c.runeProgress(r).learned,before.learned);
 assert.notEqual(c.runeProgress(r).battleScope.signature,before.battleScope.signature);
});
test('missing, duplicate or malformed node identifiers keep the old aggregate fallback',()=>{
 for(const change of [r=>delete r[0].id,r=>r[0].id=2,r=>r[0].id=true,r=>r[0].level=NaN]){
  const r=rows();change(r);assert.equal(c.runeProgress(r).battleScope,undefined);
 }
});

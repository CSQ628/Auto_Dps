const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');
const c={};vm.createContext(c);vm.runInContext(fs.readFileSync('bridge/planner.js','utf8'),c);
const rune=(id,header,extra={})=>({id,header,level:0,max:5,requires:[],values:[1,2,3,4,5],goods:[201],prices:[10],canLearn:true,...extra});
const plan=(rows,extra={})=>c.planRuneInvestment(rows,{soul:100,premium:9,squadCount:3,...extra});

test('affordable online targets outrank every pure offline target in every mode',()=>{
 for(const mode of ['growth','balanced','combat']){
  const p=plan([rune(1,'OfflineExpGain',{prices:[0],values:[1e9]}),rune(2,'KillExpGain',{prices:[100]}),rune(3,'OfflineGoodsGain')],{mode});
  assert.equal(p[0].id,2);assert.equal(p[0].offlineFallback,false);assert.ok(p.slice(1).every(x=>x.offlineFallback));
 }
});
test('unaffordable online goals allow offline soul consumption without disabling native currency gates',()=>{
 const rows=[rune(1,'AttackSpeed',{goods:[202],prices:[8]}),rune(2,'OfflineExpGain')];
 assert.equal(plan(rows,{premium:1})[0].id,2);
 assert.equal(plan(rows,{premium:1,budget:{permanent_runes:false}})[0].id,2);
 assert.equal(plan(rows,{soul:5,premium:1}).length,0);
 assert.equal(plan(rows,{soul:100,premium:1,budget:{soul_reserve:95}}).length,0);
});
test('zero default reserves unlock the eight-stone gate and spending never uses an invented conversion rate',()=>{
 const rows=[rune(1,'AttackSpeed',{goods:[202],prices:[8]}),rune(2,'BaseAttackPoint',{requires:[1],canLearn:false}),rune(3,'OfflineExpGain')];
 assert.equal(plan(rows,{premium:9,budget:{premium_reserve:2}})[0].id,3);
 const p=plan(rows);assert.equal(p[0].id,1);assert.equal(p[0].offlineFallback,false);
 assert.equal(plan(rows,{premium:0,soul:1e12})[0].id,3);
});
test('offline prerequisites are purchased only to the minimum required level for online benefit',()=>{
 const rows=[rune(1,'OfflineReward'),rune(2,'SquadSlot',{requires:[1],canLearn:false})];
 let p=plan(rows,{squadCount:1});assert.equal(p[0].id,1);assert.equal(p[0].target,2);assert.equal(p[0].offlineFallback,false);
 rows[0].level=1;rows[1].canLearn=true;p=plan(rows,{squadCount:1});assert.equal(p[0].id,2);assert.equal(p.at(-1).id,1);assert.equal(p.at(-1).offlineFallback,true);
});
test('all-rune completion includes unfinished offline targets and unavailable native nodes remain waiting',()=>{
 const rows=[rune(1,'AttackSpeed',{level:5}),rune(2,'OfflineReward',{canLearn:false})];
 assert.equal(plan(rows).length,0);assert.notEqual(c.runeWaiting(rows,{soul:100,premium:0}).reason,'runes_complete');
 rows[1].level=5;assert.equal(c.runeWaiting(rows,{soul:100,premium:0}).reason,'runes_complete');
});
test('waiting with insufficient stones reports the real currency shortage with zero reserve',()=>{
 const w=c.runeWaiting([rune(1,'AttackSpeed',{goods:[202],prices:[8]})],{soul:1e6,premium:1});
 assert.equal(w.reason,'premium_missing');assert.equal(w.minimumPremium,8);assert.equal(w.premiumSpendable,1);
});

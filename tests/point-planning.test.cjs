const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');
const c={};vm.createContext(c);vm.runInContext(fs.readFileSync('bridge/planner.js','utf8'),c);
const active=(uid,type,extra={})=>({uid,type,learned:1,unlock:0,max:10,canLearn:true,cooldown:10,increments:[1],subIncrements:[],...extra});
const passive=(uid,index,ability,extra={})=>({uid,index,ability,unlock:0,max:10,learned:0,factor:2,increment:2,trigger:'Always',requires:[],requireLevels:[],canLearn:true,...extra});
const rune=(id,header,extra={})=>({id,header,level:0,max:5,requires:[],values:[1,2,3,4,5],goods:[201],prices:[100],canLearn:true,...extra});
const skill=(as,ps,extra={})=>c.planSkillPoints(as,ps,{desired:as.map(a=>a.uid)},101,{arranged:true,frontline:true},extra);
const runes=(rs,extra={})=>c.planRuneInvestment(rs,{characters:[{level:40}],characterMax:101,squadCount:3,soul:1e9,premium:50,hasCooldown:true,hasShield:true,...extra});

test('core actives get their first point before passive investment and have no unconstrained refund plan',()=>{
 const p=skill([active('strike','GluttonyStrike',{learned:0})],[passive('power',0,'S_BaseAttackPoint_Rate')]);
 assert.equal(p.next.kind,'active');assert.equal(p.next.reason,'core_unlock');assert.equal(p.refund,undefined);
});
test('each native role directs points to its mechanic instead of universal attack speed',()=>{
 const pairs=[['HitShield','S_ShieldBonus_Rate'],['AttackSpeedStack','S_Critical_Rate'],['GluttonyStrike','S_Skill_Rate'],['ShapeShiftSlash','S_BasicDamageBonus_Rate'],['BrandBurst','S_SkillHaste_Static']];
 for(const [type,ability]of pairs){const p=skill([active('core',type,{learned:10})],[passive('role',0,ability),passive('other',1,'S_NormalMonster_Rate')]);assert.equal(p.next.skill,'role',type);}
});
test('passive routes buy exact required levels, count shared parents once, and do not fund every branch',()=>{
 const ps=[passive('root',0,'S_Defense_Rate',{max:3,learned:2}),passive('haste',1,'S_SkillHaste_Static',{requires:[0],requireLevels:[3],canLearn:false})];
 const p=skill([active('core','BrandBurst',{learned:10})],ps);assert.equal(p.next.skill,'root');assert.equal(p.next.target,'haste');assert.equal(p.next.steps,2);
 ps[0].learned=3;ps[0].canLearn=false;ps[1].canLearn=true;assert.equal(skill([active('core','BrandBurst',{learned:10})],ps).next.skill,'haste');
});
test('skill routes reject cycles, unavailable levels and malformed prerequisites without blocking independent growth',()=>{
 const ps=[passive('a',0,'S_Skill_Rate',{requires:[1],requireLevels:[1]}),passive('b',1,'S_Skill_Rate',{requires:[0],requireLevels:[1]}),passive('valid',2,'S_BaseAttackPoint_Rate')];
 assert.equal(skill([],ps).next.skill,'valid');
 ps[0].requires=[3];ps.push(passive('future',3,'S_Skill_Rate',{unlock:150}));assert.equal(skill([],ps).next.skill,'valid');
});
test('disabled active module does not hold passive points and disabled passive module does not spend them',()=>{
 const as=[active('core','HitShield',{learned:0})],ps=[passive('root',0,'S_Defense_Rate')];
 assert.equal(skill(as,ps,{active:false}).next.kind,'passive');assert.equal(skill(as,ps,{passive:false}).next.kind,'active');assert.equal(skill(as,ps,{active:false,passive:false}).next,null);
});
test('cooldown haste and shield passives follow the selected active triggers and team membership',()=>{
 const haste=passive('haste',0,'S_SkillHaste_Static'),shield=passive('shield',1,'T_ShieldBonus_Rate',{apply:1});
 assert.ok(c.passiveUtility(haste,[active('a','Unknown',{cooldown:10})])>c.passiveUtility(haste,[active('a','Unknown',{cooldown:0})]));
 assert.ok(c.passiveUtility(shield,[active('a','HitShield')],{arranged:true})>c.passiveUtility(shield,[active('a','Unknown')],{arranged:false}));
});
test('runes use one learned prerequisite level instead of maxing every ancestor',()=>{
 const rs=[rune(1,'MoveSpeed',{level:1,max:5}),rune(2,'KillExpGain',{requires:[1]})],p=runes(rs);
 assert.equal(p.find(x=>x.id===2).steps,1);assert.equal(p.find(x=>x.id===1).target,1);
 rs[0].level=0;rs[1].canLearn=false;rs[1].header='SquadSlot';const route=runes(rs,{squadCount:1}).find(x=>x.id===1);assert.equal(route.steps,2);assert.equal(route.reason,'minimum_prerequisite');
});
test('Offline prerequisites open online routes, pure offline benefit stays behind online choices, and cycles fail closed',()=>{
 const rs=[rune(1,'OfflineExpGain'),rune(2,'KillExpGain',{requires:[1],canLearn:false}),rune(3,'BaseAttackPoint')];
 let p=runes(rs);assert.equal(p.find(x=>x.id===1).target,2);assert.equal(p.find(x=>x.id===1).offlineFallback,false);
 rs[0].level=1;rs[1].canLearn=true;p=runes(rs);assert.ok(p.some(x=>x.id===2));assert.equal(p.at(-1).id,1);assert.equal(p.at(-1).offlineFallback,true);
 const cyclic=[rune(4,'KillExpGain',{requires:[5]}),rune(5,'KillGoods',{requires:[4]})];assert.equal(runes(cyclic).length,0);
});
test('soul and stone reserves are independent and unavailable expensive goals do not block ordinary spending',()=>{
 const rs=[rune(1,'KillExpGain',{prices:[1000]}),rune(2,'BaseAttackPoint',{prices:[50]}),rune(3,'DamageReduction',{goods:[202],prices:[3]})];
 assert.deepEqual(Array.from(runes(rs,{soul:100,premium:4,budget:{soul_reserve:20,premium_reserve:2}}),r=>r.id),[2]);
 assert.ok(!runes(rs,{budget:{permanent_runes:false}}).some(r=>r.id===3));
 assert.equal(runes(rs,{soul:10,premium:2}).length,0);
});
test('zero-cost foundation nodes and pressured capacity outrank optional growth; completed party reduces XP priority',()=>{
 let p=runes([rune(1,'SquadSlot',{max:1,prices:[0]}),rune(2,'KillExpGain')],{squadCount:1});assert.equal(p[0].id,1);
 p=runes([rune(1,'InventorySlot'),rune(2,'KillExpGain')],{inventoryPressure:true});assert.equal(p[0].id,1);
 p=runes([rune(1,'KillExpGain'),rune(2,'BaseAttackPoint')],{characters:[{level:101}],squadCount:1});assert.equal(p[0].id,2);
});
test('same-category rune marginal value accounts for current level and route cost',()=>{
 const p=runes([rune(1,'KillExpGain',{values:[1,1.1,1.2,1.3,1.4],level:1,prices:[100000]}),rune(2,'KillExpGain',{prices:[100]})]);assert.equal(p[0].id,2);
});
test('rune mode changes relative growth and combat priorities without altering budgets',()=>{
 const rs=[rune(1,'KillGoods'),rune(2,'NormalAttack')];assert.equal(runes(rs,{mode:'growth'})[0].id,1);assert.equal(runes(rs,{mode:'combat'})[0].id,2);
});
test('engraving waiting explains native one-level gates and never treats a reserve as completion',()=>{
 const rs=[rune(1,'MoveSpeed',{level:1}),rune(2,'AttackSpeed',{requires:[1],goods:[202],prices:[8]}),rune(3,'BaseAttackPoint',{requires:[2]})];
 const wait=c.runeWaiting(rs,{soul:1e6,premium:9,budget:{premium_reserve:2}});
 assert.equal(wait.reason,'premium_reserve');assert.equal(wait.minimumPremium,8);assert.equal(wait.premiumSpendable,7);
 rs[0].level=5;assert.equal(c.runeWaiting(rs,{soul:1e6,premium:9,budget:{premium_reserve:2}}).minimumSoul,null);
});
test('a route cannot reserve more scarce stones than the spendable total',()=>{
 const rs=[rune(1,'MoveSpeed',{goods:[202],prices:[4]}),rune(2,'SquadSlot',{requires:[1],canLearn:false,goods:[202],prices:[4]})];
 const p=runes(rs,{squadCount:1,premium:9,budget:{premium_reserve:2}});assert.equal(p.find(x=>x.id===1).target,1);
});
test('finite character point budgets cannot overspend or bypass prerequisites across levels 1 to 101',()=>{
 const ps=[passive('root',0,'S_BaseAttackPoint_Rate',{max:3}),passive('haste',1,'S_SkillHaste_Static',{max:8,unlock:5,requires:[0],requireLevels:[3]}),passive('skill',2,'S_Skill_Rate',{max:10,unlock:15,requires:[1],requireLevels:[7]})];
 const as=[active('core','GluttonyStrike',{learned:0,max:10})];let spent=0;
 for(let level=1;level<=101;level++){
  let points=level-1-spent;
  while(points>0){for(const p of ps)p.canLearn=p.learned<p.max&&p.unlock<=level&&p.requires.every((i,n)=>ps.find(r=>r.index===i).learned>=p.requireLevels[n]);
   const p=c.planSkillPoints(as,ps,{desired:['core']},level,{},{}).next;if(!p)break;
   const row=(p.kind==='active'?as:ps).find(r=>r.uid===p.skill);assert.ok(row.canLearn);assert.ok(row.learned<row.max);row.learned++;spent++;points--;assert.ok(spent<=level-1);
  }
 }
 assert.equal(spent,31);assert.ok(ps.every(p=>p.learned===p.max));assert.equal(as[0].learned,10);
});

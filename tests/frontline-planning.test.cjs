const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');
const c={};vm.createContext(c);vm.runInContext(fs.readFileSync('bridge/planner.js','utf8'),c);
const heroes=[{id:1,baseRange:.7},{id:2,baseRange:2.7},{id:3,baseRange:1.8},{id:4,baseRange:1}];
const active=(learned=10)=>({uid:'shield',type:'HitShield',learned,unlock:0,max:10,canLearn:learned<10,cooldown:20,increments:[.3]});
const passive=(uid,index,ability,learned=0)=>({uid,index,ability,unlock:0,max:10,learned,factor:2,increment:2,trigger:'Always',requires:[],requireLevels:[],canLearn:true,canRefund:true});
const passives=()=>[passive('health',0,'S_HealthPoint_Rate'),passive('attack',1,'S_BaseAttackPoint_Rate')];
const plan=(squad,rows=heroes,extra={})=>{
 const position=c.skillPartyPosition(squad,rows);
 return c.planSkillReallocation([active()],passives(),{desired:['shield']},40,1,
  {arranged:true,frontline:position.frontline===1,positionKnown:position.known},{...extra});
};

test('shortest native range keeps guardian defense allocation when squad order changes',()=>{
 for(const squad of [[1,2,3],[3,2,1],[0,2,1,3]]){
  assert.equal(c.skillPartyPosition(squad,heroes).frontline,1);
  assert.equal(plan(squad).next.skill,'health');
 }
 // Establish that the role context affects a real point allocation decision.
 const back=c.planSkillReallocation([active()],passives(),{desired:['shield']},40,1,{arranged:true,frontline:false,positionKnown:true});
 assert.equal(back.next.skill,'attack');
});

test('only arranged ranges participate and a dead hero retains its stable role',()=>{
 assert.equal(c.skillPartyPosition([2,3,4],heroes).frontline,4);
 assert.equal(c.skillPartyPosition([2,3,1],heroes.map(h=>({...h,alive:h.id!==1}))).frontline,1);
 assert.equal(c.skillPartyPosition([2,3,4],[...heroes,{id:5,baseRange:null}]).known,true);
});

test('missing, invalid, duplicated or tied role data cannot invent a frontline',()=>{
 for(const range of [undefined,null,0,-1,NaN,Infinity,'0.7']){
  const p=c.skillPartyPosition([1,2],heroes.map(h=>h.id===1?{...h,baseRange:range}:h));
  assert.equal(p.known,false);assert.equal(p.frontline,null);
 }
 for(const [squad,rows] of [[[1,2],heroes.filter(h=>h.id!==2)],[[1,1],heroes],[[1,'2'],heroes],[[1,2.5],heroes],[[],heroes],[[1,2],[{id:1,baseRange:1},{id:2,baseRange:1}]],[[1,2],[...heroes,{id:1,baseRange:.7}]]]){
  const p=c.skillPartyPosition(squad,rows);assert.equal(p.known,false);assert.equal(p.frontline,null);
 }
});

test('unknown frontline holds guardian passive refunds and spending, with no guessed target',()=>{
 const ps=passives();ps[1].learned=1;
 const p=c.planSkillReallocation([active()],ps,{desired:['shield']},40,0,{arranged:true,positionKnown:false});
 assert.equal(p.repair.reason,'position_unknown');assert.equal(p.repair.refund,undefined);assert.equal(p.next,null);
});

test('core active growth continues while position-sensitive passive allocation waits',()=>{
 const p=c.planSkillReallocation([active(0)],passives(),{desired:['shield']},40,1,{arranged:true,positionKnown:false});
 assert.equal(p.next.kind,'active');assert.equal(p.next.skill,'shield');
 const disabled=c.planSkillReallocation([active(0)],passives(),{desired:['shield']},40,1,{arranged:true,positionKnown:false},{modules:{active:false}});
 assert.equal(disabled.next,null);
});

test('passive module switches and non-guardian builds retain their independent policy',()=>{
 assert.equal(plan([1,2],heroes,{modules:{passive:false}}).repair,null);
 const ranger={...active(),type:'AttackSpeedStack'};
 const p=c.planSkillReallocation([ranger],passives(),{desired:['shield']},40,1,{arranged:true,positionKnown:false});
 assert.equal(p.repair.reason,'fill_target');assert.ok(p.next);
});

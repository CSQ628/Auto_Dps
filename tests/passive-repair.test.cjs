const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');
const planner=fs.readFileSync('bridge/planner.js','utf8'),c={};vm.createContext(c);vm.runInContext(planner,c);
const row=(uid,index,ability,extra={})=>({uid,index,ability,unlock:0,max:10,learned:0,factor:2,increment:2,trigger:'Always',requires:[],requireLevels:[],canLearn:false,canRefund:true,...extra});
const options={modules:{active:false,passive:true},allow_passive_refund:true,skill_point_reserve:0};
const plan=(ps,points=0,extra={})=>JSON.parse(JSON.stringify(c.planSkillReallocation([],ps,{desired:[]},101,points,{}, {...options,...extra})));
const canLearn=(p,ps)=>p.requires.every((index,n)=>index<0||ps.find(r=>r.index===index).learned>=p.requireLevels[n]);
const canRefund=(p,ps)=>p.learned>0&&ps.every(child=>!child.learned||child.requires.every((index,n)=>index!==p.index||p.learned-1>=child.requireLevels[n]));

test('zero wallet still plans correction, drains leaves and keeps shared prerequisites',()=>{
 const ps=[row('root',0,'S_BaseAttackPoint_Rate',{max:3,learned:3}),row('wrong',1,'S_Defense_Rate',{learned:4,requires:[0],requireLevels:[3]}),row('leaf',2,'S_Defense_Rate',{learned:2,requires:[1],requireLevels:[4]}),row('right',3,'S_BaseAttackPoint_Rate',{requires:[0],requireLevels:[3]})];
 let points=0,first=plan(ps),target=first.repair.target;assert.ok(first.repair.excess>0);assert.equal(first.repair.refund.skill,'leaf');
 const total=ps.reduce((n,p)=>n+p.learned,0),steps=[];
 for(let i=0;i<100;i++){
  for(const p of ps){p.canRefund=canRefund(p,ps);p.canLearn=points>0&&canLearn(p,ps);}
  const p=plan(ps,points);assert.deepEqual(p.repair.target,target,'restart reconstructs same target');
  if(p.repair.refund){const r=ps.find(r=>r.uid===p.repair.refund.skill);assert.ok(canRefund(r,ps));r.learned--;points++;steps.push('refund:'+r.uid);}
  else if(p.next){assert.equal(p.repair.excess,0);ps.find(r=>r.uid===p.next.skill).learned++;points--;steps.push('learn');}
  else break;
  assert.equal(points+ps.reduce((n,p)=>n+p.learned,0),total);
 }
 assert.equal(plan(ps,points).repair.excess,0);assert.ok(steps.includes('learn'));assert.ok(ps[0].learned>=3);
});

test('native refusal keeps the total switch independent and never learns into a wrong branch',()=>{
 const ps=[row('bad',0,'S_Defense_Rate',{learned:5,canRefund:false}),row('good',1,'S_BaseAttackPoint_Rate')];
 const p=plan(ps);assert.equal(p.repair.reason,'native_refund_blocked');assert.equal(p.repair.refund,null);assert.equal(p.next,null);
 assert.equal(plan(ps,0,{allow_passive_refund:false}).repair,null);
 assert.equal(plan(ps,0,{modules:{active:false,passive:false}}).repair,null);
});

test('multiple parents, cycles, invalid metadata and exact reserve are handled without a reset',()=>{
 const ps=[row('a',0,'S_Defense_Rate',{max:2,learned:2}),row('b',1,'S_Defense_Rate',{max:2,learned:2}),row('goal',2,'S_BaseAttackPoint_Rate',{requires:[0,1],requireLevels:[2,2]})];
 assert.equal(plan(ps,3,{skill_point_reserve:2}).repair.pool,7);
 assert.equal(Object.values(plan(ps,3,{skill_point_reserve:2}).repair.target).reduce((n,v)=>n+v,0),5);
 ps[0].requires=[2];ps[0].requireLevels=[1];assert.equal(plan(ps).repair.reason,'skill_catalogue_invalid');assert.equal(plan(ps).repair.refund,undefined);
 ps[0].requires=[88];assert.equal(plan(ps).repair.reason,'skill_catalogue_invalid');
});

test('active growth and passive repair converge across real level budgets without repeated refunds',()=>{
 const as=[{uid:'core',type:'GluttonyStrike',unlock:0,max:10,learned:1,cooldown:10,increments:[1]}];
 const ps=[row('root',0,'S_BaseAttackPoint_Rate',{max:3}),row('left',1,'S_SkillHaste_Static',{requires:[0],requireLevels:[3]}),row('right',2,'S_Defense_Rate',{requires:[0],requireLevels:[3]})];
 let points=0;
 for(let level=3;level<=40;level++){
  points++;
  const states=new Set();
  for(let n=0;n<150;n++){
   for(const p of ps){p.canRefund=canRefund(p,ps);p.canLearn=points>0&&canLearn(p,ps);}
   as[0].canLearn=points>0&&as[0].learned<10;
   const p=c.planSkillReallocation(as,ps,{desired:['core']},level,points,{}, {...options,modules:{active:true,passive:true}});
   if(!p.repair.refund&&!p.next)break;
   const state=JSON.stringify([points,as[0].learned,ps.map(p=>p.learned)]);assert.ok(!states.has(state),'allocation must not oscillate');states.add(state);
   if(p.repair.refund){ps.find(r=>r.uid===p.repair.refund.skill).learned--;points++;}
   else{(p.next.kind==='active'?as:ps).find(r=>r.uid===p.next.skill).learned++;points--;}
   assert.equal(points+as[0].learned+ps.reduce((n,p)=>n+p.learned,0),level-1);
   assert.ok(n<149,'bounded convergence');
  }
 }
});

function fixture(){
 let points=0,level=3,current;const calls=[];
 const dm={GetPassiveByUniqueID:uid=>uid,GetPassiveLearnedLevel:()=>level};
 const native={CanRefund:()=>true,Refund:()=>{calls.push('refund');level--;points++;return true;}};
 const character=()=>({id:1,points,skillPlanning:{repair:{target:{bad:0},refund:{skill:'bad',level}}}});
 const scan=()=>({snapshot:{account:'account',characters:[character()],sync:{},connection:{online:true}},actions:current?[current]:[]});
 const cx={api:()=>()=>0,A:{fields:{}},iter:()=>[],klass:x=>x,withManagedThread:fn=>fn(),rpc:{exports:{}},jsonSafe:x=>x,
  single:()=>dm,ref:x=>x,call:(o,n,a=[])=>o[n](...a),stat:(_,n,a=[])=>native[n](...a),scan,snapshot:()=>scan().snapshot};
 vm.createContext(cx);vm.runInContext(planner+'\n'+fs.readFileSync('bridge/automation.js','utf8')+'\nopportunityScan=scan;globalThis.execute=executeAction;',cx);
 return {calls,native,execute(extra={},strategy={}){current={id:1,key:'refund',kind:'passive_refund',skill:'bad',level:3,...extra};return cx.execute({account:'account',key:current.key,kind:current.kind,strategy});}};
}
test('executor confirms exact one-point receipt and rechecks authorization and native refusal',()=>{
 let f=fixture();assert.equal(f.execute().status,'confirmed');assert.deepEqual(f.calls,['refund']);
 for(const strategy of [{allow_passive_refund:false},{modules:{passive:false}}]){f=fixture();assert.equal(f.execute({},strategy).status,'stale');assert.deepEqual(f.calls,[]);}
 f=fixture();f.native.CanRefund=()=>false;assert.equal(f.execute().reason,'native_refund_blocked');assert.deepEqual(f.calls,[]);
 f=fixture();f.native.Refund=()=>true;assert.equal(f.execute().status,'pending');
 f=fixture();f.native.Refund=()=>false;assert.equal(f.execute().status,'rejected');
 f=fixture();assert.equal(f.execute({level:4}).status,'stale');assert.deepEqual(f.calls,[]);
});

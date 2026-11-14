const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');
const source=fs.readFileSync('bridge/planner.js','utf8'),c={};vm.createContext(c);vm.runInContext(source,c);
const opts={modules:{active:true,passive:true},allow_active_refund:true,allow_passive_refund:true,skill_point_reserve:0};
const active=(uid,learned=1,extra={})=>({uid,type:'Barrage',unlock:1,max:10,learned,canLearn:false,canRefund:true,increments:[0],...extra});
const passive=(uid,learned=0,extra={})=>({uid,index:0,unlock:1,max:40,learned,canLearn:false,canRefund:true,ability:'S_BaseAttackPoint_Rate',factor:2,increment:2,trigger:'Always',requires:[],requireLevels:[],...extra});
function plan(as,ps,points=0,options={}){return JSON.parse(JSON.stringify(c.planSkillReallocation(as,ps,{desired:as.map(a=>a.uid)},101,points,{}, {...opts,...options})));}

test('selected active excess is refunded while the first learned level remains equipped',()=>{
 const as=[active('core',6)],ps=[passive('growth')],p=plan(as,ps);
 assert.equal(p.repair.activeTarget.core,1);assert.equal(p.repair.activeExcess,5);
 assert.deepEqual(p.repair.refund,{kind:'active',skill:'core',level:6,targetLevel:1});
 assert.equal(p.next,null);assert.equal(p.repair.pool,5);
});

test('shared finite pool is history independent and converges across restarts with no lost points',()=>{
 const as=[active('core',6)],ps=[passive('growth',2)];let points=0;
 const original=plan(as,ps),seen=new Set(),total=8;
 for(let n=0;n<30;n++){
  as[0].canLearn=points>0;ps[0].canLearn=points>0;
  const p=plan(as,ps,points),key=JSON.stringify([as[0].learned,ps[0].learned,points]);
  assert.ok(!seen.has(key));seen.add(key);assert.deepEqual(p.repair.activeTarget,original.repair.activeTarget);assert.deepEqual(p.repair.target,original.repair.target);
  if(p.repair.refund){const r=p.repair.refund;(r.kind==='active'?as:ps).find(v=>v.uid===r.skill).learned--;points++;}
  else if(p.next){(p.next.kind==='active'?as:ps).find(v=>v.uid===p.next.skill).learned++;points--;}
  else break;
  assert.equal(points+as[0].learned+ps[0].learned,total);assert.ok(as[0].learned>=1);
 }
 assert.equal(as[0].learned,1);assert.equal(ps[0].learned,7);assert.equal(points,0);assert.equal(plan(as,ps).repair.reason,'aligned');
});

test('active/passive refund controls are independent and native refusal does not fabricate completion',()=>{
 let p=plan([active('core',6)],[passive('growth')],0,{allow_active_refund:false});
 assert.equal(p.repair.activeExcess,0);assert.equal(p.repair.activeTarget.core,6);
 p=plan([active('core',6)],[],0,{modules:{active:false,passive:true}});assert.equal(p.repair.activeExcess,0);
 p=plan([active('core',6)],[],0,{modules:{active:true,passive:false},skill_point_reserve:3});
 assert.deepEqual(p.repair.controls,{active:true,passive:false});assert.equal(p.repair.activeTarget.core,1);assert.equal(p.repair.excess,5);
 p=plan([active('core',6,{canRefund:false})],[passive('growth')]);
 assert.equal(p.repair.reason,'native_refund_blocked');assert.equal(p.repair.refund,null);assert.equal(p.next,null);
});

test('minimum skill level and reserve survive unlocking and growing canonical plans',()=>{
 const as=[active('a',0,{increments:[1]}),active('b',0,{increments:[2]})],ps=[passive('p')];let points=0;
 for(let level=2;level<=80;level++){
  points++;const seen=new Set();
  for(let n=0;n<200;n++){
   for(const r of [...as,...ps]){r.canLearn=points>0&&r.learned<r.max;r.canRefund=r.learned>0;}
   const p=plan(as,ps,points),key=JSON.stringify([points,as.map(a=>a.learned),ps.map(p=>p.learned)]);
   assert.ok(!seen.has(key),'must converge without oscillation');seen.add(key);
   if(p.repair.refund){const r=p.repair.refund;assert.ok(r.kind!=='active'||r.level>1);(r.kind==='active'?as:ps).find(v=>v.uid===r.skill).learned--;points++;}
   else if(p.next){(p.next.kind==='active'?as:ps).find(v=>v.uid===p.next.skill).learned++;points--;}
   else break;
   assert.equal(points+[...as,...ps].reduce((n,p)=>n+p.learned,0),level-1);
   assert.ok(n<199);
  }
 }
 assert.ok(as.every(a=>a.learned>=1));
 const p=plan(as,ps,points,{skill_point_reserve:8});assert.equal(p.repair.reserve,8);assert.ok(Object.values(p.repair.activeTarget).every(n=>n>=1));
});

test('duplicate or invalid active catalogue cannot authorize a selected refund',()=>{
 for(const as of [[active('core',-1)],[active('core',2,{max:1})],[active('core'),active('core')]]){
  const p=plan(as,[passive('p')]);assert.equal(p.repair.reason,'skill_catalogue_invalid');assert.equal(p.repair.refund,undefined);
 }
});

function executor(){
 let level=4,points=0,current;const calls=[],target={core:1},controls={active:true,passive:true};
 const character=()=>({id:1,points,activePlanning:{desired:['core']},skillPlanning:{repair:{controls,activeTarget:target,refund:{kind:'active',skill:'core',level}}}});
 const dm={GetActiveByUniqueID:uid=>uid,GetActiveLearnedLevel:()=>level,IsActiveEquipped:()=>true};
 const native={CanRefund:()=>true,Refund:()=>{calls.push('refund');level--;points++;return true;}};
 const scan=()=>({snapshot:{account:'a',characters:[character()],sync:{},connection:{online:true}},actions:current?[current]:[]});
 const ctx={api:()=>()=>0,A:{fields:{}},iter:()=>[],klass:x=>x,withManagedThread:f=>f(),rpc:{exports:{}},jsonSafe:x=>x,single:()=>dm,ref:x=>x,call:(o,n,a=[])=>o[n](...a),stat:(_,n,a=[])=>native[n](...a),scan,snapshot:()=>scan().snapshot};
 vm.createContext(ctx);vm.runInContext(source+'\n'+fs.readFileSync('bridge/automation.js','utf8')+'\nopportunityScan=scan;globalThis.run=executeAction;',ctx);
 return {native,calls,target,setLevel:n=>{level=n;},run(strategy={},extra={}){current={id:1,key:'core-refund',kind:'skill_refund',skill:'core',level,repair:true,...extra};return ctx.run({account:'a',key:current.key,kind:current.kind,strategy});}};
}

test('executor only accepts exact selected active receipts after fresh target and native authorization',()=>{
 let f=executor(),r=f.run();assert.equal(r.status,'confirmed');assert.equal(r.beforeLevel,4);assert.equal(r.afterLevel,3);assert.equal(r.afterPoints-r.beforePoints,1);assert.deepEqual(f.calls,['refund']);
 for(const strategy of [{allow_active_refund:false},{modules:{active:false}}]){f=executor();assert.equal(f.run(strategy).status,'stale');assert.deepEqual(f.calls,[]);}
 f=executor();f.native.CanRefund=()=>false;assert.equal(f.run().reason,'native_refund_blocked');assert.deepEqual(f.calls,[]);
 f=executor();f.target.core=4;assert.equal(f.run().reason,'skill_build_changed');assert.deepEqual(f.calls,[]);
 f=executor();f.setLevel(1);assert.equal(f.run().reason,'skill_build_changed');assert.deepEqual(f.calls,[]);
 f=executor();f.native.Refund=()=>true;assert.equal(f.run().status,'pending');
 f=executor();f.native.Refund=()=>false;assert.equal(f.run().status,'rejected');
});

test('active-only correction blocks new challenge only while executable and authorized',()=>{
 const repair={controls:{active:true,passive:false},excess:2,reason:'refund_branch',refund:{kind:'active',skill:'core',level:4}};
 const snapshot={squad:[1],characters:[{id:1,points:0,skillPlanning:{repair}}]},options={...opts,modules:{active:true,passive:false}};
 assert.equal(c.skillReallocationPending(snapshot,options),true);
 assert.equal(c.skillReallocationPending(snapshot,{...options,allow_active_refund:false}),false);
 repair.reason='native_refund_blocked';repair.refund=null;assert.equal(c.skillReallocationPending(snapshot,options),false);
 repair.reason='fill_target';repair.excess=0;snapshot.characters[0].points=1;assert.equal(c.skillReallocationPending(snapshot,options),true);
});

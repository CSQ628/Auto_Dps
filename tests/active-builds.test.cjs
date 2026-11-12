const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');
const context={};vm.createContext(context);
vm.runInContext(fs.readFileSync('bridge/planner.js','utf8')+'\nglobalThis.plan=planActives;',context);
const plan=(...args)=>JSON.parse(JSON.stringify(context.plan(...args)));
const row=(uid,type,unlock=0,learned=1)=>({uid,type,unlock,learned});

test('role builds respect unlock levels and retain a valid fallback for unknown roles',()=>{
 const rows=[row('shot','ParabolaShot'),row('stack','AttackSpeedStack',3),row('barrage','Barrage',8),row('critical','CriticalBuff',30,0)];
 assert.deepEqual(plan(rows,['shot','stack','barrage'],22,0).desired,['stack','barrage','shot']);
 assert.deepEqual(plan(rows,['shot','stack','barrage'],30,0).missing,['critical']);
 const fallback=plan([row('a','Unknown'),row('b','Unknown'),row('locked','Unknown',30)],['b',null,'a'],10,1);
 assert.deepEqual(fallback.desired,['b','a']);assert.equal(fallback.unequip,null);
});

test('already learned replacements get unique slots and never retire a target skill',()=>{
 const rows=[row('shield','HitShield'),row('rage','Berserk'),row('power','PowerAttack'),row('old','Unknown')];
 const p=plan(rows,['old',null,'shield'],22,0);
 assert.deepEqual(p.swaps,[{uid:'rage',slot:1,previous:null},{uid:'power',slot:0,previous:'old'}]);
 assert.equal(p.unequip,null);assert.deepEqual(p.refund,[]);
});

test('zero point replacement frees one slot and drains recoverable old points before freeing another',()=>{
 const rows=[row('shield','HitShield'),row('rage','Berserk',8,0),row('power','PowerAttack',8,0),row('old','Unknown',0,9),row('old2','Unknown')];
 let p=plan(rows,['shield','old','old2'],22,0);
 assert.deepEqual(p.unequip,{slot:1,uid:'old',target:'rage'});
 p=plan(rows,['shield',null,'old2'],22,0);
 assert.deepEqual(p.refund,['old']);assert.equal(p.unequip,null);
 assert.equal(plan(rows,['shield','old','old2'],22,1).unequip,null);
});

function fixture(){
 const slots=['old','shield','rage'],levels={old:2,shield:1,rage:1,power:0},calls=[];let points=0,current;
 const rows=()=>[row('old','AreaPowerAttack',0,levels.old),row('shield','HitShield',0,levels.shield),row('rage','Berserk',8,levels.rage),row('power','PowerAttack',8,levels.power)];
 const character=()=>({id:1,points,activePlanning:plan(rows(),slots,22,points)});
 const dm={GetEquippedActiveAt:(_,s)=>slots[s],GetActiveByUniqueID:uid=>uid,IsActiveEquipped:(_,uid)=>slots.includes(uid),GetActiveLearnedLevel:(_,uid)=>levels[uid]};
 const native={CanRefund:(_,uid)=>levels[uid]>0,Unequip:(_,slot)=>{calls.push('unequip');slots[slot]=null;return true;},
  Refund:(_,uid)=>{calls.push('refund');if(slots.includes(uid)||!levels[uid])return false;levels[uid]--;points++;return true;},
  Learn:(_,uid)=>{calls.push('learn');if(!points)return false;levels[uid]++;points--;return true;},
  Equip:(_,uid,slot)=>{calls.push('equip');if(!levels[uid])return false;slots[slot]=uid;return true;}};
 const scan=()=>({snapshot:{account:'account',characters:[character()],sync:{},connection:{online:true}},actions:current?[current]:[]});
 const c={api:()=>()=>0,A:{fields:{}},iter:()=>[],klass:x=>x,withManagedThread:fn=>fn(),rpc:{exports:{}},jsonSafe:x=>x,
  single:()=>dm,ref:x=>x,call:(o,n,a=[])=>o[n](...a),stat:(_,n,a=[])=>native[n](...a),scan,snapshot:()=>scan().snapshot};
 vm.createContext(c);vm.runInContext(fs.readFileSync('bridge/planner.js','utf8')+'\n'+fs.readFileSync('bridge/automation.js','utf8')+'\nopportunityScan=scan;globalThis.execute=executeAction;',c);
 return {slots,levels,calls,plan:()=>character().activePlanning,native,get points(){return points;},
  execute(action,mutate){current={id:1,key:action.kind,...action};if(mutate)mutate(current);return c.execute({account:'account',key:current.key,kind:current.kind});}};
}

test('real executor closes unequip refund learn equip with zero points and preserves the new build',()=>{
 const f=fixture(),oldPoints=Object.values(f.levels).reduce((a,b)=>a+b,0);
 const retire=f.plan().unequip;
 assert.equal(f.execute({kind:'skill_unequip',slot:retire.slot,skill:retire.uid,target:retire.target}).status,'confirmed');
 assert.equal(f.execute({kind:'skill_refund',skill:'old',level:2}).status,'confirmed');
 assert.equal(f.execute({kind:'active',skill:'power',level:0}).status,'confirmed');
 const swap=f.plan().swaps[0];assert.equal(f.execute({kind:'skill_equip',skill:swap.uid,slot:swap.slot}).status,'confirmed');
 assert.equal(f.execute({kind:'skill_refund',skill:'old',level:1}).status,'confirmed');
 assert.deepEqual(f.slots,['power','shield','rage']);assert.deepEqual(f.plan().missing,[]);
 assert.ok(!f.plan().refund.includes('power'));assert.equal(f.points+Object.values(f.levels).reduce((a,b)=>a+b,0),oldPoints);
 assert.deepEqual(f.calls,['unequip','refund','learn','equip','refund']);
});

test('skill execution rejects changed slots, target skills and unavailable point recovery',()=>{
 let f=fixture();assert.equal(f.execute({kind:'skill_unequip',slot:2,skill:'old',target:'power'}).reason,'skill_build_changed');assert.deepEqual(f.calls,[]);
 f=fixture();assert.equal(f.execute({kind:'skill_unequip',slot:1,skill:'shield',target:'power'}).reason,'skill_build_changed');assert.deepEqual(f.calls,[]);
 f=fixture();assert.equal(f.execute({kind:'skill_unequip',slot:0,skill:'old',target:'rage'}).reason,'skill_build_changed');assert.deepEqual(f.calls,[]);
 f=fixture();f.native.CanRefund=()=>false;assert.equal(f.execute({kind:'skill_unequip',slot:0,skill:'old',target:'power'}).reason,'skill_points_not_recoverable');assert.deepEqual(f.calls,[]);
 f=fixture();assert.equal(f.execute({kind:'skill_refund',skill:'power',level:1}).reason,'skill_is_planned');assert.deepEqual(f.calls,[]);
});


test('disabling recommended builds preserves equipped slots and only fills vacancies',()=>{
 const rows=[row('old','AreaPowerAttack'),row('shield','HitShield'),row('rage','Berserk',8),row('power','PowerAttack',8)];
 const p=plan(rows,['old',null,'shield'],22,5,false);
 assert.deepEqual(p.desired,['old','shield','rage']);assert.deepEqual(p.swaps,[{uid:'rage',slot:1,previous:null}]);
 assert.equal(p.unequip,null);assert.ok(!p.refund.includes('old'));
 assert.deepEqual(plan(rows,['old','shield','rage'],22,5,false).swaps,[]);
});

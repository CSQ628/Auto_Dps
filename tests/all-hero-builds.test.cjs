const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');
const c={};vm.createContext(c);vm.runInContext(fs.readFileSync('bridge/planner.js','utf8')+'\nglobalThis.plan=planActives;',c);
const catalogues=[
 [['AreaPowerAttack',0],['HitShield',3],['Berserk',8],['PowerAttack',8],['PowerAttack',15],['ElementalEmpower',30]],
 [['ParabolaShot',0],['AttackSpeedStack',3],['Barrage',8],['CenterStrike',8],['ParabolaShot',15],['CriticalBuff',30]],
 [['GluttonyStrike',0],['GluttonyKill',3],['GluttonyStrike',8],['GluttonyBurst',8],['FollowField',15]],
 [['ShapeShiftSlash',0],['ShapeShiftRampage',3],['SelfHeal',8],['AreaBurstAttackSpeed',8],['ShapeFormLineStrike',15]],
 [['BrandBurst',0],['HealAlly',3],['TeamAttackBuff',8],['HealAlly',8],['SignatureTeamShield',15]],
];
test('all five native hero catalogues have valid builds at each unlock boundary',()=>{
 for(const catalogue of catalogues)for(const level of [0,3,8,15,30]){
  const rows=catalogue.map(([type,unlock],i)=>({type,unlock,uid:String(i),learned:0})),p=c.plan(rows,[null,null,null],level,5);
  assert.equal(new Set(p.desired).size,p.desired.length);assert.ok(p.desired.length>0&&p.desired.length<=3);
  assert.ok(p.desired.every(uid=>rows.find(r=>r.uid===uid).unlock<=level));
 }
});
test('duplicate skill types use the highest unlocked native variant',()=>{
 const rows=catalogues[4].map(([type,unlock],i)=>({type,unlock,uid:String(i),learned:1}));
 assert.ok(c.plan(rows,['0','1',null],3,0).desired.includes('1'));
 assert.ok(c.plan(rows,['0','1','2'],8,0).desired.includes('3'));
 assert.ok(!c.plan(rows,['0','1','2'],8,0).desired.includes('1'));
});


test('Gula uses the native stack generator and spender instead of relying on four monster deaths at a Boss',()=>{
 const rows=[['strike','GluttonyStrike',0],['kill','GluttonyKill',3],['bite','GluttonyStrike',8],['burst','GluttonyBurst',8],['field','FollowField',15]].map(([uid,type,unlock])=>({uid,type,unlock,learned:1}));
 assert.deepEqual(Array.from(c.plan(rows,['kill','field','bite'],33,0).desired),['bite','field','burst']);
 assert.deepEqual(Array.from(c.plan(rows,[null,null,null],3,0).desired),['strike','kill']);
 assert.equal(c.plan(rows,['kill','field','bite'],33,0,false).swaps.length,0);
});

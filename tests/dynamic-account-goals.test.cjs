const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');
function planner(){const c={};vm.createContext(c);vm.runInContext(fs.readFileSync('bridge/planner.js','utf8'),c);return c;}
const xp={header:'KillExpGain',level:0,values:[1]};

test('XP priority uses each current native cap, including caps above the old fallback',()=>{
 const c=planner(),utility=(levels,cap)=>c.runeUtility(xp,{characters:levels.map(level=>({level})),characterMax:cap,squadCount:levels.length});
 const growing=utility([8],9),capped=utility([9],9);assert.ok(growing>capped);
 assert.equal(utility([140,139],140),growing);assert.equal(utility([140,140],140),capped);
 for(let i=0;i<4;i++){assert.equal(utility([9],9),capped);assert.equal(utility([108],140),growing);}
});

test('missing, invalid and incomplete party observations do not imply XP completion',()=>{
 const c=planner(),growing=c.runeUtility(xp,{characters:[{level:1}],characterMax:2});
 for(const cap of [undefined,null,0,-1,NaN,Infinity,1.5,'101'])
  assert.equal(c.runeUtility(xp,{characters:[{level:200}],characterMax:cap}),growing);
 for(const characters of [[],[{level:null}],[{level:101}]])
  assert.equal(c.runeUtility(xp,{characters,characterMax:101,squadCount:3}),growing);
});

function forgeFixture(){
 const c=planner(),tiers=[{tier:1,min:1},{tier:2,min:7},{tier:3,min:18}];
 const gear=new Map([[1,[{tier:3,grade:4}]],[2,[{tier:1,grade:1}]]]);
 const im={GetEquipment:id=>({get_Has:()=>gear.get(id)})};
 c.call=(o,n,a=[])=>o[n](...a);c.list=x=>x;c.itemInfo=x=>x;c.protectedEquipped=()=>false;
 const recipes=[1,2,3].map(tier=>({ID:tier,CraftType:1,CraftPart:1,RequireCubeLevel:tier===3?12:1,MinTier:tier,MaxTier:tier,MaterialID:[91],MaterialCount:[1]}));
 const entries=[{place:'inventory',info:{id:91,uid:'ore',count:20}}];
 return {c,gear,plan(characters,cube=12){return c.forgePlanning(im,characters,recipes,cube,c.tierForLevel(Math.max(...characters.map(x=>x.level)),tiers),entries,entries,c.bridgeStrategy(),{tiers});}};
}

test('mixed-level parties do not forge high tier solely for an ineligible low-level hero',()=>{
 const f=forgeFixture();assert.equal(f.plan([{id:1,level:25},{id:2,level:4}]).ID,1);
 f.gear.get(2)[0].grade=4;
 assert.equal(f.plan([{id:1,level:25},{id:2,level:4}]),null);
 assert.equal(f.plan([{id:1,level:25},{id:2,level:18}]).ID,3);
});

test('forge targets recompute across accounts, level boundaries and cube unlocks',()=>{
 const f=forgeFixture();
 for(let i=0;i<3;i++){
  assert.equal(f.plan([{id:2,level:4}]).ID,1);
  assert.equal(f.plan([{id:2,level:18}],11).ID,2);
  assert.equal(f.plan([{id:2,level:18}],12).ID,3);
 }
 assert.equal(f.plan([{id:2,level:6}]).ID,1);assert.equal(f.plan([{id:2,level:7}]).ID,2);
});

test('a lower hero can still benefit from the bottom of a native crafting band',()=>{
 const f=forgeFixture(),tiers=[{tier:1,min:1},{tier:2,min:7},{tier:3,min:18}];
 const im={GetEquipment:id=>({get_Has:()=>f.gear.get(id)})};
 assert.ok(f.c.forgeNeed(im,[{id:1,level:25},{id:2,level:4}],1,2,tiers,1)>0);
 assert.equal(f.c.forgeNeed(im,[{id:1,level:25},{id:2,level:4}],1,3,tiers,2),0);
});

test('skill goals change at native unlock levels without retaining another account role',()=>{
 const c=planner(),row=(uid,type,unlock)=>({uid,type,unlock,learned:0});
 const archer=[row('shot','ParabolaShot',1),row('stack','AttackSpeedStack',7),row('barrage','Barrage',18)];
 const mage=[row('brand','BrandBurst',1),row('heal','HealAlly',11)];
 const desired=(rows,level)=>Array.from(c.planActives(rows,[null,null,null],level,1).desired);
 for(let i=0;i<3;i++){
  assert.deepEqual(desired(archer,6),['shot']);assert.deepEqual(desired(mage,11),['brand','heal']);
  assert.deepEqual(desired(archer,18),['stack','barrage','shot']);
 }
});

test('owned DLC targets and native tower ranges remain independent across scans',()=>{
 const c=planner();for(let i=0;i<3;i++){
  assert.equal(c.contentGoal([{eligible:true,unlocked:true},{condition:'DLC',eligible:false,unlocked:false}]).eligibleTotal,1);
  assert.equal(c.contentGoal([{eligible:true,unlocked:false},{condition:'DLC',eligible:true,unlocked:false}]).eligibleTotal,2);
  assert.equal(c.nextTowerLevel({towerMaxCleared:9},9),null);assert.equal(c.nextTowerLevel({towerMaxCleared:9},20),10);
 }
});

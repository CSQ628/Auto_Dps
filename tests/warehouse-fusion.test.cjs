const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');
const c={};vm.createContext(c);vm.runInContext(fs.readFileSync('bridge/planner.js','utf8')+'\nglobalThis.subject={fusionPlans,fusionTasks};',c);
const entry=(uid,kind,count,place,tier=0,grade=1)=>({place,info:{uid,kind,count,tier,grade}});
const recipes=[{ID:1,CraftType:0,FusionType:0,Grade:1,MinTier:1,MaxTier:2,RequireCubeLevel:0,FusionCount:9},
 {ID:2,CraftType:0,FusionType:3,Grade:1,MinTier:0,MaxTier:0,RequireCubeLevel:0,FusionCount:9}];
test('ready equipment does not hide an entirely warehouse based gem batch',()=>{
 const entries=[entry('gear',1,9,'inventory',1),entry('gem',16,9,'storage')];
 const tasks=c.subject.fusionTasks(c.subject.fusionPlans(entries,recipes,1),1);
 assert.equal(tasks.length,2);assert.equal(tasks[0].ready,true);assert.equal(tasks[1].withdraw.info.uid,'gem');
});
test('mixed backpack and warehouse stacks are recalled until exactly one native batch is ready',()=>{
 let entries=[entry('bag',16,4,'inventory'),entry('stored',16,5,'storage')];
 let tasks=c.subject.fusionTasks(c.subject.fusionPlans(entries,recipes,1),1);
 assert.equal(tasks[0].ready,false);assert.equal(tasks[0].withdraw.info.uid,'stored');
 entries[1].place='inventory';tasks=c.subject.fusionTasks(c.subject.fusionPlans(entries,recipes,1),0);
 assert.equal(tasks[0].ready,true);assert.equal(tasks[0].withdraw,null);
});
test('full backpacks, insufficient quantities and unavailable cube levels do not consume materials',()=>{
 let entries=[entry('bag',16,4,'inventory'),entry('stored',16,5,'storage')];
 assert.equal(c.subject.fusionTasks(c.subject.fusionPlans(entries,recipes,1),0)[0].withdraw,null);
 entries[1].info.count=4;assert.equal(c.subject.fusionPlans(entries,recipes,1).length,0);
 assert.equal(c.subject.fusionPlans([entry('stored',16,9,'storage')],[{...recipes[1],RequireCubeLevel:10}],1).length,0);
});

test('native equipment bands combine mixed tiers across backpack and storage',()=>{
 for(const kind of [1,2,4]){
  const r={...recipes[0],FusionType:kind===4?1:0,MinTier:5,MaxTier:6};
  const rows=[entry('bag',kind,4,'inventory',5),entry('stored',kind,5,'storage',6)];
  const [p]=c.subject.fusionPlans(rows,[r],30);assert.ok(p);assert.equal(p.entries.length,2);
  assert.equal(c.subject.fusionTasks([p],1)[0].ready,false);
 }
});
test('overlapping bands prefer the highest unlocked recipe and never allocate a UID twice',()=>{
 const rows=[entry('lower',1,9,'inventory',5),entry('upper',1,9,'storage',6)];
 const rs=[{...recipes[0],ID:5,MinTier:5,MaxTier:6},{...recipes[0],ID:6,MinTier:6,MaxTier:7}];
 const plans=c.subject.fusionPlans(rows,rs,30);assert.equal(plans[0].recipe.ID,6);
 const uids=plans.flatMap(p=>p.entries.map(e=>e.info.uid));assert.equal(new Set(uids).size,uids.length);
});
test('mixed range matching never crosses category, grade or recipe bounds',()=>{
 const rows=[entry('base',1,4,'inventory',5),entry('wrong-grade',1,5,'storage',6,2),entry('outside',1,5,'storage',7),entry('accessory',4,5,'storage',6)];
 assert.equal(c.subject.fusionPlans(rows,[{...recipes[0],MinTier:5,MaxTier:6}],30).length,0);
});

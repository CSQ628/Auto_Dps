const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');
const c={};vm.createContext(c);vm.runInContext(fs.readFileSync('bridge/planner.js','utf8'),c);
const native={items:[{ID:11,ItemType:4,Tier:5,Grade:1},{ID:12,ItemType:4,Tier:5,Grade:2},{ID:21,ItemType:4,Tier:6,Grade:1},{ID:22,ItemType:4,Tier:6,Grade:2},{ID:100,RandomBagID:1000},{ID:200,RandomBagID:2000}],
 bags:[{ID:1000,Weight:1,reward:{ID:11,Count:1}},{ID:1000,Weight:1,reward:{ID:12,Count:1}},{ID:2000,Weight:1,reward:{ID:21,Count:1}},{ID:2000,Weight:1,reward:{ID:22,Count:1}}],
 stages:[{level:39,free:true,normal:5,elite:1,boss:0},{level:40,free:false,normal:0,elite:0,boss:1},{level:41,free:true,normal:5,elite:1,boss:0}],
 drops:[{Level:39,NormalBoxRate:50,NormalWeaponRate:0,NormalBoxID:100,BossBoxRate:50,BossWeaponRate:0,BossBoxID:100},
 {Level:40,NormalBoxRate:100,NormalWeaponRate:0,NormalBoxID:100,BossBoxRate:100,BossWeaponRate:0,BossBoxID:200},
 {Level:41,NormalBoxRate:50,NormalWeaponRate:0,NormalBoxID:200,BossBoxRate:50,BossWeaponRate:0,BossBoxID:200}],
 recipes:[{ID:50,CraftType:0,FusionType:4,Grade:1,MinTier:5,RequireCubeLevel:20,FusionCount:9,RandomBagID:500},
 {ID:51,CraftType:0,FusionType:4,Grade:2,MinTier:5,RequireCubeLevel:20,FusionCount:9,RandomBagID:501},
 {ID:1,CraftType:1,MaterialID:[11,12]},{ID:2,CraftType:1,MaterialID:[21,22]}],
 craftRewards:[{bag:500,id:21,weight:4,count:1},{bag:500,id:11,weight:96,count:1},{bag:501,id:22,weight:100,count:1}]};
const stock=(id,count,place='inventory')=>({info:{id,count,uid:String(id)},place});
const old={ID:1,CraftType:1,CraftPart:7,RequireCubeLevel:20,MinTier:5,MaxTier:6,MaterialID:[11,12],MaterialCount:[1,1]};
const high={...old,ID:2,RequireCubeLevel:30,MinTier:6,MaxTier:7,MaterialID:[21,22]};
function sources(){assert.equal(typeof c.buildCraftSources,'function');return c.buildCraftSources(native);}
function plan(entries=[],frontier=39,cube=33,recipes=[high,old],options={}){
 c.forgeNeed=()=>20;
 return c.forgePlanning(null,[{id:1,level:33}],recipes,cube,6,entries,entries,c.bridgeStrategy(options),{sources:sources(),frontier});
}
test('native drops distinguish free farming, first boss drops, impossible waves and synthesis probabilities',()=>{
 const s=sources();assert.equal(s.known,true);
 assert.equal(s.materials[11].firstStage,39);assert.equal(s.materials[11].firstFreeStage,39);
 assert.equal(s.materials[21].firstStage,40);assert.equal(s.materials[21].firstFreeStage,41);
 assert.equal(s.materials[21].fusion[0].probability,.04);assert.deepEqual(Array.from(s.materials[21].fusion[0].inputs),[11]);
 const x=JSON.parse(JSON.stringify(native));x.stages[0].normal=0;x.stages[0].elite=0;
 assert.equal(c.buildCraftSources(x).materials[11].firstStage,null);
});
test('incomplete forge plans use attainable upgrades instead of waiting for the highest unlocked tier',()=>{
 const p=plan([stock(12,10)]);assert.equal(p.ID,1);assert.equal(p.source,'drop');
 assert.equal(p.materials.find(m=>m.id===11).source,'drop');
 assert.equal(plan([],41).ID,2);
});
test('complete stock remains usable before its drop stage and user part priorities still win among complete recipes',()=>{
 assert.equal(plan([stock(21,1),stock(22,1)]).ID,2);
 assert.equal(plan([stock(21,1),stock(22,1)]).source,'inventory');
 const main={...old,ID:3,CraftPart:1};
 assert.equal(plan([stock(11,1),stock(12,1)],39,33,[old,main],{forge_priority_main_weapon:7,forge_priority_accessory:1}).ID,1);
});
test('synthesis is a possible source with its real cube prerequisite and is never claimed as a guaranteed reward',()=>{
 const p=plan([stock(11,9),stock(12,9)],39,33,[high]);assert.equal(p.source,'fusion_ready');
 assert.equal(p.materials[0].source,'fusion_ready');assert.equal(p.materials[0].fusion[0].probability,.04);
 const s=sources();s.materials[21].fusion[0].cubeLevel=40;s.materials[22].fusion[0].cubeLevel=40;
 c.forgeNeed=()=>20;
 assert.equal(c.forgePlanning(null,[],[high],33,6,[],[],c.bridgeStrategy(),{sources:s,frontier:39}).source,'future');
});
test('retention covers useful alternative parts without multiplying shared material requirements',()=>{
 const main={...old,ID:3,CraftPart:1},p=plan([stock(21,1),stock(22,1),stock(11,10),stock(12,10)],39,33,[high,main,old]);
 assert.equal(p.ID,2);
 assert.equal(p.retention.find(m=>m.id===11).required,1);assert.equal(p.retention.find(m=>m.id===12).required,1);
 assert.equal(p.retention.find(m=>m.id===21).required,1);
});
test('unknown provenance preserves ordinary planning and does not disable crafting or consume protected items',()=>{
 c.forgeNeed=()=>20;
 const p=c.forgePlanning(null,[],[high,old],33,6,[],[stock(21,9)],c.bridgeStrategy(),{sources:{known:false},frontier:39});
 assert.ok(p);assert.equal(p.source,'unknown');assert.equal(p.materials.find(m=>m.id===21).available,0);assert.equal(p.materials.find(m=>m.id===21).protected,9);
});


test('multi-step potential supply terminates on cycles and respects disabled synthesis',()=>{
 const s={known:true,materials:{1:{firstFreeStage:1,fusion:[]},2:{firstFreeStage:50,fusion:[{cubeLevel:10,inputs:[1]}]},3:{firstFreeStage:60,fusion:[{cubeLevel:20,inputs:[2]}]},4:{firstFreeStage:null,fusion:[{cubeLevel:0,inputs:[5]}]},5:{firstFreeStage:null,fusion:[{cubeLevel:0,inputs:[4]}]}}};
 const reachable=c.reachableCraftMaterials(s,20,39);assert.equal(reachable.get(3),2);assert.equal(reachable.has(4),false);assert.equal(c.reachableCraftMaterials(s,10,39).has(3),false);
 const p=plan([stock(11,9),stock(12,9)],39,33,[high],{modules:{combine:false}});assert.equal(p.source,'future');
});

test('failed source discovery retries at a bounded interval and stops reading tables after recovery',()=>{
 const cache={Date:{now:()=>now}};let now=0,reads=0;
 vm.createContext(cache);vm.runInContext(fs.readFileSync('bridge/planner.js','utf8'),cache);
 vm.runInContext('catalogueCache={recipes:[],materialSources:{known:false,materials:{}}}',cache);
 cache.readCraftSources=()=>{reads++;return {known:reads>=2,materials:{}};};
 assert.equal(cache.catalogue(null).materialSources.known,false);assert.equal(reads,1);
 now=59999;assert.equal(cache.catalogue(null).materialSources.known,false);assert.equal(reads,1);
 now=60000;assert.equal(cache.catalogue(null).materialSources.known,true);assert.equal(reads,2);
 now=180000;assert.equal(cache.catalogue(null).materialSources.known,true);assert.equal(reads,2);
});

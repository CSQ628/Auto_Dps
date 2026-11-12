const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');
const c={};vm.createContext(c);
vm.runInContext(fs.readFileSync('bridge/planner.js','utf8')+'\nglobalThis.subject={isFarmingStage,petPreference};',c);
const {isFarmingStage,petPreference}=c.subject;
test('a carried main-repeat flag never selects a farming pet inside the tower',()=>{
 for(const stage of [{category:1,repeat:true},{category:1,repeat:false},{category:0,repeat:false},{}]){
  assert.equal(isFarmingStage(stage),false);
  assert.ok(petPreference('T_Critical_Rate',5,isFarmingStage(stage)).group>petPreference('T_KillGoods_Rate',5,isFarmingStage(stage)).group);
 }
 assert.equal(isFarmingStage({category:0,repeat:true}),true);
});

test('native battle telemetry preserves record identity, live elapsed time and HP without writes',()=>{
 const record={sequence:7,level:2,difficulty:0,result:0,elapsed:0,characters:[{CharacterID:1,DamageDealt:120,DamageTaken:30,DamageBlocked:5,HealDealt:2}]};
 const manager={},player={},stats={_values:[10,45]},node={HealthPoint:100};let enabled=true;
 const context={stat:(_,name)=>name==='get_Default'?manager:enabled,single:()=>({}),read:(o,n)=>o[n],list:x=>x,
  call:(o,n,args=[])=>{
   if(o===manager)return ({get_Current:{...record,isNull:()=>false},get_Count:1,GetAt:{...record,isNull:()=>false}})[n];
   if(o===player)return ({get_DataID:1,get_ActualStats:stats,get_BattleNode:node})[n];
   if(n==='get_AlivePlayers')return [player];
   if(n==='get_Records')return record.characters;
   const key=n.replace('get_','');return o[key[0].toLowerCase()+key.slice(1)];
  }};
 vm.createContext(context);vm.runInContext(fs.readFileSync('bridge/automation.js','utf8').split('function combatSnapshot(s){')[1].split(/function opportunityScan\(/)[0].replace(/^/, 'function combatSnapshot(s){')+'\nglobalThis.combatReader=combatSnapshot;',context);
 const s={stage:{level:2,difficulty:0,elapsed:12}};
 const result=JSON.parse(JSON.stringify(context.combatReader(s)));
 assert.equal(result.available,true);assert.equal(result.current.sequence,7);assert.equal(result.current.elapsed,12);
 assert.equal(result.current.characters[0].dealt,120);assert.deepEqual(result.players,[{id:1,hp:45,maxHp:100}]);
 enabled=false;assert.equal(context.combatReader(s).reason,'native_statistics_disabled');
});

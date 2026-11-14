const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');
function scan({cleared=5,count=10,current=5,repeat=false,offset=0,blocked=[],towerMax=0,towerCleared=0,normalMax=160,running=false,ending=true}={}){
 const rows=Array.from({length:Math.max(5,cleared+1)},(_,i)=>({Level:i+1,Difficulty:Math.floor(i/40),Map:'Map Chapter'+String(Math.floor(i%40/10)+1).padStart(2,'0')+' A'}));
 const unavailable=new Set(blocked),gm={GetRequireItemID:(_,n)=>n===4?690100:0,CanEnterStage:(_,n)=>!unavailable.has(n),CanRepeat:(_,n)=>!unavailable.has(n),IsStageEnding:()=>ending};
 const im={get_Input:()=>({get_IsHolding:()=>false}),get_Cube:()=>({get_IsEmpty:()=>true}),FindOccupyTarget:()=>null};
 const server={get_MailUnreadCount:()=>0,get_IsLoggedIn:()=>true,get_IsTrustBlocked:()=>false};
 const sync={get_IsBusy:()=>false,get_QueueCount:()=>0,get_IsGrantBlocked:()=>false};
 const c={names:{game:'gm'},single:name=>name==='gm'||name==='DG.Manager.GameManager'?gm:name==='DG.Network.ServerManager'?server:name==='DG.Network.SyncManager'?sync:im,
  openPopups:()=>[],fullname:()=>null,A:{objectClass:()=>null},popupPolicy:()=>({blocked:[],manual:[],cleanup:null,offline:false}),sceneObject:()=>null,
  list:p=>p,read:(p,n)=>p[n],containerEntries:()=>[],protectedItem:()=>false,
  call:(p,n,args=[])=>n==='get_Datas'?p:p[n](...args)};
 vm.createContext(c);vm.runInContext(fs.readFileSync('bridge/planner.js','utf8')+'\nglobalThis.subject={progressionOpportunities,bridgeStrategy};',c);c.openPopups=()=>[];
 const snapshot={stage:{category:0,level:current,repeat,running},record:{maxCleared:cleared,towerMaxCleared:towerCleared},catalogue:{normalMax,towerMax}},actions=[];
 const add=(kind,key,label,priority,detail)=>actions.push({kind,key,...detail});
 c.subject.progressionOpportunities(snapshot,{_stageConfigTable:rows,_stageTable:rows},im,add,[],c.subject.bridgeStrategy({farm_candidate_count:count,farm_level_offset:offset}));
 c.auxiliaryOpportunities(snapshot,{},im,add,[],{preserve_open_panels:true,pause_on_manual_panels:false});
 return {snapshot,allActions:actions,actions:actions.filter(a=>a.mode==='farm')};
}
test('farming enumerates free cleared stages across the current chapter band',()=>{
 const r=scan();assert.deepEqual(Array.from(r.snapshot.progression.farmCandidates,p=>p.level),[5,3,2,1]);
 assert.deepEqual(Array.from(scan({count:3}).snapshot.progression.farmCandidates,p=>p.level),[5,3]);
 assert.deepEqual(Array.from(scan({count:1}).snapshot.progression.farmCandidates,p=>p.level),[5]);
 assert.deepEqual(Array.from(scan({offset:2}).snapshot.progression.farmCandidates,p=>p.level),[5,3,1]);
 assert.ok(r.actions.every(p=>p.freeEntry&&p.level!==4&&p.level<=5));
 assert.equal(scan({cleared:0}).actions.length,0);
});
test('already repeating a selected level emits alternatives without restarting that level',()=>{
 const r=scan({current:3,repeat:true});assert.ok(r.snapshot.progression.farmCandidates.some(p=>p.level===3));
 assert.ok(!r.actions.some(p=>p.level===3));
});

test('the current record anchors the visible game chapter across stage-zero boundaries',()=>{
 const frontierThreeNine=scan({cleared:29,current:29});
 const chapterThreeCandidates=Array.from(frontierThreeNine.snapshot.progression.farmCandidates,p=>p.level);
 assert.deepEqual(chapterThreeCandidates,[29,28,27,26,25,24,23,22,21]);
 assert.equal(frontierThreeNine.snapshot.progression.farmBand.start,21);
 assert.ok(!chapterThreeCandidates.includes(20)&&!chapterThreeCandidates.includes(18));
 const currentBand=scan({cleared:38,current:38});
 assert.deepEqual(Array.from(currentBand.snapshot.progression.farmCandidates,p=>p.level),[38,37,36,35,34,33,32,31]);
 assert.equal(currentBand.snapshot.progression.farmBand.start,31);
 assert.equal(currentBand.snapshot.progression.farmBand.chapter,4);
 assert.ok(!currentBand.snapshot.progression.farmCandidates.some(p=>p.level<31));
 const frontierFourNine=scan({cleared:39,current:39});
 assert.deepEqual(Array.from(frontierFourNine.snapshot.progression.farmCandidates,p=>p.level),[39,38,37,36,35,34,33,32,31]);
 assert.equal(frontierFourNine.snapshot.progression.farmBand.start,31);
 assert.equal(frontierFourNine.snapshot.progression.farmBand.end,39);
 assert.ok(!frontierFourNine.snapshot.progression.farmCandidates.some(p=>p.level===30));
 const chapterFour=scan({cleared:49,current:49});
 const chapterFourCandidates=Array.from(chapterFour.snapshot.progression.farmCandidates,p=>p.level);
 assert.deepEqual(chapterFourCandidates,[49,48,47,46,45,44,43,42,41]);
 assert.equal(chapterFour.snapshot.progression.farmCandidates.find(p=>p.level===49).difficulty,1);
 assert.ok(chapterFourCandidates.every(level=>Math.ceil(level/10)===5));
 const r=scan({cleared:45,current:45,offset:0});
 const levels=Array.from(r.snapshot.progression.farmCandidates,p=>p.level);
 assert.deepEqual(levels,[45,44,43,42,41]);
 assert.ok(!levels.includes(40)&&!levels.includes(18)&&!levels.includes(1));
 const spaced=scan({cleared:45,count:3,offset:2});
 assert.deepEqual(Array.from(spaced.snapshot.progression.farmCandidates,p=>p.level),[45,43]);
 const highestUnavailable=scan({cleared:45,blocked:[45]});
 assert.deepEqual(Array.from(highestUnavailable.snapshot.progression.farmCandidates,p=>p.level),[44,43,42,41]);
 const wholeBandUnavailable=scan({cleared:45,blocked:[41,42,43,44,45]});
 assert.deepEqual(Array.from(wholeBandUnavailable.snapshot.progression.farmCandidates,p=>p.level),[]);
 assert.equal(wholeBandUnavailable.snapshot.progression.farmBand.start,41);
 assert.ok(!wholeBandUnavailable.actions.some(p=>p.mode==='farm'&&p.level<41));
});
test('pushing from an old farming map jumps to the next frontier and never just disables repeat',()=>{
 const r=scan({cleared:28,current:18,repeat:true});
 const push=r.allActions.filter(p=>p.mode==='push');
 assert.equal(push.length,1);assert.equal(push[0].level,29);assert.equal(push[0].phase,'travel');
 assert.equal(push[0].repeat,false);assert.ok(!r.allActions.some(a=>a.key==='repeat_off'));
});
test('a paid gate on an already cleared low map does not prevent the free frontier challenge',()=>{
 const r=scan({cleared:8,current:3,repeat:true});
 assert.equal(r.snapshot.progression.gate,null);
 assert.equal(r.allActions.find(p=>p.mode==='push').level,9);
});
test('a missing frontier ticket enables free farming instead of replaying a cleared boss',()=>{
 const r=scan({cleared:3,current:2,repeat:false});
 assert.equal(r.snapshot.progression.gate.level,4);
 assert.ok(r.allActions.some(p=>p.mode==='guard'));assert.ok(!r.allActions.some(p=>p.mode==='push'));
});
test('incomplete main story never inserts an infinite-tower stop between push and farming',()=>{
 const incomplete=scan({cleared:49,current:49,towerMax:20,towerCleared:1,normalMax:160});
 assert.ok(!incomplete.allActions.some(a=>a.kind==='tower'));
 assert.ok(incomplete.allActions.some(a=>a.mode==='farm'&&a.level===49));
 const complete=scan({cleared:160,current:160,towerMax:20,towerCleared:1,normalMax:160});
 assert.ok(complete.allActions.some(a=>a.kind==='tower'&&a.level===2));
});


test('post-story tower entry carries an explicit free-entry receipt and only uses ended battles',()=>{
 const completed={cleared:160,current:159,towerMax:20,towerCleared:1,normalMax:160};
 const tower=scan(completed).allActions.find(a=>a.kind==='tower');
 assert.equal(tower.freeEntry,true);assert.equal(tower.ticket,0);
 assert.ok(!scan({...completed,running:true,ending:false}).allActions.some(a=>a.kind==='tower'));
 assert.ok(!scan({...completed,towerCleared:20}).allActions.some(a=>a.kind==='tower'));
});

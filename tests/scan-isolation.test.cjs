const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path'),test=require('node:test'),assert=require('node:assert/strict');
const sourceRoot=process.env.SCAN_SOURCE_ROOT||'.';
function fixture(fault){
 const pointer={isNull:()=>false};
 const base={account:'test',loaded:true,squad:[],characters:[],inventory:{count:0,capacity:20},stage:{level:1,category:0,running:true},record:{maxCleared:0},currencies:{soul:1000}};
 const options={modules:{},budget:{},auto_sort_items:false};
 const c={api:()=>()=>0,A:{fields:{}},iter:()=>[],klass:x=>x,withManagedThread:f=>f(),rpc:{exports:{}},ref:x=>x,list:x=>x,jsonSafe:x=>x,
  single:x=>x,read:(o,n)=>n==='_reachability'?pointer:o[n],
  call:(o,n)=>{
   if(n==='get_ClearedCount'&&fault==='achievements')throw Error('achievement_read');
   if(['get_IsSaveLoaded','get_IsMasterTableLoaded','CanUnlock','get_IsOnline','get_IsLoggedIn'].includes(n))return true;
   if(n==='GetAllCharacters')return [{ID:1}];
   if(['GetAllRunes','GetAllPets','get_UnlockedPets','get_AchievementConfigs'].includes(n))return [];
   if(n==='get_EquippedPetID')return '';
   if(['get_UnlockedCount','get_ClearedCount','get_QueueCount','get_SecondsUntilNextFlush'].includes(n))return 0;
   if(['get_IsTrustBlocked','get_IsBusy','get_IsGrantBlocked'].includes(n))return false;
   throw Error('unexpected_call:'+n);
  }};
 vm.createContext(c);vm.runInContext(['bridge/planner.js','bridge/automation.js'].map(p=>fs.readFileSync(path.join(sourceRoot,p),'utf8')).join('\n'),c);
 c.nativeAuxiliary=c.auxiliaryOpportunities;
 Object.assign(c,{bridgeStrategy:()=>options,maintenanceStatus:()=>({active:false}),snapshot:()=>structuredClone(base),combatSnapshot:()=>({available:false}),
  refreshRunesProvider:()=>{if(fault==='provider')throw Error('rune_provider');return pointer;},battleReadiness:()=>({known:false}),stageEntryState:()=>undefined,
  detailedActionAllowed:()=>true,contentGoal:()=>({}),growthContentRow:()=>({}),skillPartyPosition:()=>{if(fault==='characters')throw Error('skill_read');return {};},
  boxOpportunities:(s,drop,add)=>add('box','box:0','box',90,{grade:0}),
  inventoryOpportunities:(s,dm,im,add)=>{s.catalogue={characterMax:101};s.storage={pressure:false};s.equipmentPlanning=[];s.forging={ready:true};add('combine','combine:1','combine',108);if(fault==='workshop')throw Error('recipe_read');},
  runePointRows:()=>[],planRuneInvestment:()=>[],runeProgress:()=>({}),runeWaiting:()=>null,planPetFollower:()=>null,
  equipmentContext:()=>({}),auxiliaryOpportunities:s=>{if(fault==='auxiliary')throw Error('popup_read');s.manualBlockedKinds=[];s.automationBlocked=[];s.experienceBlocked=false;},
  progressionOpportunities:(s,dm,im,add)=>{s.progression={};add('progress','push:2','push',108,{mode:'push',level:2});},battleRecoveryPlans:()=>[],
  skillReallocationPending:()=>false,panelActionBlocked:()=>false,costAllowed:()=>true,
  guardedItemAction:f=>f(),cubeAction:()=>({status:'confirmed'})});
 return {c,scan:()=>c.opportunityScanFresh(),execute:()=>c.executeAction({account:'test',kind:'combine',key:'combine:1'})};
}
for(const [fault,section] of [['characters','characters'],['workshop','workshop'],['provider','runes'],['achievements','achievements']])test(section+' read failure preserves unrelated native opportunities',()=>{
 const scan=fixture(fault).scan();assert.ok(scan.actions.some(a=>a.kind==='box'));assert.ok(scan.snapshot.planningUnavailable[section]);
 if(['characters','workshop','provider'].includes(fault))assert.ok(!scan.actions.some(a=>a.kind==='progress'&&a.mode==='push'));
 if(fault==='achievements')assert.ok(scan.actions.some(a=>a.kind==='combine'));
});
test('workshop failure publishes neither its partial reservations nor actions',()=>{
 const scan=fixture('workshop').scan();assert.equal(scan.snapshot.forging,undefined);assert.equal(scan.snapshot.catalogue,undefined);assert.ok(!scan.actions.some(a=>a.kind==='combine'));
});
test('failed character plan discards earlier unlock and all dependent workshop planning',()=>{
 const scan=fixture('characters').scan();assert.ok(!scan.actions.some(a=>a.kind==='unlock'||a.kind==='combine'));assert.equal(scan.snapshot.planningUnavailable.workshop,'dependency_unavailable:characters');
});
test('each action rechecks the isolated scan and an independent combine can execute',()=>assert.equal(fixture('achievements').execute().status,'confirmed'));
test('recheck never dispatches a partially failed workshop plan',()=>assert.equal(fixture('workshop').execute().status,'stale'));
test('unknown native panel status remains a submission barrier',()=>{
 const f=fixture('auxiliary'),scan=f.scan();assert.deepEqual(Array.from(scan.snapshot.automationBlocked),['native_panel_state_unavailable']);assert.equal(f.execute().reason,'native_modal_active');
});
test('healthy scan preserves previous opportunities and adds the storage recovery barrier',()=>{
 const scan=fixture().scan();assert.equal(scan.snapshot.planningUnavailable,undefined);
 // Frozen healthy result from the preceding planner; no local backup checkout is required.
 const previous=JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures/scan-healthy-opportunities.json'),'utf8'));
 assert.equal(scan.storageRecoveryBarrier,1);
 const {storageRecoveryBarrier,...current}=JSON.parse(JSON.stringify(scan));
 assert.deepEqual(current,previous);
});
test('unknown strength holds new recovery stages but preserves same-stage recovery',()=>{
 const f=fixture('provider');f.c.battleRecoveryPlans=()=>[1,2].map(level=>({kind:'battle_recover',key:'recover:'+level,label:'recover',mode:'stage',level}));
 assert.deepEqual(Array.from(f.scan().actions.filter(a=>a.kind==='battle_recover'),a=>a.level),[1]);
});
function auxiliaryFixture(fault){
 const f=fixture(),c=f.c;c.auxiliaryOpportunities=c.nativeAuxiliary;
 const actions=[],s={inventory:{count:0,capacity:20},record:{maxCleared:0},stage:{category:0,running:true,level:1},catalogue:{normalMax:160,towerMax:100}};
 Object.assign(c,{openPopups:()=>[],popupPolicy:()=>({blocked:[],manual:[]}),panelActionBlocked:()=>false,sceneObject:()=>null,towerRepeatGuard:()=>null,nextTowerLevel:()=>1,
  call:(o,n)=>{if(n==='get_MailUnreadCount'){if(fault==='mail')throw Error('mail_read');return 0;}if(n==='IsStageEnding'){if(fault==='tower')throw Error('tower_read');return false;}if(n==='get_IsEmpty')return true;if(n==='get_IsHolding')return false;return {};},
  mailClaimObservation:()=>({available:true}),fullname:x=>x});
 return {c,s,actions,run:()=>c.auxiliaryOpportunities(s,{}, {},(...args)=>actions.push(args),[],{})};
}
test('failed skill and tower sections never mutate the previously published nested state',()=>{
 const c=fixture().c,s={characters:[{id:1,skills:[{level:1}]}],stage:{ending:false}},actions=[];
 for(const section of ['characters','tower'])c.collectOpportunitySection(s,(...a)=>actions.push(a),[],section,draft=>{
  if(section==='characters')draft.characters[0].skills[0].level=999;else draft.stage.ending=true;
  throw Error('native_read_failed');
 });
 assert.equal(s.characters[0].skills[0].level,1);assert.equal(s.stage.ending,false);assert.equal(actions.length,0);
});
test('mail failure keeps known UI state and independently readable tower state',()=>{
 const f=auxiliaryFixture('mail');f.run();assert.equal(f.s.planningUnavailable.mail,'mail_read');assert.equal(f.s.automationBlocked.length,0);assert.equal(f.s.tower.max,100);
});
test('tower failure does not discard already read mail and popup state',()=>{
 const f=auxiliaryFixture('tower');f.run();assert.equal(f.s.planningUnavailable.tower,'tower_read');assert.equal(f.s.mail.unread,0);assert.equal(f.s.automationBlocked.length,0);
});
test('unavailable workshop catalogue cannot stop a verified return from the tower',()=>{
 const f=auxiliaryFixture();f.s.stage={category:1,running:false};delete f.s.catalogue;
 f.s.planningUnavailable={workshop:'native_read_failed'};
 const c=f.c,read=c.read,call=c.call;
 c.read=(o,n)=>n==='_returnLevel'?9:n==='_returnDifficulty'?0:read(o,n);
 c.call=(o,n)=>n==='IsStageEnding'||n==='CanEnterStage'?true:n==='GetRequireItemID'?0:call(o,n);
 f.run();
 assert.equal(f.actions.find(a=>a[0]==='tower_return')[4].level,9);
 assert.equal(f.s.planningUnavailable.tower,undefined);
 assert.ok(!f.actions.some(a=>a[0]==='tower'));
});

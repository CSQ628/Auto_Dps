const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');

function fixture({panel=null,cube=false,holding=false,full=false,pause=false,accepted=true,advance=true,online=true,backlogged=false,blocked=false,counts=[10,2,1]}={}){
 const calls=[],inventory={locked:[{uid:'locked-gear',count:1}],count:full?46:38,capacity:46},cubeItems=cube?['manual-ingredient']:[];
 let opened=205;
 const drop={Count:grade=>counts[grade],TryOpen:grade=>{calls.push('TryOpen');if(accepted&&advance){counts[grade]--;opened++;}return accepted;}};
 const im={get_Input:()=>({get_IsHolding:()=>holding}),get_Cube:()=>({get_IsEmpty:()=>!cubeItems.length})};
 const server={get_MailUnreadCount:()=>0},gm={IsStageEnding:()=>false};
 const action={kind:'box',key:'box:0:205',grade:0,count:10,priority:99};
 const snapshot={account:'fixture',inventory,record:{boxes:opened,towerMaxCleared:0},catalogue:{towerMax:10},stage:{category:0,running:true},sync:{blocked,backlogged},connection:{online}};
 const c={api:()=>()=>0,A:{fields:{},objectClass:x=>x},iter:()=>[],klass:x=>x,fullname:x=>x,withManagedThread:f=>f(),rpc:{exports:{}},jsonSafe:x=>x,ref:x=>x,list:x=>x,
  single:n=>n.includes('DropManager')?drop:n.includes('RecordManager')?{get_BoxOpenCount:()=>opened}:n.includes('GameManager')?gm:n.includes('ServerManager')?server:im,
  call:(o,n,args=[])=>{if(!o||typeof o[n]!=='function')throw Error('unexpected native call '+n);return o[n](...args);},sceneObject:()=>null,read:(o,n)=>o[n],mailClaimObservation:()=>({available:false})};
 vm.createContext(c);vm.runInContext(fs.readFileSync('bridge/planner.js','utf8')+'\n'+fs.readFileSync('bridge/automation.js','utf8'),c);
 c.openPopups=()=>panel?[panel]:[];
 const actions=[],issues=[],add=(kind,key,label,priority,detail)=>actions.push({kind,key,label,priority,...detail});
 c.auxiliaryOpportunities(snapshot,{},im,add,issues,c.bridgeStrategy({preserve_open_panels:true,pause_on_manual_panels:pause}));
 // Include exactly the same native box planner and final panel filter as a full scan.
 if(c.boxOpportunities)c.boxOpportunities(snapshot,drop,add);else actions.push(action);
 const scan={snapshot,actions:actions.filter(a=>!snapshot.manualBlockedKinds.includes(a.kind))};
 c.opportunityScan=()=>scan;
 return {c,snapshot,scan,calls,cubeItems,inventory,execute:()=>c.executeAction({kind:'box',key:action.key,account:'fixture'})};
}

for(const panel of ['DG.UI.Popup.StoragePopup','DG.UI.Popup.CubePopup'])test('kept '+panel+' allows native single opening with locked gear and free slots',()=>{
 const f=fixture({panel,cube:true}),before=JSON.stringify([f.inventory.locked,f.cubeItems]);
 assert.ok(!f.snapshot.manualBlockedKinds.includes('box'));
 assert.ok(f.snapshot.manualBlockedKinds.includes('combine'));assert.ok(f.snapshot.manualBlockedKinds.includes('equipment'));
 assert.equal(f.execute().status,'confirmed');assert.deepEqual(f.calls,['TryOpen']);
 assert.equal(JSON.stringify([f.inventory.locked,f.cubeItems]),before);
 assert.equal(f.snapshot.manualPanels[0],panel);
});

test('leftover cube contents do not block opening when no item is held',()=>{
 const f=fixture({cube:true});assert.ok(!f.snapshot.manualBlockedKinds.includes('box'));
 assert.equal(f.execute().status,'confirmed');assert.deepEqual(f.cubeItems,['manual-ingredient']);
});

test('locked inventory alone never disables single opening',()=>{
 const f=fixture();assert.equal(f.execute().status,'confirmed');assert.equal(f.inventory.locked[0].count,1);
});

for(const options of [{holding:true},{panel:'DG.UI.ConfirmPopup'},{panel:'DG.UI.Popup.StoragePopup',pause:true},{panel:'DG.UI.Popup.TradePopup'},{online:false},{backlogged:true},{blocked:true}])test('opening still respects guard '+JSON.stringify(options),()=>{
 const f=fixture(options);assert.notEqual(f.execute().status,'confirmed');assert.deepEqual(f.calls,[]);
});

test('box queue counts remain visible when the bag is full and no opening is planned',()=>{
 const f=fixture({full:true});assert.equal(f.snapshot.boxes.total,13);assert.equal(f.snapshot.boxes.freeSlots,0);
 assert.ok(!f.scan.actions.some(a=>a.kind==='box'));assert.deepEqual(f.calls,[]);
});

test('native false is explained and never counted as a successful opening',()=>{
 const r=fixture({accepted:false}).execute();assert.equal(r.status,'rejected');assert.equal(r.reason,'native_box_rejected');
 assert.equal(r.queueBefore,10);assert.equal(r.queueAfter,10);assert.equal(r.recordAfter,r.recordBefore);
});

test('unconfirmed native acceptance stays reserved rather than being assumed failed',()=>{
 const r=fixture({advance:false}).execute();assert.equal(r.status,'pending');assert.equal(r.reason,'box_result_unconfirmed');
});

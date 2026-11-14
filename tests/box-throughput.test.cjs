const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');

function fixture({counts=[20,5,3],free=40,cost=1,pendingAt=0,rejectAt=0,throwAt=0,panel=null,strict=false}={}){
 const state={counts:[...counts],record:100,occupied:50-free,capacity:50,calls:[],now:0,online:true,loggedIn:true,trust:false,blocked:false,queue:0,holding:false,maintenance:false,loaded:true,panel,locked:['keep'],cost};
 const bag={get_OccupiedCount:()=>state.occupied,get_Capacity:()=>state.capacity};
 const im={get_IsLoaded:()=>state.loaded,get_Inventory:()=>bag,get_Input:()=>({get_IsHolding:()=>state.holding})};
 const dm={get_IsSaveLoaded:()=>state.loaded,get_IsMasterTableLoaded:()=>state.loaded};
 const server={get_IsLoggedIn:()=>state.loggedIn,get_IsTrustBlocked:()=>state.trust};
 const sync={get_IsGrantBlocked:()=>state.blocked,get_QueueCount:()=>state.queue};
 const reach={isNull:()=>false,get_IsOnline:()=>state.online};
 const record={get_BoxOpenCount:()=>state.record};
 const drop={Count:g=>state.counts[g],TryOpen:g=>{
  state.calls.push(g);state.now+=state.cost;const n=state.calls.length;
  if(n===throwAt)throw Error('lost native result');
  if(n===rejectAt)return false;
  if(n!==pendingAt){state.counts[g]--;state.record++;state.occupied++;state.afterOpen?.();}
  return true;
 }};
 const c={Date:{now:()=>state.now},api:()=>()=>0,A:{fields:{},objectClass:x=>x},iter:()=>[],klass:x=>x,fullname:x=>x,withManagedThread:f=>f(),rpc:{exports:{}},jsonSafe:x=>x,ref:x=>x,list:x=>x,
  single:n=>n.includes('DropManager')?drop:n.includes('RecordManager')?record:n.includes('ItemManager')?im:n.includes('ServerManager')?server:n.includes('SyncManager')?sync:dm,
  stat:()=>'/saves/fixture',read:()=>reach,
  call:(o,n,args=[])=>{if(!o||typeof o[n]!=='function')throw Error('unexpected native call '+n);return o[n](...args);}};
 vm.createContext(c);vm.runInContext(fs.readFileSync('bridge/planner.js','utf8')+'\n'+fs.readFileSync('bridge/automation.js','utf8'),c);
 c.maintenanceStatus=()=>({known:true,active:state.maintenance});c.openPopups=()=>state.panel?[state.panel]:[];
 const strategy={preserve_open_panels:true,pause_on_manual_panels:strict};
 const command=id=>({account:'fixture',requestId:id,strategy});
 return {state,c,open:id=>c.openBoxBatch(command(id)),scan:id=>c.boxScanFresh(command(id))};
}

test('one bounded batch opens eight actual boxes across all three grades without a full scan',()=>{
 const f=fixture();f.c.opportunityScan=()=>{throw Error('full growth scan must not run');};
 const r=f.open('first');assert.equal(r.status,'confirmed');assert.equal(r.openedCount,8);assert.equal(r.recordAfter-r.recordBefore,8);
 assert.equal(f.state.calls.length,8);assert.equal(new Set(f.state.calls).size,3);assert.deepEqual(f.state.locked,['keep']);
 assert.equal(r.observations.every(o=>o.accepted===true&&o.recordAfter>o.recordBefore),true);
});
test('existing queues drain over consecutive batches instead of one box per growth interval',()=>{
 const f=fixture({counts:[20,5,3]});let opened=0;
 for(let i=0;i<4;i++)opened+=f.open('batch-'+i).openedCount;
 assert.equal(opened,28);assert.equal(f.scan().snapshot.boxes.total,0);
});
test('newly dropped single box opens immediately without waiting for its grade maximum',()=>{
 const f=fixture({counts:[0,1,0]});assert.equal(f.open('one').openedCount,1);assert.equal(f.scan().snapshot.boxes.total,0);
});
test('native bag occupancy is rechecked after each box and full bag stops consumption',()=>{
 const f=fixture({free:2});const r=f.open('space');assert.equal(r.openedCount,2);assert.equal(r.stopReason,'inventory_full');assert.equal(f.state.calls.length,2);
});
test('slow native work yields after the current verified open',()=>{
 const f=fixture({cost:25});const r=f.open('slow');assert.equal(r.openedCount,1);assert.equal(r.stopReason,'box_batch_yield');
});
test('a new sync block caused by a native opening stops the batch before another consumption',()=>{
 const f=fixture();f.state.afterOpen=()=>{f.state.queue=101;};
 const r=f.open('sync-changes');assert.equal(r.openedCount,1);assert.equal(r.stopReason,'native_sync_backlog');
});
test('batch reserves the initial free slots even if inventory occupancy updates on a later frame',()=>{
 const f=fixture({free:2});f.state.afterOpen=()=>{f.state.occupied--;};
 assert.equal(f.open('deferred-bag').openedCount,2);assert.equal(f.state.calls.length,2);
});
test('duplicate command returns its receipt and never consumes twice',()=>{
 const f=fixture();assert.equal(f.open('same').openedCount,8);assert.equal(f.open('same').openedCount,8);assert.equal(f.state.calls.length,8);
});
test('partly confirmed batch stops on pending and next scan settles exactly its final box',()=>{
 const f=fixture({pendingAt:3});let r=f.open('partial');assert.equal(r.status,'pending');assert.equal(r.openedCount,2);assert.equal(f.state.calls.length,3);
 assert.equal(f.open('another').reason,'box_result_unconfirmed');assert.equal(f.state.calls.length,3);
 assert.equal(f.scan('partial').receipt.status,'pending');f.state.record++;
 r=f.scan('partial').receipt;assert.equal(r.status,'confirmed');assert.equal(r.openedCount,3);assert.equal(f.scan('partial').receipt.openedCount,3);
});
test('unknown native exception preserves pending rather than replaying the call',()=>{
 const f=fixture({throwAt:1});assert.equal(f.open('unknown').status,'pending');assert.equal(f.open('new').reason,'box_result_unconfirmed');assert.equal(f.state.calls.length,1);
});
test('rejection after a confirmed prefix reports the exact prefix and stops',()=>{
 const f=fixture({rejectAt:3});const r=f.open('reject');assert.equal(r.status,'confirmed');assert.equal(r.openedCount,2);assert.equal(r.stopReason,'native_box_rejected');assert.equal(f.state.calls.length,3);
});
for(const guard of ['online','loggedIn','trust','blocked','queue','holding','maintenance','loaded','trade','unknown','strict'])test('fast batch retains native guard '+guard,()=>{
 const f=fixture({strict:guard==='strict'}),s=f.state;
 if(['online','loggedIn','loaded'].includes(guard))s[guard]=false;
 if(['trust','blocked','holding','maintenance'].includes(guard))s[guard]=true;
 if(guard==='queue')s.queue=101;
 if(guard==='trade')s.panel='DG.UI.Popup.TradePopup';
 if(guard==='unknown')s.panel='DG.UI.ConfirmPopup';
 if(guard==='strict')s.panel='DG.UI.Popup.StoragePopup';
 const r=f.open('guard');assert.equal(r.openedCount,0);assert.equal(s.calls.length,0);
});
test('kept bag or cube window and locked gear still permit bounded native opening',()=>{
 for(const panel of ['DG.UI.Popup.StoragePopup','DG.UI.Popup.CubePopup']){
  const f=fixture({panel});assert.equal(f.open('allowed').openedCount,8);assert.deepEqual(f.state.locked,['keep']);
 }
});
test('account mismatch cannot consume any box',()=>{
 const f=fixture();assert.throws(()=>f.c.openBoxBatch({account:'wrong',requestId:'mismatch'}),/account_changed/);assert.equal(f.state.calls.length,0);
});


test('durable completed receipt restores duplicate suppression after a bridge reload',()=>{
 const first=fixture(),receipt=first.open('completed');
 const reconnected=fixture();reconnected.state.record=receipt.recordAfter;
 reconnected.c.restoreBoxReceipts([receipt]);
 assert.equal(reconnected.scan('completed').receipt.source,'durable_bridge_receipt');
 assert.equal(reconnected.open('completed').openedCount,8);
 assert.equal(reconnected.state.calls.length,0);
 assert.equal(reconnected.open('fresh').openedCount,8);
});

test('restored partial receipt still waits for its original native record before settlement',()=>{
 const first=fixture({pendingAt:3}),receipt=first.open('partial-restored');
 const reconnected=fixture();reconnected.state.record=receipt.pendingRecord;
 reconnected.c.restoreBoxReceipts([receipt]);
 assert.equal(reconnected.scan('partial-restored').receipt.status,'pending');
 assert.equal(reconnected.open('fresh').reason,'box_result_unconfirmed');
 assert.equal(reconnected.state.calls.length,0);
 reconnected.state.record++;
 assert.equal(reconnected.scan('partial-restored').receipt.openedCount,3);
 assert.equal(reconnected.scan('partial-restored').receipt.status,'confirmed');
 assert.equal(reconnected.open('fresh').openedCount,8);
});

test('receipt restoration validates the whole list before changing its cache',()=>{
 const first=fixture(),receipt=first.open('valid');const fresh=fixture();
 assert.throws(()=>fresh.c.restoreBoxReceipts([receipt,{...receipt,requestId:'bad',openedCount:99}]),/invalid_box_receipt/);
 assert.equal(fresh.open('valid').openedCount,8);assert.equal(fresh.state.calls.length,8);
});

test('another account pending receipt is neither exposed nor allowed to block the current account',()=>{
 const f=fixture({pendingAt:1});f.open('old-account');
 f.c.stat=()=>'/saves/other';
 assert.equal(f.c.boxScanFresh({requestId:'old-account'}).receipt,null);
 const r=f.c.openBoxBatch({account:'other',requestId:'new-account'});
 assert.equal(r.openedCount,8);assert.equal(f.state.calls.length,9);
});

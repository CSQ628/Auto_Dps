const fs=require('node:fs'),test=require('node:test'),assert=require('node:assert/strict');
const source=fs.readFileSync('tests/box-throughput.test.cjs','utf8').split("test('one bounded batch")[0];
const fixture=new Function('require',source+';return fixture;')(require);

test('native fence closes a missing old request and blocks a late queued callback',()=>{
 const f=fixture();
 const r=f.c.boxScanFresh({requestId:'lost',account:'fixture',sealPending:true}).receipt;
 assert.equal(r.status,'unresolved');assert.equal(r.sealed.source,'native_main_thread_fence');assert.equal(r.openedCount,0);
 assert.equal(f.c.openBoxRequest({requestId:'lost',account:'fixture'}).status,'unresolved');assert.equal(f.state.calls.length,0);
 assert.equal(f.open('fresh').openedCount,8);assert.equal(f.state.calls.length,8);
});
test('sealed old IDs remain blocked after more than a normal receipt cache of newer commands',()=>{
 const f=fixture();f.c.boxScanFresh({requestId:'old',account:'fixture',sealPending:true});
 for(let n=0;n<40;n++)f.c.boxNotStarted({requestId:'new-'+n,account:'fixture'});
 assert.equal(f.open('old').status,'unresolved');assert.equal(f.state.calls.length,0);
});
for(const mode of ['exception','accepted','prefix'])test('native fence retains unknown '+mode+' and opens only a fresh current queue',()=>{
 const f=fixture(mode==='exception'?{throwAt:1}:mode==='prefix'?{pendingAt:3}:{pendingAt:1});
 const before=f.open('old');assert.equal(before.status,'pending');const oldCalls=f.state.calls.length;
 const closed=f.c.boxScanFresh({account:'fixture',requestId:'old',sealPending:true}).receipt;
 assert.equal(closed.status,'unresolved');assert.equal(closed.openedCount,before.openedCount);
 assert.equal(f.open('old').status,'unresolved');assert.equal(f.state.calls.length,oldCalls);
 const restored=fixture();restored.c.restoreBoxReceipts([closed]);
 assert.equal(restored.open('old').status,'unresolved');assert.equal(restored.state.calls.length,0);
 assert.equal(restored.open('new').status,'confirmed');assert.equal(restored.state.calls.length,8);
});
test('sealing exposes the already confirmed native prefix separately from the unknown tail',()=>{
 const f=fixture({pendingAt:3});f.open('partial');
 const scan=f.c.boxScanFresh({requestId:'partial',account:'fixture',sealPending:true});
 assert.equal(scan.prefixReceipt.status,'pending');assert.equal(scan.prefixReceipt.openedCount,2);
 assert.equal(scan.receipt.status,'unresolved');assert.equal(scan.receipt.openedCount,2);
 assert.equal(f.state.calls.length,3);
});
test('fence never invents a result from elapsed time, missing authorization or another account',()=>{
 const f=fixture({pendingAt:1});f.open('old');f.state.now=1e9;
 assert.equal(f.scan('old').receipt.status,'pending');
 assert.equal(f.c.boxScanFresh({requestId:'old',account:'wrong',sealPending:true}).receipt.status,'pending');
 f.state.record=NaN;assert.equal(f.c.boxScanFresh({requestId:'old',account:'fixture',sealPending:true}).receipt.status,'pending');
 assert.equal(f.state.calls.length,1);
});
test('a real late native record settles normally before any unknown result is sealed',()=>{
 const f=fixture({pendingAt:3});f.open('old');f.state.record++;
 const r=f.c.boxScanFresh({requestId:'old',account:'fixture',sealPending:true}).receipt;
 assert.equal(r.status,'confirmed');assert.equal(r.openedCount,3);assert.equal(r.sealed,undefined);
});
test('restored native pending is discoverable even if the client lost its reservation',()=>{
 const f=fixture({pendingAt:1});f.open('orphan');const scan=f.scan();
 assert.equal(scan.pendingReceipt.requestId,'orphan');assert.equal(scan.boxRecoveryBarrier,1);
});
test('legacy execute cannot open a box after the scan recovery barrier',()=>{
 const f=fixture();const r=f.c.executeWorkshopRequest({kind:'box',account:'fixture',key:'box:0:100'},()=>{throw Error('must not run');});
 assert.equal(r.reason,'legacy_box_request_blocked');assert.equal(f.state.calls.length,0);
});
test('boxes stop at the pressure line and resume only after a batch of space is cleared',()=>{
 const f=fixture();f.state.capacity=10;f.state.occupied=7;
 assert.equal(f.open('headroom').openedCount,1);assert.equal(f.state.occupied,8);
 let scan=f.scan();assert.equal(scan.snapshot.boxes.relief.active,true);assert.equal(scan.actions.length,0);
 f.state.occupied=7;scan=f.scan();assert.equal(scan.snapshot.boxes.relief.active,true);assert.equal(scan.actions.length,0);
 f.state.occupied=6;scan=f.scan();assert.equal(scan.snapshot.boxes.relief.active,false);assert.ok(scan.actions.length);
 assert.equal(f.open('resume').openedCount,2);assert.equal(f.state.occupied,8);
});
test('capacity growth, account switches and disabled cleanup do not inherit an old relief cycle',()=>{
 const f=fixture();f.state.capacity=10;f.state.occupied=8;assert.ok(f.scan().snapshot.boxes.relief.active);
 f.state.capacity=20;assert.equal(f.scan().snapshot.boxes.relief.active,false);
 f.state.capacity=10;f.scan();f.state.occupied=7;f.c.stat=()=>'/saves/another';assert.equal(f.scan().snapshot.boxes.relief.active,false);
 Object.assign(f.strategy,{modules:{storage:false,combine:false,decompose:false,forge:false}});
 f.c.stat=()=>'/saves/fixture';
 f.state.occupied=9;assert.equal(f.open('cleanup-disabled').openedCount,1);
});
test('custom headroom remains stricter than proactive relief and never changes its stored setting',()=>{
 const f=fixture();f.state.capacity=20;f.state.occupied=10;f.strategy.box_free_slots=8;
 assert.equal(f.open('custom-headroom').openedCount,2);assert.equal(f.state.capacity-f.state.occupied,8);
 assert.equal(f.strategy.box_free_slots,8);assert.equal(f.scan().snapshot.boxes.relief.active,false);
});
test('disabling cleanup suboperations cannot leave an artificial pressure stop enabled',()=>{
 const f=fixture();f.state.capacity=10;f.state.occupied=9;
 Object.assign(f.strategy,{modules:{forge:false,combine:false,decompose:false},storage_deposit:false});
 const scan=f.scan();assert.equal(scan.snapshot.boxes.relief.enabled,false);
 assert.equal(scan.snapshot.boxes.openableSlots,1);assert.equal(f.open('explicit-controls').openedCount,1);
});

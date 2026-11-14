const fs=require('node:fs'),vm=require('node:vm'),crypto=require('node:crypto'),test=require('node:test'),assert=require('node:assert/strict');
function fixture(){
 const world={now:1000,calls:0,timers:new Map(),messages:[]};let seq=0;
 const c={Date:{now:()=>world.now},setTimeout:fn=>{world.timers.set(++seq,fn);return seq;},clearTimeout:id=>world.timers.delete(id),
  api:()=>()=>0,A:{fields:{}},iter:()=>[],klass:x=>x,withManagedThread:f=>f(),rpc:{exports:{}},jsonSafe:x=>JSON.parse(JSON.stringify(x)),
  method:()=>({readPointer:()=>0}),Interceptor:{attach:(_,h)=>{world.update=h.onEnter;return {detach(){}};}},
  Checksum:{compute:(alg,v)=>crypto.createHash(alg).update(v).digest('hex')},send:m=>world.messages.push(JSON.parse(JSON.stringify(m)))};
 vm.createContext(c);const worker=fs.readFileSync('bridge/worker.js','utf8');
 vm.runInContext(worker.slice(worker.indexOf('const queue=[]'),worker.indexOf('function normalBattleCounts')),c);
 vm.runInContext(fs.readFileSync('bridge/automation.js','utf8'),c);
 c.executeAction=()=>{world.calls++;return {status:'confirmed'};};
 const cmd={kind:'forge',key:'forge:fixture',requestId:'job',account:'fixture'};
 const timeout=()=>{world.now+=10001;for(const fn of [...world.timers.values()])fn();world.timers.clear();};
 return {c,world,cmd,timeout};
}
test('queued box cancellation creates a durable zero-consumption receipt and allows a fresh request',async()=>{
 const f=fixture();f.c.openBoxBatch=()=>{f.world.calls++;return {status:'confirmed',openedCount:1};};
 const p=f.c.rpc.exports.openboxes(f.cmd);f.timeout();const result=await p;
 assert.equal(result.status,'waiting');assert.equal(result.executionState,'not_started');assert.equal(result.openedCount,0);
 assert.equal(f.world.calls,0);assert.equal(f.world.messages.at(-1).channel,'box_receipt');
 f.world.update();assert.equal(f.world.calls,0,'cancelled callback cannot run on a later frame');
 const fresh=f.c.rpc.exports.openboxes({...f.cmd,requestId:'fresh'});f.world.update();assert.equal((await fresh).openedCount,1);assert.equal(f.world.calls,1);
});
test('expired frame deadline without timer delivery also proves a workshop request never executed',async()=>{
 const f=fixture(),p=f.c.rpc.exports.execute(f.cmd);f.world.now+=10001;f.world.update();
 const r=await p;assert.equal(r.status,'waiting');assert.equal(r.reason,'native_request_not_started');assert.equal(f.world.calls,0);
 assert.equal(r.workshopReceipt.result.executionState,'not_started');
 assert.equal(f.world.messages.at(-1).receipt.result.status,'waiting');
 // The same ID remains cancelled, even if an old transport resends it after recovery.
 const again=f.c.rpc.exports.execute(f.cmd);f.world.update();assert.equal((await again).status,'waiting');assert.equal(f.world.calls,0);
 const fresh=f.c.rpc.exports.execute({...f.cmd,requestId:'fresh'});f.world.update();assert.equal((await fresh).status,'confirmed');assert.equal(f.world.calls,1);
});
for(const kind of ['equipment','progress','rune','combine','forge','refine','decompose'])test(kind+' queued cancellation is retryable without native work',async()=>{
 const f=fixture(),p=f.c.rpc.exports.execute({...f.cmd,kind});f.timeout();const r=await p;
 assert.equal(r.status,'waiting');assert.equal(r.reason,'native_request_not_started');assert.equal(f.world.calls,0);
});
test('a native exception with timeout text is not treated as a cancelled queue entry',async()=>{
 const f=fixture();f.c.executeAction=()=>{f.world.calls++;throw Error('main_thread_timeout');};
 const p=f.c.rpc.exports.execute(f.cmd);f.world.update();await assert.rejects(p,/main_thread_timeout/);
 const receipt=f.c.workshopReceipt(f.cmd);assert.equal(receipt.result.status,'pending');assert.equal(f.world.calls,1);
});
test('initial box prerequisite read failure returns an unsent receipt rather than an eternal unknown',async()=>{
 const f=fixture();f.c.boxScanFresh=()=>{throw Error('temporarily_unready');};
 const p=f.c.rpc.exports.openboxes(f.cmd);f.world.update();const r=await p;
 assert.equal(r.executionState,'not_started');assert.equal(r.openedCount,0);assert.equal(f.world.calls,0);
});
test('one stalled sandbox queue does not cancel a different sandbox or consume its box',async()=>{
 const stalled=fixture(),healthy=fixture();
 const pending=stalled.c.rpc.exports.execute(stalled.cmd),running=healthy.c.rpc.exports.execute(healthy.cmd);
 healthy.world.update();assert.equal((await running).status,'confirmed');assert.equal(healthy.world.calls,1);
 stalled.timeout();assert.equal((await pending).status,'waiting');assert.equal(stalled.world.calls,0);
});

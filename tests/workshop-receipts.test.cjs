const fs=require('node:fs'),vm=require('node:vm'),crypto=require('node:crypto'),test=require('node:test'),assert=require('node:assert/strict');
function fixture({result='confirmed',fail=false}={}){
 const messages=[],world={calls:0},c={rpc:{exports:{}},withManagedThread:()=>({}),onMain:fn=>fn(),jsonSafe:x=>JSON.parse(JSON.stringify(x)),send:m=>messages.push(JSON.parse(JSON.stringify(m))),
  Checksum:{compute:(algorithm,value)=>crypto.createHash(algorithm).update(value).digest('hex')}};
 vm.createContext(c);vm.runInContext(fs.readFileSync('bridge/automation.js','utf8'),c);
 c.executeAction=cmd=>{world.calls++;if(fail)throw Error('native_reply_lost');return {status:result,consumed:[{uid:'material',count:9}],produced:[{uid:'product',count:1}]};};
 const command=(kind='combine',requestId='request')=>({kind,key:kind+':batch',requestId,account:'fixture',allowed:['material'],materialCounts:{material:9},batchSize:9});
 return {api:c.rpc.exports,world,messages,command};
}
for(const kind of ['combine','forge','refine','decompose','deposit','withdraw'])test(kind+' recovers a completed native reply across a new script without consuming twice',()=>{
 const f=fixture(),cmd=f.command(kind),first=f.api.execute(cmd);assert.equal(first.status,'confirmed');assert.equal(f.world.calls,1);
 const receipt=f.api.workshopreceipt(cmd);assert.equal(receipt.result.status,'confirmed');
 assert.equal(f.messages[0].receipt.result.status,'pending');assert.equal(f.messages.at(-1).receipt.result.status,'confirmed');
 const restarted=fixture();restarted.api.restoreworkshopreceipts([receipt]);
 assert.equal(restarted.api.execute({...cmd,materialCounts:{material:9}}).status,'confirmed');assert.equal(restarted.world.calls,0);
 assert.equal(restarted.api.workshopreceipt({...cmd,account:'other'}),null);
});
test('same request with changed materials, kind, account or nested payload never calls native again',()=>{
 const f=fixture(),cmd=f.command();f.api.execute(cmd);
 for(const patch of [{allowed:['other']},{kind:'forge'},{account:'other'},{materialCounts:{requestId:9}}]){
  assert.throws(()=>f.api.execute({...cmd,...patch}),/workshop_request_conflict/);assert.equal(f.world.calls,1);
 }
});
test('equivalent object key ordering preserves the request identity',()=>{
 const f=fixture(),cmd=f.command();f.api.execute(cmd);
 const reversed=Object.fromEntries(Object.entries(cmd).reverse());assert.equal(f.api.execute(reversed).status,'confirmed');assert.equal(f.world.calls,1);
});
test('lost native reply remains pending through repeated calls and restoration',()=>{
 const f=fixture({fail:true}),cmd=f.command();assert.throws(()=>f.api.execute(cmd),/native_reply_lost/);
 const receipt=f.api.workshopreceipt(cmd);assert.equal(receipt.result.status,'pending');assert.equal(f.api.execute(cmd).status,'pending');assert.equal(f.world.calls,1);
 const next=fixture();next.api.restoreworkshopreceipts([receipt]);assert.equal(next.api.execute(cmd).status,'pending');assert.equal(next.world.calls,0);
});
test('native pending is retained and unrelated requests can still execute',()=>{
 const f=fixture({result:'pending'}),cmd=f.command();f.api.execute(cmd);f.api.execute(cmd);f.api.execute(f.command('forge','other'));
 assert.equal(f.world.calls,2);assert.equal(f.api.workshopreceipt(cmd).result.status,'pending');
});
test('corrupt restoration is atomic and cannot replace a known native result',()=>{
 const f=fixture(),cmd=f.command();f.api.execute(cmd);const receipt=f.api.workshopreceipt(cmd);
 assert.throws(()=>f.api.restoreworkshopreceipts([{...receipt,requestId:'new'}, {...receipt,kind:'unknown'}]),/invalid_workshop_receipt_store/);
 assert.equal(f.api.workshopreceipt({...cmd,requestId:'new'}),null);
 assert.throws(()=>f.api.restoreworkshopreceipts([{...receipt,result:{status:'pending'}}]),/workshop_receipt_conflict/);
 assert.equal(f.api.workshopreceipt(cmd).result.status,'confirmed');
});
test('completed receipt pruning retains every unresolved request',()=>{
 const pending=fixture({result:'pending'}),cmd=pending.command();pending.api.execute(cmd);
 const f=fixture();f.api.restoreworkshopreceipts([pending.api.workshopreceipt(cmd)]);
 for(let n=0;n<40;n++)f.api.execute(f.command('forge','done-'+n));
 assert.equal(f.api.workshopreceipt(cmd).result.status,'pending');assert.equal(f.api.execute(cmd).status,'pending');assert.equal(f.world.calls,40);
});
test('a full unresolved journal refuses further consumption without losing any reservation',()=>{
 const f=fixture({result:'pending'});
 for(let n=0;n<256;n++)f.api.execute(f.command('forge','pending-'+n));
 const r=f.api.execute(f.command('combine','overflow'));assert.equal(r.status,'waiting');assert.equal(r.reason,'workshop_receipt_capacity');assert.equal(f.world.calls,256);
 assert.equal(f.api.workshopreceipt(f.command('forge','pending-0')).result.status,'pending');
});


for(const kind of ['deposit','withdraw']){
 test(kind+' refuses late legacy commands without a numbered receipt',()=>{
  const f=fixture(),cmd=f.command(kind);delete cmd.requestId;
  for(let n=0;n<3;n++){const r=f.api.execute(cmd);assert.equal(r.reason,'storage_request_id_required');assert.equal(r.executionState,'not_started');}
  assert.equal(f.world.calls,0);assert.equal(f.messages.length,0);
 });
 test(kind+' unknown numbered transfer is queried instead of replayed after restoration',()=>{
  const f=fixture({fail:true}),cmd=f.command(kind);assert.throws(()=>f.api.execute(cmd),/native_reply_lost/);
  const next=fixture();next.api.restoreworkshopreceipts([f.api.workshopreceipt(cmd)]);
  for(let n=0;n<3;n++)assert.equal(next.api.execute(cmd).status,'pending');assert.equal(next.world.calls,0);assert.equal(f.world.calls,1);
 });
}

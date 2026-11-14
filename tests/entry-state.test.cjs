const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');
function fixture(){
 const native={sequence:14,occupied:false,ticket:0},calls=[];
 const c={api:()=>()=>0,names:{game:'game',items:'items'},single:x=>x,
  read:(o,n)=>{
   if(n==='_enterSequence')return native.sequence;
   if(n==='_occupied')return {isNull:()=>!native.occupied};
   throw Error('unexpected field');
  },call:(o,n,args)=>{calls.push({o,n,args});if(n==='GetRequireItemID')return native.ticket;throw Error('unexpected call');}};
 vm.createContext(c);vm.runInContext(fs.readFileSync('bridge/planner.js','utf8'),c);
 return {native,c,calls,read:(stage={category:0,level:66})=>JSON.parse(JSON.stringify(c.stageEntryState({stage})))};
}
test('entry observer reads current free stage and native occupied flag without item mutation',()=>{
 const f=fixture(),first=f.read();assert.equal(first.known,true);assert.equal(first.free,true);assert.equal(first.occupied,false);
 f.native.sequence++;f.native.occupied=true;const second=f.read();
 assert.equal(second.sequence,15);assert.equal(second.occupied,true);assert.equal(first.observer,second.observer);
 assert.ok(f.calls.every(x=>x.n==='GetRequireItemID'));
});
test('paid main and tower scenes cannot masquerade as free cancellation evidence',()=>{
 for(const category of [0,1]){
  const f=fixture();f.native.ticket=690200;
  assert.equal(f.read({category,level:70}).free,false);
  assert.deepEqual(Array.from(f.calls[0].args),[category,70]);
 }
});
test('missing native entry field isolates the observer without throwing away the scan',()=>{
 const f=fixture();f.c.read=()=>{throw Error('native field unavailable');};
 assert.deepEqual(f.read(),{known:false,reason:'native_entry_state_unavailable'});
});
test('recreated bridge changes its observer identity even in the same game lifetime',()=>{
 assert.notEqual(fixture().read().observer,fixture().read().observer);
});

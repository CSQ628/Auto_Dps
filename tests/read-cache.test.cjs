const fs=require('node:fs'),vm=require('node:vm'),test=require('node:test'),assert=require('node:assert/strict');
const source=fs.readFileSync('bridge/worker.js','utf8');
function fixture(){
 const c={calls:[],generation:1};vm.createContext(c);
 // Exercise the real scan scope and wrappers with a deterministic native boundary.
 vm.runInContext(source.slice(0,source.indexOf('const methodCache='))+
  source.slice(source.indexOf('function invoke('),source.indexOf('function invokeFresh('))+
  source.slice(source.indexOf('function single('),source.indexOf('function singleFresh('))+
  source.slice(source.indexOf('function read('),source.indexOf('function readFresh('))+
  source.slice(source.indexOf('function list('),source.indexOf('function listFresh('))+
  `
   function invokeFresh(k,o,n,args,sig){if(scanStats)scanStats.nativeCalls++;calls.push([k,o,n,args,sig]);return generation++;}
   function singleFresh(n){calls.push(['single',n]);return generation++;}
   function readFresh(o,n){calls.push(['read',o,n]);return generation++;}
   function listFresh(p,limit){calls.push(['list',p,limit]);return [3,1,2];}
   globalThis.run=withReadOnlyScan;globalThis.invokeRead=invoke;globalThis.singleton=single;globalThis.fieldRead=read;
   globalThis.listRead=list;globalThis.stats=()=>lastScanPerformance;
  `,c);
 return c;
}
test('one scan reuses identical native observations and reports its cost',()=>{
 const f=fixture();f.run(()=>{
  assert.equal(f.invokeRead('C','one','get_Level'),f.invokeRead('C','one','get_Level'));
  assert.equal(f.singleton('Manager'),f.singleton('Manager'));
  assert.equal(f.fieldRead('one','Tier'),f.fieldRead('one','Tier'));
 });
 assert.equal(f.calls.length,3);assert.equal(f.stats().nativeCalls,1);assert.equal(f.stats().cacheHits,3);assert.ok(f.stats().scanMs>=0);
});
test('cache distinguishes receiver, type, argument, signature and field',()=>{
 const f=fixture();f.run(()=>{
  for(const args of [['C','one','CanEquip',[1],'int'],['C','two','CanEquip',[1],'int'],['D','one','CanEquip',[1],'int'],['C','one','CanEquip',[2],'int'],['C','one','CanEquip',[1],'enum']])f.invokeRead(...args);
  f.fieldRead('one','Tier');f.fieldRead('two','Tier');f.fieldRead('one','Grade');
 });assert.equal(f.calls.length,8);assert.equal(f.stats().cacheHits,0);
});
test('next scan and mutation validation reread native state',()=>{
 const f=fixture();let before;f.run(()=>{before=f.invokeRead('C','one','get_Count');});
 assert.notEqual(f.invokeRead('C','one','get_Count'),before);
 f.run(()=>{assert.notEqual(f.invokeRead('C','one','get_Count'),before);});
 assert.equal(f.calls.length,3);
});
test('actions and scoring calls always execute even inside a scan',()=>{
 const f=fixture();f.run(()=>{
  for(const name of ['TryMoveToCube','TryExecute','CalculateEquipScore','SetCategory'])assert.notEqual(f.invokeRead('C','one',name),f.invokeRead('C','one',name));
 });assert.equal(f.calls.length,8);assert.equal(f.stats().cacheHits,0);
});
test('exceptions clear the scan scope and nested scopes share only the active scan',()=>{
 const f=fixture();assert.throws(()=>f.run(()=>{
  const first=f.invokeRead('C','one','IsReady');f.run(()=>assert.equal(f.invokeRead('C','one','IsReady'),first));throw Error('fixture_failure');
 }),/fixture_failure/);
 assert.equal(f.stats().cacheHits,1);f.invokeRead('C','one','IsReady');
 f.run(()=>f.invokeRead('C','one','IsReady'));assert.equal(f.calls.length,3);assert.equal(f.stats().cacheHits,0);
});


test('known pure lookups reuse observations while arbitrary Get methods remain fresh',()=>{
 const f=fixture();f.run(()=>{
  for(const name of ['GetEquipment','GetPassiveLearnedLevel','FindObjectsOfTypeAll'])assert.equal(f.invokeRead('C','one',name,[1]),f.invokeRead('C','one',name,[1]));
  for(const name of ['GetAndRemove','TryBuildScoreBasis'])assert.notEqual(f.invokeRead('C','one',name),f.invokeRead('C','one',name));
 });assert.equal(f.calls.length,7);assert.equal(f.stats().cacheHits,3);
});

test('cached collection reads return independent arrays and expire between scans',()=>{
 const f=fixture();f.run(()=>{
  f.listRead('one').sort();assert.deepEqual(Array.from(f.listRead('one')),[3,1,2]);
  f.listRead('one',10);f.listRead('two');
 });assert.equal(f.calls.length,3);assert.equal(f.stats().cacheHits,1);
 f.run(()=>f.listRead('one'));assert.equal(f.calls.length,4);
});

test('metadata layouts reuse only types and offsets while native values stay fresh',()=>{
 const c={typeReads:0,offsetReads:0,value:1,nativeCalls:0};vm.createContext(c);
 vm.runInContext(`
 const methodLayouts=new Map(),fieldLayouts=new Map();let scanStats=null;
 const nil={isNull:()=>true},PS=8;
 const Memory={alloc:()=>({writePointer(){},add(){return this;},readPointer:()=>nil})};
 const method=()=>({toString:()=> 'method-1'}),field=()=>({toString:()=> 'field-1'});
 const A={param:()=> 'int',returnType:()=> 'int',objectClass:()=> 'Class',fieldType:()=> 'int',
  fieldOffset:()=>{offsetReads++;return 4;},invoke:()=>{nativeCalls++;return {isNull:()=>false,value:value++};},unbox:p=>p};
 function tn(){typeReads++;return 'System.Int32';}
 function primitive(p){return p.value;}function arg(){return nil;}function classFromType(t){return t;}function classIsEnum(){return false;}
 `+source.slice(source.indexOf('function invokeFresh('),source.indexOf('function call('))+
 source.slice(source.indexOf('function readFresh('),source.indexOf('function list('))+`
 globalThis.invokeNative=invokeFresh;globalThis.readNative=readFresh;
 `,c);
 assert.equal(c.invokeNative('C','one','Mutate',[1]),1);
 assert.equal(c.invokeNative('C','one','Mutate',[2]),2);
 assert.equal(c.nativeCalls,2);assert.equal(c.typeReads,2);
 const obj={add:()=>({value:c.value++})};
 assert.equal(c.readNative(obj,'Count'),3);assert.equal(c.readNative(obj,'Count'),4);
 assert.equal(c.offsetReads,1);assert.equal(c.typeReads,3);
});

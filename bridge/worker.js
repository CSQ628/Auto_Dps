// Runs after il2cpp.js inside the same Frida script. All game calls run on BattleManager.Update.
// Cache immutable observations only inside a synchronous scan; mutations always read fresh state.
let scanReads=null,scanStats=null,lastScanPerformance=null;
function withReadOnlyScan(fn){
 if(scanReads!==null)return fn();
 const started=Date.now();scanReads=new Map();scanStats={nativeCalls:0,cacheHits:0};
 try{return fn();}finally{lastScanPerformance={...scanStats,scanMs:Math.max(0,Date.now()-started)};scanReads=null;scanStats=null;}
}
function cachedScanRead(key,fn){
 if(scanReads===null||key===null)return fn();
 if(scanReads.has(key)){scanStats.cacheHits++;return scanReads.get(key);}
 const value=fn();scanReads.set(key,value);return value;
}
const methodCache=new Map(), fieldCache=new Map(), methodLayouts=new Map(), fieldLayouts=new Map();
function method(k,name,n,signature) {
  const key=k+':'+name+':'+n+':'+(signature||''); if(methodCache.has(key))return methodCache.get(key);
  const own=iter(A.methods,k).filter(m=>utf(A.methodName(m))===name && A.paramCount(m)===n && (!signature || Array.from({length:n},(_,i)=>tn(A.param(m,i))).join(',')===signature));
  if(own.length>1)throw Error('ambiguous_method:'+fullname(k)+'.'+name);
  if(own.length===1){methodCache.set(key,own[0]);return own[0];}
  const parent=A.parent(k); if(!parent.isNull())return method(parent,name,n,signature);
  throw Error('missing_method:'+fullname(k)+'.'+name);
}
function field(k,name) {
  const key=k+':'+name; if(fieldCache.has(key))return fieldCache.get(key);
  const f=iter(A.fields,k).find(f=>utf(A.fieldName(f))===name);
  if(f){fieldCache.set(key,f);return f;}
  const parent=A.parent(k);if(!parent.isNull())return field(parent,name);
  throw Error('missing_field:'+fullname(k)+'.'+name);
}
function klass(n){
 let k=types.get(n);if(k)return k;
 const fromName=api('class_from_name','pointer',['pointer','pointer','pointer']),last=n.lastIndexOf('.');
 for(let i=0;i<size.readU64().toNumber();i++){
  k=fromName(A.image(asms.add(i*PS).readPointer()),Memory.allocUtf8String(n.slice(0,last)),Memory.allocUtf8String(n.slice(last+1)));
  if(!k.isNull()){types.set(n,k);return k;}
 }throw Error('missing_class:'+n);
}
function managedString(p){return p.isNull()?null:p.add(20).readUtf16String(p.add(16).readS32());}
function primitive(p,t){
  if(t==='System.Boolean')return p.readU8()!==0;
  if(['System.Int32','System.UInt32'].includes(t))return p.readS32();
  if(t==='System.Single')return p.readFloat(); if(t==='System.Double')return p.readDouble();
  if(t==='System.Int64')return Number(p.readS64());if(t==='System.UInt64')return Number(p.readU64());
  return undefined;
}
function arg(v,t){
  if(v===null)return nil;
  if(typeof v==='object' && v.$ptr)return ptr(v.$ptr);
  if(t==='System.String')return A.string(Memory.allocUtf8String(v));
  const p=Memory.alloc(16);
  if(t==='System.Boolean')p.writeU8(v?1:0);
  else if(t==='System.Single')p.writeFloat(v);
  else if(t==='System.Double')p.writeDouble(v);
  else if(t==='System.Int64')p.writeS64(v);
  else if(t==='System.UInt64')p.writeU64(v);
  else p.writeS32(v);
  return p;
}
function invoke(k,obj,name,args=[],signature=null){
 const key=scanReads!==null&&(/^(get_|Is|Can)/.test(name)||['GetEquipment','GetAllCharacters','GetActiveSkills','GetPassiveSkills','GetEquippedActives','GetActiveLearnedLevel','GetPassiveLearnedLevel','GetTotalExpToReach','GetExpToNext','GetSquadSlots','FindObjectsOfTypeAll'].includes(name))?'getter:'+k+':'+obj+':'+name+':'+JSON.stringify(args)+':'+signature:null;
 return cachedScanRead(key,()=>invokeFresh(k,obj,name,args,signature));
}
function invokeFresh(k,obj,name,args=[],signature=null){
 if(scanStats)scanStats.nativeCalls++;
  const m=method(k,name,args.length,signature),params=Memory.alloc(Math.max(PS,args.length*PS));
  const key=m.toString();let layout=methodLayouts.get(key);
  if(!layout){layout={args:args.map((_,i)=>tn(A.param(m,i))),result:tn(A.returnType(m)),isEnum:classIsEnum(classFromType(A.returnType(m)))};methodLayouts.set(key,layout);}
  const keep=[];args.forEach((v,i)=>{const p=arg(v,layout.args[i]);keep.push(p);params.add(i*PS).writePointer(p);});
  const exc=Memory.alloc(PS);exc.writePointer(nil);
  const result=A.invoke(m,obj||nil,args.length?params:nil,exc);
  if(!exc.readPointer().isNull())throw Error('managed_exception:'+fullname(k)+'.'+name+':'+fullname(A.objectClass(exc.readPointer())));
  const ret=layout.result;
  if(result.isNull())return null;
  if(ret==='System.String')return managedString(result);
  if(ret.startsWith('System.')){const value=primitive(A.unbox(result),ret);if(value!==undefined)return value;}
  // Known enum return values are boxed Int32.
  if(layout.isEnum)return A.unbox(result).readS32();
  return result;
}
function call(obj,name,args=[],sig=null){if(!obj||obj.isNull())throw Error('object_not_ready:'+name);return invoke(A.objectClass(obj),obj,name,args,sig);}
function stat(n,name,args=[],sig=null){return invoke(klass(n),nil,name,args,sig);}
function ref(p){return {$ptr:p.toString()};}
function single(n){return cachedScanRead('singleton:'+n,()=>singleFresh(n));}
function singleFresh(n){
  let k=klass(n);
  while(!k.isNull()){
    for(const f of iter(A.fields,k)){
      if((A.fieldFlags(f)&16) && /instance/i.test(utf(A.fieldName(f)))){
        const out=Memory.alloc(PS);out.writePointer(nil);A.staticGet(f,out);const p=out.readPointer();
        if(!p.isNull() && fullname(A.objectClass(p))===n)return p;
      }
    }
    k=A.parent(k);
  }
  throw Error('singleton_not_ready:'+n);
}
const classFromType=api('class_from_type','pointer',['pointer']),classIsEnum=api('class_is_enum','bool',['pointer']);
function read(obj,name){return cachedScanRead(scanReads===null?null:'field:'+obj+':'+name,()=>readFresh(obj,name));}
function readFresh(obj,name){
 const f=field(A.objectClass(obj),name),key=f.toString();let layout=fieldLayouts.get(key);
 if(!layout){const ft=A.fieldType(f);layout={type:tn(ft),offset:A.fieldOffset(f),isEnum:classIsEnum(classFromType(ft))};fieldLayouts.set(key,layout);}
 const p=obj.add(layout.offset),v=primitive(p,layout.type);if(v!==undefined)return v;
 if(layout.type==='System.String')return managedString(p.readPointer());if(layout.isEnum)return p.readS32();return p.readPointer();
}
function list(p,limit=12000){
 const values=cachedScanRead(scanReads===null?null:'list:'+p+':'+limit,()=>listFresh(p,limit));
 // Callers may sort their result. Keep the scan's observation order immutable.
 return scanReads===null?values:values.slice();
}
function listFresh(p,limit=12000){
 if(!p||p.isNull())return [];
 const k=A.objectClass(p);
 if(fullname(k).endsWith('[]')){
  const n=p.add(24).readU64().toNumber();if(n>limit)throw Error('array_limit');
  const element=api('class_get_element_class','pointer',['pointer'])(k),name=fullname(element),isEnum=classIsEnum(element);
  const strides={'System.Boolean':1,'System.Int32':4,'System.UInt32':4,'System.Int64':8,'System.UInt64':8,'System.Single':4,'System.Double':8};
  const step=isEnum?4:(strides[name]||PS);
  return Array.from({length:n},(_,i)=>{const at=p.add(32+i*step);return isEnum?at.readS32():name==='System.String'?managedString(at.readPointer()):(primitive(at,name)??at.readPointer());});
 }
 const count=call(p,'get_Count');if(count>limit)throw Error('collection_limit:'+count);return Array.from({length:count},(_,i)=>call(p,'get_Item',[i]));
}
const objectNew=api('object_new','pointer',['pointer']);
// This Unity runtime uses pointer-sized Il2CppGCHandle values.
const gcNew=api('gchandle_new','pointer',['pointer','bool']);
const gcFree=api('gchandle_free','void',['pointer']);
const handles=[];let runeProvider=null,runeProviderHandle=null;
function releaseRunesProvider(){
 if(runeProviderHandle!==null)gcFree(runeProviderHandle);
 runeProvider=null;runeProviderHandle=null;
}
function refreshRunesProvider(){
 // RuneSaveStateProvider keeps a private level cache. Rebuild from native records
 // once per complete scan, including execution's prerequisite scan, not per node.
 const next=objectNew(klass('DG.UI.Rune.RuneSaveStateProvider')),handle=gcNew(next,0);
 try{call(next,'.ctor');}catch(error){gcFree(handle);throw error;}
 releaseRunesProvider();runeProvider=next;runeProviderHandle=handle;return next;
}
function runesProvider(){return runeProvider||refreshRunesProvider();}
const queue=[];let servicing=false;
// Only errors created by removal from this queue prove that fn never ran.
const mainNotStartedErrors=new WeakSet();
function mainNotStartedError(reason){const error=Error(reason);mainNotStartedErrors.add(error);return error;}
function isMainNotStarted(error){return mainNotStartedErrors.has(error);}

function onMain(fn){return new Promise((resolve,reject)=>{const entry={fn,resolve,reject,deadline:Date.now()+10000};queue.push(entry);entry.timer=setTimeout(()=>{const i=queue.indexOf(entry);if(i>=0){queue.splice(i,1);reject(mainNotStartedError('main_thread_timeout'));}},10000);});}
const hook=Interceptor.attach(method(klass('DG.InGame.Battle.Manager.BattleManager'),'Update',0).readPointer(),{
  onEnter(){if(servicing||!queue.length)return;servicing=true;const job=queue.shift();clearTimeout(job.timer);try{if(Date.now()>job.deadline)throw mainNotStartedError('expired_before_execution');job.resolve(job.fn());}catch(e){job.reject(e);}finally{servicing=false;}}
});
function normalBattleCounts(rm){
 try{return {normalClears:call(rm,'get_NormalStageClearCount'),normalFails:call(rm,'get_NormalStageFailCount')};}
 catch(error){return {normalClears:null,normalFails:null};}
}
function snapshot(){
 const dm=single('DG.Manager.DataManager');
 if(!call(dm,'get_IsSaveLoaded')||!call(dm,'get_IsMasterTableLoaded'))throw Error('data_not_ready');
 const im=single('DG.Item.Manager.ItemManager'), gm=single('DG.Manager.GameManager'), bm=single('DG.InGame.Battle.Manager.BattleManager');
 const cm=single('DG.Manager.CurrencyManager'), drop=single('DG.Manager.DropManager'), rm=single('DG.Manager.RecordManager');
 const st=call(bm,'get_Stage');
 const characters=list(read(dm,'HasCharacters')).map(c=>{
  const row={id:call(c,'get_ID'),level:call(c,'get_Level'),exp:call(c,'get_Exp'),points:call(c,'get_RemainingPoint')};
  // Native cumulative thresholds keep level-up resets out of experience deltas.
  try{const reach=call(dm,'GetTotalExpToReach',[row.level]),next=call(dm,'GetExpToNext',[row.level]);
   if(Number.isFinite(reach)&&reach>=0&&Number.isFinite(row.exp)&&row.exp>=0&&Number.isFinite(next)&&next>=0){row.expTotal=reach+row.exp;row.expNext=next;}
  }catch(error){row.expTotal=null;row.expNext=null;}
  return row;
 });
 return {at:Date.now(),account:stat('DG.Save.InGame.SaveEnvironment','get_Directory').replaceAll('\\','/').split('/').pop(),saveDirectory:stat('DG.Save.InGame.SaveEnvironment','get_Directory'),nickname:call(dm,'get_Nickname'),loaded:call(im,'get_IsLoaded'),inventory:{count:call(call(im,'get_Inventory'),'get_OccupiedCount'),capacity:call(call(im,'get_Inventory'),'get_Capacity')},
  stage:{level:call(st,'get_Level'),wave:call(st,'get_Wave'),difficulty:call(st,'get_Difficulty'),category:call(st,'get_Category'),running:call(st,'get_IsRunning'),elapsed:call(st,'get_ElapsedTime'),repeat:call(gm,'get_RepeatStage'),alivePlayers:list(call(bm,'get_AlivePlayers')).length,aliveMonsters:list(call(bm,'get_AliveMonsters')).length},
  currencies:{soul:call(cm,'Get',[201]),premium:call(cm,'Get',[202])},characters,
  boxes:[0,1,2].map(grade=>({grade,count:call(drop,'Count',[grade]),max:call(drop,'Max',[grade]),auto:call(drop,'IsAutoOpenEnabled',[grade])})),
  record:{...normalBattleCounts(rm),clears:call(rm,'get_StageClearCount'),maxStage:call(rm,'get_MaxReachedLevel'),maxCleared:call(rm,'get_MaxClearedLevel'),towerMaxCleared:call(rm,'get_MaxClearedInfinityTowerLevel'),deaths:call(rm,'get_DeathCount'),kills:call(rm,'get_KillCountNormal'),boxes:call(rm,'get_BoxOpenCount')},
  squad:stat('DG.Manager.SquadManager','GetSquadSlots'),
 };
}
function jsonSafe(value){if(value instanceof NativePointer)return {$ptr:value.toString(),type:fullname(A.objectClass(value))};if(Array.isArray(value))return value.map(jsonSafe);if(value&&typeof value==='object'){const out={};Object.entries(value).forEach(([k,v])=>out[k]=jsonSafe(v));return out;}return value;}
Object.assign(rpc.exports,{
 snapshot(){return onMain(()=>{const s=snapshot();s.squad=list(s.squad);return jsonSafe(s);});},
 probe(spec){return onMain(()=>{
   let obj=spec.singleton?single(spec.singleton):spec.pointer?ptr(spec.pointer):null;
   let value=spec.static?stat(spec.static,spec.method,spec.args||[],spec.signature):spec.field?read(obj,spec.field):call(obj,spec.method,spec.args||[],spec.signature);
   if(spec.list)value=list(value).map(p=>spec.fields?Object.fromEntries(spec.fields.map(f=>[f,read(p,f)])):p);
   return jsonSafe(value);
 });},
 dispose(){hook.detach();withManagedThread(()=>{releaseRunesProvider();handles.splice(0).forEach(handle=>gcFree(handle));});while(queue.length){const job=queue.shift();clearTimeout(job.timer);job.reject(Error('disposed'));}return true;}
});

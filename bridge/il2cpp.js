'use strict';
// Runtime names and method pointers come from IL2CPP, never from fixed build offsets.
const mod = Process.getModuleByName('GameAssembly.dll');
const nil = ptr(0), PS = Process.pointerSize;
function api(name, ret, args) { return new NativeFunction(mod.getExportByName('il2cpp_' + name), ret, args); }
const A = {
  domain: api('domain_get', 'pointer', []), attach: api('thread_attach', 'pointer', ['pointer']),
  currentThread:api('thread_current','pointer',[]),detachThread:api('thread_detach','void',['pointer']),
  assemblies: api('domain_get_assemblies', 'pointer', ['pointer', 'pointer']),
  image: api('assembly_get_image', 'pointer', ['pointer']), imageName: api('image_get_name', 'pointer', ['pointer']),
  count: api('image_get_class_count', 'uint64', ['pointer']), klass: api('image_get_class', 'pointer', ['pointer', 'uint64']),
  name: api('class_get_name', 'pointer', ['pointer']), ns: api('class_get_namespace', 'pointer', ['pointer']),
  declaring: api('class_get_declaring_type', 'pointer', ['pointer']), parent: api('class_get_parent', 'pointer', ['pointer']), methods: api('class_get_methods', 'pointer', ['pointer', 'pointer']),
  fields: api('class_get_fields', 'pointer', ['pointer', 'pointer']), fieldName: api('field_get_name', 'pointer', ['pointer']),
  fieldType: api('field_get_type', 'pointer', ['pointer']), fieldOffset: api('field_get_offset', 'int', ['pointer']),
  fieldFlags: api('field_get_flags', 'uint', ['pointer']), staticGet: api('field_static_get_value', 'void', ['pointer', 'pointer']),
  methodName: api('method_get_name', 'pointer', ['pointer']), paramCount: api('method_get_param_count', 'uint', ['pointer']),
  param: api('method_get_param', 'pointer', ['pointer', 'uint']), paramName: api('method_get_param_name', 'pointer', ['pointer', 'uint']),
  returnType: api('method_get_return_type', 'pointer', ['pointer']), flags: api('method_get_flags', 'uint', ['pointer', 'pointer']),
  typeName: api('type_get_name', 'pointer', ['pointer']), objectClass: api('object_get_class', 'pointer', ['pointer']),
  invoke: api('runtime_invoke', 'pointer', ['pointer', 'pointer', 'pointer', 'pointer']),
  unbox: api('object_unbox', 'pointer', ['pointer']), string: api('string_new', 'pointer', ['pointer']),
};
function utf(p) { return p.isNull() ? '' : p.readUtf8String(); }
function tn(t) { return utf(A.typeName(t)); }
function fullname(k) { const outer=A.declaring(k); return (outer.isNull()?utf(A.ns(k)):fullname(outer)) + '.' + utf(A.name(k)); }
function iter(fn, k) { const state = Memory.alloc(PS); state.writePointer(nil); const rows=[]; for(let p=fn(k,state);!p.isNull();p=fn(k,state))rows.push(p); return rows; }
const domain = A.domain();
// A persistent Frida thread attached to IL2CPP can hold up Unity's domain shutdown.
// Metadata discovery borrows an existing managed thread or owns a scoped attachment.
function withManagedThread(fn){
 const owned=A.currentThread().isNull()?A.attach(domain):null;
 try{return fn();}finally{if(owned)A.detachThread(owned);}
}
const types = new Map();
const size = Memory.alloc(PS); const asms = A.assemblies(domain,size);
withManagedThread(()=>{for(let i=0;i<size.readU64().toNumber();i++) {
  const img=A.image(asms.add(i*PS).readPointer());
  if(utf(A.imageName(img))!=='Assembly-CSharp.dll')continue;
  for(let j=0;j<Number(A.count(img));j++){const k=A.klass(img,j);types.set(fullname(k),k);}
}});
function describe(k) {
  return {name:fullname(k), parent:A.parent(k).isNull()?null:fullname(A.parent(k)),
    fields:iter(A.fields,k).map(f=>({name:utf(A.fieldName(f)),type:tn(A.fieldType(f)),offset:A.fieldOffset(f),flags:A.fieldFlags(f)})),
    methods:iter(A.methods,k).map(m=>({name:utf(A.methodName(m)),pointer:m.readPointer().sub(mod.base).toString(),
      flags:A.flags(m,nil),returns:tn(A.returnType(m)),params:Array.from({length:A.paramCount(m)},(_,i)=>({name:utf(A.paramName(m,i)),type:tn(A.param(m,i))}))}))};
}
rpc.exports = {
  inventory(filter) {return withManagedThread(()=>Array.from(types).filter(([n])=>n.includes(filter)).map(([,k])=>describe(k)));},
};

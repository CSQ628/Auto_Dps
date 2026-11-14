export function preferredInstance(instances) {
 return instances.reduce((best,instance)=>{
  const level=Number.isInteger(instance.snapshot?.record?.maxCleared)?instance.snapshot.record.maxCleared:-1;
  const bestLevel=Number.isInteger(best?.snapshot?.record?.maxCleared)?best.snapshot.record.maxCleared:-1;
  return !best||level>bestLevel?instance:best;
 },null);
}

export function mapStageName(level) {
 if(!Number.isInteger(level)||level<=0)return '—';
 return `${Math.ceil(level/10)}-${level%10||10}`;
}

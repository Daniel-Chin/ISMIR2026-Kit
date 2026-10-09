// SQLite-backed Durable Object KV interface; limit individual values and multi-key batches.
const batches = values => Array.from({length:Math.ceil(values.length/100)},(_,i)=>values.slice(i*100,i*100+100));
export async function getBlob(storage,key) {
  const size=await storage.get(key+':size');if(size===undefined)return null;
  const keys=Array.from({length:size},(_,i)=>key+':'+i),all=new Map();
  for(const batch of batches(keys))for(const[k,v]of await storage.get(batch))all.set(k,v);
  if(keys.some(k=>typeof all.get(k)!=='string'))throw Error('Incomplete durable record');
  return keys.map(k=>all.get(k)).join('');
}
export async function putBlobs(storage,values) {
  await storage.transaction(async tx=>{
    for(const[key,value]of Object.entries(values)) {
      const pieces=[];for(let i=0;i<value.length;i+=16000)pieces.push(value.slice(i,i+16000));
      const old=await tx.get(key+':size')||0,entries=[[key+':size',pieces.length],...pieces.map((p,i)=>[key+':'+i,p])];
      for(const batch of batches(entries))await tx.put(Object.fromEntries(batch));
      const unused=[];for(let i=pieces.length;i<old;i++)unused.push(key+':'+i);
      for(const batch of batches(unused))await tx.delete(batch);
    }
  });
}
export const putBlob=(storage,key,value)=>putBlobs(storage,{[key]:value});
export async function deleteKeys(storage,keys) {for(const batch of batches(keys))await storage.delete(batch);}
export async function putEntries(storage,entries) {for(const batch of batches(Object.entries(entries)))await storage.put(Object.fromEntries(batch));}

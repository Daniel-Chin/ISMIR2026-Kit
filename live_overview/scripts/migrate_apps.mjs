// Run on the OLD SERVER only, after final backup, with ADMIN_KEY set in the environment.
// Reads existing v1/v2 encrypted grants in memory and transmits over HTTPS; writes no token export.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
const [origin,configPath,mode]=process.argv.slice(2);
if(!origin||!configPath||mode!=='--replace-profiles'||!process.env.ADMIN_KEY||!origin.startsWith('https://')||new URL(origin).origin!==origin) {
  console.error('Usage: ADMIN_KEY environment required; node scripts/migrate_apps.mjs https://NEW-BACKEND /var/lib/ismir-zoom/zoom_apps.json --replace-profiles');process.exit(1);
}
const config=JSON.parse(fs.readFileSync(configPath)),dir=path.join(path.dirname(configPath),'app-tokens');
const key=fs.existsSync(path.join(dir,'encryption.key'))?fs.readFileSync(path.join(dir,'encryption.key')):null;
async function call(route,method,body){const r=await fetch(origin+route,{method,headers:{Authorization:'Bearer '+process.env.ADMIN_KEY,'Content-Type':'application/json'},body:JSON.stringify(body)});const data=await r.json();if(!r.ok)throw Error(data.error||'Import failed');return data;}
let imported=0;
for(const[id,app]of Object.entries(config.apps||{})) {
  if(!/^v[1-9]\d{0,3}$/.test(id))throw Error('Invalid profile ID');
  await call('/api/admin/apps/'+id,'PUT',{...app,origin});
  if(app.enabled===false)continue;
  const grants=[];
  for(const filename of fs.existsSync(dir)?fs.readdirSync(dir):[]) {
    const match=filename.match(new RegExp('^'+id+'-([a-f0-9]{64})\\.enc$'));if(!match)continue;
    if(!key||key.length!==32)throw Error('Restore original token encryption.key first.');
    const bytes=fs.readFileSync(path.join(dir,filename)),dec=crypto.createDecipheriv('aes-256-gcm',key,bytes.subarray(0,12));
    dec.setAAD(Buffer.from(filename));dec.setAuthTag(bytes.subarray(12,28));
    const tokens=JSON.parse(Buffer.concat([dec.update(bytes.subarray(28)),dec.final()]).toString());
    grants.push({id,clientId:app.clientId,ownerHash:match[1],tokens});
  }
  for(let i=0;i<grants.length;i+=100){await call('/api/admin/grants/import','POST',{grants:grants.slice(i,i+100)});imported+=Math.min(100,grants.length-i);}
  console.log(id+': profile and '+grants.length+' grants imported');
}
console.log('Done: '+imported+' grants. Update Zoom URLs if the origin changed. Old single-app zoom_tokens.json is not migrated.');

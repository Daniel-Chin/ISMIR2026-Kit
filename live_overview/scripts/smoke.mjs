import assert from 'node:assert/strict';
import WebSocket from 'ws';
const [origin,viewerOrigin]=process.argv.slice(2);
if(!origin||!viewerOrigin||!origin.startsWith('https://')||new URL(origin).origin!==origin){console.error('Usage: node scripts/smoke.mjs https://BACKEND https://PUBLIC-OVERVIEW-ORIGIN');process.exit(1);}
const health=await fetch(origin+'/api/health').then(r=>r.json());assert(health.ok&&health.configured,'Configure secrets first');
const res=await fetch(origin+'/api/state',{headers:{Origin:viewerOrigin}});assert.equal(res.status,200);assert.equal(res.headers.get('Access-Control-Allow-Origin'),viewerOrigin);assert((await res.json()).ok);
assert.equal((await fetch(origin+'/api/admin/status')).status,401);
assert.equal((await fetch(origin+'/api/state',{headers:{Origin:'https://not-allowed.invalid'}})).status,403);
assert.equal((await fetch(origin+'/admin.html')).status,200);
await new Promise((resolve,reject)=>{
 const ws=new WebSocket(origin.replace('https:','wss:')+'/ws/public',{origin:viewerOrigin});let full=false;
 const timeout=setTimeout(()=>{ws.terminate();reject(Error('No full state + live slice within 20s'));},20000);
 ws.on('error',e=>{clearTimeout(timeout);reject(e);});ws.on('message',raw=>{const value=JSON.parse(raw);if(value.type==='state')full=true;if(full&&value.type==='live'){clearTimeout(timeout);ws.close();resolve();}});
});
console.log('PASS: deployed health, CORS, auth boundary, assets, WebSocket baseline and live updates. Zoom client behavior still requires a real meeting test.');

import test from 'node:test';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import {harness,BASE,KEY,schedule,installWebSockets} from './harness.js';
import {seal,unseal} from '../src/security.js';
import {livePacket,publicState} from '../src/model.js';
import {getBlob} from '../src/storage.js';
installWebSockets();
const app={origin:BASE,clientId:'client-1',clientSecret:'secret-1',webhookSecret:'webhook-1'};
function contextToken(ctx,secret=app.clientSecret) {
 const iv=crypto.randomBytes(12),aad=Buffer.from('zoom'),cipher=crypto.createCipheriv('aes-256-gcm',crypto.createHash('sha256').update(secret).digest(),iv);cipher.setAAD(aad);
 const data=Buffer.concat([cipher.update(JSON.stringify({uid:'host-user',exp:Date.now()+60000,ts:Date.now(),...ctx})),cipher.final()]);const al=Buffer.alloc(2),dl=Buffer.alloc(4);al.writeUInt16LE(aad.length);dl.writeUInt32LE(data.length);
 return Buffer.concat([Buffer.from([iv.length]),iv,al,aad,dl,data,cipher.getAuthTag()]).toString('base64');
}
async function setup() {
 const h=await harness();assert.equal((await h.admin('/api/admin/apps/v1',app,'PUT')).status,200);
 const key=h.object.zoom.grantKey('v1',app,'host-user');await h.storage.put(key,seal({installedAt:Date.now(),expiresAt:Date.now()+3600000,access_token:'private-access',refresh_token:'private-refresh'},h.env,key));
 const token=contextToken({mid:'meeting'}),headers={'X-Zoom-App-Context':token};
 const ctx={meetingUUID:'meeting',roomUUID:'',meetingId:'123456789',role:'host',participantUUID:'host-participant'};
 async function bind(client='central',mode='attendance',context=ctx,identity=token,intent=1,eventId='poster') {return h.call('/zoom/app/v1/api/observer/session',{protocol:2,clientId:client,intent,mode,eventId,context},{'X-Zoom-App-Context':identity});}
 let seq=0;
 async function send(bound,type,fields={},identity=token) {return h.call('/zoom/app/v1/observer/event',{seq:++seq,context:bound.context,type,...fields},{'X-Zoom-App-Context':identity,Authorization:'Bearer '+bound.token});}
 return {...h,get object(){return h.object;},h,ctx,token,headers,bind,send};
}
test('CORS only allows public reads; private auth, legacy endpoints and static paths fail closed',async()=>{
 const h=await harness();
 assert.equal((await h.call('/api/state',undefined,{Origin:'https://live.example'})).res.headers.get('access-control-allow-origin'),'https://live.example');
 assert.equal((await h.call('/api/state',undefined,{Origin:'https://evil.example'})).status,403);
 assert.equal((await h.call('/api/admin/import',{schedule},{Origin:'https://live.example',Authorization:'Bearer '+KEY})).status,403);
 assert.equal((await h.call('/api/admin/status')).status,401);
 assert.equal((await h.call('/api/observer/catalog',{})).status,401);
 assert.equal((await h.raw('/.dev.vars')).status,404);
 assert.equal((await h.raw('/zoom-app-observer.html')).status,404);
 assert.equal((await h.raw('/admin.html')).status,200);
 assert.equal((await h.raw('/api/state',{method:'OPTIONS',headers:{Origin:'https://live.example','Access-Control-Request-Method':'GET','Access-Control-Request-Headers':'Authorization'}})).status,403);
});
test('Host counts and atomic mapping survive object reinitialization; tickets retain original real-time freshness',async()=>{
 const h=await setup(),bound=(await h.bind()).data;assert.equal(bound.ok,true);
 const heartbeat=(await h.send(bound,'heartbeat')).data;
 const snapshot={lobby:['host-participant'],rooms:[{roomUUID:'management-1',name:'Room 1',members:['volunteer','attendee']}]};
 assert.equal((await h.send(bound,'attendance',{sampleTicket:heartbeat.sampleTicket,snapshot})).status,200);
 assert.equal((await h.send(bound,'mapping',{revision:bound.mappingRevision,mapping:[{roomUUID:'management-1',paperId:'p1'}]})).status,200);
 await h.restart();
 let state=(await h.call('/api/state')).data.state;assert.equal(state.events[0].headcounts.zoom,3);assert.equal(state.events[0].headcounts.lobbyZoom,1);assert.equal(state.events[0].papers[0].headcounts.zoom,2);
 assert.equal((await h.bind()).data.token,bound.token);
 assert(!JSON.stringify(state).includes('host-participant'));assert(!JSON.stringify(state).includes('private-access'));
 const raw=await getBlob(h.storage,'hub');assert(!raw.includes('volunteer'));assert(!raw.includes(bound.token));
 h.object.hub.snapshots.get('poster').at-=21000;await h.alarm();state=(await h.call('/api/state')).data.state;
 assert.equal(state.events[0].headcounts.available,false);assert.equal(state.events[0].metrics.peakZoom,3);
 assert.equal((await h.send(bound,'attendance',{sampleTicket:'expired-ticket',snapshot})).status,422);
});
test('Co-host auto-resolves a distinct room UUID, receives speech, then is fenced by remapping and deauthorization',async()=>{
 const h=await setup(),central=(await h.bind()).data;
 const snapshot={lobby:['host-participant'],rooms:[{roomUUID:'management-1',name:'Room 1',members:['volunteer','attendee']}]};
 async function sample(){const hb=(await h.send(central,'heartbeat')).data;assert.equal((await h.send(central,'attendance',{sampleTicket:hb.sampleTicket,snapshot})).status,200);}
 await sample();await h.send(central,'mapping',{revision:central.mappingRevision,mapping:[{roomUUID:'management-1',paperId:'p1'}]});
 const ctx={...h.ctx,role:'cohost',roomUUID:'instance-1',participantUUID:'volunteer'},identity=contextToken({mid:'instance-1',pid:'meeting'});
 assert.equal((await h.bind('room','speaker',ctx,identity)).data.code,'ROOM_PENDING');
 await sample();const room=(await h.bind('room','speaker',ctx,identity,2)).data;assert.equal(room.paperId,'p1');
 const hb=(await h.send(room,'heartbeat',{},identity)).data;assert.equal((await h.send(room,'speaker',{users:[{id:'volunteer',name:'Speaker A'}],ageMs:0,sampleTicket:hb.sampleTicket},identity)).status,200);
 await h.restart();let state=(await h.call('/api/state')).data.state;assert.equal(state.events[0].papers[0].live.activeSpeakerName,'Speaker A');
 assert.equal((await h.send(room,'heartbeat')).data.code,'CONTEXT');
 const cfg=h.object.hub.config('poster');await h.send(central,'mapping',{revision:cfg.revision,mapping:[{roomUUID:'management-1',paperId:'p2'}]});
 assert.equal((await h.send(room,'heartbeat',{},identity)).data.code,'MAPPING_CHANGED');
 assert.equal((await h.admin('/api/admin/apps/v1',undefined,'DELETE')).status,200);
 state=(await h.call('/api/state')).data.state;assert.equal(state.events[0].headcounts.available,false);
});
test('Webinar receives count only; no roster or speaker leaks',async()=>{
 const h=await setup(),ctx={...h.ctx,meetingId:'987654321'},bound=(await h.bind('webinar','session',ctx,h.token,1,'webinar')).data;
 const hb=(await h.send(bound,'heartbeat')).data;
 assert.equal((await h.send(bound,'attendance',{sampleTicket:hb.sampleTicket,snapshot:{total:502}})).status,200);
 assert.equal((await h.send(bound,'attendance',{sampleTicket:hb.sampleTicket,snapshot:{total:502,users:['name']}})).status,400);
 const event=(await h.call('/api/state')).data.state.events[1];assert.equal(event.headcounts.zoom,502);assert(!('live'in event));
});
test('Failed storage commit cannot return success or retain new in-memory telemetry',async()=>{
 const h=await setup(),bound=(await h.bind()).data;const before=h.object.hub.sessions.get(bound.token).seq;
 h.storage.fail=true;assert.equal((await h.send(bound,'heartbeat')).status,503);h.storage.fail=false;
 assert.equal(h.object.hub.sessions.get(bound.token).seq,before);
});
test('Stop intent survives reinitialization and fences delayed bind',async()=>{
 const h=await setup(),bound=(await h.bind()).data;
 assert.equal((await h.call('/zoom/app/v1/api/observer/cancel',{clientId:'central',intent:2},h.headers)).status,200);await h.restart();
 assert.equal((await h.bind()).data.code,'SUPERSEDED');assert.equal((await h.send(bound,'heartbeat')).data.code,'RELEASED');
});
test('OAuth state survives reinitialization, is bound to cookie/profile and is single-use',async()=>{
 const h=await setup();let response=await h.raw('/zoom/oauth/callback/v1?code=direct');assert.equal(response.status,302);
 response=await h.raw('/zoom/oauth/start/v1');const location=new URL(response.headers.get('location')),state=location.searchParams.get('state');assert(state);
 const cookie=response.headers.get('set-cookie').split(';')[0];await h.restart();
 assert.equal((await h.raw('/zoom/oauth/callback/v1?state='+state+'&code=x')).status,401);
 const original=globalThis.fetch;
 globalThis.fetch=async url=>String(url).includes('/oauth/token')?new Response(JSON.stringify({access_token:'access-2',refresh_token:'refresh-2',expires_in:3600})):new Response(JSON.stringify({id:'new-user'}));
 try{response=await h.raw('/zoom/oauth/callback/v1?state='+state+'&code=x',{headers:{Cookie:cookie}});assert.equal(response.status,200);assert.equal((await h.raw('/zoom/oauth/callback/v1?state='+state+'&code=x',{headers:{Cookie:cookie}})).status,401);}finally{globalThis.fetch=original;}
 const key=h.object.zoom.grantKey('v1',app,'new-user');assert.equal((await h.object.zoom.grant(key)).access_token,'access-2');assert(!String(await h.storage.get(key)).includes('access-2'));
});
test('Profile-specific webhook signatures and delayed deauthorization after reinstall',async()=>{
 const h=await setup(),key=h.object.zoom.grantKey('v1',app,'host-user'),record=await h.object.zoom.grant(key);
 async function webhook(data,secret=app.webhookSecret){const body=JSON.stringify(data),ts=String(Math.floor(Date.now()/1000)),sig='v0='+crypto.createHmac('sha256',secret).update(`v0:${ts}:${body}`).digest('hex');return h.raw('/zoom/webhook/v1',{method:'POST',headers:{'x-zm-request-timestamp':ts,'x-zm-signature':sig},body});}
 assert.equal((await webhook({event:'endpoint.url_validation',payload:{plainToken:'test'}},'wrong')).status,401);
 let r=await webhook({event:'endpoint.url_validation',payload:{plainToken:'test'}});assert.equal(r.status,200);assert((await r.json()).encryptedToken);
 const event={event:'app_deauthorized',event_ts:record.installedAt-1,payload:{client_id:app.clientId,user_id:'host-user'}};
 await webhook(event);assert(await h.object.zoom.grant(key));event.event_ts=Date.now()+1;await webhook(event);assert.equal(await h.object.zoom.grant(key),null);
});
test('Viewer telemetry packets survive reinitialization; schedule replacement sends full baseline; shared-IP 1000 sockets',async()=>{
 const h=await harness(),clients=[];for(let i=0;i<1000;i++){const r=await h.raw('/ws/public',{headers:{Upgrade:'websocket',Origin:'https://live.example','cf-connecting-ip':'1.2.3.4'}});assert.equal(r.status,101);clients.push(r.webSocket);}
 assert.equal(h.ctx.getWebSockets().length,1000);await h.restart();await h.alarm();
 const sample=clients[0].messages.map(JSON.parse);assert.equal(sample[0].type,'state');assert.equal(sample[1].type,'live');
 assert(Buffer.byteLength(JSON.stringify(sample[1]))<Buffer.byteLength(JSON.stringify(sample[0]))/3);
 for(const client of clients)assert.equal(client.messages.length,2);
 await h.admin('/api/admin/import',{schedule});await h.alarm();assert.equal(JSON.parse(clients[0].messages.at(-1)).type,'state');
 for(const client of clients)client.close();assert.equal(h.ctx.getWebSockets().length,0);
});
test('Large schedules chunk safely; failed import leaves existing schedule and mappings intact',async()=>{
 const h=await harness(),large=structuredClone(schedule);large.events[0].papers[0].abstract='x'.repeat(200000);
 assert.equal((await h.admin('/api/admin/import',{schedule:large})).status,200);await h.restart();assert.equal((await h.call('/api/state')).data.state.events[0].papers[0].abstract.length,200000);
 const bad=structuredClone(large);bad.events.push(bad.events[0]);assert.equal((await h.admin('/api/admin/import',{schedule:bad})).status,400);
 assert.equal((await h.call('/api/state')).data.state.events.length,2);
});
test('Debug clock changes event visibility without extending real-time telemetry; disabling edits keeps explicit state',async()=>{
 const h=await setup(),bound=(await h.bind()).data,hb=(await h.send(bound,'heartbeat')).data;
 await h.send(bound,'attendance',{sampleTicket:hb.sampleTicket,snapshot:{lobby:['host-participant'],rooms:[]}});
 const age=h.object.hub.snapshots.get('poster').at;
 assert.equal((await h.admin('/api/debug-clock',{fakeNow:'2026-10-06T10:40:00Z',speed:0})).status,200);
 assert.equal(h.object.hub.snapshots.get('poster').at,age);
 assert.equal((await h.admin('/api/debug-clock',{fakeNow:'2026-10-06T12:30:00Z',speed:0})).status,200);
 const state=(await h.call('/api/state')).data.state;assert.equal(state.events[0].status,'history');assert.equal(state.events[0].links.zoom,undefined);
 assert.equal((await h.send(bound,'heartbeat')).data.code,'NOT_LIVE');
 h.env.ALLOW_DEBUG_CLOCK='0';assert.equal((await h.admin('/api/debug-clock',{enabled:false})).status,403);
});
test('Token refresh is serialized with durable grant updates',async()=>{
 const h=await setup(),key=h.object.zoom.grantKey('v1',app,'host-user'),old=await h.object.zoom.grant(key);old.expiresAt=0;await h.storage.put(key,seal(old,h.env,key));
 const original=globalThis.fetch;let exchanges=0;
 globalThis.fetch=async()=>{exchanges++;return new Response(JSON.stringify({access_token:'renewed',refresh_token:'renewed-refresh',expires_in:3600}));};
 try{
  const tokens=await Promise.all([h.object.locked(()=>h.object.zoom.accessToken(key,app)),h.object.locked(()=>h.object.zoom.accessToken(key,app))]);assert.deepEqual(tokens,['renewed','renewed']);assert.equal(exchanges,1);
 }finally{globalThis.fetch=original;}
 await h.restart();assert.equal((await h.object.zoom.grant(key)).refresh_token,'renewed-refresh');
});
test('Admin can add a Zoom test link; CSV refresh preserves it for the same event only',async()=>{
 const h=await harness();const link='https://zoom.us/j/555555555?pwd=test';
 assert.equal((await h.admin('/api/admin/event-link',{eventId:'poster',zoom:'https://evil.example/j/555'})).status,400);
 assert.equal((await h.admin('/api/admin/event-link',{eventId:'poster',zoom:link})).status,200);
 const fresh=structuredClone(schedule);fresh.events[0].links={};await h.admin('/api/admin/import',{schedule:fresh});
 assert.equal(h.object.meta.schedule.events[0].links.zoom,link);
 fresh.events[0].title='Unrelated session';await h.admin('/api/admin/import',{schedule:fresh});
 assert.equal(h.object.meta.schedule.events[0].links.zoom,undefined);
});
test('Live public state links Zoom through the program redirect, never the raw live_url',()=>{
 const raw='https://zoom.us/j/123?pwd=secret';
 const meta={revision:1,scheduleRevision:1,clock:{enabled:false},peaks:{events:{},posters:{}},schedule:{conference:{},events:[{id:'event-42',sourceEventId:'42',type:'poster',title:'Poster Session 1',startsAt:'2026-01-01T00:00:00Z',endsAt:'2099-01-01T00:00:00Z',links:{zoom:raw},papers:[{id:'paper-7',links:{}}]}]}};
 const state=publicState(meta,{decorate(){}});
 assert.equal(state.events[0].links.zoom,'https://ismir2026program.ismir.net/zoom.html?event_uid=42');
 assert.ok(!JSON.stringify(state).includes(raw)&&!JSON.stringify(livePacket(state)).includes(raw));
 assert.equal(meta.schedule.events[0].links.zoom,raw);
});

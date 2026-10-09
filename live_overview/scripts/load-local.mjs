// Real loopback HTTP/WebSockets with a Node adapter for DO storage and WebSocketPair.
// This measures the application protocol, NOT Cloudflare CPU quotas or global edge capacity.
import http from 'node:http';
import {once} from 'node:events';
import assert from 'node:assert/strict';
import WebSocket,{WebSocketServer} from 'ws';
import {harness,BASE,KEY,installWebSockets} from '../test/harness.js';
installWebSockets();
const count=Number(process.argv[2]||1000);if(!Number.isInteger(count)||count<1||count>1200)throw Error('Local test viewer count must be 1–1200');
const h=await harness({ALLOW_LEGACY_OBSERVER:'1',OBSERVER_KEY:KEY});
const wsServer=new WebSocketServer({noServer:true});
const server=http.createServer(async(req,res)=>{
 try{const chunks=[];for await(const chunk of req)chunks.push(chunk);const response=await h.raw(req.url,{method:req.method,headers:req.headers,...(['GET','HEAD'].includes(req.method)?{}:{body:Buffer.concat(chunks)})});res.writeHead(response.status,Object.fromEntries(response.headers));res.end(Buffer.from(await response.arrayBuffer()));}catch{res.writeHead(500);res.end();}
});
server.on('upgrade',async(req,socket,head)=>{
 const response=await h.raw(req.url,{headers:req.headers});
 if(response.status!==101){socket.end('HTTP/1.1 '+response.status+' Error\r\nConnection: close\r\n\r\n');return;}
 const internal=response.webSocket;
 wsServer.handleUpgrade(req,socket,head,ws=>{
   for(const message of internal.messages)ws.send(message);internal.messages.length=0;
   internal.on('message',message=>{internal.messages.length=0;if(ws.readyState===1)ws.send(message);});
   ws.on('close',()=>internal.close());ws.on('error',()=>internal.close());ws.on('message',()=>ws.close(1008));
 });
});
server.listen(0,'127.0.0.1');await once(server,'listening');const origin='http://127.0.0.1:'+server.address().port;
const failures=[],latencies=[];let messages=0,bytes=0;const clients=[];
async function open(){return new Promise((resolve,reject)=>{const started=performance.now(),ws=new WebSocket(origin.replace('http:','ws:')+'/ws/public',{origin:'https://live.example'});const timer=setTimeout(()=>reject(Error('Handshake timeout')),10000);ws.on('error',reject);ws.on('message',data=>{messages++;bytes+=data.length;const p=JSON.parse(data);if(p.type==='state'){clearTimeout(timer);latencies.push(performance.now()-started);resolve(ws);}});});}
async function post(path,body,token){const r=await fetch(origin+path,{method:'POST',headers:{'Content-Type':'application/json','X-Observer-Key':KEY,...(token?{Authorization:'Bearer '+token}:{})},body:JSON.stringify(body)});const data=await r.json();if(!r.ok)throw Object.assign(Error(data.error),data);return data;}
const ctx={meetingUUID:'meeting',meetingId:'123456789',roomUUID:'',role:'host',participantUUID:'host'};
const bind=(client,mode,context,intent=1)=>post('/api/observer/session',{protocol:2,eventId:'poster',clientId:client,mode,context,intent});
const host=await bind('host','attendance',ctx);const seqs=new Map();
const send=(s,type,more={})=>{const seq=(seqs.get(s.token)||0)+1;seqs.set(s.token,seq);return post('/observer/event',{context:s.context,seq,type,...more},s.token);};
const snapshot={lobby:['host'],rooms:Array.from({length:11},(_,i)=>({roomUUID:'r'+i,name:'Room '+i,members:['v'+i,'a'+i]}))};
async function sample(){const hb=await send(host,'heartbeat');await send(host,'attendance',{sampleTicket:hb.sampleTicket,snapshot});}
await sample();await send(host,'mapping',{revision:host.mappingRevision,mapping:snapshot.rooms.map((r,i)=>({roomUUID:r.roomUUID,paperId:'p'+(i+1)}))});
for(let i=0;i<11;i++)try{await bind('v'+i,'speaker',{...ctx,role:'cohost',roomUUID:'instance-'+i,participantUUID:'v'+i});}catch(e){assert.equal(e.code,'ROOM_PENDING');}
await sample();const speakers=[];for(let i=0;i<11;i++)speakers.push(await bind('v'+i,'speaker',{...ctx,role:'cohost',roomUUID:'instance-'+i,participantUUID:'v'+i},2));
const start=performance.now();
try {
 for(let i=0;i<count;i+=50)clients.push(...await Promise.all(Array.from({length:Math.min(50,count-i)},open)));
 const connectedMs=performance.now()-start;
 for(let round=0;round<5;round++) {
   await sample();
   for(let i=0;i<speakers.length;i++){const hb=await send(speakers[i],'heartbeat');await send(speakers[i],'speaker',{sampleTicket:hb.sampleTicket,ageMs:0,users:[{id:'v'+i,name:'Speaker '+i}]});}
   await h.alarm();await new Promise(r=>setTimeout(r,50));
 }
 // Reconnect 20% of viewers as a burst; old sockets must release their slots.
 const reconnect=Math.floor(count/5);for(let i=0;i<reconnect;i++)clients[i].terminate();await new Promise(r=>setTimeout(r,80));
 for(let i=0;i<reconnect;i+=50){const fresh=await Promise.all(Array.from({length:Math.min(50,reconnect-i)},open));fresh.forEach((ws,j)=>clients[i+j]=ws);}
 await h.restart();await h.alarm();await new Promise(r=>setTimeout(r,80));
 assert.equal(h.ctx.getWebSockets().length,count);const state=(await (await fetch(origin+'/api/state')).json()).state;
 assert.equal(state.events[0].headcounts.zoom,23);assert.equal(state.events[0].papers.filter(p=>p.live.activeSpeakerTalking).length,11);
 latencies.sort((a,b)=>a-b);
 console.log(JSON.stringify({environment:'Node loopback adapter; not workerd or Cloudflare',viewers:count,observers:12,reconnected:reconnect,rounds:5,connectedMs:Math.round(connectedMs),p95HandshakeMs:Math.round(latencies[Math.floor(latencies.length*.95)]),receivedMessages:messages,receivedBytes:bytes,durationMs:Math.round(performance.now()-start),result:'passed'},null,2));
}finally{for(const ws of clients)ws.terminate();wsServer.close();server.closeAllConnections();server.close();}

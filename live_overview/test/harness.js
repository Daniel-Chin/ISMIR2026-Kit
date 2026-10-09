// In-process adapter, NOT the Cloudflare runtime. Keeps storage/websocket contracts explicit.
import fs from 'node:fs';
import {EventEmitter} from 'node:events';
import worker from '../src/worker.js';
import {Conference} from '../src/conference.js';
const NativeResponse=globalThis.Response;
export function installWebSockets() {
  class Socket extends EventEmitter {
    constructor(){super();this.readyState=1;this.messages=[];}
    send(text){if(this.readyState!==1)throw Error('Closed');this.other.messages.push(text);this.other.emit('message',text);}
    close(code=1000){if(this.readyState!==1)return;this.readyState=3;this.other.readyState=3;this.emit('close',code);this.other.emit('close',code);}
    serializeAttachment(value){this.attachment=structuredClone(value);}
    deserializeAttachment(){return structuredClone(this.attachment);}
  }
  globalThis.WebSocketPair=class {constructor(){this[0]=new Socket();this[1]=new Socket();this[0].other=this[1];this[1].other=this[0];}};
  globalThis.Response=class extends NativeResponse {constructor(body,init){if(init?.status===101){super(null,{status:200});Object.defineProperty(this,'status',{value:101});this.webSocket=init.webSocket;}else super(body,init);}};
}
export class Storage {
  constructor(){this.data=new Map();this.alarm=null;this.writes=0;this.fail=false;}
  async get(key){if(Array.isArray(key))return new Map(key.filter(k=>this.data.has(k)).map(k=>[k,structuredClone(this.data.get(k))]));return structuredClone(this.data.get(key));}
  async put(key,value){if(this.fail)throw Error('Injected storage failure');if(typeof key==='object'){for(const[k,v]of Object.entries(key))await this.put(k,v);return;}if(Buffer.byteLength(JSON.stringify(value))>128*1024)throw Error('Value too large');this.data.set(key,structuredClone(value));this.writes++;}
  async delete(key){if(Array.isArray(key)){for(const k of key)this.data.delete(k);}else this.data.delete(key);}
  async list({prefix='',limit=Infinity}={}){return new Map([...this.data].filter(([k])=>k.startsWith(prefix)).slice(0,limit).map(([k,v])=>[k,structuredClone(v)]));}
  async transaction(work){const before=structuredClone(this.data);try{return await work(this);}catch(e){this.data=before;throw e;}}
  async getAlarm(){return this.alarm;}
  async setAlarm(time){this.alarm=time;}
}
export const BASE='https://backend.example';
export const KEY='test-admin-strong-key-12345678901234567890';
export const schedule={conference:{name:'Test',timeZone:'Asia/Dubai'},events:[{id:'poster',type:'poster',title:'Poster session',startsAt:'2026-10-06T10:00:00Z',endsAt:'2026-10-06T12:00:00Z',links:{zoom:'https://zoom.us/j/123456789'},papers:Array.from({length:12},(_,i)=>({id:'p'+(i+1),title:'Paper '+(i+1),abstract:'A long public abstract. '.repeat(100)}))},{id:'webinar',type:'keynote',title:'Webinar',startsAt:'2026-10-06T10:00:00Z',endsAt:'2026-10-06T12:00:00Z',links:{zoom:'https://zoom.us/w/987654321'}}]};
export async function harness(extra={}) {
  const storage=new Storage(),sockets=[];
  const ctx={storage,blockConcurrencyWhile(fn){this.ready=Promise.resolve().then(fn);return this.ready;},getWebSockets(){return sockets.filter(s=>s.readyState===1);},acceptWebSocket(s){sockets.push(s);}};
  const env={ADMIN_KEY:KEY,TOKEN_ENCRYPTION_KEY:'a'.repeat(64),ALLOW_DEBUG_CLOCK:'1',PUBLIC_VIEW_ORIGINS:'https://live.example',MAX_PUBLIC_WS_CLIENTS:'1500',...extra,ASSETS:{async fetch(req){const name=new URL(req.url).pathname;try{return new Response(fs.readFileSync(new URL('../public'+name,import.meta.url)),{headers:{'Content-Type':name.endsWith('.html')?'text/html':'text/javascript'}});}catch{return new Response('Not found',{status:404});}}}};
  let object=new Conference(ctx,env);await ctx.ready;
  env.CONFERENCE={idFromName:n=>n,get:()=>({fetch:req=>object.fetch(req)})};
  async function raw(path,options={}){return worker.fetch(new Request(BASE+path,options),env);}
  async function call(path,body,extra={}){const res=await raw(path,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json',...extra},...(body===undefined?{}:{body:JSON.stringify(body)})});let data;try{data=await res.json();}catch{}return {status:res.status,data,res};}
  async function admin(path,body,method){return raw(path,{method:method||(body===undefined?'GET':'POST'),headers:{Authorization:'Bearer '+KEY,'Content-Type':'application/json'},...(body===undefined?{}:{body:JSON.stringify(body)})});}
  await admin('/api/admin/import',{schedule,clock:{enabled:true,baseFakeIso:'2026-10-06T10:30:00Z',baseRealIso:new Date().toISOString(),speed:0}});
  return {storage,ctx,env,raw,call,admin,get object(){return object;},async restart(){object=new Conference(ctx,env);await ctx.ready;return object;},async alarm(){storage.alarm=null;await object.alarm();}};
}

import {failure, hash, json, headers, authorize, seal, unseal, encryptionKey, bodyJSON} from './security.js';
import {defaultMeta, ObserverHub, restoreHub, exportHub, cleanupHub, conferenceNow, status, publicState, updatePeaks, livePacket, validateSchedule, setClock, importRuntime} from './model.js';
import {getBlob,putBlobs,deleteKeys,putEntries} from './storage.js';
import {Zoom, PROFILE, validateApp} from './zoom.js';
export class Conference {
  constructor(ctx,env) {
    this.ctx=ctx;this.env=env;this.tail=Promise.resolve();this.budgets=new Map();this.zoom=new Zoom(this);
    ctx.blockConcurrencyWhile(()=>this.load());
  }
  async load() {
    const meta=await getBlob(this.ctx.storage,'meta'),schedule=await getBlob(this.ctx.storage,'schedule'),hub=await getBlob(this.ctx.storage,'hub');
    this.meta=meta?JSON.parse(meta):defaultMeta();this.meta.schedule=schedule?JSON.parse(schedule):defaultMeta().schedule;
    this.makeHub();if(hub)restoreHub(this.hub,unseal(hub,this.env,'observer-state-v1'));
    cleanupHub(this.hub);this.scheduleCache=null;
  }
  makeHub() {
    this.hub=new ObserverHub({events:()=>this.meta.schedule.events,live:e=>status(e,conferenceNow(this.meta.clock))==='live',store:()=>this.meta.mappings,changed:()=>{this.meta.revision++;}});
  }
  locked(work) {
    const next=this.tail.catch(()=>{}).then(work);this.tail=next;return next;
  }
  limit(key,max) {
    const now=Date.now();let b=this.budgets.get(key);if(!b||b.until<now){b={n:0,until:now+60000};this.budgets.set(key,b);}
    if(this.budgets.size>4000)for(const[k,v]of this.budgets)if(v.until<now)this.budgets.delete(k);
    if(++b.n>max)throw failure('Too many requests; retry shortly.',429,'RATE');
  }
  async persistHub(schedule=false) {
    const {schedule:ignored,...meta}=this.meta;
    const values={meta:JSON.stringify(meta),hub:seal(exportHub(this.hub),this.env,'observer-state-v1')};
    if(schedule)values.schedule=JSON.stringify(this.meta.schedule);
    try {await putBlobs(this.ctx.storage,values);}catch(e){await this.load();throw failure('State could not be saved; retry shortly.',503,'NETWORK');}
    await this.ensureAlarm(3000);
  }
  async ensureAlarm(delay) {
    const due=Date.now()+delay,old=await this.ctx.storage.getAlarm();
    if(!old||old>due)await this.ctx.storage.setAlarm(due);
  }
  state() {return publicState(this.meta,this.hub,this.env.ALLOW_DEBUG_CLOCK==='1');}
  revokeOwner(owner,prefix=false) {
    for(const s of this.hub.sessions.values())if(prefix?s.appOwner?.startsWith(owner):s.appOwner===owner)this.hub.revoke(s,'APP_AUTH');
    this.meta.revision++;
  }
  async observer(req,path,body,identity=null) {
    const owner=identity?identity.app+':'+identity.user:'';
    if(owner)this.limit('identity:'+owner,1200);
    if(identity&&path!=='/observer/event'&&body.clientId)body.clientId=hash(owner+':'+body.clientId);
    if(identity&&(path==='/api/observer/session'||path==='/observer/event')&&body.type!=='release') {
      const c=body.context;
      let signedRoomMatches=Boolean(c&&identity.mid&&c.meetingUUID===(identity.pid||identity.mid)&&
        (c.roomUUID||'')===(identity.pid?identity.mid:''));
      // Some Zoom clients sign only the parent meeting even inside a breakout room.
      // Accept that representation only for speaker mode, with Host roster proof.
      if(!signedRoomMatches&&c?.roomUUID&&!identity.pid&&identity.mid&&c.meetingUUID===identity.mid) {
        let mode=body.mode,session;
        if(path==='/observer/event') {
          const token=(req.headers.get('authorization')||'').replace(/^Bearer /,'');
          session=this.hub.session(token);
          if((session.appOwner||'')!==owner)throw failure('Connection belongs to another App/user.',401,'APP_AUTH');
          mode=session.mode;
        }
        if(mode==='speaker') {
          const eventId=session?.eventId||body.eventId;
          const snap=this.hub.attendance(eventId);
          const room=snap?.membership.get(c.participantUUID);
          const cfg=this.hub.config(eventId);
          if(!snap||!room||cfg.meetingUUID!==identity.mid||!cfg.mapping[room])
            throw failure('Waiting for fresh central Host attendance and your room mapping.',422,'ROOM_PENDING');
          if(session&&room!==session.breakoutRoomId)
            throw failure('Host roster shows a different room. Reconnecting.',422,'CONTEXT');
          // bind() still requires a roster collected after the room claim;
          // receive() still enforces the complete bound context and sequence.
          signedRoomMatches=true;
        }
      }
      if(!signedRoomMatches)throw failure('Zoom meeting or room changed. Reconnecting.',422,'CONTEXT');
    }

    if(!identity) {
      if(this.env.ALLOW_LEGACY_OBSERVER!=='1')throw failure('Open the configured Zoom App profile.',401,'APP_AUTH');
      if(path!=='/observer/event')authorize(new Request(req.url,{headers:{Authorization:'Bearer '+(req.headers.get('x-observer-key')||'')}}),this.env.OBSERVER_KEY);
    }
    if(path==='/api/observer/catalog')return json({ok:true,events:this.hub.catalog()});
    let result;
    try {
      if(path==='/api/observer/session') {
        this.limit('bind:'+owner+':'+body.clientId,120);
        result=this.hub.bind(body);if(owner)this.hub.sessions.get(result.token).appOwner=owner;
      } else if(path==='/api/observer/cancel')result=this.hub.cancel(body);
      else if(path==='/observer/event') {
        const token=(req.headers.get('authorization')||'').replace(/^Bearer /,'');
        const session=this.hub.session(token);
        if((session.appOwner||'')!==owner)throw failure('Connection belongs to another App/user.',401,'APP_AUTH');
        this.limit('session:'+token,180);result=this.hub.receive(token,body);
      } else throw failure('Not found.',404);
    } finally {
      // Failed binds also record intent tombstones, preventing delayed switch/stop rollback.
      updatePeaks(this.meta,this.hub);await this.persistHub();
    }
    return json(result);
  }
  async admin(req,url) {
    authorize(req,this.env.ADMIN_KEY);this.limit('admin',120);
    const path=url.pathname;
    if(req.method==='GET'&&path==='/api/admin/status')return json({ok:true,version:'1.0.0-beta.2',events:this.meta.schedule.events.length,connections:this.ctx.getWebSockets().length,debugClock:this.state().debugClock,profiles:this.meta.profileIds,legacyObserver:this.env.ALLOW_LEGACY_OBSERVER==='1'});
    if(req.method==='GET'&&path==='/api/admin/events')return json({ok:true,events:this.meta.schedule.events.map(e=>({id:e.id,title:e.title,startsAt:e.startsAt,zoom:e.links?.zoom||''}))});
    if(req.method==='POST'&&path==='/api/admin/event-link') {
      const body=await bodyJSON(req);const event=this.meta.schedule.events.find(e=>e.id===body.eventId);
      if(!event)throw failure('Session not found.',404);
      let url;try{url=new URL(body.zoom);}catch{throw failure('Please enter a Zoom join URL.');}
      if(url.protocol!=='https:'||url.username||url.password||!/(^|\.)(zoom\.us|zoom\.com|zoomgov\.com)$/.test(url.hostname)||!/^\/(?:j|s|w|wc\/join)\/\d+(?:\/|$)/.test(url.pathname))throw failure('Use a direct HTTPS Zoom join link containing the numeric meeting ID.');
      event.links={...event.links,zoom:url.href};event.zoomKind=event.type==='poster'?'meeting':'webinar';
      delete this.meta.mappings[event.id];for(const session of this.hub.sessions.values())if(session.eventId===event.id)this.hub.revoke(session,'CONTEXT');
      this.meta.scheduleRevision++;this.meta.revision++;await this.persistHub(true);return json({ok:true});
    }
    if(req.method==='GET'&&path==='/api/admin/export')return json({ok:true,schedule:this.meta.schedule,runtime:{observerRoomMappings:structuredClone(this.meta.mappings),events:Object.fromEntries(Object.entries(this.meta.peaks.events).map(([k,v])=>[k,{peakZoom:v}])),posters:Object.fromEntries(Object.entries(this.meta.peaks.posters).map(([k,v])=>[k,{peakZoom:v}]))},clock:this.meta.clock});
    if(req.method==='POST'&&path==='/api/admin/import') {
      const body=await bodyJSON(req,8000000),replacement=validateSchedule(body.schedule);
      // CSV exports currently have empty live_url. Preserve manually configured links only
      // for the exact same source ID, title and event type; never transfer across unrelated sessions.
      for(const e of replacement.events) {
        const old=this.meta.schedule.events.find(x=>x.id===e.id&&x.type===e.type&&x.title===e.title);
        if(!e.links.zoom&&old?.links?.zoom){e.links.zoom=old.links.zoom;e.zoomKind=old.zoomKind;}
      }
      const draft=defaultMeta();draft.schedule=replacement;draft.profileIds=this.meta.profileIds;
      draft.revision=this.meta.revision+1;draft.scheduleRevision=this.meta.scheduleRevision+1;
      // A schedule edit preserves valid old mappings and peaks unless a migration bundle overrides them.
      const oldRuntime={observerRoomMappings:structuredClone(this.meta.mappings),events:Object.fromEntries(Object.entries(this.meta.peaks.events).map(([k,v])=>[k,{peakZoom:v}])),posters:Object.fromEntries(Object.entries(this.meta.peaks.posters).map(([k,v])=>[k,{peakZoom:v}]))};
      for(const e of replacement.events) {
        const same=this.meta.schedule.events.some(x=>x.id===e.id&&x.type===e.type&&x.title===e.title);
        if(!same){delete oldRuntime.events[e.id];delete oldRuntime.observerRoomMappings[e.id];}
      }
      if(body.runtime)importRuntime(draft,body.runtime);
      else {
        for(const e of replacement.events){const cfg=oldRuntime.observerRoomMappings[e.id];if(cfg)cfg.mapping=Object.fromEntries(Object.entries(cfg.mapping).filter(([,pid])=>(e.papers||[]).some(p=>p.id===pid)));}
        importRuntime(draft,oldRuntime);
      }
      draft.clock={...this.meta.clock};
      if(body.clock) {
        if(body.clock.enabled && this.env.ALLOW_DEBUG_CLOCK!=='1')throw failure('Debug clock is disabled.',403);
        setClock(draft,body.clock.enabled?{fakeNow:new Date(conferenceNow(body.clock)).toISOString(),speed:body.clock.speed}:{enabled:false});
      }
      this.meta=draft;this.makeHub();await this.persistHub(true);
      return json({ok:true,events:replacement.events.length,reconnectObservers:true});
    }
    const appMatch=path.match(/^\/api\/admin\/apps\/(v[1-9]\d{0,3})$/);
    if(appMatch&&req.method==='PUT') {
      const id=appMatch[1],app=validateApp(id,await bodyJSON(req));
      for(const other of this.meta.profileIds)if(other!==id){const value=await this.ctx.storage.get('app:'+other);if(value&&unseal(value,this.env,'app:'+other).clientId===app.clientId)throw failure('Client ID is already assigned to '+other);}
      // Replacing a profile invalidates old grants: imported credentials may refer to a different app.
      const grants=await this.ctx.storage.list({prefix:'grant:'+id+':'});
      if(grants.size)await deleteKeys(this.ctx.storage,[...grants.keys()]);
      await this.ctx.storage.put('app:'+id,seal(app,this.env,'app:'+id));
      if(!this.meta.profileIds.includes(id))this.meta.profileIds.push(id);
      this.revokeOwner(id+':',true);await this.persistHub();
      return json({ok:true,id,installUrl:app.origin+'/zoom/oauth/start/'+id,reinstallRequired:true});
    }
    if(appMatch&&req.method==='DELETE') {
      const id=appMatch[1];await this.ctx.storage.delete('app:'+id);
      const grants=await this.ctx.storage.list({prefix:'grant:'+id+':'});if(grants.size)await deleteKeys(this.ctx.storage,[...grants.keys()]);
      this.meta.profileIds=this.meta.profileIds.filter(x=>x!==id);this.revokeOwner(id+':',true);await this.persistHub();return json({ok:true});
    }
    // Import existing encrypted multi-app grants without exposing access tokens in responses.
    if(req.method==='POST'&&path==='/api/admin/grants/import') {
      const body=await bodyJSON(req,4000000);if(!Array.isArray(body.grants)||body.grants.length>200)throw failure('Expected up to 200 grant records.');
      const entries={};
      for(const item of body.grants) {
        const app=await this.zoom.app(item.id);if(item.clientId!==app.clientId||!/^[a-f0-9]{64}$/.test(item.ownerHash||''))throw failure('Grant profile/client mismatch.');
        if(!item.tokens?.access_token||!item.tokens.refresh_token||!Number.isFinite(item.tokens.installedAt)||!Number.isFinite(item.tokens.expiresAt))throw failure('Invalid token record.');
        const key='grant:'+item.id+':'+item.ownerHash;entries[key]=seal(item.tokens,this.env,key);
      }
      await putEntries(this.ctx.storage,entries);return json({ok:true,imported:body.grants.length});
    }
    if(req.method==='POST'&&path==='/api/admin/reset-runtime') {this.meta.mappings={};this.meta.peaks={events:{},posters:{}};this.meta.revision++;this.makeHub();await this.persistHub();return json({ok:true});}
    return json({ok:false,error:'Not found.'},404);
  }
  async handle(req) {
    const url=new URL(req.url),path=url.pathname;
    if(path==='/api/health'&&req.method==='GET')return json({ok:true,version:'1.0.0-beta.2',configured:Boolean(this.env.ADMIN_KEY?.length>=24&&/^[a-f0-9]{64}$/i.test(this.env.TOKEN_ENCRYPTION_KEY||'')),scheduleLoaded:!!this.meta.schedule.events.length});
    if(path==='/api/state'&&req.method==='GET')return json({ok:true,state:this.state()});
    if(path==='/ws/public') {
      if(req.method!=='GET'||req.headers.get('upgrade')?.toLowerCase()!=='websocket')return json({ok:false,error:'WebSocket upgrade required.'},426);
      const max=Math.max(1,Math.min(5000,Number(this.env.MAX_PUBLIC_WS_CLIENTS)||1500));
      if(this.ctx.getWebSockets().length>=max)throw failure('Viewer capacity reached; retry shortly.',503,'CAPACITY');
      const [client,server]=Object.values(new WebSocketPair());this.ctx.acceptWebSocket(server);
      server.serializeAttachment({scheduleRevision:this.meta.scheduleRevision});
      server.send(JSON.stringify({type:'state',state:this.state()}));await this.ensureAlarm(3000);
      return new Response(null,{status:101,webSocket:client});
    }
    encryptionKey(this.env); // Fail closed for operations requiring durable private state.
    if(path.startsWith('/api/admin/'))return this.admin(req,url);
    if(path==='/api/debug-clock') {
      if(req.method==='GET')return json({ok:true,debugClock:this.state().debugClock});
      if(!['POST','DELETE'].includes(req.method))throw failure('Method not allowed.',405);
      authorize(req,this.env.DEBUG_CLOCK_KEY||this.env.ADMIN_KEY);
      if(this.env.ALLOW_DEBUG_CLOCK!=='1')throw failure('Debug clock is disabled.',403);
      setClock(this.meta,req.method==='DELETE'?{enabled:false}:await bodyJSON(req));this.meta.revision++;await this.persistHub();return json({ok:true,debugClock:this.state().debugClock,state:this.state()});
    }
    const match=path.match(/^\/zoom\/(oauth\/(?:start|callback)|app|webhook)\/(v[1-9]\d{0,3})(\/.*)?$/);
    if(match)return this.zoom.route(req,url,match);
    if(req.method==='POST'&&(path.startsWith('/api/observer/')||path==='/observer/event'))return this.observer(req,path,await bodyJSON(req));
    return json({ok:false,error:'Not found.'},404);
  }
  async fetch(req) {
    return this.locked(async()=>{
      try{return await this.handle(req);}catch(e){if(!e.status)console.error('Backend error',e.stack || e.message || e.name);return json({ok:false,code:e.code||'NETWORK',error:e.status?e.message:'Service unavailable; retry shortly.'},e.status||503);}
    });
  }
  async alarm() {
    return this.locked(async()=>{
      const changed=cleanupHub(this.hub);if(changed)await this.persistHub();
      const sockets=this.ctx.getWebSockets();
      if(sockets.length) {
        const state=this.state(),live=JSON.stringify(livePacket(state));let full;
        for(const ws of sockets)try{
          if(ws.deserializeAttachment()?.scheduleRevision!==this.meta.scheduleRevision){full ||= JSON.stringify({type:'state',state});ws.send(full);ws.serializeAttachment({scheduleRevision:this.meta.scheduleRevision});}
          else ws.send(live);
        }catch{try{ws.close(1011,'Reconnect');}catch{}}
      }
      let oauth=await this.ctx.storage.list({prefix:'oauth:',limit:1000});const expired=[...oauth].filter(([,v])=>v.exp<Date.now()).map(([k])=>k);
      if(expired.length)await deleteKeys(this.ctx.storage,expired);
      const active=this.hub.snapshots.size||[...this.hub.sessions.values()].some(s=>this.hub.connected(s));
      if(sockets.length||active)await this.ensureAlarm(3000);
      else if(oauth.size>expired.length)await this.ensureAlarm(600000);
      else if(this.hub.clients.size)await this.ensureAlarm(3600000);
    });
  }
  webSocketMessage(ws) {ws.close(1008,'Read-only connection');}
  webSocketClose(ws,code) {try{ws.close(code===1005?1000:code);}catch{}}
  webSocketError(ws) {try{ws.close(1011,'Reconnect');}catch{}}
}

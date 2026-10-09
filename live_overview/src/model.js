import { failure } from './security.js';
import hubModule from './observer-hub.cjs';
export const { ObserverHub, ObserverError } = hubModule;
const clone = value => JSON.parse(JSON.stringify(value));
const count = n => Math.max(0, Math.min(5000, Math.round(Number(n) || 0)));
export const defaultMeta = () => ({schema:1, revision:1, scheduleRevision:1, schedule:{conference:{name:'ISMIR 2026',timeZone:'Asia/Dubai'}, events:[]}, mappings:{}, peaks:{events:{},posters:{}}, clock:{enabled:false,revision:1,speed:1}, profileIds:[]});
export function conferenceNow(clock, now = Date.now()) {
  if (!clock?.enabled) return now;
  const fake = Date.parse(clock.baseFakeIso), real = Date.parse(clock.baseRealIso);
  return Number.isFinite(fake) && Number.isFinite(real) ? fake + (now-real)*clock.speed : now;
}
export function status(event, now) {
  const a = Date.parse(event.startsAt), b = Date.parse(event.endsAt);
  return !Number.isFinite(a) || !Number.isFinite(b) || now < a ? 'upcoming' : now < b ? 'live' : 'history';
}
const reserved = new Set(['__proto__','prototype','constructor']);
export function validId(value) { return typeof value === 'string' && value.length > 0 && value.length <= 200 && !reserved.has(value); }
function links(raw) {
  const out = {};
  for (const [k,v] of Object.entries(raw || {})) {
    if (reserved.has(k) || typeof v !== 'string') continue;
    try { const u = new URL(v); if (u.protocol === 'https:' && !u.username && !u.password) out[k] = u.href; }
    catch { if (/^(?:\/(?!\/)|\.\.?\/|static\/)/.test(v)) out[k]=v; }
  }
  return out;
}
export function validateSchedule(input) {
  if (!input || !Array.isArray(input.events) || !input.conference || typeof input.conference !== 'object' || input.events.length > 1000) throw failure('Expected schedule.json with conference and events.');
  const s=clone(input), ids = new Set(), papers = new Set();
  for (const e of s.events) {
    if (!validId(e.id) || ids.has(e.id) || !Number.isFinite(Date.parse(e.startsAt)) || Date.parse(e.endsAt) <= Date.parse(e.startsAt) || !Number.isFinite(Date.parse(e.endsAt))) throw failure('Invalid/duplicate event ID or time range.');
    ids.add(e.id); e.links=links(e.links);
    if (e.links.youtube && /(^|\.)(zoom\.us|zoom\.com|zoomgov\.com)$/.test(new URL(e.links.youtube,'https://invalid.local').hostname)) {e.links.zoom ||= e.links.youtube; delete e.links.youtube;}
    if (e.links.zoom) e.zoomKind=e.type==='poster'?'meeting':'webinar';
    if (e.papers && !Array.isArray(e.papers)) throw failure('papers must be an array.');
    for (const p of e.papers || []) {if(!validId(p.id) || papers.has(p.id)) throw failure('Invalid/duplicate paper ID.'); papers.add(p.id); p.links=links(p.links);}
  }
  return s;
}
export function setClock(meta, input, now = Date.now()) {
  const revision = (meta.clock.revision || 0)+1;
  if(input.enabled===false || input.reset) {meta.clock={enabled:false,revision,speed:1};return;}
  const t=Date.parse(input.fakeNow || input.debugNow || input.now || input.baseFakeIso), speed=Number(input.speed ?? 0);
  if(!Number.isFinite(t)||!Number.isFinite(speed)||speed<0||speed>100) throw failure('Invalid time or speed (0–100).');
  meta.clock={enabled:true,baseFakeIso:new Date(t).toISOString(),baseRealIso:new Date(now).toISOString(),speed,revision};
}
export function exportHub(hub) {
  return {sessions:[...hub.sessions],clients:[...hub.clients].map(([k,v])=>[k,{...v,error:v.error?{message:v.error.message,status:v.error.status,code:v.error.code}:undefined}]),
    slots:[...hub.slots],snapshots:[...hub.snapshots].map(([k,v])=>[k,{...v,membership:v.membership?[...v.membership]:undefined}]),claims:[...hub.claims],roomIdentities:[...hub.roomIdentities],sampleOrder:hub.sampleOrder};
}
export function restoreHub(hub, value) {
  if(!value) return;
  for(const key of ['sessions','clients','slots','snapshots','claims','roomIdentities']) hub[key]=new Map(value[key]||[]);
  for(const v of hub.clients.values()) if(v.error) v.error=new ObserverError(v.error.code,v.error.message,v.error.status);
  for(const v of hub.snapshots.values()) if(v.membership) v.membership=new Map(v.membership);
  hub.sampleOrder=value.sampleOrder||0;
}
export function cleanupHub(hub, now=Date.now()) {
  let changed=false;
  for (const [id,snap] of hub.snapshots) if(!hub.attendance(id)) {hub.snapshots.delete(id);changed=true;}
  for(const s of hub.sessions.values()) {
    if(s.speakers && (now-s.speakers.at>hub.speakerMs || !hub.connected(s))) {s.speakers=null;changed=true;}
    // Keep intent tombstones for a day; erase participant/context data after lease expiry.
    if(now-s.lastSeen>hub.leaseMs && (!s.revoked || Object.keys(s.ctx).length)) {if(!s.revoked)hub.revoke(s,'SESSION_LOST');s.ctx={};changed=true;}
  }
  const before=hub.clients.size+hub.sessions.size+hub.claims.size+hub.roomIdentities.size; hub.prune();
  return changed || before!==hub.clients.size+hub.sessions.size+hub.claims.size+hub.roomIdentities.size;
}
const quiet = () => ({observerConnected:false,activeSpeakerTalking:false,activeSpeakerName:'',presenterTalking:false,audienceTalking:false,speakerState:'disconnected'});
// The raw Zoom URL (events.csv live_url) stays server-side; viewers get the program site's redirect page.
export const ZOOM_REDIRECT='https://ismir2026program.ismir.net/zoom.html?event_uid=';
const eventUid = e => String(e.sourceEventId || String(e.id).replace(/^event-/,'')).trim();
function publicLinks(raw, state, uid) {
  const value={...raw};
  if(state!=='live') for(const k of ['zoom','youtube','livestream','live']) delete value[k];
  else if(value.zoom) { if(uid) value.zoom=ZOOM_REDIRECT+encodeURIComponent(uid); else delete value.zoom; }
  return value;
}
export function publicState(meta, hub, allowDebug=false, now=Date.now()) {
  const fake=conferenceNow(meta.clock,now), events=[];
  for (const source of meta.schedule.events) {
    const e=clone(source); e.status=status(e,fake);e.links=publicLinks(e.links,e.status,eventUid(e));
    e.headcounts={zoom:0,available:e.status!=='live',partial:false};e.metrics={peakZoom:meta.peaks.events[e.id]||0};
    for(const p of e.papers || []) {p.links=publicLinks(p.links,e.status,eventUid(e));p.status=e.status; p.headcounts={zoom:0,available:e.status!=='live',partial:false};p.metrics={peakZoom:meta.peaks.posters[p.id]||0}; if(e.type==='poster') p.live=quiet();else delete p.live;}
    if(e.type==='poster') e.live=quiet();else delete e.live;
    hub.decorate(e);
    events.push(e);
  }
  const serverNow=new Date(fake).toISOString();
  return {schemaVersion:3,version:meta.revision,scheduleRevision:meta.scheduleRevision,updatedAt:serverNow,serverNow,conference:clone(meta.schedule.conference),debugClock:{...meta.clock,serverNow,realNow:new Date(now).toISOString(),canSet:allowDebug,storage:'durable-object'},events};
}
export function updatePeaks(meta, hub) {
  let changed=false;
  for(const e of meta.schedule.events) {
    if(status(e,conferenceNow(meta.clock))!=='live') continue;
    const snap=hub.attendance(e.id); if(!snap) continue;
    if(snap.total>(meta.peaks.events[e.id]||0)) {meta.peaks.events[e.id]=count(snap.total);changed=true;}
    for(const room of snap.rooms||[]) {const id=meta.mappings[e.id]?.mapping[room.roomUUID];if(id && room.count>(meta.peaks.posters[id]||0)) {meta.peaks.posters[id]=count(room.count);changed=true;}}
  }
  return changed;
}
// Every update is a complete telemetry slice; missing/reordered deltas cannot accumulate stale data.
export function livePacket(state) {
  const slice = p => ({id:p.id,status:p.status,links:p.links,headcounts:p.headcounts,metrics:p.metrics,...(p.live?{live:p.live}:{})});
  return {type:'live',scheduleRevision:state.scheduleRevision,version:state.version,serverNow:state.serverNow,updatedAt:state.updatedAt,debugClock:state.debugClock,
    events:state.events.map(e=>({...slice(e),papers:(e.papers||[]).map(slice)}))};
}
export function importRuntime(meta, runtime) {
  const mappings=runtime.observerRoomMappings||{};
  for(const e of meta.schedule.events) {
    meta.peaks.events[e.id]=count(runtime.events?.[e.id]?.peakZoom);
    for(const p of e.papers||[]) meta.peaks.posters[p.id]=count(runtime.posters?.[p.id]?.peakZoom);
    const cfg=mappings[e.id]; if(!cfg) continue;
    const papers=new Set((e.papers||[]).map(p=>p.id)), seen=new Set(), mapping={};
    for(const [room,paper] of Object.entries(cfg.mapping||{})) {
      if(!validId(room)||!papers.has(paper)||seen.has(paper)) throw failure('Invalid imported room mapping.');
      seen.add(paper);mapping[room]=paper;
    }
    meta.mappings[e.id]={revision:Math.max(0,Math.floor(Number(cfg.revision)||0)),meetingUUID:String(cfg.meetingUUID||''),mapping};
  }
}

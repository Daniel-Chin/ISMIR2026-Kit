const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const box={module:{exports:{}},URL};vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname,'../overview-source/public-connection.js'),'utf8'),box);const connection=box.module.exports;
function harness(initialMode = 'good') {
  let time = 100000, mode = initialMode, delayed;
  const timers = new Map(), states = [], statuses = [], requests = [], sockets = [], storage = new Map(); let nextId = 0;
  const state = { conference: { name: 'Test' }, events: [{ id: 'poster', type: 'poster', startsAt: '2026-01-01', endsAt: '2027-01-01',
    links: { zoom: 'https://zoom.us/j/123?pwd=private' }, headcounts: { zoom: 6, lobbyZoom: 2, available: true },
    papers: [{ live: { observerConnected: true, activeSpeakerName: 'Alice', activeSpeakerTalking: true }, headcounts: { zoom: 4, available: true } }] }],
    debugClock: { enabled: false, revision: 4 }, serverNow: '2026-10-01T00:00:00Z' };
  class Socket { constructor(url) { this.url = url; sockets.push(this); } close() { this.onclose?.(); } }
  const env = { Date: { now: () => time }, AbortController, WebSocket: Socket,
    setTimeout(fn, ms) { const id = ++nextId; timers.set(id, { fn, at: time + ms }); return id; }, clearTimeout(id) { timers.delete(id); },
    setInterval() { return 0; }, clearInterval() {}, localStorage: { getItem: k => storage.get(k), setItem: (k, v) => storage.set(k, v) },
    fetch: async (url, options) => { requests.push({ url, options });
      if (url.startsWith('./')) return Response.json({ conference: { name: 'Saved' }, events: [{ title: 'Offline session' }] });
      if (mode === 'bad') throw new TypeError('Network unavailable');
      if (mode === 'delayed') return new Promise(resolve => { delayed = () => resolve(Response.json({ ok: true, state })); });
      return Response.json({ ok: true, state });
    },
  };
  const api = connection(env), client = api.start({ apiOrigin: 'https://api.example.org', fallbackUrl: './schedule-snapshot.json', onState: s => states.push(s), onStatus: (...s) => statuses.push(s) });
  return { api, client, states, statuses, requests, sockets, storage, state, mode: x => { mode = x; },
    advance: ms => { time += ms; }, delayed: () => delayed(), settle: () => new Promise(r => setImmediate(r)) };
}
test('static transport targets backend without credentials, clears stale counts/speakers/links and recovers; cache has no telemetry', async () => {
  const h = harness(); await h.settle();
  assert.equal(h.requests[0].url, 'https://api.example.org/api/state'); assert.equal(h.requests[0].options.credentials, 'omit');
  assert.equal(h.sockets[0].url, 'wss://api.example.org/ws/public');
  assert.equal(h.states.at(-1).events[0].headcounts.zoom, 6);
  const saved = [...h.storage.values()][0]; assert.ok(!saved.includes('Alice')); assert.ok(!saved.includes('private'));
  h.mode('bad'); h.advance(11000); h.client.tick(); await h.settle();
  const old = h.states.at(-1); assert.equal(old.events[0].headcounts.available, false); assert.equal(old.events[0].papers[0].live.observerConnected, false);
  assert.equal(old.events[0].links.zoom, undefined); assert.equal(h.statuses.at(-1)[0], false);
  h.mode('good'); await h.client.refresh(); assert.equal(h.states.at(-1).events[0].headcounts.zoom, 6); assert.equal(h.statuses.at(-1)[0], true);
  h.client.stop();
});
test('late HTTP cannot overwrite newer socket state; fallback never wins over successful live state', async () => {
  const h = harness(); await h.settle(); h.mode('delayed');
  const pending = h.client.refresh(); await h.settle();
  const newer = structuredClone(h.state); newer.events[0].headcounts.zoom = 9;
  h.sockets[0].onmessage({ data: JSON.stringify({ type: 'state', state: newer }) }); h.delayed(); await pending;
  assert.equal(h.states.at(-1).events[0].headcounts.zoom, 9);
  h.sockets[0].onmessage({ data: 'malformed' }); h.advance(11000); h.mode('bad'); h.client.tick(); await h.settle();
  assert.equal(h.states.at(-1).offline, true); h.client.stop();
});

test('first visit during API outage shows snapshot metadata and reconnects without a page reload', async () => {
  const h = harness('bad'); await h.settle(); await h.settle();
  assert.equal(h.states.at(-1).events[0].title, 'Offline session'); assert.equal(h.states.at(-1).offline, true);
  assert.equal(h.states.at(-1).events[0].headcounts.available, false);
  h.mode('good'); h.advance(5001); h.client.tick(); await h.settle();
  assert.equal(h.states.at(-1).events[0].headcounts.zoom, 6); assert.equal(h.statuses.at(-1)[0], true);
  h.client.stop();
});
test('complete live slices replace stale telemetry without losing metadata; wrong schedule version is rejected',()=>{
 const api=connection({}),state={scheduleRevision:4,conference:{name:'Conference'},events:[{id:'e',title:'Keep me',papers:[{id:'p',abstract:'Keep abstract'}]}]};
 const item={status:'live',links:{zoom:'https://zoom.us/j/1'},headcounts:{available:true,zoom:3},metrics:{peakZoom:3}};
 const packet={type:'live',scheduleRevision:4,serverNow:'2026-10-06T11:00:00Z',version:10,debugClock:{enabled:false},events:[{...item,id:'e',papers:[{...item,id:'p',live:{observerConnected:true,activeSpeakerName:'Alice'}}]}]};
 const merged=api.mergeLive(state,packet);assert.equal(merged.events[0].title,'Keep me');assert.equal(merged.events[0].papers[0].abstract,'Keep abstract');assert.equal(merged.events[0].papers[0].live.activeSpeakerName,'Alice');assert.equal(merged.offline,false);
 packet.scheduleRevision++;assert.equal(api.mergeLive(state,packet),null);packet.scheduleRevision--;packet.events[0].papers=[];assert.equal(api.mergeLive(state,packet),null);
});

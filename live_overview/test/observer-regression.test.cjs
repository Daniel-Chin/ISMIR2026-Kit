'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { ObserverHub } = require('../src/observer-hub.cjs');
const Core = require('../src/observer-core.cjs');
const event = { id: 'poster', type: 'poster', title: 'Posters', links: { zoom: 'https://zoom.us/j/123456789' }, papers: [{ id: 'p1' }, { id: 'p2' }] };
const ctx = { meetingUUID: 'meeting', roomUUID: '', meetingId: '123456789', role: 'host', participantUUID: 'host' };
const snapshot = { rooms: [{ roomUUID: 'r1', name: 'Room 1', members: ['a', 'b'] }, { roomUUID: 'r2', name: 'Room 2', members: ['c'] }], lobby: ['host'] };
function setup() {
  let time = 100000, live = true; const store = {};
  const options = { events: () => [event, { ...event, id: 'talk', type: 'keynote' }], live: () => live, store: () => store, changed() {}, now: () => time };
  const hub = new ObserverHub(options);
  const body = (clientId = 'central', mode = 'attendance', extra = {}) => ({ protocol: 2, clientId, intent: 1, eventId: 'poster', mode, context: { ...ctx, ...(mode === 'speaker' ? { role: 'cohost', roomUUID: 'instance-r1', participantUUID: 'b' } : {}) }, ...extra });
  const bind = (...args) => hub.bind(body(...args));
  function send(s, type, extra = {}) {
    const state = hub.sessions.get(s.token);
    return hub.receive(s.token, { context: s.context, seq: state.seq + 1, type, sampleTicket: state.sampleTicket?.id, ...extra });
  }
  const sample = (s, value = snapshot) => { send(s, 'heartbeat'); return send(s, 'attendance', { snapshot: value }); };
  function speaker(client = 'room', extra = {}) {
    let intent = (hub.clients.get(client)?.intent || 0) + 1;
    try { return bind(client, 'speaker', { ...extra, intent }); } catch (e) { if (e.code !== 'ROOM_PENDING') throw e; }
    const central = [...hub.sessions.values()].find(s => s.mode === 'attendance' && hub.connected(s));
    sample(hub.bound(central));
    return bind(client, 'speaker', { ...extra, intent: intent + 1 });
  }
  function mapped() {
    const central = bind(); sample(central);
    send(central, 'mapping', { revision: hub.config('poster').revision, mapping: [{ roomUUID: 'r1', paperId: 'p1' }, { roomUUID: 'r2', paperId: 'p2' }] });
    return central;
  }
  const view = () => { const e = structuredClone({ ...event, status: 'live' }); hub.decorate(e); return e; };
  return { hub, options, body, bind, speaker, send, sample, mapped, view, advance: n => time += n, end: () => live = false };
}
const code = expected => e => e.code === expected;
test('Zoom schema: joined only, UUID dedup, main roster union, assigned remains in lobby', () => {
  const result = Core.attendance({ state: 'open', rooms: [{ breakoutRoomId: 'r1', participants: [
    { participantUUID: 'a', participantStatus: 'joined' }, { participantUUID: 'b', participantStatus: 'assigned' },
  ] }] }, { participants: ['host', 'a', 'b', 'host'].map(participantUUID => ({ participantUUID })) });
  assert.deepEqual(result.rooms[0].members, ['a']); assert.deepEqual(result.lobby, ['host', 'b']); assert.equal(result.total, 3);
});
test('permission omissions and transition duplicates never become zero counts', () => {
  assert.throws(() => Core.rooms({ state: 'open', rooms: [{ breakoutRoomId: 'r1' }] }), /member lists unavailable/);
  assert.throws(() => Core.ids(undefined), /participant list/);
  assert.throws(() => Core.rooms({ state: 'open', rooms: ['r1', 'r2'].map(breakoutRoomId => ({ breakoutRoomId, participants: [{ participantUUID: 'a', participantStatus: 'joined' }] })) }), /moving/);
  assert.deepEqual(Core.rooms({ state: 'closed', rooms: [{ breakoutRoomId: 'r1' }] })[0].members, []);
});
test('authorized Co-host gets current breakout context; exiting removes stale parent', () => {
  const user = { role: 'coHost', status: 'authorized', participantUUID: 'observer' };
  assert.equal(Core.context({ meetingUUID: 'r1', parentUUID: 'm1' }, user, { meetingID: '123 456' }).roomUUID, 'r1');
  assert.equal(Core.context({ meetingUUID: 'm1' }, user, { meetingID: '123 456' }).roomUUID, '');
  assert.throws(() => Core.context({}, { ...user, role: 'attendee' }, {}), /Co-host/);
  assert.throws(() => Core.context({}, { ...user, status: 'authenticated' }, {}), /authorize/);
});
test('bind rejects wrong role, meeting, mode, main-room speaker and unmapped room', () => {
  const f = setup();
  for (const [context, mode, expected] of [[{ ...ctx, role: 'attendee' }, 'attendance', 'ROLE'], [{ ...ctx, meetingId: '999' }, 'attendance', 'MEETING'], [ctx, 'speaker', 'ROOM'], [{ ...ctx, roomUUID: 'r1' }, 'speaker', 'MAPPING'], [ctx, 'session', 'MODE']]) {
    assert.throws(() => f.bind(expected, mode, { context }), code(expected));
  }
});
test('central counts stay available without any speaker observer; no identities in public state', () => {
  const f = setup(); f.mapped(); const e = f.view();
  assert.equal(e.headcounts.zoom, 4); assert.equal(e.papers[0].headcounts.zoom, 2);
  assert.equal(e.papers[0].live.speakerState, 'disconnected'); assert.equal(e.papers[0].headcounts.available, true);
  assert.equal(JSON.stringify(e).includes('participantUUID'), false);
});
test('speaker channel is Co-host compatible, scoped, independent of attendance freshness', () => {
  const f = setup(); f.mapped(); const s = f.speaker();
  f.send(s, 'heartbeat'); f.send(s, 'speaker', { users: [{ id: 'a', name: 'Alice' }], ageMs: 0 });
  assert.equal(f.view().papers[0].live.activeSpeakerName, 'Alice');
  assert.throws(() => f.send(s, 'attendance', { snapshot }), code('SCOPE'));
  f.advance(21000); f.send(s, 'heartbeat'); f.send(s, 'speaker', { users: [{ id: 'a', name: 'Alice' }], ageMs: 0 });
  assert.equal(f.view().headcounts.available, false); assert.equal(f.view().papers[0].live.speakerState, 'recent');
});
test('silence, unknown and disconnected are different; heartbeats cannot extend speech or counts', () => {
  const f = setup(), c = f.mapped(), s = f.speaker();
  f.send(s, 'heartbeat'); f.send(s, 'speaker', { users: [], ageMs: 0 });
  assert.equal(f.view().papers[0].live.speakerState, 'quiet');
  f.advance(10001); f.send(s, 'heartbeat'); assert.equal(f.view().papers[0].live.speakerState, 'unknown');
  f.advance(10000); f.send(c, 'heartbeat'); assert.equal(f.view().headcounts.available, false);
  f.advance(10001); assert.equal(f.view().papers[0].live.speakerState, 'disconnected');
});
test('mapping corrections are atomic and fence delayed speaker packets', () => {
  const f = setup(), c = f.mapped(), s = f.speaker();
  const revision = f.hub.config('poster').revision;
  assert.throws(() => f.send(c, 'mapping', { revision, mapping: [{ roomUUID: 'r1', paperId: 'p1' }, { roomUUID: 'r2', paperId: 'p1' }] }), code('MAPPING'));
  assert.equal(f.hub.config('poster').revision, revision);
  f.send(c, 'mapping', { revision, mapping: [{ roomUUID: 'r1', paperId: 'p2' }, { roomUUID: 'r2', paperId: 'p1' }] });
  assert.throws(() => f.send(s, 'heartbeat'), code('MAPPING_CHANGED'));
  const corrected = f.speaker();
  assert.equal(corrected.paperId, 'p2'); assert.equal(f.view().papers[1].headcounts.zoom, 2);
  assert.throws(() => f.send(c, 'mapping', { revision, mapping: [] }), code('MAPPING_CHANGED'));
});
test('takeover fences old updates and release; revoked pruning cannot erase new snapshot', () => {
  const f = setup(), old = f.mapped();
  assert.throws(() => f.bind('replacement'), code('OCCUPIED'));
  const next = f.bind('replacement', 'attendance', { intent: 2, takeover: true }); f.sample(next);
  assert.throws(() => f.send(old, 'release'), code('REPLACED'));
  f.hub.revoke(f.hub.sessions.get(old.token)); assert.equal(f.view().headcounts.zoom, 4);
});
test('lost bind response retries idempotently; old intent cannot undo switch or stop', () => {
  const f = setup(), a = f.bind(); assert.equal(f.bind().token, a.token);
  assert.throws(() => f.bind('central', 'attendance', { intent: 2, context: { ...ctx, meetingId: 'bad' } }), code('MEETING'));
  assert.throws(() => f.bind(), code('SUPERSEDED'));
  assert.equal(f.hub.session(a.token).token, a.token); // invalid selection cannot evict a valid binding
  f.hub.cancel({ clientId: 'central', intent: 3 });
  assert.throws(() => f.bind('central', 'attendance', { intent: 2 }), code('SUPERSEDED'));
  assert.throws(() => f.send(a, 'heartbeat'), code('RELEASED'));
});
test('delayed/replayed samples and malformed snapshots do not renew freshness or mutate sequence', () => {
  const f = setup(), c = f.mapped();
  const s = f.hub.session(c.token); const seq = s.seq;
  assert.throws(() => f.send(c, 'attendance', { snapshot: { ...snapshot, lobby: ['a'] } }), code('TRANSITION'));
  assert.equal(s.seq, seq);
  f.advance(13000); assert.throws(() => f.send(c, 'attendance', { snapshot }), code('OLD_SAMPLE'));
  const oldSeen = s.lastSeen;
  assert.equal(f.hub.receive(c.token, { context: c.context, type: 'heartbeat', seq }).duplicate, true);
  assert.equal(s.lastSeen, oldSeen);
  f.advance(8000); assert.equal(f.view().headcounts.available, false);
});
test('new meeting instance clears mappings; server restart retains mapping but never cached telemetry', () => {
  const f = setup(), c = f.mapped();
  const restarted = new ObserverHub(f.options);
  assert.equal(restarted.config('poster').mapping.r1, 'p1'); assert.equal(restarted.attendance('poster'), null);
  assert.throws(() => restarted.session(c.token), code('SESSION_LOST'));
  f.bind('central', 'attendance', { intent: 2, context: { ...ctx, meetingUUID: 'new-instance' } });
  assert.deepEqual(f.hub.config('poster').mapping, {});
});
test('schedule end rejects telemetry; non-poster sessions accept only numeric counts', () => {
  const f = setup(), c = f.bind('talk', 'session', { eventId: 'talk' });
  f.send(c, 'heartbeat'); f.send(c, 'attendance', { snapshot: { total: 2 } });
  const e = { id: 'talk', type: 'keynote', status: 'live', links: { zoom: 'url' } }; f.hub.decorate(e);
  assert.equal(e.headcounts.zoom, 2); f.end(); assert.throws(() => f.send(c, 'heartbeat'), code('NOT_LIVE'));
});

test('distinct management ID and breakout UUID resolve from joined participant UUID; legacy aliases cannot override', () => {
  const f = setup(), c = f.mapped();
  const speakerContext = { ...ctx, role: 'cohost', roomUUID: '994AC5DF-CE40-DF92-8B28-D2124ABF0CA2', participantUUID: 'b' };
  f.options.store().poster.roomInstanceUUIDs = { r2: speakerContext.roomUUID }; // Wrong old manual input.
  assert.throws(() => f.bind('room', 'speaker', { context: speakerContext }), code('ROOM_PENDING'));
  f.sample(c);
  const s = f.bind('room', 'speaker', { intent: 2, context: speakerContext });
  assert.equal(s.breakoutRoomId, 'r1'); assert.equal(s.paperId, 'p1'); assert.equal(s.roomName, 'Room 1');
  assert.equal(f.bind('room', 'speaker', { intent: 2, context: speakerContext }).token, s.token);
  f.send(s, 'heartbeat'); f.send(s, 'speaker', { users: [{ id: 'b', name: 'Bob' }], ageMs: 0 });
  assert.equal(f.view().papers[0].live.activeSpeakerName, 'Bob');
  assert.equal(f.hub.roomStatus('poster')[0].speakerConnected, true);
  assert.equal(f.hub.catalog()[0].config.roomInstanceUUIDs, undefined);
  for (const value of [f.view(), f.hub.roomStatus('poster'), f.hub.catalog(), f.options.store()]) {
    assert.ok(!JSON.stringify(value).includes('membership'));
  }
  const restarted = new ObserverHub(f.options);
  assert.throws(() => restarted.bind(f.body('new', 'speaker', { context: speakerContext })), code('ROOM_PENDING'));
  assert.equal(restarted.attendance('poster'), null);
  f.send(c, 'mapping', { revision: f.hub.config('poster').revision, mapping: [{ roomUUID: 'r1', paperId: 'p1' }] });
  assert.equal(f.options.store().poster.roomInstanceUUIDs, undefined);
});
test('a delayed snapshot collected before the room claim cannot establish a binding', () => {
  const f = setup(), c = f.mapped();
  f.send(c, 'heartbeat'); // Collection starts before Co-host connects.
  assert.throws(() => f.bind('room', 'speaker'), code('ROOM_PENDING'));
  f.send(c, 'attendance', { snapshot });
  assert.throws(() => f.bind('room', 'speaker', { intent: 2 }), code('ROOM_PENDING'));
  f.sample(c);
  assert.equal(f.bind('room', 'speaker', { intent: 3 }).paperId, 'p1');
});
test('missing, lobby-only and stale membership wait; duplicate membership never replaces good counts', () => {
  const f = setup(), c = f.mapped();
  assert.throws(() => f.bind('room', 'speaker'), code('ROOM_PENDING'));
  f.sample(c, { rooms: [{ roomUUID: 'r1', members: ['a'] }], lobby: ['host', 'b'] });
  assert.throws(() => f.bind('room', 'speaker', { intent: 2 }), code('ROOM_PENDING'));
  assert.throws(() => f.sample(c, { rooms: [{ roomUUID: 'r1', members: ['b'] }, { roomUUID: 'r2', members: ['b'] }], lobby: [] }), code('TRANSITION'));
  assert.equal(f.view().headcounts.zoom, 3);
  f.sample(c); f.advance(20001);
  assert.throws(() => f.bind('room', 'speaker', { intent: 3 }), code('ROOM_PENDING'));
  f.sample(c); assert.equal(f.bind('room', 'speaker', { intent: 4 }).paperId, 'p1');
});
test('fresh Host roster fences missed room change; stale SDK context cannot attach to the new paper', () => {
  const f = setup(), c = f.mapped(), s = f.speaker();
  f.send(s, 'heartbeat'); f.send(s, 'speaker', { users: [{ id: 'b', name: 'Bob' }], ageMs: 0 });
  const moved = { rooms: [{ roomUUID: 'r1', members: ['a'] }, { roomUUID: 'r2', members: ['b', 'c'] }], lobby: ['host'] };
  f.sample(c, moved);
  assert.throws(() => f.send(s, 'speaker', { users: [{ id: 'b', name: 'Late' }], ageMs: 0 }), code('CONTEXT'));
  assert.equal(f.view().papers[0].live.activeSpeakerName, '');
  assert.throws(() => f.bind('room', 'speaker', { intent: 3 }), code('ROOM_PENDING'));
  f.sample(c, moved);
  assert.throws(() => f.bind('room', 'speaker', { intent: 4 }), code('ROOM_PENDING'));
  const newContext = { ...s.context, roomUUID: 'instance-r2' };
  assert.throws(() => f.bind('room', 'speaker', { intent: 5, context: newContext }), code('ROOM_PENDING'));
  f.sample(c, moved);
  const next = f.bind('room', 'speaker', { intent: 6, context: newContext });
  assert.equal(next.paperId, 'p2'); assert.equal(next.breakoutRoomId, 'r2');
});
test('Stop fences pending auto-discovery and reconnect requires a new sample', () => {
  const f = setup(), c = f.mapped();
  assert.throws(() => f.bind('room', 'speaker'), code('ROOM_PENDING'));
  f.hub.cancel({ clientId: 'room', intent: 2 }); f.sample(c);
  assert.throws(() => f.bind('room', 'speaker'), code('SUPERSEDED'));
  assert.throws(() => f.bind('room', 'speaker', { intent: 3 }), code('ROOM_PENDING'));
  f.sample(c); assert.equal(f.bind('room', 'speaker', { intent: 4 }).paperId, 'p1');
});

test('count-only channel rejects names, rosters and malformed counts; stale and replayed samples cannot renew attendance', () => {
  const f = setup(), c = f.bind('talk', 'session', { eventId: 'talk' });
  const view = () => { const e = { id: 'talk', type: 'keynote', status: 'live', links: { zoom: 'url' }, live: { activeSpeakerName: 'Old Name' } }; f.hub.decorate(e); return e; };
  f.sample(c, { total: 3 });
  assert.equal(view().headcounts.zoom, 3); assert.equal(view().live, undefined);
  assert.deepEqual(Object.keys(f.hub.snapshots.get('talk')).sort(), ['at', 'order', 'token', 'total']);
  for (const value of [{ total: -1 }, { total: 1.5 }, { total: '3' }, { total: 5001 }, { total: 2, name: 'Alice' }, { rooms: [], lobby: ['host'] }, {}]) {
    assert.throws(() => f.sample(c, value), code('INPUT'));
    assert.equal(view().headcounts.zoom, 3);
  }
  assert.throws(() => f.send(c, 'speaker', { users: [{ id: 'a', name: 'Alice' }], ageMs: 0 }), code('SCOPE'));
  f.advance(20001); f.send(c, 'heartbeat'); assert.equal(view().headcounts.available, false);
  f.sample(c, { total: 5 }); assert.equal(view().headcounts.zoom, 5);
  const state = f.hub.sessions.get(c.token), packet = { context: c.context, type: 'attendance', seq: state.seq, sampleTicket: state.sampleTicket.id, snapshot: { total: 5 } };
  f.advance(20001); f.hub.receive(c.token, packet); assert.equal(view().headcounts.available, false);
  f.sample(c, { total: 0 }); assert.equal(view().headcounts.available, true); assert.equal(view().headcounts.zoom, 0);
});

test('Webinar numeric join links resolve meeting IDs, registration tokens need an explicit ID', () => {
  const f = setup();
  for (const url of ['https://zoom.us/w/123456789?tk=x', 'https://zoom.us/s/123456789', 'https://zoom.us/wc/join/123456789', 'https://zoom.us/j/123456789']) {
    f.options.events = () => [{ ...event, id: 'talk', type: 'oral', links: { zoom: url } }];
    const h = new ObserverHub(f.options);
    assert.equal(h.catalog()[0].meetingId, '123456789');
    assert.equal(h.bind(f.body('talk', 'session', { eventId: 'talk' })).mode, 'session');
  }
  f.options.events = () => [{ ...event, id: 'talk', type: 'oral', links: { zoom: 'https://zoom.us/webinar/register/WN_opaque' } }];
  const h = new ObserverHub(f.options);
  assert.throws(() => h.bind(f.body('talk', 'session', { eventId: 'talk' })), code('MEETING'));
});

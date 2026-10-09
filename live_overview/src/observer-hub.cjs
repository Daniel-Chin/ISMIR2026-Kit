'use strict';
const crypto = require('crypto');
const { required, signature, roomInstanceKey } = require('./observer-core.cjs');
class ObserverError extends Error {
  constructor(code, message, status = 409) { super(message); Object.assign(this, { code, status }); }
}
function fail(code, message, status) { throw new ObserverError(code, message, status); }
const clone = value => JSON.parse(JSON.stringify(value));
function meetingNumber(event) {
  const explicit = event.zoomWebinarId || event.zoomMeetingId || event.meetingId;
  if (explicit) return String(explicit).replace(/\s/g, '');
  try { return new URL(event.links.zoom).pathname.match(/\/(?:j|s|w|wc\/join)\/(\d+)(?:\/|$)/)?.[1] || ''; } catch { return ''; }
}
class ObserverHub {
  constructor({ events, live, store, changed, now = Date.now, leaseMs = 20000, countMs = 20000, speakerMs = 10000 }) {
    Object.assign(this, { events, live, store, changed, now, leaseMs, countMs, speakerMs });
    this.sessions = new Map(); this.clients = new Map(); this.slots = new Map(); this.snapshots = new Map();
    this.claims = new Map(); this.roomIdentities = new Map(); this.sampleOrder = 0;
  }
  event(id) {
    const e = this.events().find(e => e.id === id && e.links?.zoom);
    if (!e || !this.live(e)) fail('NOT_LIVE', 'This session is not live. Select a live session.', 422);
    return e;
  }
  config(id) {
    const cfg = this.store()[id] || { revision: 0, meetingUUID: '', mapping: {} };
    // v0.9.4 manual aliases are no longer authoritative. Keep paper mappings only.
    return { revision: cfg.revision, meetingUUID: cfg.meetingUUID, mapping: cfg.mapping };
  }
  catalog() {
    return this.events().filter(e => this.live(e) && e.links?.zoom).map(e => ({
      id: e.id, title: e.title, type: e.type, meetingId: meetingNumber(e),
      papers: e.type === 'poster' ? (e.papers || []).map(p => ({ id: p.id, displayId: p.displayId, title: p.title })) : [],
      config: clone(this.config(e.id)),
    }));
  }
  checkContext(event, ctx, mode) {
    if (!ctx || !['host', 'cohost'].includes(ctx.role)) fail('ROLE', 'Host or Co-host is required.', 403);
    required(ctx.meetingUUID, 'Meeting UUID'); required(ctx.participantUUID, 'Participant UUID');
    if (!meetingNumber(event) || ctx.meetingId !== meetingNumber(event)) fail('MEETING', 'Wrong Zoom meeting for the selected session. Check the schedule Zoom link.', 422);
    if (mode === 'speaker') {
      if (event.type !== 'poster' || !ctx.roomUUID) fail('ROOM', 'Enter a poster breakout room to monitor speakers.', 422);
      const cfg = this.config(event.id);
      if (cfg.meetingUUID !== ctx.meetingUUID) fail('MAPPING', 'Waiting for central attendance in this meeting instance. The Host must connect in the main room.', 422);
    } else if (ctx.roomUUID) fail('ROOM', 'Attendance and session observers must stay in the main Zoom room.', 422);
    if (mode === 'attendance' && event.type !== 'poster') fail('MODE', 'Use Session mode for a non-poster meeting.', 422);
    if (mode === 'session' && event.type === 'poster') fail('MODE', 'Use Central attendance or Room speakers for posters.', 422);
    if (!['attendance', 'speaker', 'session'].includes(mode)) fail('MODE', 'Invalid observer mode.', 422);
  }
  resolveRoom(client, event, ctx) {
    const claimKey = crypto.createHash('sha256').update(JSON.stringify([event.id, signature(ctx)])).digest('hex');
    let claim = this.claims.get(client);
    if (!claim || claim.key !== claimKey) {
      claim = { key: claimKey, afterOrder: this.sampleOrder, at: this.now() };
      this.claims.set(client, claim);
    }
    claim.at = this.now();
    const snap = this.attendance(event.id);
    // A ticket issued before the room claim may describe the previous room,
    // even if its response arrives later. Never use it to establish a binding.
    if (!snap || snap.order <= claim.afterOrder) fail('ROOM_PENDING', 'Identifying your room automatically. Waiting for a fresh participant list from the central Host.', 422);
    const roomId = snap.membership.get(ctx.participantUUID);
    if (!roomId) fail('ROOM_PENDING', 'Waiting for Zoom to show you as joined in a breakout room. The central Host must keep attendance connected.', 422);
    const identityKey = JSON.stringify([event.id, ctx.meetingUUID, roomInstanceKey(ctx.roomUUID)]);
    const known = this.roomIdentities.get(identityKey);
    if (known && known.roomId !== roomId) fail('ROOM_PENDING', 'Zoom room context and participant list are still changing. Retrying automatically.', 422);
    if (!this.config(event.id).mapping[roomId]) fail('MAPPING', 'Your room was detected. Waiting for the central Host to map this room to a paper.', 422);
    return { roomId, identityKey, order: snap.order, name: snap.rooms.find(r => r.roomUUID === roomId)?.name || roomId };
  }
  key(eventId, mode, ctx) { return JSON.stringify([eventId, mode, mode === 'speaker' ? ctx.roomUUID : 'main']); }
  connected(s) { return Boolean(s && !s.revoked && this.slots.get(s.slot) === s.token && this.now() - s.lastSeen <= this.leaseMs); }
  revoke(s, code = 'REPLACED') {
    if (!s) return;
    s.revoked = code; s.speakers = null;
    if (this.slots.get(s.slot) === s.token) this.slots.delete(s.slot);
    if (this.snapshots.get(s.eventId)?.token === s.token) this.snapshots.delete(s.eventId);
  }
  bind(body) {
    if (body.protocol !== 2) fail('UPGRADE', 'Reload the Observer page; this server requires Observer v2.', 426);
    const client = required(body.clientId, 'Observer client ID');
    const intent = Number(body.intent);
    if (!Number.isSafeInteger(intent) || intent < 1) fail('INPUT', 'Invalid connection generation.', 400);
    const prior = this.clients.get(client);
    if (prior && intent < prior.intent) fail('SUPERSEDED', 'A newer connection action already replaced this request.');
    const fingerprint = crypto.createHash('sha256').update(JSON.stringify([body.eventId, body.mode, body.context, body.takeover === true])).digest('hex');
    if (prior && intent === prior.intent) {
      if (fingerprint !== prior.fingerprint) fail('SUPERSEDED', 'Connection generation was reused with different settings.');
      if (prior.error) throw prior.error;
      const old = this.sessions.get(prior.token);
      if (old?.revoked) fail(old.revoked, 'This observer was replaced. Use Connect explicitly to resume.');
      if (old) return this.bound(old);
    }
    // Record intent before validation. Delayed requests can never roll back a newer user action.
    const record = { intent, fingerprint, at: this.now() }; this.clients.set(client, record);
    try {
      const event = this.event(body.eventId), mode = body.mode;
      this.checkContext(event, body.context, mode);
      const resolved = mode === 'speaker' ? this.resolveRoom(client, event, body.context) : null;
      const breakoutRoomId = resolved?.roomId || '';
      if (mode !== 'speaker') this.claims.delete(client);
      const ctx = clone(body.context), slot = this.key(event.id, mode, { roomUUID: breakoutRoomId });
      const incumbent = this.sessions.get(this.slots.get(slot));
      if (this.connected(incumbent) && incumbent.client !== client && !body.takeover) fail('OCCUPIED', 'Another observer is connected here. Use Take over only when replacing it.');
      // Validate fully before releasing a working assignment.
      for (const s of this.sessions.values()) if (s.client === client && !s.revoked) this.revoke(s);
      if (incumbent) this.revoke(incumbent);
      if (mode !== 'speaker') {
        const cfg = this.config(event.id);
        if (cfg.meetingUUID !== ctx.meetingUUID) {
          for (const s of this.sessions.values()) if (s.eventId === event.id) this.revoke(s, 'MAPPING_CHANGED');
          for (const [key, value] of this.roomIdentities) if (value.eventId === event.id) this.roomIdentities.delete(key);
          this.store()[event.id] = { revision: cfg.revision + 1, meetingUUID: ctx.meetingUUID, mapping: {} };
        }
      }
      const cfg = this.config(event.id);
      const s = { token: crypto.randomBytes(32).toString('base64url'), client, slot, eventId: event.id, mode, ctx, breakoutRoomId,
        roomName: resolved?.name || '', proofOrder: resolved?.order || 0,
        mappingRevision: cfg.revision, paperId: mode === 'speaker' ? cfg.mapping[breakoutRoomId] : '',
        seq: 0, lastSeen: this.now(), speakers: null, lastPacket: null };
      if (resolved) this.roomIdentities.set(resolved.identityKey, { eventId: event.id, roomId: breakoutRoomId, at: this.now() });
      this.claims.delete(client); // Any later rebind needs a new roster; retries use the saved token.
      this.sessions.set(s.token, s); this.slots.set(slot, s.token); record.token = s.token;
      this.changed(); this.prune(); return this.bound(s);
    } catch (e) { record.error = e; throw e; }
  }
  cancel(body) {
    const client = required(body.clientId, 'Observer client ID'), intent = Number(body.intent);
    if (!Number.isSafeInteger(intent) || intent < 1) fail('INPUT', 'Invalid generation.', 400);
    const prior = this.clients.get(client);
    if (prior && intent < prior.intent) fail('SUPERSEDED', 'Newer action already applied.');
    this.claims.delete(client);
    this.clients.set(client, { intent, at: this.now(), error: new ObserverError('RELEASED', 'Observer stopped.') });
    for (const s of this.sessions.values()) if (s.client === client && !s.revoked) this.revoke(s, 'RELEASED');
    this.changed(); return { ok: true };
  }
  bound(s) {
    return { ok: true, token: s.token, eventId: s.eventId, mode: s.mode, paperId: s.paperId, breakoutRoomId: s.breakoutRoomId, roomName: s.roomName,
      context: s.ctx, mappingRevision: s.mappingRevision, config: clone(this.config(s.eventId)),
      leaseMs: this.leaseMs, speakerMs: this.speakerMs };
  }
  session(token) {
    const s = this.sessions.get(token);
    if (!s) fail('SESSION_LOST', 'Server session expired or restarted. Reconnecting.', 401);
    if (s.revoked || this.slots.get(s.slot) !== token) fail(s.revoked || 'REPLACED', 'This observer has been replaced; it cannot reconnect automatically.');
    this.event(s.eventId);
    if (s.mode === 'speaker') {
      const cfg = this.config(s.eventId);
      if (cfg.meetingUUID !== s.ctx.meetingUUID || cfg.revision !== s.mappingRevision) fail('MAPPING_CHANGED', 'Room mapping changed. Reconnecting to the corrected paper.');
    }
    return s;
  }
  receive(token, body) {
    const s = this.session(token);
    // Fixed binding, context and sequence are enforced on every packet, including retries.
    if (!body.context || signature(body.context) !== signature(s.ctx)) fail('CONTEXT', 'Zoom role or room changed; reconnect before sending data.', 422);
    const seq = Number(body.seq);
    if (!Number.isSafeInteger(seq) || seq < 1) fail('INPUT', 'Invalid sequence.', 400);
    if (seq <= s.seq) return { ...this.bound(s), duplicate: true }; // Never refresh freshness on replay.
    const type = body.type;
    if (['speaker', 'attendance'].includes(type) && (!s.sampleTicket || body.sampleTicket !== s.sampleTicket.id || this.now() - s.sampleTicket.at > 12000)) {
      fail('OLD_SAMPLE', 'Sample window expired. Collect a fresh Zoom snapshot.', 422);
    }
    let data;
    if (type === 'attendance') {
      if (s.mode === 'speaker') fail('SCOPE', 'Room speaker observers cannot publish counts.', 403);
      data = this.validateSnapshot(body.snapshot, s);
    } else if (type === 'speaker') {
      if (s.mode !== 'speaker') fail('SCOPE', 'Only poster room observers can publish speakers.', 403);
      if (!Array.isArray(body.users) || body.users.length > 100) fail('INPUT', 'Invalid speakers.', 400);
      const age = Number(body.ageMs);
      if (!Number.isFinite(age) || age < 0 || age > this.speakerMs) fail('OLD_SAMPLE', 'Speaker sample expired. Waiting for a new Zoom event.', 422);
      data = [...new Map(body.users.map(u => [required(u.id, 'Speaker UUID'), { id: u.id, name: required(u.name, 'Speaker name').slice(0, 120) }])).values()];
    } else if (type === 'mapping') {
      if (s.mode !== 'attendance') fail('SCOPE', 'Only central attendance can correct room mapping.', 403);
      data = this.validateMapping(body, s);
    } else if (!['heartbeat', 'release', 'unavailable'].includes(type)) fail('INPUT', 'Unknown observer event.', 400);
    s.seq = seq; s.lastSeen = this.now();
    if (type === 'heartbeat') s.sampleTicket = { id: crypto.randomBytes(12).toString('hex'), at: this.now(), order: ++this.sampleOrder };
    if (type === 'release') this.revoke(s, 'RELEASED');
    if (type === 'unavailable') {
      if (s.mode !== 'speaker') this.snapshots.delete(s.eventId);
      s.speakers = null;
    }
    if (type === 'attendance') {
      this.snapshots.set(s.eventId, { ...data, at: this.now(), token, order: s.sampleTicket.order });
      // Catch a missed SDK room-change event and fence speech from the old room.
      for (const other of this.sessions.values()) {
        if (other.eventId === s.eventId && other.mode === 'speaker' && !other.revoked &&
            s.sampleTicket.order > other.proofOrder && data.membership.get(other.ctx.participantUUID) !== other.breakoutRoomId) {
          this.revoke(other, 'CONTEXT');
          this.claims.delete(other.client);
        }
      }
    }
    if (type === 'speaker') s.speakers = { users: data, at: this.now() - body.ageMs };
    if (type === 'mapping') {
      const cfg = this.config(s.eventId);
      this.store()[s.eventId] = { ...cfg, revision: cfg.revision + 1, ...data };
      // All room writers are fenced, even when only another room was changed.
      for (const other of this.sessions.values()) if (other.eventId === s.eventId && other.mode === 'speaker') this.revoke(other, 'MAPPING_CHANGED');
      s.mappingRevision = cfg.revision + 1;
    }
    this.changed();
    return { ...this.bound(s), sampleTicket: s.sampleTicket?.id, rooms: s.mode === 'attendance' ? this.roomStatus(s.eventId) : undefined };
  }
  validateSnapshot(raw, s) {
    if (s.mode === 'session') {
      if (!raw || Object.keys(raw).length !== 1 || !Number.isSafeInteger(raw.total) || raw.total < 0 || raw.total > 5000) {
        fail('INPUT', 'Expected a count-only snapshot. Reload the Observer App if it is outdated.', 400);
      }
      return { total: raw.total }; // No participant roster is uploaded or retained.
    }
    if (!raw || !Array.isArray(raw.rooms) || !Array.isArray(raw.lobby) || raw.rooms.length > 100) fail('INPUT', 'Incomplete attendance snapshot.', 400);
    const people = new Set(), roomIds = new Set(), membership = new Map();
    function members(list, roomId) {
      if (!Array.isArray(list) || list.length > 5000) fail('INPUT', 'Invalid member list.', 400);
      return list.map(id => {
        required(id, 'Participant UUID');
        if (people.has(id)) fail('TRANSITION', 'Duplicate participant across rooms. Retry the snapshot.', 422);
        people.add(id); membership.set(id, roomId); return id;
      });
    }
    const rooms = raw.rooms.map(r => {
      required(r.roomUUID, 'Room UUID');
      if (roomIds.has(r.roomUUID)) fail('INPUT', 'Duplicate room.', 400);
      roomIds.add(r.roomUUID);
      return { roomUUID: r.roomUUID, name: String(r.name || r.roomUUID).slice(0, 160), count: members(r.members, r.roomUUID).length };
    });
    const lobby = members(raw.lobby, '').length;
    if (people.size > 5000) fail('INPUT', 'Too many participants.', 400);
    return { rooms, lobby, total: people.size, membership }; // Private memory only; never serialized or exposed in roomStatus.
  }
  validateMapping(body, s) {
    const cfg = this.config(s.eventId), snap = this.snapshots.get(s.eventId);
    if (body.revision !== cfg.revision) fail('MAPPING_CHANGED', 'Mapping changed elsewhere. Reload the table before saving.');
    if (!snap || snap.token !== s.token || this.now() - snap.at > this.countMs) fail('SNAPSHOT', 'Refresh the Zoom room list before saving mappings.', 422);
    if (!Array.isArray(body.mapping) || body.mapping.length > 100) fail('INPUT', 'Invalid room mapping.', 400);
    const rooms = new Set(snap.rooms.map(r => r.roomUUID));
    const papers = new Set((this.event(s.eventId).papers || []).map(p => p.id));
    const seen = new Set(), result = Object.create(null);
    for (const pair of body.mapping) {
      if (!rooms.has(pair.roomUUID) || !papers.has(pair.paperId) || result[pair.roomUUID] || seen.has(pair.paperId)) fail('MAPPING', 'Map each room and paper at most once, using the current Zoom room list.', 422);
      result[pair.roomUUID] = pair.paperId; seen.add(pair.paperId);
    }
    return { mapping: result };
  }
  roomStatus(eventId) {
    const snap = this.snapshots.get(eventId), cfg = this.config(eventId);
    return (snap?.rooms || []).map(r => {
      const s = this.sessions.get(this.slots.get(this.key(eventId, 'speaker', { roomUUID: r.roomUUID })));
      return { ...r, paperId: cfg.mapping[r.roomUUID] || '', speakerConnected: this.connected(s) };
    });
  }
  attendance(eventId) {
    const snap = this.snapshots.get(eventId), owner = snap && this.sessions.get(snap.token);
    return snap && this.connected(owner) && this.now() - snap.at <= this.countMs ? snap : null;
  }
  speaker(eventId, roomUUID, mode = 'speaker') {
    const s = this.sessions.get(this.slots.get(this.key(eventId, mode, { roomUUID })));
    const connected = this.connected(s);
    const fresh = connected && s.speakers && this.now() - s.speakers.at <= this.speakerMs;
    const users = fresh ? s.speakers.users : [];
    return { observerConnected: connected, observerStale: Boolean(s && !connected),
      activeSpeakerTalking: users.length > 0, activeSpeakerName: users.map(u => u.name).join(', '),
      activeSpeakers: users.map(u => ({ name: u.name })), speakerState: !connected ? 'disconnected' : !fresh ? 'unknown' : users.length ? 'recent' : 'quiet',
      presenterTalking: false, audienceTalking: false };
  }
  decorate(event) {
    if (event.status !== 'live') return;
    const snap = this.attendance(event.id);
    const count = n => ({ zoom: n ?? 0, available: n != null, partial: false });
    if (event.type === 'poster') {
      const mapping = this.config(event.id).mapping;
      event.headcounts = { ...count(snap?.total), lobbyZoom: snap?.lobby ?? 0 };
      event.attendanceSource = 'central_zoom_snapshot';
      for (const p of event.papers || []) {
        const room = Object.keys(mapping).find(r => mapping[r] === p.id);
        p.headcounts = count(room ? snap?.rooms.find(r => r.roomUUID === room)?.count : undefined);
        p.live = this.speaker(event.id, room || '__unmapped__');
      }
    } else if (event.links?.zoom) {
      event.headcounts = count(snap?.total);
      delete event.live;
    }
  }
  prune() {
    // Tombstones outlive any normal delayed request; active connections are never removed here.
    const cutoff = this.now() - 24 * 60 * 60 * 1000;
    for (const [key, s] of this.sessions) if (s.lastSeen < cutoff) { this.revoke(s); this.sessions.delete(key); }
    for (const [key, c] of this.claims) if (c.at < cutoff) this.claims.delete(key);
    for (const [key, r] of this.roomIdentities) if (r.at < cutoff) this.roomIdentities.delete(key);
    for (const [key, c] of this.clients) if (c.at < cutoff) this.clients.delete(key);
  }
}
module.exports = { ObserverHub, ObserverError, meetingNumber };

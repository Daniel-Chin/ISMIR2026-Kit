'use strict';
/* Observer v2: one serialized loop, immutable bindings, no offline telemetry queue. */
const $ = id => document.getElementById(id);
const Core = window.ObserverCore;
const appProfile = /^v[1-9]\d{0,3}$/.test(window.ISMIR_ZOOM_PROFILE || '') ? window.ISMIR_ZOOM_PROFILE : '';
const key = appProfile || new URLSearchParams(location.hash.slice(1)).get('key') || '';
let appAuthConfig = null;
const clientId = crypto.randomUUID(); // Each webview owns its own connection.
const TICK_MS = 3000, SPEAKER_MS = 10000;
const contextApis = ['getRunningContext', 'getMeetingContext', 'getMeetingUUID', 'getUserContext', 'getMeetingParticipants'];
const contextEvents = ['onMyUserContextChange', 'onRunningContextChange', 'onBreakoutRoomChange', 'onParticipantChange'];
function requiredApis() {
  return [...contextApis, ...(appProfile ? ['getAppContext'] : []), ...(desired?.mode === 'attendance' ? ['getBreakoutRoomList'] : desired?.mode === 'speaker' ? ['onActiveSpeakerChange'] : [])];
}
function requestedApis() {
  return [...requiredApis(), ...contextEvents.filter(name => desired?.mode !== 'session' || name !== 'onBreakoutRoomChange'), ...(desired?.mode === 'attendance' ? ['onMeetingConfigChanged'] : desired?.mode === 'speaker' ? ['onMyMediaChange'] : [])];
}
let events = [], desired = null, binding = null, bindRequest = null, generation = 0, intent = 0, seq = 0;
let busy = false, timer, needsConfig = true, listeners = new Set(), sdkConfig, context = null;
let confirmedContext = false, members = new Map(), lastSpeaker = null, speakerRevision = 0, sentSpeakerRevision = -1;
let catalogAt = 0, lastGoodAt = 0, failures = 0, stoppedByReplacement = false;
let rooms = [], mappingDirty = false, mappingKey = '', mappingDraft = [], pendingMapping = null;
let lastSdkTimestamp = 0, roleAtConfig = '', contextEpoch = 0, transitionPending = false;
function chip(id, message, ok = false) { $(id).textContent = message; $(id).className = `observer-chip ${ok ? 'ok' : 'warn'}`; }
function error(message, code = 'SDK') { return Object.assign(new Error(message), { code }); }
function sdkError(name, cause) {
  const message = cause?.message || String(cause || 'Zoom API unavailable.');
  return Object.assign(error(`Zoom ${name}: ${message}`, 'SDK'), { sdkApi: name, zoomCode: cause?.code });
}
function invalidateSpeaker() {
  lastSpeaker = null; members = new Map(); speakerRevision++; sentSpeakerRevision = -1;
  chip('speaker-status', 'Waiting for a fresh speaker signal');
}
function checkpoint(g) { if (g !== generation) throw error('Operation superseded.', 'CANCELLED'); }
async function request(path, body, token) {
  const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 8000);
  try {
    let identityHeaders = {};
    if (appProfile) {
      if (!sdkConfig) {
        appAuthConfig ||= sdk('config', { version: '0.16', capabilities: ['getAppContext'] }).catch(e => { appAuthConfig = null; throw e; });
        await appAuthConfig;
      }
      const signed = await sdk('getAppContext');
      if (!signed?.context) throw error('Zoom identity unavailable. Check getAppContext permission and reopen the App.', 'APP_AUTH');
      identityHeaders = { 'X-Zoom-App-Context': signed.context };
    }
    const res = await fetch(appProfile ? `/zoom/app/${appProfile}${path}` : path, { method: 'POST', cache: 'no-store', signal: controller.signal,
      headers: { 'Content-Type': 'application/json', ...identityHeaders, ...(token ? { Authorization: `Bearer ${token}` } : appProfile ? {} : { 'X-Observer-Key': key }) },
      body: JSON.stringify(body) });
    const data = await res.json();
    if (!res.ok || data.ok === false) throw error(data.error || `HTTP ${res.status}`, data.code || 'HTTP');
    return data;
  } catch (e) {
    if (e.name === 'AbortError' || e instanceof TypeError || e instanceof SyntaxError) throw error('Connection interrupted; retrying automatically.', 'NETWORK');
    throw e;
  }
  finally { clearTimeout(timeout); }
}
async function sdk(name, arg) {
  if (!window.zoomSdk || typeof zoomSdk[name] !== 'function') throw sdkError(name, 'Open this page inside the Zoom App on a supported desktop client.');
  let timeout;
  try { return await Promise.race([zoomSdk[name](arg), new Promise((_, reject) => { timeout = setTimeout(() => reject(error(`Zoom ${name} timed out; retrying.`, 'SDK')), 6500); })]); }
  catch (e) { throw sdkError(name, e); }
  finally { clearTimeout(timeout); }
}
function register() {
  const on = (name, callback) => {
    if (!requestedApis().includes(name) || sdkConfig.unsupportedApis?.includes(name) || listeners.has(name) || typeof zoomSdk[name] !== 'function') return;
    try { zoomSdk[name](callback); listeners.add(name); }
    catch (e) { if (name === 'onActiveSpeakerChange' && desired?.mode === 'speaker') throw sdkError(name, e); }
  };
  on('onActiveSpeakerChange', event => {
    if (!confirmedContext || !binding || desired?.mode !== 'speaker' || !Array.isArray(event.users)) return;
    const ts = Number(event.timestamp);
    if (Number.isFinite(ts) && ts < lastSdkTimestamp) return;
    lastSdkTimestamp = Number.isFinite(ts) ? ts : lastSdkTimestamp;
    // Ignore stale callback delivery across room changes; Zoom timestamps are seconds.
    if (ts && ts * 1000 < contextEpoch - 1500) return;
    const users = event.users.filter(u => members.has(u.participantUUID)).map(u => ({ id: u.participantUUID,
      name: String(u.screenName || members.get(u.participantUUID)?.screenName || 'Zoom participant').slice(0, 120) }));
    if (event.users.length && !users.length) return; // Not a verified member of this room.
    lastSpeaker = { users, at: performance.now() }; speakerRevision++;
    chip('speaker-status', users.length ? `Recent speaker: ${users.map(u => u.name).join(', ')}` : 'No active speakers reported', true);
    wake(400);
  });
  on('onMyMediaChange', event => {
    if (desired?.mode !== 'speaker' || event.media?.audio?.state !== false || !lastSpeaker || !context || !lastSpeaker.users.some(u => u.id === context.participantUUID)) return;
    lastSpeaker = { users: lastSpeaker.users.filter(u => u.id !== context.participantUUID), at: lastSpeaker.at };
    speakerRevision++; wake(400);
  });
  const contextChanged = () => {
    confirmedContext = false; transitionPending = true; needsConfig = true;
    contextEpoch = Date.now(); lastSdkTimestamp = 0; invalidateSpeaker();
    generation++; // Invalidates every in-flight SDK read and upload response.
    const old = binding; binding = null; bindRequest = null;
    if (old) release(old);
    chip('conference-sync-status', 'Zoom context changed · checking role and room');
    wake(500);
  };
  on('onBreakoutRoomChange', contextChanged);
  on('onRunningContextChange', contextChanged);
  on('onMyUserContextChange', contextChanged);
  on('onParticipantChange', () => wake(500));
  on('onMeetingConfigChanged', () => wake(500));
}
async function configure(g) {
  const result = await sdk('config', { version: '0.16', popoutSize: { width: 700, height: 850 }, capabilities: requestedApis() });
  checkpoint(g); sdkConfig = result;
  register();
  const unsupported = requiredApis().filter(name => result.unsupportedApis?.includes(name));
  if (unsupported.length) throw sdkError(unsupported.join(', '), 'Reported unsupported by Zoom config. Check Marketplace → Surface → Zoom Apps SDK → Add APIs, app authorization, role and client version.');
  needsConfig = false;
}
async function zoomContext(g) {
  if (needsConfig) {
    await configure(g);
  }
  const user = await sdk('getUserContext'); checkpoint(g);
  const roleSignature = `${user.role}:${user.status}`;
  if (roleAtConfig && roleSignature !== roleAtConfig) {
    await configure(g);
  }
  roleAtConfig = roleSignature;
  const [uuid, meeting, running] = await Promise.all([sdk('getMeetingUUID'), sdk('getMeetingContext'), sdk('getRunningContext')]);
  checkpoint(g);
  if (!['inMeeting', 'inWebinar'].includes(running.context || running.runningContext)) throw error('Join the scheduled Zoom meeting first.', 'ROOM');
  const ctx = Core.context(uuid, user, meeting);
  if (transitionPending && context && Core.signature(ctx) === Core.signature(context)) {
    transitionPending = false;
    throw error('Waiting for Zoom to finish updating the room and role.', 'ROOM');
  }
  transitionPending = false;
  if (context && Core.signature(ctx) !== Core.signature(context)) {
    const old = binding; binding = null; bindRequest = null; if (old) release(old);
    invalidateSpeaker(); contextEpoch = Date.now(); lastSdkTimestamp = 0;
  }
  context = ctx; confirmedContext = true;
  chip('zoom-status', `${ctx.role === 'host' ? 'Host' : 'Co-host'} · app authorized`, true);
  chip('room-status', ctx.roomUUID ? (binding?.roomName || 'Breakout room · identifying automatically') : (running.context || running.runningContext) === 'inWebinar' ? 'Webinar' : 'Main meeting room', true);
  return ctx;
}
async function loadCatalog(g) {
  const data = await request('/api/observer/catalog', {}); checkpoint(g);
  events = data.events; catalogAt = Date.now();
  const previous = $('poster-id').value;
  $('poster-id').replaceChildren(new Option('Select a live Zoom session…', ''));
  for (const e of events) $('poster-id').add(new Option(e.title, e.id));
  $('poster-id').value = events.some(e => e.id === previous) ? previous : '';
  $('poster-id').disabled = !key;
  controls();
}
function selectedMode() {
  const e = events.find(e => e.id === $('poster-id').value);
  return e?.type === 'poster' ? $('observer-mode').value : 'session';
}
function controls() {
  const event = events.find(e => e.id === $('poster-id').value);
  $('mode-field').hidden = event?.type !== 'poster';
  $('speaker-status-row').hidden = (desired?.mode || selectedMode()) === 'session';
  $('target-help').textContent = event?.type === 'poster'
    ? 'The selected session must match your Zoom meeting. Breakout observers identify their room and paper automatically from the central Host’s participant list.'
    : 'Attendance only. Open this App as an authorized Host or Co-host in the matching webinar, select this session and connect. Keep the App open; attendee names are not uploaded.';
  const changed = desired && (desired.eventId !== event?.id || desired.mode !== selectedMode());
  $('connect-btn').disabled = !key || !event || Boolean(desired && !changed && !stoppedByReplacement);
  $('connect-btn').textContent = changed ? 'Switch session / mode' : binding ? 'Connected' : desired ? 'Connecting…' : 'Connect observer';
  $('disconnect-btn').disabled = !desired && !binding;
  $('participants-btn').disabled = !desired;
  $('mapping-panel').hidden = desired?.mode !== 'attendance';
  $('target-summary').textContent = binding
    ? `Connected: ${events.find(e => e.id === binding.eventId)?.title || binding.eventId}${binding.paperId ? ` · ${binding.paperId} · ${events.find(e => e.id === binding.eventId)?.papers.find(p => p.id === binding.paperId)?.title || ''}` : binding.mode === 'attendance' ? ' · All-room attendance' : ''}`
    : desired ? 'Waiting for Zoom permissions, room mapping or network…' : 'Select a session and connect inside Zoom.';
  $('apply-mapping').disabled = !binding || !mappingDirty || Boolean(pendingMapping);
}
function wake(delay = TICK_MS) { clearTimeout(timer); timer = setTimeout(tick, delay); }
function release(old) {
  request('/observer/event', { context: old.context, seq: ++seq, type: 'release' }, old.token).catch(() => {});
}
async function send(type, fields, g) {
  const current = binding;
  if (!current) throw error('Connection is being re-established.', 'CANCELLED');
  const data = await request('/observer/event', { context: current.context, seq: ++seq, type, ...fields }, current.token);
  checkpoint(g);
  if (binding !== current) throw error('Connection superseded.', 'CANCELLED');
  binding.config = data.config; binding.mappingRevision = data.mappingRevision;
  lastGoodAt = Date.now();
  return data;
}
function renderMappings(status) {
  rooms = status || rooms;
  if (!binding || desired?.mode !== 'attendance') return;
  const cfg = binding.config;
  // A save may commit even if its response is lost. Reconcile against server truth
  // without overwriting a newer local edit made while that request was in flight.
  if (mappingDirty && sameMapping(mappingDraft.filter(p => p.paperId), Object.entries(cfg.mapping).map(([roomUUID, paperId]) => ({ roomUUID, paperId })))) mappingDirty = false;
  const nextKey = JSON.stringify([binding.eventId, cfg.revision, rooms.map(r => [r.roomUUID, r.name])]);
  if (nextKey === mappingKey || mappingDirty) {
    for (const row of $('room-mappings').children) {
      const room = rooms.find(r => r.roomUUID === row.dataset.room);
      if (room) row.querySelector('.mapping-status').textContent = `${room.count} joined · speaker observer ${room.speakerConnected ? 'connected' : 'offline'}`;
    }
    return;
  }
  mappingKey = nextKey;
  mappingDraft = rooms.map(r => ({ roomUUID: r.roomUUID, paperId: cfg.mapping[r.roomUUID] || '' }));
  $('room-mappings').replaceChildren();
  const event = events.find(e => e.id === binding.eventId);
  for (const room of rooms) {
    const row = document.createElement('div'); row.className = 'observer-field mapping-row'; row.dataset.room = room.roomUUID;
    const label = document.createElement('label'); label.textContent = `${room.name} · ${room.roomUUID.slice(0, 12)}`;
    const select = document.createElement('select'); select.id = `room-${rooms.indexOf(room)}`; label.htmlFor = select.id;
    select.add(new Option('Not mapped — excluded from paper counts', ''));
    for (const p of event?.papers || []) select.add(new Option(`${p.displayId || p.id} · ${p.title}`, p.id));
    select.value = cfg.mapping[room.roomUUID] || '';
    select.addEventListener('change', () => { mappingDraft.find(r => r.roomUUID === room.roomUUID).paperId = select.value; mappingDirty = true; controls(); });
    const state = document.createElement('p'); state.className = 'observer-help mapping-status';
    state.textContent = `${room.count} joined · speaker observer ${room.speakerConnected ? 'connected' : 'offline'}`;
    row.append(label, select, state); $('room-mappings').append(row);
  }
  $('mapping-help').textContent = rooms.length ? 'Review each room → paper mapping and Apply. Co-host observers identify their rooms automatically from the joined participant list; no UUID entry is needed.' : 'No breakout rooms returned. Create rooms in Zoom, then Refresh.';
  controls();
}
function sameMapping(a, b) {
  const normalized = rows => JSON.stringify(rows.map(r => [r.roomUUID, r.paperId]).sort());
  return normalized(a) === normalized(b);
}
async function collectCounts(ctx, g) {
  if (desired.mode === 'session') {
    const list = await sdk('getMeetingParticipants'); checkpoint(g);
    const ids = Core.ids(list.participants);
    if (!ids.includes(ctx.participantUUID)) throw error('Zoom participant list does not include this observer; checking permissions and retrying.', 'SDK');
    return { total: ids.length };
  }
  const first = await sdk('getBreakoutRoomList'); checkpoint(g);
  const main = await sdk('getMeetingParticipants'); checkpoint(g);
  const second = await sdk('getBreakoutRoomList'); checkpoint(g);
  const fingerprint = value => JSON.stringify(Core.rooms(value).map(r => [r.roomUUID, r.members.slice().sort()]).sort());
  if (fingerprint(first) !== fingerprint(second)) throw error('Participants are moving; refreshing the room snapshot.', 'TRANSITION');
  return Core.attendance(second, main);
}
async function verifyRoom(ctx, g) {
  const u = await sdk('getMeetingUUID'); checkpoint(g);
  if ((u.parentUUID || u.meetingUUID) !== ctx.meetingUUID || (u.parentUUID ? u.meetingUUID : '') !== ctx.roomUUID) {
    confirmedContext = false; throw error('Zoom room changed during collection. Reconnecting.', 'CONTEXT');
  }
}
async function tick() {
  if (busy) { wake(300); return; }
  busy = true; const g = generation;
  try {
    if (!key) { chip('conference-sync-status', 'Open from the configured Zoom App entry (access key missing)'); return; }
    if (!catalogAt || Date.now() - catalogAt > 15000) await loadCatalog(g);
    if (!desired || stoppedByReplacement) return;
    const ctx = await zoomContext(g);
    if (!binding) {
      bindRequest ||= { protocol: 2, clientId, intent: ++intent, eventId: desired.eventId, mode: desired.mode,
        context: ctx, takeover: Boolean(desired.takeover) };
      // A failed request may have committed. Retry the identical intent until its outcome is known.
      const result = await request('/api/observer/session', bindRequest); checkpoint(g);
      binding = result; bindRequest = null;
      if (binding.roomName) chip('room-status', binding.roomName, true); desired.takeover = false; seq = 0; invalidateSpeaker();
      mappingKey = ''; mappingDirty = false; pendingMapping = null;
    }
    const heartbeat = await send('heartbeat', {}, g);
    let sampleTicket = heartbeat.sampleTicket;
    if (desired.mode !== 'speaker') {
      const snapshot = await collectCounts(ctx, g); await verifyRoom(ctx, g);
      const counted = await send('attendance', { snapshot, sampleTicket }, g);
      const total = desired.mode === 'session' ? snapshot.total : snapshot.lobby.length + snapshot.rooms.reduce((n, r) => n + r.members.length, 0);
      chip('headcount-status', `${total} Zoom participants · hosts included`, true);
      renderMappings(counted.rooms);
      if (pendingMapping) {
        const action = pendingMapping; pendingMapping = null;
        try {
          await send('mapping', action, g);
          if (sameMapping(mappingDraft.filter(p => p.paperId), action.mapping)) mappingDirty = false;
          mappingKey = ''; renderMappings(rooms);
        } catch (e) {
          if (!['MAPPING', 'INPUT', 'SNAPSHOT'].includes(e.code)) throw e;
          $('mapping-help').textContent = e.message;
        }
      }
    }
    if (desired.mode === 'speaker') {
      const list = await sdk('getMeetingParticipants'); checkpoint(g);
      Core.ids(list.participants); // Missing permission is not an empty room.
      members = new Map(list.participants.map(p => [p.participantUUID, p]));
      await verifyRoom(ctx, g);
      if (lastSpeaker && performance.now() - lastSpeaker.at <= SPEAKER_MS && sentSpeakerRevision !== speakerRevision) {
        const revision = speakerRevision;
        const sample = lastSpeaker;
        await send('speaker', { users: sample.users.filter(u => members.has(u.id)), ageMs: performance.now() - sample.at, sampleTicket }, g);
        sentSpeakerRevision = revision;
      }
      if (!lastSpeaker || performance.now() - lastSpeaker.at > SPEAKER_MS) chip('speaker-status', 'Listening · no recent speaker signal', true);
      if (desired.mode === 'speaker') chip('headcount-status', 'Managed by central attendance', true);
    } else if (desired.mode === 'attendance') chip('speaker-status', 'Managed by observers inside each breakout room', true);
    failures = 0; chip('conference-sync-status', `Synced · ${new Date(lastGoodAt).toLocaleTimeString()}`, true);
  } catch (e) {
    if (e.code === 'CANCELLED' || g !== generation) return;
    failures++; confirmedContext = false; invalidateSpeaker();
    if (desired?.mode !== 'speaker') chip('headcount-status', 'No fresh count · checking connection and permissions');
    chip('conference-sync-status', e.message || 'Connection lost · retrying automatically');
    if (e.sdkApi) {
      chip('zoom-status', `SDK error · ${e.sdkApi}`);
      if (desired?.mode === 'attendance') $('mapping-help').textContent = `Room mapping is waiting for Zoom API access. ${e.message}`;
    }
    if (['REPLACED', 'RELEASED', 'SUPERSEDED', 'OCCUPIED'].includes(e.code)) {
      binding = null; bindRequest = null; stoppedByReplacement = true;
      $('takeover-btn').hidden = e.code !== 'OCCUPIED';
      chip('conference-sync-status', e.code === 'OCCUPIED' ? e.message : 'This observer was replaced or stopped. Click Connect to resume deliberately.');
    } else if (e.code === 'ROOM_PENDING') {
      binding = null; bindRequest = null; failures = 0; // Normal auto-discovery, poll without permission reconfiguration.
    } else if (['SESSION_LOST', 'MAPPING_CHANGED', 'CONTEXT'].includes(e.code)) {
      const old = binding; binding = null; bindRequest = null; if (old && e.code === 'CONTEXT') release(old);
      if (e.code === 'MAPPING_CHANGED') { mappingDirty = false; pendingMapping = null; mappingKey = ''; }
    } else if (['NOT_LIVE', 'MEETING', 'ROOM', 'MODE', 'MAPPING', 'ROLE', 'SDK'].includes(e.code) || !e.code) {
      const old = binding; binding = null; bindRequest = null; if (old) release(old);
      needsConfig = true;
      if (e.code === 'NOT_LIVE' || e.code === 'MEETING' || e.code === 'MODE') { desired = null; catalogAt = 0; }
    } else if (e.code === 'KEY' || e.code === 'UPGRADE') { desired = null; binding = null; }
    // Failed transport is never replayed as a fresh speech event or count sample.
    if (binding && !['NETWORK', 'HTTP', 'RATE', 'OLD_SAMPLE', 'TRANSITION'].includes(e.code)) {
      await send('unavailable', {}, g).catch(() => {});
    }
  } finally {
    busy = false; controls();
    wake(failures ? Math.min(15000, TICK_MS * 2 ** Math.min(failures - 1, 3)) + Math.random() * 500 : TICK_MS);
  }
}
function connect(takeover = false) {
  generation++; const old = binding; binding = null; bindRequest = null; if (old) release(old);
  desired = { eventId: $('poster-id').value, mode: selectedMode(), takeover };
  stoppedByReplacement = false; failures = 0; confirmedContext = false; needsConfig = true;
  mappingDirty = false; mappingKey = ''; pendingMapping = null; invalidateSpeaker();
  $('takeover-btn').hidden = true; controls(); wake(0);
}
$('connect-btn').addEventListener('click', () => connect());
$('takeover-btn').addEventListener('click', () => connect(true));
$('disconnect-btn').addEventListener('click', () => {
  generation++; desired = null; binding = null; bindRequest = null; confirmedContext = false; invalidateSpeaker();
  const g = generation;
  const cancellation = { protocol: 2, clientId, intent: ++intent };
  request('/api/observer/cancel', cancellation).then(() => { if (g === generation) chip('conference-sync-status', 'Stopped'); }).catch(() => { if (g === generation) chip('conference-sync-status', 'Stopped locally · server connection expires within 20 seconds'); });
  chip('conference-sync-status', 'Stopping…'); controls();
});
$('participants-btn').addEventListener('click', () => { needsConfig = true; catalogAt = 0; failures = 0; wake(0); });
$('poster-id').addEventListener('change', controls); $('observer-mode').addEventListener('change', controls);
$('apply-mapping').addEventListener('click', () => {
  if (!binding || !mappingDirty) return;
  pendingMapping = { revision: binding.config.revision, mapping: mappingDraft.filter(p => p.paperId).map(p => ({ ...p })) };
  controls(); wake(0);
});
$('discard-mapping').addEventListener('click', () => { mappingDirty = false; pendingMapping = null; mappingKey = ''; renderMappings(rooms); });
window.addEventListener('online', () => { failures = 0; needsConfig = true; invalidateSpeaker(); wake(0); });
window.addEventListener('offline', () => {
  confirmedContext = false; invalidateSpeaker(); chip('conference-sync-status', 'Offline · waiting to reconnect');
  if (desired?.mode !== 'speaker') chip('headcount-status', 'No fresh count · offline');
});
document.addEventListener('visibilitychange', () => { if (!document.hidden) { needsConfig = true; invalidateSpeaker(); wake(0); } });
setInterval(() => {
  if (binding && Date.now() - lastGoodAt > 12000) chip('conference-sync-status', 'No recent server acknowledgement · reconnecting');
}, 3000);
$('theme-toggle').addEventListener('click', () => {
  const dark = document.documentElement.dataset.theme !== 'dark'; document.documentElement.dataset.theme = dark ? 'dark' : 'light';
  $('theme-toggle').textContent = dark ? '☀️ Lights On' : '🌙 Lights Off';
  try { localStorage.setItem('ismirColorTheme', dark ? 'dark' : 'light'); } catch (_) {}
});
controls(); wake(0);

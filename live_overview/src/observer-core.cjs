/* Shared Zoom payload validation. No names are used as identity keys. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.ObserverCore = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  function required(value, label) {
    if (typeof value !== 'string' || !value.trim() || value.length > 200) throw new Error(`${label} is missing or invalid.`);
    return value.trim();
  }
  function ids(participants) {
    if (!Array.isArray(participants)) throw new Error('Zoom did not return a participant list. Ask the Host to run attendance.');
    return [...new Set(participants.map(p => required(p.participantUUID, 'Participant UUID')))];
  }
  function context(uuid, user, meeting) {
    const role = String(user.role || '').toLowerCase().replace(/[-_ ]/g, '');
    if (!['host', 'cohost'].includes(role)) throw new Error('Ask the Host to make you Co-host, then retry.');
    if (user.status !== 'authorized') throw new Error('Add and authorize this Zoom App first (Guest Mode is not supported).');
    const current = required(uuid.meetingUUID, 'Meeting UUID');
    const parent = String(uuid.parentUUID || '');
    return { meetingUUID: parent || current, roomUUID: parent ? current : '',
      meetingId: String(meeting.meetingID || '').replace(/\s/g, ''), role,
      participantUUID: required(user.participantUUID, 'Your participant UUID') };
  }
  function rooms(result) {
    if (!Array.isArray(result.rooms) || !['open', 'closed'].includes(result.state)) throw new Error('Zoom breakout list is incomplete; counts are unavailable.');
    const seenRooms = new Set(), seenPeople = new Set();
    return result.rooms.map(room => {
      const roomUUID = required(room.breakoutRoomId, 'Breakout room UUID');
      if (seenRooms.has(roomUUID)) throw new Error('Duplicate Zoom room UUID. Retry after the room transition.');
      seenRooms.add(roomUUID);
      let members = [];
      if (result.state === 'open') {
        if (!Array.isArray(room.participants)) throw new Error('Room member lists unavailable. Run attendance as the meeting Host.');
        if (room.participants.some(p => !['assigned', 'joined'].includes(p.participantStatus))) throw new Error('Zoom did not report joined/assigned status. Counts are unavailable.');
        members = ids(room.participants.filter(p => p.participantStatus === 'joined'));
      }
      for (const id of members) {
        if (seenPeople.has(id)) throw new Error('A participant is moving between rooms; retrying the snapshot.');
        seenPeople.add(id);
      }
      return { roomUUID, name: String(room.name || roomUUID).slice(0, 160), members };
    });
  }
  function attendance(breakouts, main) {
    const normalized = rooms(breakouts);
    const inRooms = new Set(normalized.flatMap(r => r.members));
    const mainIds = ids(main.participants);
    // Main-room APIs may include the meeting roster. Stable UUIDs avoid double counting.
    const lobby = mainIds.filter(id => !inRooms.has(id));
    return { rooms: normalized, lobby, total: new Set([...mainIds, ...inRooms]).size };
  }
  function signature(ctx) { return JSON.stringify([ctx.meetingUUID, ctx.roomUUID, ctx.meetingId, ctx.role, ctx.participantUUID]); }
  // UUID spelling can vary, but management IDs and meeting-instance UUIDs
  // remain separate namespaces. Never decode/convert one namespace to the other.
  function roomInstanceKey(value) {
    const text = required(value, 'Room observer UUID');
    return /^\{?[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\}?$/i.test(text)
      ? text.replace(/[{}]/g, '').toLowerCase() : text;
  }
  return { required, ids, context, rooms, attendance, signature, roomInstanceKey };
});

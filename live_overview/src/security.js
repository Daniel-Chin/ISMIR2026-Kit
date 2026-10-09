import crypto from 'node:crypto';
export const failure = (message, status = 400, code = 'INPUT') => Object.assign(new Error(message), { status, code });
export const hash = value => crypto.createHash('sha256').update(value).digest('hex');
export const random = () => crypto.randomBytes(32).toString('base64url');
export function equal(a, b) {
  const x = Buffer.from(String(a || '')), y = Buffer.from(String(b || ''));
  return x.length === y.length && crypto.timingSafeEqual(x, y);
}
export function encryptionKey(env) {
  if (!/^[a-f0-9]{64}$/i.test(env.TOKEN_ENCRYPTION_KEY || '')) throw failure('Configure TOKEN_ENCRYPTION_KEY (64 hex characters).', 503, 'CONFIG');
  return Buffer.from(env.TOKEN_ENCRYPTION_KEY, 'hex');
}
export function seal(value, env, scope) {
  const iv = crypto.randomBytes(12), cipher = crypto.createCipheriv('aes-256-gcm', encryptionKey(env), iv);
  cipher.setAAD(Buffer.from(scope));
  const data = Buffer.concat([cipher.update(Buffer.from(JSON.stringify(value), 'utf8')), cipher.final()]);
  return Buffer.concat([iv, cipher.getAuthTag(), data]).toString('base64');
}
export function unseal(value, env, scope) {
  const bytes = Buffer.from(value, 'base64'), cipher = crypto.createDecipheriv('aes-256-gcm', encryptionKey(env), bytes.subarray(0, 12));
  cipher.setAAD(Buffer.from(scope)); cipher.setAuthTag(bytes.subarray(12, 28));
  return JSON.parse(Buffer.concat([cipher.update(bytes.subarray(28)), cipher.final()]).toString());
}
export const headers = {
  'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer', 'X-Content-Type-Options': 'nosniff',
  'Content-Security-Policy': "default-src 'self'; base-uri 'self'; object-src 'none'; script-src 'self' 'unsafe-inline' https://appssdk.zoom.us; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self' data:; connect-src 'self' https: wss:; form-action 'self'",
};
export const json = (value, status = 200, extra = {}) => new Response(JSON.stringify(value), {status, headers: {...headers, 'Content-Type': 'application/json; charset=utf-8', ...extra}});
export const html = (value, status = 200, extra = {}) => new Response(value, {status, headers: {...headers, 'Content-Type': 'text/html; charset=utf-8', ...extra}});
export async function readBody(req, max = 600000) {
  if (Number(req.headers.get('content-length')) > max) throw failure('Request too large.', 413);
  if (!req.body) return '';
  const reader = req.body.getReader(), chunks = []; let size = 0;
  while (true) {
    const {done, value} = await reader.read(); if (done) break;
    size += value.length; if (size > max) { await reader.cancel(); throw failure('Request too large.', 413); }
    chunks.push(Buffer.from(value));
  }
  return Buffer.concat(chunks).toString('utf8');
}
export async function bodyJSON(req, max) {
  try { const value = JSON.parse(await readBody(req, max) || '{}'); if (!value || typeof value !== 'object' || Array.isArray(value)) throw 0; return value; }
  catch (e) { if (e?.status) throw e; throw failure('Invalid JSON object.'); }
}
export function authorize(req, key) {
  if (!key || key.length < 24 || !equal(req.headers.get('authorization'), 'Bearer ' + key)) throw failure('Authorization required.', 401, 'KEY');
}

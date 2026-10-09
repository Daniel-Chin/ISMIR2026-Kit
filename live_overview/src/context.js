import crypto from 'node:crypto';
import { failure } from './security.js';
export function decryptContext(value, secret, now = Date.now()) {
  try {
    if (typeof value !== 'string' || value.length > 16000 || !/^[A-Za-z0-9_+/=-]+$/.test(value)) throw 0;
    const buf = Buffer.from(value, 'base64'); let p = 0;
    const take = n => { if (!Number.isInteger(n) || n < 0 || p + n > buf.length) throw 0; const out = buf.subarray(p, p + n); p += n; return out; };
    const iv = take(take(1).readUInt8());
    const aad = take(take(2).readUInt16LE());
    const data = take(take(4).readUInt32LE());
    const tag = take(16); if (p !== buf.length || iv.length < 12) throw 0;
    const decipher = crypto.createDecipheriv('aes-256-gcm', crypto.createHash('sha256').update(secret).digest(), iv);
    decipher.setAAD(aad); decipher.setAuthTag(tag);
    const ctx = JSON.parse(Buffer.concat([decipher.update(data), decipher.final()]).toString('utf8'));
    const millis = n => Number(n) < 1e12 ? Number(n) * 1000 : Number(n);
    const exp = millis(ctx.exp), ts = millis(ctx.ts);
    if (!Number.isFinite(exp) || exp <= now || !Number.isFinite(ts) || ts > now + 30000 || !ctx.uid || typeof ctx.uid !== 'string') throw 0;
    return ctx;
  } catch { throw failure('Zoom identity is missing or expired. Reopen the App or check getAppContext permission.', 401, 'APP_AUTH'); }
}

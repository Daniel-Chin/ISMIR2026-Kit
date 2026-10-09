import fs from 'node:fs';import crypto from 'node:crypto';
const file='secrets.private.json';
fs.writeFileSync(file,JSON.stringify({ADMIN_KEY:crypto.randomBytes(32).toString('hex'),TOKEN_ENCRYPTION_KEY:crypto.randomBytes(32).toString('hex')},null,2)+'\n',{flag:'wx',mode:0o600});
console.log('Created secrets.private.json. Keep a secure backup; never commit it. Do not regenerate TOKEN_ENCRYPTION_KEY for an existing deployment.');

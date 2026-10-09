import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('..',import.meta.url));
test('Migration export strips old telemetry and OAuth, preserves mapping/peaks, and never overwrites a backup',()=>{
 const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'ismir-export-'));try {
  fs.mkdirSync(path.join(tmp,'data'));
  fs.writeFileSync(path.join(tmp,'data/schedule.json'),JSON.stringify({conference:{name:'Test'},events:[]}));
  fs.writeFileSync(path.join(tmp,'data/runtime.json'),JSON.stringify({credentials:{secret:'must-not-export'},observerRoomMappings:{e:{revision:1,mapping:{r:'p'}}},events:{e:{peakZoom:10,live:{activeSpeakerName:'private-name'}}},posters:{p:{peakZoom:4,live:{participantUUID:'private-id'}}}}));
  const out=path.join(tmp,'private.json'),script=path.join(root,'scripts/migrate_server.py');
  execFileSync('python3',[script,'--source',tmp,'--output',out]);const text=fs.readFileSync(out,'utf8'),value=JSON.parse(text);
  assert.equal(value.runtime.events.e.peakZoom,10);assert.equal(value.runtime.observerRoomMappings.e.mapping.r,'p');assert.equal(value.clock.enabled,false);
  assert(!text.includes('private-name'));assert(!text.includes('private-id'));assert(!text.includes('must-not-export'));
  assert.equal(fs.statSync(out).mode&0o777,0o600);assert.throws(()=>execFileSync('python3',[script,'--source',tmp,'--output',out],{stdio:'pipe'}));
 }finally{fs.rmSync(tmp,{recursive:true,force:true});}
});
test('Public export includes new live transport, relative URLs and no private backend assets',()=>{
 const tmp=fs.mkdtempSync(path.join(os.tmpdir(),'ismir-static-'));try{
  const out=path.join(tmp,'site');execFileSync('python3',[path.join(root,'scripts/build_public_site.py'),'--api-origin','https://backend.example','--output',out]);
  const files=fs.readdirSync(out);assert(files.includes('.nojekyll'));assert(!files.some(f=>/admin|observer|server|secret|worker/.test(f)));
  const html=fs.readFileSync(path.join(out,'index.html'),'utf8');assert(!html.includes('class="debug-clock-panel"'));assert(!/(?:src|href)="\/(?!\/)/.test(html));
  assert(fs.readFileSync(path.join(out,'public-connection.js'),'utf8').includes("packet.type === 'live'"));
  assert(fs.readFileSync(path.join(out,'public-site-config.js'),'utf8').includes('https://backend.example'));
  fs.writeFileSync(path.join(out,'personal.txt'),'must survive');assert.throws(()=>execFileSync('python3',[path.join(root,'scripts/build_public_site.py'),'--api-origin','https://backend.example','--output',out],{stdio:'pipe'}));
 }finally{fs.rmSync(tmp,{recursive:true,force:true});}
});

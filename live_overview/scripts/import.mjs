import fs from 'node:fs';
const [origin,file]=process.argv.slice(2);
if(!origin||!file||new URL(origin).origin!==origin||!origin.startsWith('https://')){console.error('Usage: npm run import -- https://BACKEND-HOST /path/to/schedule-or-private-bundle.json');process.exit(1);}
// Do not put the key in command arguments/history. Prefer ADMIN_KEY environment variable.
let key=process.env.ADMIN_KEY;
if(!key){console.error('Set ADMIN_KEY securely first (bash: read -s -p "Admin key: " ADMIN_KEY; export ADMIN_KEY).');process.exit(1);}
const data=JSON.parse(fs.readFileSync(file,'utf8'));
const result=await fetch(origin+'/api/admin/import',{method:'POST',headers:{Authorization:'Bearer '+key,'Content-Type':'application/json'},body:JSON.stringify(data.schedule?data:{schedule:data})});
const body=await result.json();console.log(JSON.stringify(body,null,2));if(!result.ok)process.exit(1);

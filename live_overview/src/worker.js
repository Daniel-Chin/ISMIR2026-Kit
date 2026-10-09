import {json,headers} from './security.js';
export {Conference} from './conference.js';
const assets=new Set(['/zoom-app-observer.html','/zoom-app-observer.js','/observer-core.js','/styles.css','/theme-toggle.js','/admin.html','/admin.js']);
export default {
  async fetch(req,env) {
    const url=new URL(req.url),origin=req.headers.get('origin')||'';
    const own=env.PUBLIC_ORIGIN||url.origin;
    const allowed=new Set(String(env.PUBLIC_VIEW_ORIGINS||'').split(',').map(s=>s.trim()).filter(Boolean));
    const cross=!!origin&&origin!==own;
    const read=['/api/state','/ws/public'].includes(url.pathname)&&allowed.has(origin);
    if(cross&&(!read||!['GET','OPTIONS'].includes(req.method)))return json({ok:false,error:'Cross-origin access is limited to public reads.'},403);
    if(req.method==='OPTIONS') {
      if(!read||url.pathname!=='/api/state'||req.headers.get('access-control-request-method')!=='GET'||req.headers.get('access-control-request-headers'))return json({ok:false,error:'Preflight denied.'},403);
      return new Response(null,{status:204,headers:{...headers,'Access-Control-Allow-Origin':origin,'Access-Control-Allow-Methods':'GET','Vary':'Origin'}});
    }
    if(url.pathname==='/')return new Response(null,{status:302,headers:{...headers,Location:'/admin.html'}});
    if(assets.has(url.pathname)&&['GET','HEAD'].includes(req.method)) {
      if(url.pathname==='/zoom-app-observer.html'&&env.ALLOW_LEGACY_OBSERVER!=='1')return json({ok:false,error:'Use /zoom/app/v1 (or your profile).'},404);
      const response=await env.ASSETS.fetch(req),out=new Response(response.body,response);for(const[k,v]of Object.entries(headers))out.headers.set(k,v);return out;
    }
    if(!(url.pathname.startsWith('/api/')||url.pathname.startsWith('/zoom/')||url.pathname==='/observer/event'||url.pathname==='/ws/public'))return json({ok:false,error:'Not found.'},404);
    try {
      const stub=env.CONFERENCE.get(env.CONFERENCE.idFromName('ismir-2026'));
      const response=await stub.fetch(req);
      if(response.status===101)return response;
      const out=new Response(response.body,response);out.headers.set('Vary','Origin');if(cross&&read)out.headers.set('Access-Control-Allow-Origin',origin);return out;
    }catch{return json({ok:false,code:'NETWORK',error:'Backend unavailable; retry shortly.'},503,cross&&read?{'Access-Control-Allow-Origin':origin,'Vary':'Origin'}:{});}
  }
};

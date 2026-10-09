import crypto from 'node:crypto';
import {failure, hash, random, equal, seal, unseal, json, html, bodyJSON, readBody, headers} from './security.js';
import {decryptContext} from './context.js';
export const PROFILE=/^v[1-9]\d{0,3}$/;
export function validateApp(id,input) {
  if(!PROFILE.test(id)) throw failure('Profile must be v1, v2, …');
  for(const field of ['clientId','clientSecret','webhookSecret']) if(typeof input[field]!=='string'||!input[field]||input[field].length>1000) throw failure('Missing '+field);
  let origin;try{origin=new URL(input.origin);}catch{throw failure('Invalid profile origin.');}
  if(origin.protocol!=='https:' || origin.origin!==input.origin) throw failure('Profile origin must be an exact HTTPS origin.');
  return {clientId:input.clientId,clientSecret:input.clientSecret,webhookSecret:input.webhookSecret,origin:input.origin,enabled:input.enabled!==false};
}
export class Zoom {
  constructor(owner) {this.owner=owner;this.store=owner.ctx.storage;this.env=owner.env;}
  async app(id) {
    const value=PROFILE.test(id)&&await this.store.get('app:'+id);
    if(!value)throw failure('App profile not configured.',404,'APP_AUTH');
    const app=unseal(value,this.env,'app:'+id);if(!app.enabled)throw failure('App profile disabled.',403,'APP_AUTH');return app;
  }
  grantKey(id,app,uid) {return 'grant:'+id+':'+hash(app.clientId+':'+uid);}
  async grant(key) {const value=await this.store.get(key);return value?unseal(value,this.env,key):null;}
  async tokens(app,params) {
    const response=await fetch('https://zoom.us/oauth/token',{method:'POST',signal:AbortSignal.timeout(8000),headers:{Authorization:'Basic '+Buffer.from(app.clientId+':'+app.clientSecret).toString('base64'),'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams(params)});
    if(!response.ok) throw failure('Zoom token exchange failed. Check profile credentials and callback URL, then install again.',502,'APP_AUTH');
    const data=await response.json();if(!data.access_token||!data.refresh_token||!Number.isFinite(Number(data.expires_in)))throw failure('Incomplete Zoom token response.',502,'APP_AUTH');
    return {...data,expiresAt:Date.now()+Number(data.expires_in)*1000};
  }
  // Runs under the coordinator's mutation queue: refresh and deauthorization cannot race.
  async accessToken(key,app) {
    const old=await this.grant(key);if(!old)throw failure('Install this App again.',401,'APP_AUTH');
    if(old.expiresAt>Date.now()+60000)return old.access_token;
    const fresh=await this.tokens(app,{grant_type:'refresh_token',refresh_token:old.refresh_token});
    await this.store.put(key,seal({...old,...fresh},this.env,key));return fresh.access_token;
  }
  async identity(req,id,app) {
    const context=decryptContext(req.headers.get('x-zoom-app-context'),app.clientSecret);
    const key=this.grantKey(id,app,context.uid);
    if(!await this.grant(key))throw failure('Install and authorize this App before connecting.',401,'APP_AUTH');
    return {app:id,user:hash(app.clientId+':'+context.uid),mid:context.mid||'',pid:context.pid||''};
  }
  async route(req,url,match) {
    const [,route,id,suffix='']=match, app=await this.app(id), now=Date.now();
    if(url.origin!==app.origin)throw failure('Open this App using its configured origin.',403,'APP_AUTH');
    if(req.method==='GET' && route==='app'&&!suffix) {
      const asset=await this.env.ASSETS.fetch(new Request(new URL('/zoom-app-observer.html',url)));
      const page=(await asset.text()).replace('<head>',`<head><base href="/"><script>window.ISMIR_ZOOM_PROFILE=${JSON.stringify(id)};</script>`);
      return html(page);
    }
    if(req.method==='POST'&&route==='app'&&['/api/observer/catalog','/api/observer/session','/api/observer/cancel','/observer/event'].includes(suffix)) {
      const identity=await this.identity(req,id,app), body=await bodyJSON(req);
      return this.owner.observer(req,suffix,body,identity);
    }
    if(req.method==='GET'&&!suffix&&route==='oauth/start') {
      this.owner.limit('oauth:'+req.headers.get('cf-connecting-ip'),30);
      if((await this.store.list({prefix:'oauth:',limit:501})).size>=500)throw failure('Too many pending authorizations.',429);
      const state=random();await this.store.put('oauth:'+hash(state),{id,exp:now+600000});await this.owner.ensureAlarm(600000);
      const auth=new URL('https://zoom.us/oauth/authorize');auth.search=new URLSearchParams({response_type:'code',client_id:app.clientId,redirect_uri:app.origin+'/zoom/oauth/callback/'+id,state});
      return new Response(null,{status:302,headers:{...headers,Location:auth.href,'Set-Cookie':`zoom_oauth_${id}=${state}; Path=/zoom/oauth/callback/${id}; HttpOnly; Secure; SameSite=Lax; Max-Age=600`}});
    }
    if(req.method==='GET'&&!suffix&&route==='oauth/callback') {
      if(url.searchParams.has('error'))throw failure('Zoom authorization declined. Start installation again.',400,'APP_AUTH');
      const state=url.searchParams.get('state');
      if(!state)return new Response(null,{status:302,headers:{...headers,Location:app.origin+'/zoom/oauth/start/'+id}});
      if(state.length>200)throw failure('Invalid OAuth state.',401,'APP_AUTH');
      const key='oauth:'+hash(state),pending=await this.store.get(key);
      const cookie=(req.headers.get('cookie')||'').split(';').map(x=>x.trim()).find(x=>x.startsWith(`zoom_oauth_${id}=`))?.split('=')[1];
      if(!pending||pending.id!==id||pending.exp<now||!equal(cookie,state))throw failure('Authorization expired. Start installation again.',401,'APP_AUTH');
      await this.store.delete(key);const code=url.searchParams.get('code');if(!code)throw failure('Missing OAuth code.');
      const tokens=await this.tokens(app,{grant_type:'authorization_code',code,redirect_uri:app.origin+'/zoom/oauth/callback/'+id});
      const userResponse=await fetch('https://api.zoom.us/v2/users/me',{headers:{Authorization:'Bearer '+tokens.access_token},signal:AbortSignal.timeout(8000)});
      if(!userResponse.ok)throw failure('Add user:read:user permission, then install again.',502,'APP_AUTH');
      const user=await userResponse.json();if(typeof user.id!=='string'||!user.id)throw failure('Missing Zoom user identity.',502);
      const grantKey=this.grantKey(id,app,user.id);await this.store.put(grantKey,seal({...tokens,installedAt:Date.now()},this.env,grantKey));
      return html(`<!doctype html><meta charset="utf-8"><title>Zoom App installed</title><h1>Zoom app installed successfully — ${id}</h1><p>You can close this tab and return to Zoom.</p>`,200,{'Set-Cookie':`zoom_oauth_${id}=; Path=/zoom/oauth/callback/${id}; HttpOnly; Secure; SameSite=Lax; Max-Age=0`});
    }
    if(req.method==='POST'&&route==='webhook'&&!suffix) {
      const raw=await readBody(req),ts=req.headers.get('x-zm-request-timestamp')||'';
      const expected='v0='+crypto.createHmac('sha256',app.webhookSecret).update(`v0:${ts}:${raw}`).digest('hex');
      if(!/^\d+$/.test(ts)||Math.abs(now-Number(ts)*1000)>300000||!equal(expected,req.headers.get('x-zm-signature')))throw failure('Invalid webhook signature.',401,'APP_AUTH');
      let data;try{data=JSON.parse(raw);}catch{throw failure('Invalid webhook JSON.');}
      if(data.event==='endpoint.url_validation') {
        const token=data.payload?.plainToken;if(typeof token!=='string')throw failure('Missing validation token.');
        return json({plainToken:token,encryptedToken:crypto.createHmac('sha256',app.webhookSecret).update(token).digest('hex')});
      }
      if(data.event==='app_deauthorized') {
        const payload=data.payload||{};
        if(payload.client_id!==app.clientId||typeof payload.user_id!=='string'||!Number.isFinite(Number(data.event_ts)))throw failure('Invalid deauthorization target or timestamp.');
        const key=this.grantKey(id,app,payload.user_id),record=await this.grant(key);
        if(record&&Number(data.event_ts)>=record.installedAt) {
          await this.store.delete(key);this.owner.revokeOwner(id+':'+hash(app.clientId+':'+payload.user_id));await this.owner.persistHub();
        }
      }
      return json({ok:true});
    }
    return json({ok:false,error:'Not found.'},404);
  }
}

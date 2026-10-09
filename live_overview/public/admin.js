'use strict';
const $=id=>document.getElementById(id);
$('origin').value=location.origin;
async function api(path,method='GET',data) {
  const response=await fetch(path,{method,cache:'no-store',headers:{Authorization:'Bearer '+$('key').value,'Content-Type':'application/json'},...(data?{body:JSON.stringify(data)}:{})});
  const result=await response.json();if(!response.ok||result.ok===false)throw Error(result.error||'请求失败');return result;
}
function action(id,fn){$(id).onclick=async()=>{const button=$(id);button.disabled=true;$('message').textContent='处理中…';try{await fn();$('message').textContent='完成';}catch(e){$('message').textContent=e.message;}finally{button.disabled=false;}};}
action('status',async()=>{$('details').textContent=JSON.stringify(await api('/api/admin/status'),null,2);});
action('export',async()=>{const value=await api('/api/admin/export'),url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='ismir-private-backup.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
action('import',async()=>{const file=$('schedule').files[0];if(!file)throw Error('请选择 JSON 文件。');const data=JSON.parse(await file.text());await api('/api/admin/import','POST',data.schedule?data:{schedule:data});});
action('clock',async()=>{const date=new Date($('time').value);if(!Number.isFinite(date.getTime()))throw Error('请选择日期与时间。');const result=await api('/api/debug-clock','POST',{fakeNow:date.toISOString(),speed:Number($('speed').value)});$('details').textContent=JSON.stringify(result.debugClock,null,2);});
action('real',async()=>{await api('/api/debug-clock','DELETE');});
action('app',async()=>{const id=$('profile').value.trim(),origin=$('origin').value.trim();await api('/api/admin/apps/'+encodeURIComponent(id),'PUT',{origin,clientId:$('clientId').value.trim(),clientSecret:$('clientSecret').value,webhookSecret:$('webhookSecret').value});$('clientSecret').value='';$('webhookSecret').value='';$('app-links').textContent=`Home URL: ${origin}/zoom/app/${id}\nOAuth callback: ${origin}/zoom/oauth/callback/${id}\nWebhook: ${origin}/zoom/webhook/${id}\n安装入口: ${origin}/zoom/oauth/start/${id}\nDomain Allow List: ${new URL(origin).hostname}`;});
action('disable',async()=>{await api('/api/admin/apps/'+encodeURIComponent($('profile').value.trim()),'DELETE');$('app-links').textContent='已停用；重新保存配置并安装后才能使用。';});

let scheduleEvents=[];
action('load-events',async()=>{scheduleEvents=(await api('/api/admin/events')).events;const select=$('event-id');select.replaceChildren();for(const e of scheduleEvents){const o=document.createElement('option');o.value=e.id;o.textContent=e.title;select.append(o);}select.onchange=()=>{$('event-zoom').value=scheduleEvents.find(e=>e.id===select.value)?.zoom||'';};select.onchange();});
action('save-link',async()=>{await api('/api/admin/event-link','POST',{eventId:$('event-id').value,zoom:$('event-zoom').value.trim()});});

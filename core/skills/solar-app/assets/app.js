'use strict';
const $=id=>document.getElementById(id);
let workspace=null,current=new URLSearchParams(location.search).get('conversation'),view='chat',busy=false,refreshing=false,signature='',audioId=null,audioSeen=null,voiceBusy=false,selectedThread=new URLSearchParams(location.search).get('thread');
const states={queued:'En cola',running:'Trabajando',active:'Trabajando',succeeded:'Listo',done:'Listo',failed:'No completado',cancelled:'Detenido',talking:'Conversación'};
function node(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
function markdown(text){const root=node('div',undefined,'document');let code=null,list=null;for(const line of text.split('\n')){if(line.startsWith('```')){if(code){root.append(code);code=null;}else code=node('pre');list=null;continue;}if(code){code.textContent+=line+'\n';continue;}const h=line.match(/^(#{1,3}) (.*)$/);if(h){root.append(node('h'+(h[1].length+1),h[2]));list=null;continue;}const li=line.match(/^[-*] (.*)$/);let p;if(li){if(!list){list=node('ul');root.append(list);}p=node('li');list.append(p);}else{list=null;p=node('p');root.append(p);}const content=li?li[1]:line;for(const part of content.split(/(\*\*.*?\*\*)/g))p.append(part.startsWith('**')&&part.endsWith('**')?node('strong',part.slice(2,-2)):document.createTextNode(part));}if(code)root.append(code);return root;}
function button(text,fn){const b=node('button',text);b.onclick=()=>Promise.resolve(fn()).catch(error);return b;}
function error(e){$('notice').textContent=e.message||String(e);}
function url(path,query={}){return path+'?'+new URLSearchParams({workspace:workspace||'',...query});}
async function api(path,body){const response=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({workspace,...body})});const data=await response.json();if(!response.ok)throw Error(data.error||'No se pudo completar la petición');return data;}
async function post(path,body={}){return api(path,body);}
async function select(id){if(audioId)await exitVoice();current=id;signature='';selectedThread=null;history.replaceState(null,'','/app?conversation='+encodeURIComponent(id));showView('chat');await refresh();}
async function create(){const c=await post('/api/app/conversations');await select(c.id);return c.id;}
function showView(name){view=name;for(const v of ['chat','files','system'])$(v).hidden=v!==name;document.querySelectorAll('[data-view]').forEach(b=>b.classList.toggle('selected',b.dataset.view===name));$('title').textContent={chat:'Conversaciones',files:'Archivos de los planetas',system:'Estado y registros'}[name];if(name==='files')loadFiles().catch(error);if(name==='system')loadSystem().catch(error);}
function renderConversation(data){if(view==='chat')$('title').textContent=data.conversation.title==='New conversation'?'Nueva conversación':data.conversation.title;const next=JSON.stringify(data.messages);if(next!==signature){const nearBottom=$('messages').scrollHeight-$('messages').scrollTop-$('messages').clientHeight<120;signature=next;$('messages').replaceChildren();for(const m of data.messages){const a=node('article',undefined,'message '+m.role);a.append(node('div',m.role==='user'?'TÚ':'SOLAR','who'),markdown(m.text));if(m.work_thread_id)a.append(button('Abrir encargo ↗',()=>openWork(m.work_thread_id)));if(m.role==='assistant')a.append(button('Escuchar',()=>speak(m)));$('messages').append(a);}if(nearBottom||busy)$('messages').scrollTop=$('messages').scrollHeight;}
$('activity').replaceChildren();if(!data.work.length)$('activity').append(node('p','Los encargos de esta conversación aparecerán aquí.','muted'));for(const w of data.work){const card=node('article',undefined,'work-card');card.append(node('h3',w.title),node('span',w.cancellation_requested&&['queued','running'].includes(w.status)?'Parada solicitada…':states[w.status]||w.status,'badge'),node('small',w.provider_used||w.provider_requested));card.append(button('Ver ejecución',()=>openWork(w.thread_id)));if(['queued','running','active'].includes(w.status)){const b=button('Detener',async()=>{await post('/api/app/runs/'+w.run_id+'/cancel');await refresh();});b.disabled=!!w.cancellation_requested;card.append(b);}$('activity').append(card);}

}
async function refresh(){if(refreshing)return;refreshing=true;try{const d=await api('/api/app/bootstrap');if(workspace&&workspace!==d.workspace){await exitVoice();throw Error('El espacio de trabajo ha cambiado. Recarga Solar.');}workspace=d.workspace;$('connection').textContent='Conectado a este Mac';$('workspace').textContent=workspace;$('send').disabled=busy||!d.enabled;$('dictate').disabled=!d.enabled;if(!d.enabled)$('notice').textContent='La conversación no está activada en este servicio.';$('conversations').replaceChildren();for(const c of d.conversations){const b=button(c.title==='New conversation'?'Nueva conversación':c.title,()=>select(c.id));b.classList.toggle('active',c.id===current);$('conversations').append(b);}if(current){const cid=current;const data=await api(url('/api/app/conversations/'+cid));if(cid===current)renderConversation(data);}else if(d.threads.length){$('activity').replaceChildren(node('p','Ejecuciones anteriores','label'));for(const t of d.threads.slice(0,30))$('activity').append(button(t.title,()=>openWork(t.thread_id)));}if(selectedThread)await openWork(selectedThread,true);}catch(e){error(e);$('connection').textContent='No se pudo actualizar Solar';}finally{refreshing=false;}}
async function send(){const text=$('text').value.trim();if(!text||busy)return;if(!current)await create();const cid=current;busy=true;$('send').disabled=true;$('notice').textContent='Solar está respondiendo…';const id=crypto.randomUUID();try{const data=await post('/api/app/conversations/'+cid+'/messages',{text,request_id:id});if(cid===current){$('text').value='';renderConversation(data);}$('notice').textContent='';}catch(e){error(e);}finally{busy=false;$('send').disabled=false;await refresh();}}
async function openWork(id,quiet=false){selectedThread=id;const d=await api(url('/api/app/threads/'+id));if(selectedThread!==id)return;$('inspectTitle').textContent=d.thread.title;$('activity').hidden=true;$('preview').hidden=false;$('backActivity').hidden=false;$('preview').replaceChildren();for(const r of d.runs){$('preview').append(node('p',states[r.status]||r.status,'badge'),node('p',r.input),r.output?markdown(r.output):node('pre',r.error||'El resultado aparecerá aquí.'));if(r.output){const path=(d.artifacts||[]).find(a=>a.run_id===r.run_id)?.path;if(path)$('preview').append(button('Abrir archivo del resultado',()=>previewFile(path)));}}}
function back(){selectedThread=null;$('inspectTitle').textContent='Actividad';$('activity').hidden=false;$('preview').hidden=true;$('backActivity').hidden=true;}
async function previewFile(path){selectedThread=null;const response=await fetch(url('/api/app/file',{path}));if(!response.ok){const d=await response.json();throw Error(d.error||'No se pudo abrir el archivo');}$('inspectTitle').textContent=path.split('/').pop();$('activity').hidden=true;$('preview').hidden=false;$('backActivity').hidden=false;$('preview').replaceChildren(node('p',path,'muted'));const type=response.headers.get('Content-Type')||'';if(type.startsWith('image/')){const img=node('img');img.alt=path;img.src=url('/api/app/file',{path});$('preview').append(img);}else if(type.startsWith('application/pdf')){const frame=node('iframe');frame.title=path;frame.src=url('/api/app/file',{path});$('preview').append(frame);}else {const text=await response.text();$('preview').append(path.endsWith('.md')?markdown(text):node('pre',text));}}
async function loadFiles(){const d=await api(url('/api/app/files',{q:$('search').value,planet:$('planet').value}));if($('planet').options.length===1)for(const p of d.planets){const o=node('option',p);o.value=p;$('planet').append(o);}$('fileCount').textContent=d.total+' archivos · Se muestran hasta 250 resultados';$('fileList').replaceChildren();for(const f of d.files){const row=node('div',undefined,'file-row');const b=button(f.path.split('/').pop(),()=>previewFile(f.path));b.append(node('small',f.path));row.append(b,node('span',Math.ceil(f.size/1024)+' KB'));$('fileList').append(row);}$('fileEvents').replaceChildren();for(const e of d.events){const row=node('div',undefined,'file-row');row.append(node('span',({created:'Creado',modified:'Modificado',deleted:'Eliminado'})[e.action]));row.append(e.action==='deleted'?node('span',e.path):button(e.path,()=>previewFile(e.path)));$('fileEvents').append(row);}if(!d.events.length)$('fileEvents').append(node('p','Todavía no se han observado cambios.','muted'));}
async function loadSystem(){const [health,logs]=await Promise.all([api('/api/status'),api(url('/api/app/logs'))]);$('health').textContent=health.text;$('events').replaceChildren();for(const e of logs.events)$('events').append(node('div',(e.type||e.event_type||'Evento')+' · '+(e.created_at||e.timestamp||'')+'\n'+JSON.stringify(e.payload||{}),'event'));$('logs').replaceChildren();for(const l of logs.logs){const d=node('details');d.append(node('summary',l.name),node('pre',l.text));$('logs').append(d);}if(!logs.logs.length)$('logs').append(node('p','Los registros aparecerán cuando se ejecute el primer encargo.','muted'));}
async function startAudio(){
  if(audioId||voiceBusy)return;
  if(!current)await create();
  voiceBusy=true;
  try{
    const recording=await post('/api/app/audio/start',{conversation_id:current});
    audioId=recording.id;audioSeen=null;
    $('voiceState').hidden=false;
    $('voiceLabel').textContent='Grabando. Pulsa Terminar para revisar el texto.';
    $('finishAudio').disabled=false;
  }finally{voiceBusy=false;}
}
async function exitVoice(){
  if(audioId)await post('/api/app/audio/discard',{id:audioId});
  audioId=null;$('voiceState').hidden=true;
}
async function pollAudio(){
  if(!audioId||voiceBusy)return;
  const recording=await api(url('/api/app/audio'));
  if(recording.id!==audioId||recording.conversation_id!==current)return;
  if(recording.state==='transcribing'){
    $('voiceLabel').textContent='Transcribiendo en este Mac…';$('finishAudio').disabled=true;
  }
  if(recording.state==='ready'&&audioSeen!==recording.id){
    audioSeen=recording.id;audioId=null;
    $('text').value=recording.text;
    $('voiceState').hidden=true;$('text').focus();
  }else if(recording.state==='error'){
    audioId=null;$('voiceState').hidden=true;error(recording.text);
  }
}
async function speak(message){await post('/api/app/speak',{message_id:message.id});}
$('new').onclick=()=>create().catch(error);$('example').onclick=()=>{$('text').value=$('example').textContent;$('text').focus();};$('form').onsubmit=e=>{e.preventDefault();send().catch(error);};$('text').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send().catch(error);}};document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>showView(b.dataset.view));$('backActivity').onclick=back;$('planet').onchange=()=>loadFiles().catch(error);let searchTimer;$('search').oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>loadFiles().catch(error),250);};document.querySelectorAll('[data-action]').forEach(b=>b.onclick=async()=>{b.disabled=true;try{const r=await post('/api/actions/client',{action:b.dataset.action});$('health').textContent=r.output||JSON.stringify(r);}catch(e){error(e);}finally{b.disabled=false;}});$('dictate').onclick=()=>startAudio().catch(error);$('finishAudio').onclick=()=>post('/api/app/audio/stop',{id:audioId}).catch(error);$('exitVoice').onclick=()=>exitVoice().catch(error);
window.addEventListener('pagehide',()=>{if(audioId)navigator.sendBeacon('/api/app/audio/discard',new Blob([JSON.stringify({workspace,id:audioId})],{type:'application/json'}));});
refresh();setInterval(()=>{refresh();pollAudio().catch(error);if(view==='files')loadFiles().catch(error);},2000);

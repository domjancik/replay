const $ = id => document.getElementById(id);
let token = '', library = [], jobs = [], selectedJob = null, pageReady = false, capabilities;
let previewKey = '', pageRequest = 0, usbBusy = false;
const notice = message => { $('notice').textContent = message; $('notice').hidden = !message; };
async function api(path, body, raw = false) {
  const response = await fetch(path, body === undefined ? {} : {method:'POST',
    headers:{'Content-Type':raw?'application/octet-stream':'application/json','X-Replay-Token':token},
    body:raw?body:JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(data.error || 'Request failed');
    error.code = data.code;
    throw error;
  }
  return data;
}
const safely = fn => async (...args) => { try { await fn(...args); } catch(error) { notice(error.message); } };
function option(value, label) { const item=document.createElement('option');item.value=value;item.textContent=label;return item; }
async function loadLibrary(selected) {
  library = await api('/api/library');
  const previous=selected || $('notebook').value;
  $('notebook').replaceChildren(...library.map(n=>option(n.id,n.name + (n.has_pdf?' · PDF paired':''))));
  if (!library.length) $('notebook').append(option('', 'Import a notebook to begin'));
  if (library.some(n=>n.id===previous)) $('notebook').value=previous;
  await selectNotebook();
}
async function selectNotebook() {
  $('notebook-preview').hidden=true;
  const notebook=library.find(n=>n.id===$('notebook').value);
  const previousPage = $('page').value;
  $('page').replaceChildren();$('pair-open').disabled=!notebook;
  const initial = notebook?.pages.find(p=>p.available && p.id===previousPage)
    || notebook?.pages.find(p=>p.available);
  $('page').disabled=!initial;
  if (!notebook) {
    pageRequest++;pageReady=false;resetClipping();updateGenerateButton();
    $('page-info').textContent='Import a notebook to see its pages.';
    return;
  }
  for (const page of notebook.pages) {
    const item=option(page.id,`Page ${page.number}${page.available?'':' · no stroke data'}`);
    item.disabled=!page.available;$('page').append(item);
  }
  if (!initial) {
    pageRequest++;pageReady=false;resetClipping();updateGenerateButton();
    $('page-info').textContent='This notebook has no pages with saved stroke data.';
    return;
  }
  $('page').value=initial.id;
  await selectPage();
}
function resetClipping() {
  $('canvas-clipping').hidden=true;
  $('allow-clipping').checked=false;
}
function updateGenerateButton() {
  $('generate').disabled=!pageReady || !capabilities.ffmpeg
    || (!$('canvas-clipping').hidden && !$('allow-clipping').checked);
}
function canvasSummary(){$('canvas-summary').textContent=`Canvas: ${$('width').value} × ${$('height').value} · manual offset (${$('offset-x').value}, ${$('offset-y').value})`;}
async function selectPage() {
  showNotebookPreview();
  const version=++pageRequest;pageReady=false;resetClipping();updateGenerateButton();
  $('page-info').textContent='Reading page…';
  try {
    const info=await api(`/api/page?document=${encodeURIComponent($('notebook').value)}&page=${encodeURIComponent($('page').value)}`);
    if (version!==pageRequest) return;
    const notebook=library.find(n=>n.id===$('notebook').value);
    const needsPdf=info.unresolved_anchors && !notebook.has_pdf;
    const needsPoppler=info.unresolved_anchors && notebook.has_pdf && !capabilities.poppler;
    $('page-info').textContent=`${info.strokes.toLocaleString()} strokes${info.paper_size?' · Source canvas '+info.paper_size.join(' × '):''}. `+
      (needsPdf?'Attach a matching notebook PDF to resolve text anchors.':needsPoppler?'Install Poppler and restart the utility to resolve text anchors.':notebook.has_pdf?'Paired PDF saved locally.':'Saved locally.');
    if(info.paper_size){$('width').value=info.paper_size[0];$('height').value=info.paper_size[1];$('offset-x').value=info.paper_size[0]/2;}
    canvasSummary();
    pageReady=!!info.strokes && !needsPdf && !needsPoppler;
    updateGenerateButton();
  } catch(error) {if(version===pageRequest){$('page-info').textContent=error.message;throw error;}}
}
async function upload(input, path) {
  const file=input.files[0];if(!file)return;
  try {
    if(file.size>128*1024*1024)throw new Error('File exceeds 128 MiB.');
    notice('Importing into your local library…');
    const result=await api(path,file,true);
    await loadLibrary(result.id);
    notice('Notebook saved locally.');
  } finally {
    input.value='';
  }
}
async function generate() {
  if(!pageReady)return;
  const version = pageRequest;
  $('generate').disabled=true;notice('');
  try {
    const settings={};
    for(const key of ['width','height','offset-x','offset-y','seconds','fps','output-width'])settings[key.replaceAll('-','_')]=Number($(key).value);
    settings.backend=$('backend').value;
    settings.ordering=$('ordering').value;
    settings.allow_clipping=$('allow-clipping').checked;
    const job=await api('/api/jobs',{document:$('notebook').value,page:$('page').value,settings});
    selectedJob=job.id;previewKey='';await poll();
  } catch (error) {
    if (error.code!=='canvas_clipping') throw error;
    if (version===pageRequest) {
      $('canvas-settings').open=true;
      $('canvas-warning').textContent=error.message;
      $('canvas-clipping').hidden=false;
    }
  } finally {updateGenerateButton();}
}
function showJob(job) {
  if(!job)return;
  $('view-title').textContent=`${job.name} · page ${job.page}`;
  $('view-state').textContent=job.state.toUpperCase();
  $('empty').hidden=true;
  const complete=job.state==='complete';
  $('video').hidden=!complete;$('downloads').hidden=!complete;
  $('export-open').disabled=!complete || job.kind==='export';
  $('view-progress').hidden=complete;
  $('progress').value=Math.min(.99,job.frames/Math.max(1,job.expected_frames));
  $('progress-text').textContent=job.error || (job.state==='queued'?'Queued — another replay will finish first.':`${job.frames} / ~${job.expected_frames} frames · ${job.state}${job.state==='running'?' · final verification and video encoding follow':''}`);
  const base=`/media/${job.id}/`;
  if(complete){
    if($('video').dataset.job!==job.id){$('video').poster=base+'static.png';$('video').src=base+'replay.mp4';$('video').dataset.job=job.id;}
    $('preview').hidden=true;
    $('download-video').href=base+'replay.mp4';$('download-image').href=base+'static.png';$('download-manifest').href=base+'manifest.json';
  }else{
    $('video').pause();
    const key=job.id+':'+job.frames;
    $('preview').hidden=job.frames<2;
    if(job.frames>=2 && key!==previewKey){$('preview').src=base+'latest.png?frame='+job.frames;previewKey=key;}
  }
}
function showNotebookPreview() {
  const image=$('notebook-preview');
  const job=jobs.find(j=>j.state==='complete' && j.kind!=='export'
    && j.document_id===$('notebook').value && j.page_id===$('page').value);
  image.hidden=!job;
  $('notebook-preview-label').textContent=job?'Saved render · selected page':'No saved preview for this page yet.';
  if(!job){image.removeAttribute('src');return;}
  const source=`/media/${job.id}/static.png`;
  if(image.getAttribute('src')!==source){
    image.alt=`${job.name} · page ${job.page}`;
    image.onerror=()=>{image.hidden=true;$('notebook-preview-label').textContent='Preview unavailable.';};
    image.src=source;
  }
}
async function poll() {
  jobs=await api('/api/jobs');
  showNotebookPreview();
  $('jobs').replaceChildren();
  if(!jobs.length){const p=document.createElement('p');p.className='hint';p.textContent='Your render queue is empty.';$('jobs').append(p);}
  for(const job of jobs){
    const row=document.createElement('div');row.className='job';
    const open=document.createElement('button');open.className='open';open.textContent=`${job.name} · page ${job.page}`;
    const totalSeconds=(job.state==='complete'?job.frames:job.expected_frames)/job.settings.fps;
    const detail=document.createElement('small');detail.textContent=`${totalSeconds.toFixed(1)}s total · ${job.settings.fps} fps · ${job.settings.ordering==='entry'?'entry order':'by layer'} · ${job.settings.viewport.join(' × ')}${job.finished&&job.started?' · rendered in '+Math.round(job.finished-job.started)+'s':''}`;open.append(detail);
    open.onclick=()=>{selectedJob=job.id;previewKey='';showJob(job);};
    const state=document.createElement('span');state.className='state';state.textContent=job.state;row.append(open,state);
    if(['queued','running'].includes(job.state)){const cancel=document.createElement('button');cancel.className='quiet';cancel.textContent='Cancel';cancel.onclick=safely(async()=>{await api('/api/cancel',{id:job.id});await poll();});row.append(cancel);}
    $('jobs').append(row);
  }
  if(!selectedJob && jobs.length)selectedJob=jobs[0].id;
  showJob(jobs.find(j=>j.id===selectedJob));
}
async function browse(folder='', label='Tablet') {
  if(usbBusy)return;
  $('usb-status').textContent='Connecting to USB web interface…';$('usb-items').replaceChildren();
  try{
    const entries=await api('/api/usb?folder='+encodeURIComponent(folder));
    $('usb-location').textContent=label;$('usb-status').textContent='Choose a folder or import a notebook.';
    for(const entry of entries.sort((a,b)=>Number(b.folder)-Number(a.folder)||a.name.localeCompare(b.name))){
      const row=document.createElement('div');row.className='usb-item';
      const name=document.createElement('span');name.textContent=(entry.folder?'▱ ':'')+entry.name;
      const action=document.createElement('button');action.textContent=entry.folder?'Open':'Import';
      action.disabled=!!(!entry.folder && entry.file_type && entry.file_type!=='notebook');
      action.dataset.unsupported=String(action.disabled);
      action.onclick=async()=>{
        if(usbBusy)return;
        if(entry.folder){await browse(entry.id,entry.name);return;}
        usbBusy=true;document.querySelectorAll('#usb-items button').forEach(b=>b.disabled=true);
        $('usb-status').textContent='Saving notebook and verifying two raw reads… This can take a minute.';
        try{const result=await api('/api/usb-import',{id:entry.id,pdf:$('include-pdf').checked});await loadLibrary(result.id);$('usb-dialog').close();notice('Notebook saved locally.');}
        catch(error){$('usb-status').textContent=error.message+($('include-pdf').checked?' Try without the PDF for pages without text anchors. Any downloaded raw data is retained locally.':'');}
        finally{usbBusy=false;document.querySelectorAll('#usb-items button').forEach(b=>b.disabled=b.dataset.unsupported==='true');}
      };row.append(name,action);$('usb-items').append(row);
    }
  }catch(error){$('usb-status').textContent='USB unavailable: '+error.message+'. Check the cable and USB web interface setting. Saved notebooks still work.';}
}
let cropImage=null, cropRect=null, cropStart=null, exportSource=null;
function drawCrop(){
  if(!cropImage)return;
  const canvas=$('crop-canvas'), ctx=canvas.getContext('2d');
  ctx.clearRect(0,0,canvas.width,canvas.height);ctx.drawImage(cropImage,0,0);
  if(cropRect){const [x,y,w,h]=cropRect;ctx.fillStyle='rgba(0,0,0,.35)';
    ctx.fillRect(0,0,canvas.width,y);ctx.fillRect(0,y+h,canvas.width,canvas.height-y-h);
    ctx.fillRect(0,y,x,h);ctx.fillRect(x+w,y,canvas.width-x-w,h);
    ctx.strokeStyle='#e94d37';ctx.lineWidth=Math.max(2,canvas.width/250);ctx.strokeRect(x,y,w,h);}
}
function cropFields(){['crop-x','crop-y','crop-w','crop-h'].forEach((id,i)=>$(id).value=cropRect[i]);drawCrop();}
function resetCrop(){if(!cropImage)return;cropRect=[0,0,cropImage.width,cropImage.height];cropFields();}
async function openExport(){
  const job=jobs.find(j=>j.id===selectedJob);if(!job || job.state!=='complete' || job.kind==='export')return;
  exportSource=job.id;cropImage=null;$('export-save').disabled=true;$('export-status').textContent='Loading final image…';
  $('export-dialog').showModal();
  const image=new Image();
  image.onload=()=>{cropImage=image;const canvas=$('crop-canvas');canvas.width=image.width;canvas.height=image.height;resetCrop();$('export-status').textContent='';$('export-save').disabled=false;};
  image.onerror=()=>{$('export-status').textContent='Could not load the final image.';};
  image.src=`/media/${job.id}/static.png`;
}
function cropPoint(event){const box=$('crop-canvas').getBoundingClientRect();return [Math.max(0,Math.min(cropImage.width,Math.round((event.clientX-box.left)*cropImage.width/box.width))),Math.max(0,Math.min(cropImage.height,Math.round((event.clientY-box.top)*cropImage.height/box.height)))];}
function setupExport(){
  $('export-open').onclick=safely(openExport);$('export-close').onclick=()=>$('export-dialog').close();$('crop-reset').onclick=resetCrop;
  for(const id of ['crop-x','crop-y','crop-w','crop-h'])$(id).oninput=()=>{cropRect=['crop-x','crop-y','crop-w','crop-h'].map(key=>Number($(key).value));drawCrop();};
  const canvas=$('crop-canvas');
  canvas.onpointerdown=event=>{if(!cropImage)return;cropStart=cropPoint(event);canvas.setPointerCapture(event.pointerId);};
  canvas.onpointermove=event=>{if(!cropStart)return;const point=cropPoint(event);cropRect=[Math.min(cropStart[0],point[0]),Math.min(cropStart[1],point[1]),Math.abs(point[0]-cropStart[0]),Math.abs(point[1]-cropStart[1])];cropFields();};
  canvas.onpointerup=canvas.onpointercancel=()=>{cropStart=null;};
  $('export-save').onclick=async()=>{
    $('export-save').disabled=true;$('export-status').textContent='Queuing export…';
    try{const job=await api('/api/export',{job:exportSource,crop:cropRect,reverse_speed:Number($('reverse-speed').value)});selectedJob=job.id;previewKey='';$('export-dialog').close();await poll();}
    catch(error){$('export-status').textContent=error.message;}
    finally{$('export-save').disabled=false;}
  };
}
async function start(){
  setupExport();
  capabilities=await api('/api/session');token=capabilities.token;
  const {setupCloud}=await import('/cloud-ui.mjs');
  setupCloud({sessionToken:()=>token,importArchive:async(raw)=>{
    const result=await api('/api/upload',raw,true);
    await loadLibrary(result.id);notice('Cloud notebook saved locally. Choose a page to animate.');
  }});
  $('backend').querySelector('[value=rust]').disabled=!capabilities.rust;
  $('backend').value=capabilities.rust?'rust':'python';
  if(!capabilities.ffmpeg)notice('FFmpeg was not found. Install it and restart the utility before generating videos.');
  for(const id of ['width','height','offset-x','offset-y'])$(id).oninput=()=>{
    resetClipping();canvasSummary();updateGenerateButton();
  };
  $('allow-clipping').onchange=updateGenerateButton;
  $('notebook').onchange=safely(selectNotebook);$('page').onchange=safely(selectPage);
  $('refresh').onclick=safely(()=>loadLibrary());$('generate').onclick=safely(generate);
  $('upload-open').onclick=()=>$('upload').click();$('upload').onchange=safely(()=>upload($('upload'),'/api/upload'));
  $('pair-open').onclick=()=>$('pair').click();$('pair').onchange=safely(()=>upload($('pair'),'/api/upload-pdf?document='+encodeURIComponent($('notebook').value)));
  $('usb-open').onclick=()=>{$('usb-dialog').showModal();browse();};$('usb-close').onclick=()=>$('usb-dialog').close();$('usb-up').onclick=()=>browse();
  await loadLibrary();await poll();setInterval(()=>poll().catch(error=>notice('Server unavailable: '+error.message)),2000);
}
safely(start)();

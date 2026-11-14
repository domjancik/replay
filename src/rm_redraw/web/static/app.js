const $ = id => document.getElementById(id);
const mediaUrl=(id,file)=>globalThis.replayBrowser?globalThis.replayBrowser.media(id,file):`/media/${id}/${file}`;
let token = '', library = [], jobs = [], selectedJob = null, pageReady = false, capabilities;
let previewKey = '', pageRequest = 0, usbBusy = false;
let usbCompanion=null;
let rendererBackend="python";
let selectionPreview = null, previewRefreshTimer;
let expandedNotebook=null, galleryList=false, galleryFocused=false;
const pageThumbnails=new Map(), thumbnailStates=new Map();
let thumbnailObserver=null, activeThumbnail=null;
const visibleThumbnailSlots=new Set(), thumbnailQueue=new Map();
const notice = message => { $('notice').textContent = message; $('notice').hidden = !message; };
let pendingWork=0;
async function api(path, body, raw = false) {
  const tracked=body!==undefined || path.startsWith('/api/usb') || path.startsWith('/api/page?') || path==='/api/library' || path==='/api/session';
  if(tracked){pendingWork++;$('work-status').hidden=false;}
  try{return await requestApi(path,body,raw);}
  finally{if(tracked){pendingWork--;$('work-status').hidden=pendingWork===0;}}
}
async function requestApi(path, body, raw = false) {
  if(globalThis.replayBrowser)return globalThis.replayBrowser.api(path,body);
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
  expandedNotebook=$('notebook').value || null;
  await selectNotebook();
  renderGallery();
}
async function selectNotebook() {
  clearTimeout(previewRefreshTimer);
  selectionPreview=null;
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
  clearTimeout(previewRefreshTimer);
  selectionPreview=null;
  selectedJob=null;$('video').hidden=true;$('preview').hidden=true;$('downloads').hidden=true;$('view-progress').hidden=true;
  renderPageReplays();
  showNotebookPreview();
  $('selected-notebook-title').textContent=library.find(n=>n.id===$('notebook').value)?.name || 'Choose a notebook';
  $('view-title').textContent='Page '+($('page').selectedOptions[0]?.textContent.replace('Page ','') || '');
  $('view-state').textContent='PREVIEW';
  renderGallery();
  const version=++pageRequest;pageReady=false;resetClipping();updateGenerateButton();
  $('page-info').textContent='Reading page…';
  try {
    const info=await api(`/api/page?document=${encodeURIComponent($('notebook').value)}&page=${encodeURIComponent($('page').value)}`);
    if (version!==pageRequest) return;
    const notebook=library.find(n=>n.id===$('notebook').value);
    const needsPdf=info.unresolved_anchors && !notebook.has_pdf;
    const needsPoppler=info.unresolved_anchors && notebook.has_pdf && !capabilities.poppler;
    $('page-info').textContent=`${info.strokes.toLocaleString()} strokes${info.paper_size?' · Source canvas '+info.paper_size.join(' × '):''}. `+
      (needsPdf?(capabilities.hosted?'Attach the matching native PDF to resolve this page’s text anchors in the browser.':'Attach a matching notebook PDF to resolve text anchors.'):needsPoppler?'Install Poppler and restart the utility to resolve text anchors.':notebook.has_pdf?'Paired PDF saved locally.':'Saved locally.');
    if(info.paper_size){$('width').value=info.paper_size[0];$('height').value=info.paper_size[1];$('offset-x').value=info.paper_size[0]/2;}
    if(info.source_to_page_transform){$('offset-x').value=info.source_to_page_transform[4];$('offset-y').value=info.source_to_page_transform[5];}
    canvasSummary();
    pageReady=!!info.strokes && !needsPdf && !needsPoppler;
    updateGenerateButton();
    requestSelectionPreview(version);
  } catch(error) {if(version===pageRequest){$('page-info').textContent=error.message;throw error;}}
}
async function requestSelectionPreview(version) {
  const pending={document:$('notebook').value,page:$('page').value,state:'queued'};
  selectionPreview=pending;showNotebookPreview();
  const settings={};
  for(const key of ['width','height','offset-x','offset-y'])settings[key.replaceAll('-','_')]=Number($(key).value);
  Object.assign(settings,{seconds:6,fps:6,output_width:234,backend:rendererBackend});
  try {
    let result=await api('/api/page-preview',{document:pending.document,page:pending.page,settings});
    while(version===pageRequest && selectionPreview===pending){
      Object.assign(pending,result);
      thumbnailStates.set(pending.document+'/'+pending.page,result);updateGalleryImages();
      if(result.state==='complete'){pageThumbnails.set(pending.document+'/'+pending.page,result.url);updateGalleryImages();}
      showNotebookPreview();
      if(!['queued','running'].includes(result.state))return;
      await new Promise(resolve=>setTimeout(resolve,1500));
      if(version!==pageRequest || selectionPreview!==pending)return;
      result=await api('/api/page-preview?id='+encodeURIComponent(result.id));
    }
  } catch(error){
    if(version===pageRequest && selectionPreview===pending){pending.state='failed';pending.error=error.message;showNotebookPreview();}
  }
}
async function upload(input, path) {
  const file=input.files[0];if(!file)return;
  try {
    if(file.size>128*1024*1024)throw new Error('File exceeds 128 MiB.');
    notice('Importing into your local library…');
    const result=await api(path,file,true);
    await loadLibrary(result.id);
    setLibrarySource('local');
    notice('Notebook saved locally.');
  } finally {
    input.value='';
  }
}
function readDuration(){
  const seconds=Number($('seconds').value);
  if(!Number.isFinite(seconds)||seconds<2||seconds>60)throw new Error('Choose a duration from 2 to 60 seconds.');
  return seconds;
}
async function generate() {
  if(!pageReady)return;
  const version = pageRequest;
  $('generate').disabled=true;notice('');
  try {
    const settings={};
    for(const key of ['width','height','offset-x','offset-y','seconds','fps','output-width'])settings[key.replaceAll('-','_')]=Number($(key).value);
    settings.seconds=readDuration();
    settings.backend=rendererBackend;
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
function renderPageReplays(){
  const matching=jobs.filter(j=>j.state==='complete' && j.document_id===$('notebook').value && j.page_id===$('page').value)
    .sort((a,b)=>b.created-a.created);
  $('page-replays').hidden=!matching.length;
  $('page-replay-count').textContent=String(matching.length);
  const list=$('page-replay-list');list.replaceChildren();
  for(const job of matching){
    const button=document.createElement('button');button.className='page-replay';
    button.setAttribute('aria-pressed',String(selectedJob===job.id));
    const image=document.createElement('img');image.alt='';image.loading='lazy';image.src=mediaUrl(job.id,'static.png');image.onerror=()=>{image.hidden=true;};
    const label=document.createElement('span');
    label.textContent=`${job.kind==='export'?'Export':'Replay'} · ${(job.frames/job.settings.fps).toFixed(1)}s · ${job.settings.fps} fps`;
    const detail=document.createElement('small');detail.textContent=`${job.settings.viewport.join(' × ')} · ${job.settings.ordering==='entry'?'entry order':'by layer'}`;
    label.append(detail);button.append(image,label);
    button.onclick=()=>{selectedJob=job.id;previewKey='';showJob(job);renderPageReplays();};
    list.append(button);
  }
}
function showJob(job) {
  if(!job)return;
  $('view-title').textContent=`${job.name} · page ${job.page}`;
  $('view-state').textContent=job.state.toUpperCase();
  $('empty').hidden=true;$('notebook-preview').hidden=true;$('notebook-preview-label').hidden=true;
  const complete=job.state==='complete';
  $('video').hidden=!complete;$('downloads').hidden=!complete;
  $('export-open').disabled=!complete || job.kind==='export';
  $('view-progress').hidden=complete;
  $('progress').value=Math.min(.99,job.frames/Math.max(1,job.expected_frames));
  $('progress-text').textContent=job.error || (job.state==='queued'?'Queued — another replay will finish first.':`${job.frames} / ~${job.expected_frames} frames · ${job.state}${job.state==='running'?' · final verification and video encoding follow':''}`);
  const media=file=>mediaUrl(job.id,file);
  if(complete){
    if($('video').dataset.job!==job.id){$('video').poster=media('static.png');$('video').src=media('replay.mp4');$('video').dataset.job=job.id;}
    $('preview').hidden=true;
    $('download-video').href=media('replay.mp4');$('download-video').download='replay'+(job.extension||'.mp4');$('download-image').href=media('static.png');$('download-manifest').href=media('manifest.json');
  }else{
    $('video').pause();
    const key=job.id+':'+job.frames;
    $('preview').hidden=job.frames<2;
    if(job.frames>=2 && key!==previewKey){$('preview').src=media('latest.png')+(capabilities.hosted?'':'?frame='+job.frames);previewKey=key;}
  }
}
function showNotebookPreview() {
  if(selectedJob)return;
  $('notebook-preview-label').hidden=false;
  const image=$('notebook-preview');
  const job=jobs.find(j=>j.state==='complete' && j.kind!=='export'
    && j.document_id===$('notebook').value && j.page_id===$('page').value);
  const rendered=selectionPreview?.document===$('notebook').value && selectionPreview?.page===$('page').value ? selectionPreview : null;
  if(rendered && (!job || rendered.state==='complete')){
    image.hidden=rendered.state!=='complete';$('empty').hidden=rendered.state==='complete';
    $('notebook-preview-label').textContent=rendered.state==='complete'?'Rendered page preview':rendered.state==='failed'?'Preview unavailable: '+rendered.error:rendered.state==='queued'?'Page preview queued…':'Rendering page preview…';
    if(rendered.state==='complete' && image.getAttribute('src')!==rendered.url){
      image.alt='Rendered preview of selected page';image.onerror=()=>{image.hidden=true;};image.src=rendered.url;
    }
    return;
  }
  image.hidden=!job;$('empty').hidden=!!job;
  $('notebook-preview-label').textContent=job?'Saved render · selected page':'No saved preview for this page yet.';
  if(!job){image.removeAttribute('src');return;}
  const source=mediaUrl(job.id,'static.png');
  if(image.getAttribute('src')!==source){
    image.alt=`${job.name} · page ${job.page}`;
    image.onerror=()=>{image.hidden=true;$('notebook-preview-label').textContent='Preview unavailable.';};
    image.src=source;
  }
}
const recentPreviewCache = new Map();
function recentPreview(job) {
  const key=job.id+':'+(job.state==='complete');
  if(recentPreviewCache.has(key))return recentPreviewCache.get(key);
  const tile=document.createElement('span');tile.className='recent-preview';tile.textContent='—';
  if(job.state==='complete'){
    const image=document.createElement('img');image.alt='';image.loading='lazy';image.decoding='async';
    image.src=mediaUrl(job.id,'static.png');
    image.onerror=()=>{tile.replaceChildren();tile.textContent='—';};
    tile.textContent='';tile.append(image);
  }
  recentPreviewCache.set(key,tile);return tile;
}
let queueView=false;
function queueJobs(filter='all'){
  const rank={running:0,queued:1};
  return jobs.filter(j=>filter==='all'||(filter==='active'?['queued','running'].includes(j.state):j.state===filter))
    .slice().sort((a,b)=>(rank[a.state]??2)-(rank[b.state]??2)||(a.state==='queued'&&b.state==='queued'?a.created-b.created:b.created-a.created));
}
function renderJobs(){
  const active=jobs.filter(j=>['queued','running'].includes(j.state)).length;
  $('source-queue').textContent=`Queue${active?' · '+active:''}`;
  $('queue-summary').textContent=`${jobs.filter(j=>j.state==='running').length} running · ${jobs.filter(j=>j.state==='queued').length} waiting · ${jobs.filter(j=>j.state==='complete').length} complete · ${jobs.filter(j=>j.state==='failed').length} failed`;
  const shown=queueView?queueJobs($('queue-filter').value||'all'):jobs;
  $('jobs').replaceChildren();
  if(!shown.length){const p=document.createElement('p');p.className='hint';p.textContent='No replays in this view.';$('jobs').append(p);}
  for(const job of shown){
    const row=document.createElement('div');row.className='job';
    const open=document.createElement('button');open.className='open';
    const label=document.createElement('span');label.className='recent-label';label.textContent=`${job.name} · page ${job.page}`;
    const totalSeconds=(job.state==='complete'?job.frames:job.expected_frames)/job.settings.fps;
    const detail=document.createElement('small');detail.textContent=`${totalSeconds.toFixed(1)}s total · ${job.settings.fps} fps · ${job.settings.ordering==='entry'?'entry order':'by layer'} · ${job.settings.viewport.join(' × ')}${job.finished&&job.started?' · rendered in '+Math.round(job.finished-job.started)+'s':''}`;label.append(detail);open.append(recentPreview(job),label);
    open.onclick=()=>{selectedJob=job.id;previewKey='';showJob(job);};
    const state=document.createElement('span');state.className='state';state.setAttribute('aria-busy',String(['queued','running'].includes(job.state)));state.textContent=job.state+(job.state==='running'&&job.expected_frames?' · '+Math.min(100,Math.round((job.frames||0)/job.expected_frames*100))+'%':'');row.append(open,state);
    if(['queued','running'].includes(job.state)){const cancel=document.createElement('button');cancel.className='quiet';cancel.textContent='Cancel';cancel.onclick=safely(async()=>{await api('/api/cancel',{id:job.id});await poll();});row.append(cancel);}
    if(queueView&&job.error){const error=document.createElement('small');error.className='job-error';error.textContent=job.error;row.append(error);}
    $('jobs').append(row);
  }
}
async function poll() {
  jobs=await api('/api/jobs');
  const previewKeys=new Set(jobs.map(j=>j.id+':'+(j.state==='complete')));
  for(const key of recentPreviewCache.keys())if(!previewKeys.has(key))recentPreviewCache.delete(key);
  showNotebookPreview();
  renderJobs();
  renderPageReplays();
  updateGalleryImages();
  showJob(jobs.find(j=>j.id===selectedJob));
}
let usbBrowseGeneration=0,usbPreviewObserver=null,usbPreviewTask=Promise.resolve(),usbPreviewQueue=[];
const usbPreviewUrls=new Set();
function clearUsbPreviews(){
  usbBrowseGeneration++;usbPreviewObserver?.disconnect();usbPreviewQueue=[];
  for(const url of usbPreviewUrls)URL.revokeObjectURL(url);usbPreviewUrls.clear();
}
function setUsbConnected(connected){
  $('usb-setup').hidden=connected;$('usb-connected').hidden=!connected;
}
function observeUsbPreviews(){
  if(!usbCompanion || typeof IntersectionObserver==='undefined')return;
  const generation=usbBrowseGeneration,client=usbCompanion;
  usbPreviewObserver=new IntersectionObserver(entries=>{
    if(generation!==usbBrowseGeneration)return;
    for(const entry of entries){
      if(entry.isIntersecting){if(!usbPreviewQueue.includes(entry.target))usbPreviewQueue.push(entry.target);}
      else usbPreviewQueue=usbPreviewQueue.filter(slot=>slot!==entry.target);
    }
    usbPreviewTask=usbPreviewTask.then(async()=>{
      while(usbPreviewQueue.length && generation===usbBrowseGeneration && !usbBusy){
        const slot=usbPreviewQueue.shift(),label=slot.children[0];usbPreviewObserver.unobserve(slot);label.setAttribute('aria-busy','true');label.textContent='Loading preview…';
        try{
          const bytes=await client.thumbnail(slot.dataset.usbId);
          if(generation!==usbBrowseGeneration)return;
          if(!bytes){label.textContent='Preview requires companion v0.3.0';continue;}
          const image=document.createElement('img');image.alt='Tablet preview · last opened page';
          const url=URL.createObjectURL(new Blob([bytes],{type:'image/png'}));usbPreviewUrls.add(url);
          image.src=url;image.onerror=()=>{image.hidden=true;label.hidden=false;label.textContent='Preview unavailable';};
          label.hidden=true;slot.append(image);
        }catch{if(generation===usbBrowseGeneration)label.textContent='Preview unavailable';}
        finally{label.setAttribute('aria-busy','false');}
      }
    });
  },{rootMargin:'0px'});
  document.querySelectorAll('[data-usb-id]').forEach(slot=>usbPreviewObserver.observe(slot));
}
async function browse(folder='', label='Tablet') {
  if(usbBusy)return;
  clearUsbPreviews();const generation=usbBrowseGeneration;
  const companion=!!$('usb-companion-use').checked;
  await usbPreviewTask;
  if(generation!==usbBrowseGeneration || companion!==!!$('usb-companion-use').checked)return;
  $('usb-status').setAttribute('aria-busy','true');
  $('usb-status').textContent='Connecting to USB web interface…';$('usb-items').replaceChildren();
  try{
    const entries=$('usb-companion-use').checked
      ? await (usbCompanion || {documents:async()=>{throw new Error('Connect the USB companion first');}}).documents(folder)
      : await api('/api/usb?folder='+encodeURIComponent(folder));
    if(generation!==usbBrowseGeneration || companion!==!!$('usb-companion-use').checked)return;
    setUsbConnected(true);
    $('usb-location').textContent=label;$('usb-status').textContent='Choose a folder or import a notebook.';
    for(const entry of entries.sort((a,b)=>Number(b.folder)-Number(a.folder)||a.name.localeCompare(b.name))){
      const row=document.createElement('div');row.className='notebook-card usb-card';
      const name=document.createElement('span');name.className='notebook-name';name.textContent=entry.name;
      const cover=document.createElement('span');cover.className='notebook-cover usb-cover';
      const placeholder=document.createElement('span');placeholder.className='thumbnail-status';placeholder.textContent=entry.folder?'▱ Folder':companion?'Preview not loaded':'Preview available after import';cover.append(placeholder);
      if(!entry.folder && companion)cover.dataset.usbId=entry.id;
      const action=document.createElement('button');action.textContent=entry.folder?'Open':'Import';
      action.disabled=!!(!entry.folder && entry.file_type && entry.file_type!=='notebook');
      action.dataset.unsupported=String(action.disabled);
      action.onclick=async()=>{
        if(usbBusy)return;
        if(entry.folder){await browse(entry.id,entry.name);return;}
        usbBusy=true;usbPreviewQueue=[];await usbPreviewTask;$('usb-companion-use').disabled=true;document.querySelectorAll('#usb-items button').forEach(b=>b.disabled=true);
        $('usb-status').setAttribute('aria-busy','true');
        $('usb-status').textContent='Saving notebook and verifying two raw reads… This can take a minute.';
        try{const result=$('usb-companion-use').checked
          ? await api('/api/upload',await usbCompanion.download(entry.id),true)
          : await api('/api/usb-import',{id:entry.id,pdf:$('include-pdf').checked});await loadLibrary(result.id);setLibrarySource('local');notice('Notebook saved locally. Choose a page to animate.');}
        catch(error){$('usb-status').textContent=error.message+($('include-pdf').checked?' Try without the PDF for pages without text anchors. Any downloaded raw data is retained locally.':'');}
        finally{$('usb-status').setAttribute('aria-busy','false');usbBusy=false;$('usb-companion-use').disabled=false;document.querySelectorAll('#usb-items button').forEach(b=>b.disabled=b.dataset.unsupported==='true');}
      };action.className='quiet usb-card-action';row.append(cover,name,action);$('usb-items').append(row);
    }
    observeUsbPreviews();
    if(!entries.length)$('usb-status').textContent='This folder is empty.';
  }catch(error){if(generation!==usbBrowseGeneration || companion!==!!$('usb-companion-use').checked)return;setUsbConnected(false);$('usb-status').textContent='USB unavailable: '+error.message+'. Check the cable and USB web interface setting. Saved notebooks still work.';}
  finally{if(generation===usbBrowseGeneration)$('usb-status').setAttribute('aria-busy','false');}
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
  image.src=mediaUrl(job.id,'static.png');
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
  setupExport();setupGallery();
  capabilities=await api('/api/session');token=capabilities.token;
  if(capabilities.hosted){$('usb-companion-use').checked=true;$('usb-companion-settings').hidden=false;}
  const {setupCloud}=await import('/cloud-ui.mjs');
  setupCloud({sessionToken:()=>token,getSavedNotebooks:()=>api('/api/library'),importArchive:async(raw,source)=>{
    const query=capabilities.hosted&&source?.version?'?cloud_id='+encodeURIComponent(source.id)+'&cloud_version='+encodeURIComponent(source.version):'';
    const result=await api('/api/upload'+query,raw,true);
    await loadLibrary(result.id);setLibrarySource('local');notice('Cloud notebook saved locally. Choose a page to animate.');
  }});
  rendererBackend=capabilities.rust?'rust':'python';
  if(!capabilities.ffmpeg)notice(capabilities.hosted?'This browser does not support video encoding. Try current Chrome or Edge.':'FFmpeg was not found. Install it and restart the utility before generating videos.');
  for(const id of ['width','height','offset-x','offset-y'])$(id).oninput=()=>{
    resetClipping();canvasSummary();updateGenerateButton();
    clearTimeout(previewRefreshTimer);
    previewRefreshTimer=setTimeout(()=>requestSelectionPreview(pageRequest),600);
  };
  $('allow-clipping').onchange=updateGenerateButton;
  $('notebook').onchange=safely(selectNotebook);$('page').onchange=safely(selectPage);
  $('refresh').onclick=safely(()=>loadLibrary());$('generate').onclick=safely(generate);
  $('upload-open').onclick=()=>$('upload').click();$('upload').onchange=safely(()=>upload($('upload'),'/api/upload'));
  $('pair-open').onclick=()=>$('pair').click();$('pair').onchange=safely(()=>upload($('pair'),'/api/upload-pdf?document='+encodeURIComponent($('notebook').value)));
  $('usb-up').onclick=()=>browse();
  setupUsbCompanion();
  await loadLibrary();await poll();setInterval(()=>poll().catch(error=>notice('Server unavailable: '+error.message)),2000);
}
safely(start)();


function thumbnailFor(documentId,pageId){
  const cached=pageThumbnails.get(documentId+'/'+pageId);
  if(cached)return cached;
  const job=jobs.find(j=>j.document_id===documentId && (!pageId || j.page_id===pageId) && j.state==='complete' && j.kind!=='export');
  return job?mediaUrl(job.id,'static.png'):null;
}
function thumbnailStatus(documentId,pageId){
  if(thumbnailFor(documentId,pageId))return {state:'complete'};
  const page=library.find(n=>n.id===documentId)?.pages.find(p=>p.id===pageId);
  if(page && !page.available)return {state:'unavailable'};
  return thumbnailStates.get(documentId+'/'+pageId) || {state:'waiting'};
}
function thumbnailProgress(notebook){
  const counts={total:0,ready:0,running:0,queued:0,failed:0,waiting:0};
  for(const page of notebook.pages){
    if(!page.available)continue;
    counts.total++;
    const state=thumbnailStatus(notebook.id,page.id).state;
    counts[state==='complete'?'ready':state]++;
  }
  return counts;
}
function paintThumbnail(slot){
  const {document:documentId,page:pageId}=slot.dataset;
  const status=thumbnailStatus(documentId,pageId),source=thumbnailFor(documentId,pageId);
  const [image,label]=slot.children;
  slot.dataset.state=status.state;
  slot.setAttribute('aria-busy',String(['running','queued'].includes(status.state)));
  label.textContent={complete:'Ready',queued:'Queued',running:'Generating…',failed:'Preview failed',waiting:'Not generated',unavailable:'No saved ink'}[status.state];
  label.hidden=status.state==='complete';slot.title=status.error || label.textContent;
  image.hidden=!source;
  if(source && image.getAttribute('src')!==source)image.src=source;
}
function galleryImage(documentId,pageId){
  const slot=document.createElement('span');slot.className='thumbnail-slot';
  slot.dataset.document=documentId;slot.dataset.page=pageId || '';
  const image=document.createElement('img');image.alt='';image.loading='lazy';image.decoding='async';
  const label=document.createElement('span');label.className='thumbnail-status';
  image.onerror=()=>{image.hidden=true;label.hidden=false;label.textContent='Image unavailable';slot.dataset.state='failed';};
  slot.append(image,label);paintThumbnail(slot);return slot;
}
function updateGalleryProgress(){
  const notebook=library.find(n=>n.id===expandedNotebook);if(!notebook)return;
  const c=thumbnailProgress(notebook);
  $('thumbnail-progress').max=Math.max(1,c.total);$('thumbnail-progress').value=c.ready+c.failed;
  const parts=[`${c.ready} of ${c.total} previews ready`];
  if(c.running)parts.push(`${c.running} generating`);
  if(c.queued)parts.push(`${c.queued} queued`);
  if(c.failed)parts.push(`${c.failed} failed`);
  if(c.waiting)parts.push(`${c.waiting} deferred until visible`);
  $('thumbnail-progress-label').textContent=parts.join(' · ');
}
function updateGalleryImages(){
  document.querySelectorAll('.thumbnail-slot').forEach(paintThumbnail);
  updateGalleryProgress();
}
function renderGallery(){
  if(!$('notebook-gallery'))return;
  const query=$('notebook-search').value.trim().toLocaleLowerCase();
  const grid=$('notebook-gallery');grid.classList.toggle('list-view',galleryList);
  const pages=$('page-gallery');
  const scrollTop=pages.dataset.notebook===expandedNotebook?pages.scrollTop:0;
  const drawer=$('page-drawer');if(drawer.parentElement===grid)grid.after(drawer);grid.replaceChildren();grid.hidden=galleryFocused;
  $('drawer-open').hidden=galleryFocused;$('drawer-close').textContent=galleryFocused?'← All notebooks':'Collapse ↑';
  drawer.classList.toggle('focused-notebook',galleryFocused);
  const matches=library.filter(n=>n.name.toLocaleLowerCase().includes(query));
  for(const notebook of matches){
    const card=document.createElement('button');card.className='notebook-card';
    card.setAttribute('aria-expanded',String(expandedNotebook===notebook.id));
    card.setAttribute('aria-controls','page-drawer');
    const cover=document.createElement('span');cover.className='notebook-cover';
    cover.append(galleryImage(notebook.id,notebook.pages.find(p=>p.available)?.id));
    const title=document.createElement('span');title.className='notebook-name';title.textContent=notebook.name;
    const count=document.createElement('small');count.textContent=notebook.pages.length+' pages';
    const arrow=document.createElement('span');arrow.className='cover-arrow';arrow.textContent=expandedNotebook===notebook.id?'⌄':'›';arrow.setAttribute('aria-hidden','true');
    card.append(cover,title,count,arrow);
    card.onclick=safely(async()=>{if(expandedNotebook===notebook.id){expandedNotebook=null;renderGallery();return;}expandedNotebook=notebook.id;$('notebook').value=notebook.id;await selectNotebook();renderGallery();});
    grid.append(card);
  }
  if(!matches.length){const text=document.createElement('p');text.className='hint';text.textContent=library.length?'No notebooks match your search.':'Connect your reMarkable or import a notebook to begin.';grid.append(text);}
  const notebook=(galleryFocused?library:matches).find(n=>n.id===expandedNotebook);$('page-drawer').hidden=!notebook;
  if(notebook && !galleryFocused){
    const columns=galleryList?1:Math.max(1,getComputedStyle(grid).gridTemplateColumns.split(' ').length);
    const index=matches.findIndex(n=>n.id===notebook.id);const after=Math.min(matches.length-1,Math.floor(index/columns)*columns+columns-1);
    grid.children[after]?.after(drawer);
  }
  pages.dataset.notebook=notebook?.id || '';pages.replaceChildren();if(!notebook){observeGalleryThumbnails();return;}
  $('drawer-title').textContent=notebook.name+' · '+notebook.pages.length+' pages';
  for(const page of notebook.pages){
    const card=document.createElement('button');card.className='page-card';card.disabled=!page.available;
    card.setAttribute('aria-label','Page '+page.number+(page.available?'':' · no saved ink'));
    card.setAttribute('aria-pressed',String($('notebook').value===notebook.id && $('page').value===page.id));
    const paper=document.createElement('span');paper.className='page-paper';paper.append(galleryImage(notebook.id,page.id));
    const number=document.createElement('span');number.textContent=String(page.number);card.append(paper,number);
    card.onclick=safely(async()=>{$('page').value=page.id;await selectPage();});pages.append(card);
  }
  pages.scrollTop=scrollTop;updateGalleryProgress();observeGalleryThumbnails();
}
function observeGalleryThumbnails(){
  if(typeof IntersectionObserver==='undefined')return;
  thumbnailObserver?.disconnect();visibleThumbnailSlots.clear();
  reconcileThumbnailQueue();
  thumbnailObserver=new IntersectionObserver(entries=>{
    for(const entry of entries){
      if(entry.isIntersecting)visibleThumbnailSlots.add(entry.target);
      else visibleThumbnailSlots.delete(entry.target);
    }
    reconcileThumbnailQueue();
  },{root:null,rootMargin:'0px',threshold:0});
  document.querySelectorAll('.thumbnail-slot').forEach(slot=>thumbnailObserver.observe(slot));
}
function reconcileThumbnailQueue(){
  const visible=new Map();
  for(const slot of visibleThumbnailSlots){
    const {document:documentId,page:pageId}=slot.dataset;
    visible.set(documentId+'/'+pageId,{document:documentId,page:pageId});
  }
  for(const key of thumbnailQueue.keys())if(!visible.has(key)){
    thumbnailQueue.delete(key);if(key!==activeThumbnail)thumbnailStates.delete(key);
  }
  for(const [key,item] of visible){
    const state=thumbnailStatus(item.document,item.page).state;
    if(key!==activeThumbnail && ['waiting','queued'].includes(state)){
      thumbnailQueue.set(key,item);thumbnailStates.set(key,{state:'queued'});
    }
  }
  updateGalleryImages();queueMicrotask(processThumbnailQueue);
}
function thumbnailStillVisible(key){
  return [...visibleThumbnailSlots].some(slot=>slot.dataset.document+'/'+slot.dataset.page===key);
}
async function processThumbnailQueue(){
  if(activeThumbnail)return;
  while(thumbnailQueue.size){
    const [key,item]=thumbnailQueue.entries().next().value;thumbnailQueue.delete(key);
    if(thumbnailFor(item.document,item.page))continue;
    activeThumbnail=key;
    try{
      const info=await api(`/api/page?document=${encodeURIComponent(item.document)}&page=${encodeURIComponent(item.page)}`);
      // A scroll while reading metadata must not submit an offscreen render.
      if(!thumbnailStillVisible(key)){thumbnailStates.delete(key);continue;}
      const [width,height]=info.paper_size || [1404,1872];
      const settings={width,height,offset_x:info.source_to_page_transform?.[4] ?? width/2,offset_y:info.source_to_page_transform?.[5] ?? 0,seconds:6,fps:6,output_width:234,backend:rendererBackend};
      let result=await api('/api/page-preview',{...item,settings});
      thumbnailStates.set(key,result);updateGalleryImages();
      while(['queued','running'].includes(result.state)){
        await new Promise(resolve=>setTimeout(resolve,1500));
        result=await api('/api/page-preview?id='+result.id);
        thumbnailStates.set(key,result);updateGalleryImages();
      }
      if(result.state==='complete')pageThumbnails.set(key,result.url);
    }catch(error){thumbnailStates.set(key,{state:'failed',error:error.message});}
    finally{activeThumbnail=null;updateGalleryImages();}
  }
}
function setLibrarySource(source){
  if(source!=='tablet')clearUsbPreviews();
  const cloud=source==='cloud',tablet=source==='tablet';queueView=source==='queue';
  $('library-view-title').textContent=cloud?'Cloud notebooks':tablet?'Connected tablet':queueView?'Replay queue':'Saved notebooks';
  $('queue-controls').hidden=!queueView;
  $('replay-history').classList.toggle('queue-view',queueView);
  $('history-title').textContent=queueView?'Replay queue':'Your replays';
  $('source-queue').setAttribute('aria-pressed',String(queueView));
  $('local-library').hidden=cloud||tablet||queueView;$('cloud-library').hidden=!cloud;
  $('tablet-library').hidden=!tablet;$('source-tablet').setAttribute('aria-pressed',String(tablet));
  $('source-cloud').setAttribute('aria-pressed',String(cloud));
  $('source-local').setAttribute('aria-pressed',String(!cloud&&!tablet&&!queueView));
  $('notebook-search').hidden=cloud||tablet||queueView;$('gallery-grid').hidden=cloud||tablet||queueView;$('gallery-list').hidden=cloud||tablet||queueView;
  renderJobs();
}
function setupSettingPicker(id, buttonsId){
  const select=$(id),buttons=$(buttonsId).querySelectorAll('button');
  const sync=()=>buttons.forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.value===select.value)));
  buttons.forEach(button=>button.onclick=()=>{select.value=button.dataset.value;sync();});
  select.onchange=sync;sync();
}
function setupGallery(){
  $('source-queue').onclick=()=>setLibrarySource('queue');
  $('queue-filter').onchange=renderJobs;
  $('source-local').onclick=()=>setLibrarySource('local');
  $('source-cloud').onclick=()=>setLibrarySource('cloud');
  $('source-tablet').onclick=()=>{setLibrarySource('tablet');if(!$('usb-companion-use').checked||usbCompanion)browse();};
  $('cloud-gallery-refresh').onclick=()=>$('cloud-refresh').onclick();
  $('notebook-search').oninput=renderGallery;
  $('drawer-close').onclick=()=>{if(galleryFocused){galleryFocused=false;renderGallery();return;}expandedNotebook=null;renderGallery();};
  $('drawer-open').onclick=()=>{galleryFocused=true;renderGallery();};
  window.addEventListener('resize',()=>renderGallery());
  for(const [id,list] of [['gallery-grid',false],['gallery-list',true]])$(id).onclick=()=>{galleryList=list;$('gallery-grid').setAttribute('aria-pressed',String(!list));$('gallery-list').setAttribute('aria-pressed',String(list));renderGallery();};
  for(const [id,delta] of [['page-prev',-1],['page-next',1]])$(id).onclick=safely(async()=>{const pages=[...$('page').options].filter(p=>!p.disabled);const i=pages.findIndex(p=>p.value===$('page').value);const next=pages[i+delta];if(next){$('page').value=next.value;await selectPage();}});
  setupSettingPicker('ordering','ordering-buttons');setupSettingPicker('fps','fps-buttons');setupSettingPicker('output-width','output-width-buttons');
  const syncDuration=()=>$('duration-buttons').querySelectorAll('button').forEach(button=>button.setAttribute('aria-pressed',String(Number(button.dataset.seconds)===Number($('seconds').value))));
  $('seconds').oninput=syncDuration;
  $('duration-buttons').querySelectorAll('button').forEach(button=>button.onclick=()=>{$('seconds').value=button.dataset.seconds;syncDuration();});
}

function setupUsbCompanion(){
  $('usb-companion-origin').textContent=location.origin;
  $('usb-settings-toggle').onclick=()=>{$('usb-setup').hidden=!$('usb-setup').hidden;};
  $('usb-companion-use').onchange=()=>{
    clearUsbPreviews();setUsbConnected(false);
    const enabled=$('usb-companion-use').checked;
    $('usb-companion-settings').hidden=!enabled;
    $('include-pdf').disabled=enabled;if(enabled)$('include-pdf').checked=false;
    $('usb-items').replaceChildren();$('usb-status').textContent=enabled?'Start the companion and paste its connection key.':'';
    if(!enabled){usbCompanion?.disconnect();usbCompanion=null;browse();}
  };
  $('usb-companion-connect').onclick=async()=>{
    $('usb-companion-connect').disabled=true;
    $('usb-companion-connect').setAttribute('aria-busy','true');
    try{
      const {createUsbCompanion}=await import('/usb-companion.mjs');
      usbCompanion?.disconnect();usbCompanion=createUsbCompanion();
      const key=$('usb-companion-key').value.trim();$('usb-companion-key').value='';
      await usbCompanion.connect(key);await browse();
    }catch(error){usbCompanion?.disconnect();usbCompanion=null;setUsbConnected(false);$('usb-status').textContent=error.message;}
    finally{$('usb-companion-connect').disabled=false;$('usb-companion-connect').setAttribute('aria-busy','false');}
  };
  $('usb-companion-disconnect').onclick=()=>{clearUsbPreviews();setUsbConnected(false);usbCompanion?.disconnect();usbCompanion=null;$('usb-items').replaceChildren();$('usb-status').textContent='Companion disconnected from this tab.';};
  window.addEventListener('pagehide',()=>usbCompanion?.disconnect());
}

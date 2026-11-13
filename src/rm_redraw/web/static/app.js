const $ = id => document.getElementById(id);
let token = '', library = [], jobs = [], selectedJob = null, pageReady = false, capabilities;
let previewKey = '', pageRequest = 0, usbBusy = false;
let selectionPreview = null, previewRefreshTimer;
let expandedNotebook=null, galleryEpoch=0, galleryList=false, galleryFocused=false;
const pageThumbnails=new Map();
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
  expandedNotebook=$('notebook').value || null;
  await selectNotebook();
  renderGallery();
  warmGallery();
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
      (needsPdf?'Attach a matching notebook PDF to resolve text anchors.':needsPoppler?'Install Poppler and restart the utility to resolve text anchors.':notebook.has_pdf?'Paired PDF saved locally.':'Saved locally.');
    if(info.paper_size){$('width').value=info.paper_size[0];$('height').value=info.paper_size[1];$('offset-x').value=info.paper_size[0]/2;}
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
  Object.assign(settings,{seconds:6,fps:6,output_width:234,backend:$('backend').value});
  try {
    let result=await api('/api/page-preview',{document:pending.document,page:pending.page,settings});
    while(version===pageRequest && selectionPreview===pending){
      Object.assign(pending,result);
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
  $('empty').hidden=true;$('notebook-preview').hidden=true;$('notebook-preview-label').hidden=true;
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
  const source=`/media/${job.id}/static.png`;
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
    image.src=`/media/${job.id}/static.png`;
    image.onerror=()=>{tile.replaceChildren();tile.textContent='—';};
    tile.textContent='';tile.append(image);
  }
  recentPreviewCache.set(key,tile);return tile;
}
async function poll() {
  jobs=await api('/api/jobs');
  const previewKeys=new Set(jobs.map(j=>j.id+':'+(j.state==='complete')));
  for(const key of recentPreviewCache.keys())if(!previewKeys.has(key))recentPreviewCache.delete(key);
  showNotebookPreview();
  $('jobs').replaceChildren();
  if(!jobs.length){const p=document.createElement('p');p.className='hint';p.textContent='Your render queue is empty.';$('jobs').append(p);}
  for(const job of jobs){
    const row=document.createElement('div');row.className='job';
    const open=document.createElement('button');open.className='open';
    const label=document.createElement('span');label.className='recent-label';label.textContent=`${job.name} · page ${job.page}`;
    const totalSeconds=(job.state==='complete'?job.frames:job.expected_frames)/job.settings.fps;
    const detail=document.createElement('small');detail.textContent=`${totalSeconds.toFixed(1)}s total · ${job.settings.fps} fps · ${job.settings.ordering==='entry'?'entry order':'by layer'} · ${job.settings.viewport.join(' × ')}${job.finished&&job.started?' · rendered in '+Math.round(job.finished-job.started)+'s':''}`;label.append(detail);open.append(recentPreview(job),label);
    open.onclick=()=>{selectedJob=job.id;previewKey='';showJob(job);};
    const state=document.createElement('span');state.className='state';state.textContent=job.state;row.append(open,state);
    if(['queued','running'].includes(job.state)){const cancel=document.createElement('button');cancel.className='quiet';cancel.textContent='Cancel';cancel.onclick=safely(async()=>{await api('/api/cancel',{id:job.id});await poll();});row.append(cancel);}
    $('jobs').append(row);
  }
  updateGalleryImages();
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
  setupExport();setupGallery();
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
    clearTimeout(previewRefreshTimer);
    previewRefreshTimer=setTimeout(()=>requestSelectionPreview(pageRequest),600);
  };
  $('backend').onchange=()=>requestSelectionPreview(pageRequest);
  $('allow-clipping').onchange=updateGenerateButton;
  $('notebook').onchange=safely(selectNotebook);$('page').onchange=safely(selectPage);
  $('refresh').onclick=safely(()=>loadLibrary());$('generate').onclick=safely(generate);
  $('upload-open').onclick=()=>$('upload').click();$('upload').onchange=safely(()=>upload($('upload'),'/api/upload'));
  $('pair-open').onclick=()=>$('pair').click();$('pair').onchange=safely(()=>upload($('pair'),'/api/upload-pdf?document='+encodeURIComponent($('notebook').value)));
  $('usb-open').onclick=()=>{$('usb-dialog').showModal();browse();};$('usb-close').onclick=()=>$('usb-dialog').close();$('usb-up').onclick=()=>browse();
  await loadLibrary();await poll();setInterval(()=>poll().catch(error=>notice('Server unavailable: '+error.message)),2000);
}
safely(start)();


function thumbnailFor(documentId,pageId){
  const cached=pageThumbnails.get(documentId+'/'+pageId);
  if(cached)return cached;
  const job=jobs.find(j=>j.document_id===documentId && (!pageId || j.page_id===pageId) && j.state==='complete' && j.kind!=='export');
  return job?`/media/${job.id}/static.png`:null;
}
function galleryImage(documentId,pageId){
  const image=document.createElement('img');image.alt='';image.loading='lazy';image.decoding='async';
  image.dataset.document=documentId;image.dataset.page=pageId || '';
  image.onerror=()=>{image.hidden=true;};
  const source=thumbnailFor(documentId,pageId);image.hidden=!source;if(source)image.src=source;
  return image;
}
function updateGalleryImages(){
  document.querySelectorAll('#notebook-gallery img,#page-gallery img').forEach(image=>{
    const source=thumbnailFor(image.dataset.document,image.dataset.page);
    if(source && image.getAttribute('src')!==source){image.src=source;image.hidden=false;}
  });
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
    card.onclick=safely(async()=>{galleryEpoch++;if(expandedNotebook===notebook.id){expandedNotebook=null;renderGallery();return;}expandedNotebook=notebook.id;$('notebook').value=notebook.id;await selectNotebook();renderGallery();warmGallery();});
    grid.append(card);
  }
  if(!matches.length){const text=document.createElement('p');text.className='hint';text.textContent=library.length?'No notebooks match your search.':'Connect your reMarkable or import a notebook to begin.';grid.append(text);}
  const notebook=(galleryFocused?library:matches).find(n=>n.id===expandedNotebook);$('page-drawer').hidden=!notebook;
  if(notebook && !galleryFocused){
    const columns=galleryList?1:Math.max(1,getComputedStyle(grid).gridTemplateColumns.split(' ').length);
    const index=matches.findIndex(n=>n.id===notebook.id);const after=Math.min(matches.length-1,Math.floor(index/columns)*columns+columns-1);
    grid.children[after]?.after(drawer);
  }
  pages.dataset.notebook=notebook?.id || '';pages.replaceChildren();if(!notebook)return;
  $('drawer-title').textContent=notebook.name+' · '+notebook.pages.length+' pages';
  for(const page of notebook.pages){
    const card=document.createElement('button');card.className='page-card';card.disabled=!page.available;
    card.setAttribute('aria-label','Page '+page.number+(page.available?'':' · no saved ink'));
    card.setAttribute('aria-pressed',String($('notebook').value===notebook.id && $('page').value===page.id));
    const paper=document.createElement('span');paper.className='page-paper';paper.append(galleryImage(notebook.id,page.id));
    const number=document.createElement('span');number.textContent=String(page.number);card.append(paper,number);
    card.onclick=safely(async()=>{$('page').value=page.id;await selectPage();});pages.append(card);
  }
  pages.scrollTop=scrollTop;
}
async function warmGallery(){
  const epoch=++galleryEpoch,notebook=library.find(n=>n.id===expandedNotebook);if(!notebook)return;
  for(const page of notebook.pages){
    if(epoch!==galleryEpoch || expandedNotebook!==notebook.id)return;
    if(!page.available || thumbnailFor(notebook.id,page.id))continue;
    try{
      const info=await api(`/api/page?document=${notebook.id}&page=${encodeURIComponent(page.id)}`);
      if(epoch!==galleryEpoch)return;
      const [width,height]=info.paper_size || [1404,1872];
      const settings={width,height,offset_x:width/2,offset_y:0,seconds:6,fps:6,output_width:234,backend:$('backend').value};
      let result=await api('/api/page-preview',{document:notebook.id,page:page.id,settings});
      while(['queued','running'].includes(result.state)){
        await new Promise(resolve=>setTimeout(resolve,1500));if(epoch!==galleryEpoch)return;
        result=await api('/api/page-preview?id='+result.id);
      }
      if(result.state==='complete'){pageThumbnails.set(notebook.id+'/'+page.id,result.url);updateGalleryImages();}
    }catch{ /* An unavailable page must not block the rest of the notebook. */ }
  }
}
function setupGallery(){
  $('notebook-search').oninput=renderGallery;
  $('drawer-close').onclick=()=>{if(galleryFocused){galleryFocused=false;renderGallery();return;}galleryEpoch++;expandedNotebook=null;renderGallery();};
  $('drawer-open').onclick=()=>{galleryFocused=true;renderGallery();};
  window.addEventListener('resize',()=>renderGallery());
  for(const [id,list] of [['gallery-grid',false],['gallery-list',true]])$(id).onclick=()=>{galleryList=list;$('gallery-grid').setAttribute('aria-pressed',String(!list));$('gallery-list').setAttribute('aria-pressed',String(list));renderGallery();};
  for(const [id,delta] of [['page-prev',-1],['page-next',1]])$(id).onclick=safely(async()=>{const pages=[...$('page').options].filter(p=>!p.disabled);const i=pages.findIndex(p=>p.value===$('page').value);const next=pages[i+delta];if(next){$('page').value=next.value;await selectPage();}});
  $('duration-buttons').querySelectorAll('button').forEach(button=>button.onclick=()=>{$('seconds').value=button.dataset.seconds;$('duration-buttons').querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));});
}

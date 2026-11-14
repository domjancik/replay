export function pageInkBounds(page){
 const visible=new Set(page.groups.filter(g=>g.visible).map(g=>g.group_id));
   const order=new Set(page.replay_order);let bounds=null;
   for(const stroke of page.strokes){if(!visible.has(stroke.group_id)||!order.has(stroke.stroke_id))continue;
    for(const p of stroke.points){const pad=Math.max(8,Math.abs(p.width||0));
     if(!bounds)bounds=[p.x-pad,p.y-pad,p.x+pad,p.y+pad];
     else{bounds[0]=Math.min(bounds[0],p.x-pad);bounds[1]=Math.min(bounds[1],p.y-pad);bounds[2]=Math.max(bounds[2],p.x+pad);bounds[3]=Math.max(bounds[3],p.y+pad);}
    }
   }return bounds;
}
export async function deleteSavedNotebook(db,docs,jobs,id){
 if(!docs.some(doc=>doc.id===id))throw Error('Saved notebook not found');
 if(jobs.some(job=>job.document_id===id&&['queued','running'].includes(job.state)))throw Error('Cancel active replays for this notebook before deleting it.');
 const remaining=docs.filter(doc=>doc.id!==id);
 await new Promise((resolve,reject)=>{
  const tx=db.transaction('records','readwrite'),store=tx.objectStore('records');
  store.delete('archive/'+id);store.delete('pdf/'+id);store.put(remaining,'documents');
  tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error||Error('Could not delete notebook'));
 });
 return remaining;
}
// Notebook archives and generated media stay in this origin's IndexedDB.
export function rpcWorker(){
 const worker=new Worker('/worker.mjs',{type:'module'});let serial=0;const pending=new Map();
 worker.onmessage=({data})=>{const p=pending.get(data.id);if(!p)return;if(data.progress){p.progress?.(data);return;}pending.delete(data.id);data.error?p.reject(Error(data.error)):p.resolve(data.result);};
 worker.onerror=()=>{for(const p of pending.values())p.reject(Error('Browser worker stopped. Try a lower resolution.'));pending.clear();};
 return {call(data,progress){return new Promise((resolve,reject)=>{const id=++serial;pending.set(id,{resolve,reject,progress});worker.postMessage({id,...data});});},stop(){worker.terminate();for(const p of pending.values())p.reject(Error('Cancelled'));pending.clear();}};
}
export async function createBrowserApi(){
 // One library writer prevents two tabs from overwriting each other's queue snapshots.
 if(navigator.locks)await new Promise((resolve,reject)=>{
  navigator.locks.request('replay-library-writer',{ifAvailable:true},lock=>{
   if(!lock){reject(Error('rePlay is already open in another tab. Close that tab and reload here.'));return;}
   resolve();return new Promise(()=>{});
  }).catch(reject);
 });
 const db=await new Promise((resolve,reject)=>{const r=indexedDB.open('replay-library-v1',1);r.onupgradeneeded=()=>r.result.createObjectStore('records');r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});
 const get=key=>new Promise((resolve,reject)=>{const r=db.transaction('records').objectStore('records').get(key);r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});
 const put=(key,value)=>new Promise((resolve,reject)=>{const t=db.transaction('records','readwrite');t.objectStore('records').put(value,key);t.oncomplete=resolve;t.onerror=()=>reject(t.error);t.onabort=()=>reject(t.error||Error('Browser storage is full'));});
 const parser=rpcWorker(),urls=new Map(),previews=new Map();
 let docs=await get('documents')||[],jobs=await get('jobs')||[],running=false,activeWorker=null;
 for(const job of jobs)if(['queued','running'].includes(job.state)){job.state='interrupted';job.error='This browser tab closed before the replay finished.';}
 for(const job of jobs)if(job.state==='complete')for(const file of ['static.png','replay.mp4','manifest.json']){const blob=await get(job.id+'/'+file);if(blob)urls.set(job.id+'/'+file,URL.createObjectURL(blob));}
 const media=(id,file)=>urls.get(id+'/'+file)||'';
 const saveJobs=()=>put('jobs',jobs);
 async function source(document,page){const doc=docs.find(d=>d.id===document),entry=doc?.pages.find(p=>p.id===page&&p.available);if(!entry)throw Error('Page unavailable');return {raw:new Uint8Array(await (await get('archive/'+document)).arrayBuffer()),member:entry.member,page};}
 const anchorCache=new Map();
 async function prepare(body){
  try{
   const src=await source(body.document,body.page);
   const plan=await parser.call({op:'anchors',...src,settings:body.settings});
   let anchor_result;
   if(plan){
    const doc=docs.find(d=>d.id===body.document);
    const pdf=await get('pdf/'+doc.id);
    if(!pdf)throw Error('Attach the matching native PDF to resolve this page’s text anchors');
    const key=JSON.stringify([doc.id,doc.pdf_sha256,body.page,body.settings]);
    anchor_result=anchorCache.get(key);
    if(!anchor_result){
     const {nativeInkMask}=await import('/pdf-reference.mjs');
     const reference=await nativeInkMask(pdf,doc.pages.find(p=>p.id===body.page).number,[body.settings.width,body.settings.height]);
     const worker=rpcWorker();let fits;
     try{fits=await worker.call({op:'match',request:{...reference,templates:plan.templates}});}finally{worker.stop();}
     anchor_result={fits,evidence:`Rust/WASM native anchor matching; PDF SHA256 ${doc.pdf_sha256}; PDF.js 6.5.438 ink-only raster at ${reference.width}x${reference.height}; direct text removed; luminance <245`};
     if(anchorCache.size>=16)anchorCache.delete(anchorCache.keys().next().value);
     anchorCache.set(key,anchor_result);
    }
   }
   const result=await parser.call({op:'prepare',...src,settings:body.settings,anchor_result});
   const rotation=body.settings.rotation??0;
   if(![0,90,180,270].includes(rotation))throw Error('Invalid page rotation');
   result.config.rotation=rotation;
   result.config.output_kind=body.settings.output_kind||'video';
   if(rotation%180)result.config.viewport=[result.config.viewport[1],result.config.viewport[0]];
   if(anchor_result)result.anchor_evidence=anchor_result.evidence;
   return result;
  }catch(error){if(error.message.includes('outside the selected canvas'))error.code='canvas_clipping';throw error;}
 }
 async function storeResult(job,result){
  for(const [file,blob] of [['static.png',result.image],['replay.mp4',result.video],['manifest.json',new Blob([JSON.stringify({settings:job.settings,input:job.input,source_reference:job.source_reference,crop:job.crop,reverse_speed:job.reverse_speed,frames:result.frames,engine:'Rust/WASM',anchor_evidence:job.anchor_evidence,parser:job.parser,finalEqualsStatic:true})],{type:'application/json'})]]){if(!blob)continue;await put(job.id+'/'+file,blob);urls.set(job.id+'/'+file,URL.createObjectURL(blob));}
  job.extension=result.extension;job.frames=job.expected_frames=result.frames;job.state='complete';job.finished=Date.now()/1000;
 }
 async function pump(){
  if(running)return;running=true;
  try{for(let job;job=jobs.find(j=>j.state==='queued');){
   job.state='running';job.started=Date.now()/1000;await saveJobs();
   try{const prepared=await prepare(job.input);if(job.state==='cancelled')continue;
    job.parser=prepared.parser;job.anchor_evidence=prepared.anchor_evidence;job.settings={...prepared.config,viewport:job.crop?job.crop.slice(2):prepared.config.viewport};activeWorker=rpcWorker();
    const result=await activeWorker.call({op:'render',still:job.kind==='image',prepared,crop:job.crop,reverse_speed:job.reverse_speed},p=>{job.frames=p.progress;job.expected_frames=p.total;if(p.image){const key=job.id+'/latest.png';if(urls.has(key))URL.revokeObjectURL(urls.get(key));urls.set(key,URL.createObjectURL(p.image));}});
    if(job.state!=='cancelled')await storeResult(job,result);
   }catch(error){if(job.state!=='cancelled'){job.state='failed';job.error=error.message;}}
   finally{activeWorker?.stop();activeWorker=null;await saveJobs();}
  }}finally{running=false;}
 }
 async function api(path,body){
  const url=new URL(path,location.origin);
  if(url.pathname==='/api/session')return {token:'browser',rust:true,ffmpeg:typeof VideoEncoder!=='undefined',poppler:true,hosted:true};
  if(url.pathname==='/api/library')return docs;
  if(url.pathname==='/api/delete-notebook'){docs=await deleteSavedNotebook(db,docs,jobs,body.id);anchorCache.clear();previews.clear();return {};}
  if(url.pathname==='/api/upload'){
   const blob=body instanceof Blob?body:new Blob([body]);if(blob.size>128*1024*1024)throw Error('Notebook exceeds 128 MiB');
   const info=await parser.call({op:'inspect',raw:new Uint8Array(await blob.arrayBuffer())});
   const cloudId=url.searchParams.get('cloud_id'),cloudVersion=url.searchParams.get('cloud_version');
   let cloud_source;
   if(cloudId||cloudVersion){
    if(!/^[a-f0-9-]{36}$/i.test(cloudId||'')||!/^[a-f0-9]{64}$/i.test(cloudVersion||''))throw Error('Invalid cloud source version');
    cloud_source={id:cloudId,version:cloudVersion};
   }
   const existing=docs.find(d=>d.sha256===info.sha256);if(existing){if(cloud_source){existing.cloud_source=cloud_source;await put('documents',docs);}return existing;}
   const doc={...info,...(cloud_source?{cloud_source}:{}),id:crypto.randomUUID().replaceAll('-','')};await put('archive/'+doc.id,blob);docs.push(doc);await put('documents',docs);return doc;
  }
  if(url.pathname==='/api/upload-pdf'){
   const doc=docs.find(d=>d.id===url.searchParams.get('document'));if(!doc)throw Error('Choose a notebook first');
   const blob=body instanceof Blob?body:new Blob([body]);if(blob.size>128*1024*1024)throw Error('PDF exceeds 128 MiB');
   const {pdfPageCount}=await import('/pdf-reference.mjs');
   if(await pdfPageCount(blob)!==doc.pages.length)throw Error('PDF page count must match the notebook’s ordered pages');
   const digest=await crypto.subtle.digest('SHA-256',await blob.arrayBuffer());
   await put('pdf/'+doc.id,blob);doc.pdf_sha256=[...new Uint8Array(digest)].map(v=>v.toString(16).padStart(2,'0')).join('');doc.has_pdf=true;
   await put('documents',docs);anchorCache.clear();previews.clear();return doc;
  }
  if(url.pathname==='/api/page')return parser.call({op:'info',...await source(url.searchParams.get('document'),url.searchParams.get('page'))});
  if(url.pathname==='/api/jobs'&&!body)return jobs.slice().sort((a,b)=>b.created-a.created);
  if(url.pathname==='/api/jobs'||url.pathname==='/api/export'){
   if(jobs.filter(j=>['queued','running'].includes(j.state)).length>=8)throw Error('Queue is full (8 jobs)');
   let input=body,crop,reverse_speed=0,kind=body.settings?.output_kind==='image'?'image':'replay';
   if(url.pathname==='/api/export'){
    const original=jobs.find(j=>j.id===body.job&&j.state==='complete'&&j.kind!=='export'&&j.kind!=='image');if(!original)throw Error('Choose a completed original replay');
    input=original.input;crop=body.crop;reverse_speed=body.reverse_speed;kind='export';
    if(!Array.isArray(crop)||crop.length!==4||!crop.every(Number.isInteger)||crop[0]<0||crop[1]<0||crop[2]<2||crop[3]<2||crop[0]+crop[2]>original.settings.viewport[0]||crop[1]+crop[3]>original.settings.viewport[1])throw Error('Crop must lie inside the image');
    crop=crop.map(v=>Math.floor(v/2)*2);
    if(![0,2,4,8].includes(reverse_speed))throw Error('Invalid reverse speed');
   }
   const prepared=await prepare(input),doc=docs.find(d=>d.id===input.document);
   const job={id:crypto.randomUUID().replaceAll('-',''),document_id:doc.id,page_id:input.page,page:doc.pages.find(p=>p.id===input.page).number,name:doc.name+(kind==='export'?(reverse_speed?' · loop':' · crop'):''),kind,state:'queued',created:Date.now()/1000,frames:0,expected_frames:kind==='image'?1:prepared.frames.length,settings:prepared.config,input:structuredClone(input),source_reference:{document_id:doc.id,page_id:input.page,archive_sha256:doc.sha256,paired_pdf_sha256:doc.pdf_sha256||null,cloud_source:doc.cloud_source||null},crop,reverse_speed};
   jobs.unshift(job);await saveJobs();pump().catch(error=>{console.error('Queue storage failure');});return job;
  }
  if(url.pathname==='/api/cancel'){const job=jobs.find(j=>j.id===body.id);if(job&&['queued','running'].includes(job.state)){const active=job.state==='running';job.state='cancelled';if(active)activeWorker?.stop();await saveJobs();}return {};}
  if(url.pathname==='/api/canvas-bounds'){
   const prepared=await prepare({...body,settings:{...body.settings,allow_clipping:true}});
   return {bounds:pageInkBounds(prepared.request.page)};
  }
  if(url.pathname==='/api/page-preview'){
   if(!body)return previews.get(url.searchParams.get('id'));
   const id=JSON.stringify(body);if(previews.has(id))return previews.get(id);
   const result={id,state:'queued'};previews.set(id,result);
   (async()=>{let worker;try{const prepared=await prepare({...body,settings:{...body.settings,allow_clipping:true}});result.state='running';worker=rpcWorker();const output=await worker.call({op:'render',prepared,preview:true});result.url=URL.createObjectURL(output.image);result.state='complete';}catch(error){result.state='failed';result.error=error.message;}finally{worker?.stop();}})();return result;
  }
  throw Error(url.pathname.startsWith('/api/usb')?'Hosted USB access requires the optional companion. Enable it in this dialog.':'This operation is not available in the browser edition.');
 }
 return {api,media};
}

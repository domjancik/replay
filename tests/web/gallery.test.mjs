import assert from 'node:assert/strict';
import {test} from 'node:test';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
class Element {
  constructor(){this.children=[];this.value='';this.dataset={};this.attrs={};this.scrollTop=0;this.classList={toggle(){}};}
  setAttribute(k,v){this.attrs[k]=v;}
  getAttribute(k){return this.attrs[k];}
  append(...children){for(const child of children){child.detach();child.parentElement=this;this.children.push(child);}}
  detach(){if(this.parentElement){const siblings=this.parentElement.children;siblings.splice(siblings.indexOf(this),1);this.parentElement=null;}}
  after(child){child.detach();const siblings=this.parentElement.children;siblings.splice(siblings.indexOf(this)+1,0,child);child.parentElement=this.parentElement;}
  replaceChildren(){for(const child of this.children)child.parentElement=null;this.children=[];this.scrollTop=0;}
  querySelectorAll(){return [];}
}
function fixture(){
 const elements=new Map();const el=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
 const root=new Element();root.append(el('notebook-gallery'),el('page-drawer'));el('page-drawer').append(el('page-gallery'));
 const context=vm.createContext({document:{getElementById:el,createElement:()=>new Element()},window:{addEventListener(){}},getComputedStyle:()=>({gridTemplateColumns:'1fr 1fr 1fr 1fr'}),setTimeout,clearTimeout});
 vm.runInContext(readFileSync(new URL('../../src/rm_redraw/web/static/app.js',import.meta.url),'utf8').replace('safely(start)();',''),context);
 vm.runInContext(`library=Array.from({length:6},(_,i)=>({id:String(i),name:'Notebook '+i,pages:Array.from({length:21},(_,p)=>({id:String(p),number:p+1,available:true}))}));expandedNotebook='1';$('notebook').value='1';renderGallery();setupGallery();`,context);
 return {el,context};
}
test('drawer is inline after selected row and opens into pages-only view',()=>{
 const {el}=fixture();assert.equal(el('notebook-gallery').children[4],el('page-drawer'));assert.equal(el('page-gallery').children.length,21);
 el('drawer-open').onclick();assert.equal(el('notebook-gallery').hidden,true);assert.equal(el('page-drawer').hidden,false);assert.equal(el('drawer-open').hidden,true);
 el('drawer-close').onclick();assert.equal(el('notebook-gallery').hidden,false);assert.equal(el('notebook-gallery').children[4],el('page-drawer'));
 el('drawer-close').onclick();assert.equal(el('page-drawer').hidden,true);
});
test('selecting pages preserves internal scroll, switching notebook resets it',()=>{
 const {el,context}=fixture();el('page-gallery').scrollTop=210;vm.runInContext("$('page').value='18';renderGallery();",context);
 assert.equal(el('page-gallery').scrollTop,210);
 assert.equal(el('page-gallery').children[18].attrs['aria-pressed'],'true');
 vm.runInContext("expandedNotebook='2';renderGallery();",context);assert.equal(el('page-gallery').scrollTop,0);
});
test('thumbnail states and notebook counts distinguish queued, running, failed and ready',()=>{
 const {context}=fixture();
 vm.runInContext(`
 pageThumbnails.set('1/0','/ready.png');
 thumbnailStates.set('1/1',{state:'running'});
 thumbnailStates.set('1/2',{state:'failed',error:'Unsupported anchors'});
 thumbnailStates.set('1/3',{state:'queued'});
 `,context);
 const counts=JSON.parse(vm.runInContext("JSON.stringify(thumbnailProgress(library[1]))",context));
 assert.deepEqual(counts,{total:21,ready:1,running:1,queued:1,failed:1,waiting:17});
 assert.equal(vm.runInContext("thumbnailStatus('1','0').state",context),'complete');
 assert.equal(vm.runInContext("thumbnailStatus('1','2').error",context),'Unsupported anchors');
});
test('missing thumbnails display status instead of looking like blank paper',()=>{
 const {context}=fixture();
 assert.equal(vm.runInContext("galleryImage('1','0').children[1].textContent",context),'Not generated');
 vm.runInContext("thumbnailStates.set('1/0',{state:'running'})",context);
 assert.equal(vm.runInContext("galleryImage('1','0').children[1].textContent",context),'Generating…');
});
test('cloud gallery view hides local notebooks and keeps a visible unlock action',()=>{
 const {el,context}=fixture();
 vm.runInContext("setLibrarySource('cloud')",context);
 assert.equal(el('local-library').hidden,true);
 assert.equal(el('cloud-library').hidden,false);
 assert.equal(el('source-cloud').attrs['aria-pressed'],'true');
 vm.runInContext("setLibrarySource('local')",context);
 assert.equal(el('local-library').hidden,false);
 assert.equal(el('cloud-library').hidden,true);
});
test('switching to companion ignores a stale direct USB listing',async()=>{
 const {context,el}=fixture();
 const pending=vm.runInContext("api=()=>new Promise(resolve=>{globalThis.resolveUsb=resolve});browse();",context);
 await new Promise(resolve=>setImmediate(resolve));
 el('usb-companion-use').checked=true;el('usb-status').textContent='Connect companion';
 context.resolveUsb([]);await pending;
 assert.equal(el('usb-status').textContent,'Connect companion');
});
test('only visible thumbnail slots request renders, including covers of unopened notebooks',async()=>{
 const {context}=fixture();const observers=[],requests=[];
 context.IntersectionObserver=class {constructor(callback){this.callback=callback;observers.push(this);}observe(){}disconnect(){}};
 context.queueMicrotask=queueMicrotask;
 context.document.querySelectorAll=()=>context.slots;
 context.slots=vm.runInContext("[galleryImage('0','0'),galleryImage('1','15')]",context);
 context.apiMock=async(path,body)=>{requests.push({path,body});return body?{state:'complete',url:'/preview.png'}:{paper_size:[64,64]};};
 vm.runInContext('api=apiMock;observeGalleryThumbnails()',context);
 assert.equal(requests.length,0);
 observers.at(-1).callback([{target:context.slots[0],isIntersecting:true}]);
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(requests.filter(r=>r.body).length,1);
 assert.equal(requests.find(r=>r.body).body.document,'0');
 assert.equal(vm.runInContext("thumbnailStatus('1','15').state",context),'waiting');
 observers.at(-1).callback([{target:context.slots[0],isIntersecting:false},{target:context.slots[1],isIntersecting:true}]);
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(requests.filter(r=>r.body).length,2);
 assert.equal(requests.at(-1).body.page,'15');
});
test('scrolling away before metadata resolves prevents an offscreen render',async()=>{
 const {context}=fixture();let observer,resolveInfo;const calls=[];
 context.IntersectionObserver=class {constructor(callback){observer=callback;}observe(){}disconnect(){}};
 context.queueMicrotask=queueMicrotask;context.document.querySelectorAll=()=>context.slots;
 context.slots=vm.runInContext("[galleryImage('0','0')]",context);
 context.apiMock=path=>{calls.push(path);return new Promise(resolve=>{resolveInfo=resolve;});};
 vm.runInContext('api=apiMock;observeGalleryThumbnails()',context);
 observer([{target:context.slots[0],isIntersecting:true}]);await new Promise(resolve=>setImmediate(resolve));
 observer([{target:context.slots[0],isIntersecting:false}]);resolveInfo({paper_size:[64,64]});await new Promise(resolve=>setImmediate(resolve));
 assert.equal(calls.length,1);assert.equal(vm.runInContext("thumbnailStatus('0','0').state",context),'waiting');
});

test('dedicated queue hides notebooks and restores gallery on exit',()=>{
 const {el}=fixture();el('source-queue').onclick();
 assert.equal(el('local-library').hidden,true);
 assert.equal(el('cloud-library').hidden,true);
 assert.equal(el('queue-controls').hidden,false);
 assert.equal(el('source-queue').attrs['aria-pressed'],'true');
 el('source-local').onclick();
 assert.equal(el('queue-controls').hidden,true);
 assert.equal(el('local-library').hidden,false);
});
test('queue filters active work and sorts waiting jobs oldest first',()=>{
 const {context}=fixture();
 vm.runInContext(`jobs=[{id:'new',state:'queued',created:3},{id:'done',state:'complete',created:0},{id:'old',state:'queued',created:1},{id:'run',state:'running',created:2}];`,context);
 assert.deepEqual(JSON.parse(vm.runInContext("JSON.stringify(queueJobs('active').map(j=>j.id))",context)),['run','old','new']);
 assert.deepEqual(JSON.parse(vm.runInContext("JSON.stringify(queueJobs('complete').map(j=>j.id))",context)),['done']);
});

test('selected page lists only its completed replays including exports and opens a saved video',()=>{
 const {context,el}=fixture();el('page').value='4';
 vm.runInContext(`jobs=[
 {id:'older',document_id:'1',page_id:'4',state:'complete',created:1,frames:24,settings:{fps:12,viewport:[702,936]}},
 {id:'loop',kind:'export',document_id:'1',page_id:'4',state:'complete',created:3,frames:36,settings:{fps:12,viewport:[468,624]}},
 {id:'other',document_id:'2',page_id:'4',state:'complete'},
 {id:'pending',document_id:'1',page_id:'4',state:'running'},
 {id:'page',document_id:'1',page_id:'5',state:'complete'}];renderPageReplays();`,context);
 assert.equal(el('page-replays').hidden,false);
 assert.equal(el('page-replay-list').children.length,2);
 el('page-replay-list').children[0].onclick();
 assert.equal(el('video').src,'/media/loop/replay.mp4');
 assert.equal(el('download-video').href,'/media/loop/replay.mp4');
 el('page').value='9';vm.runInContext('renderPageReplays()',context);
 assert.equal(el('page-replays').hidden,true);
 assert.equal(el('page-replay-list').children.length,0);
});

test('tablet is an inline notebook source and switching sources hides its controls',()=>{
 const {el,context}=fixture();
 el('usb-companion-use').checked=true;
 el('source-tablet').onclick();
 assert.equal(el('tablet-library').hidden,false);
 assert.equal(el('local-library').hidden,true);
 assert.equal(el('cloud-library').hidden,true);
 assert.equal(el('source-tablet').attrs['aria-pressed'],'true');
 assert.equal(el('source-local').attrs['aria-pressed'],'false');
 vm.runInContext("setLibrarySource('cloud')",context);
 assert.equal(el('tablet-library').hidden,true);
 assert.equal(el('source-tablet').attrs['aria-pressed'],'false');
});


test('source views identify their content separately from the saved library',()=>{
 const {el}=fixture();
 el('source-cloud').onclick();
 assert.equal(el('library-view-title').textContent,'Cloud notebooks');
 el('source-local').onclick();
 assert.equal(el('library-view-title').textContent,'Saved notebooks');
 el('source-queue').onclick();
 assert.equal(el('library-view-title').textContent,'Replay queue');
});

test('file import returns from a remote source to saved notebooks',async()=>{
 const {el,context}=fixture();
 el('source-cloud').onclick();
 vm.runInContext("api=async()=>({id:'new'});loadLibrary=async()=>{};",context);
 await vm.runInContext("upload({files:[{size:10}],value:'file'},'/api/upload')",context);
 assert.equal(el('local-library').hidden,false);
 assert.equal(el('cloud-library').hidden,true);
});


test('connected USB collapses setup and can restore it on disconnect',()=>{
 const {el,context}=fixture();
 vm.runInContext('setUsbConnected(true)',context);
 assert.equal(el('usb-setup').hidden,true);
 assert.equal(el('usb-connected').hidden,false);
 vm.runInContext('setUsbConnected(false)',context);
 assert.equal(el('usb-setup').hidden,false);
 assert.equal(el('usb-connected').hidden,true);
});


test('USB listings use gallery cards and collapse connection setup',async()=>{
 const {el,context}=fixture();
 vm.runInContext("api=async()=>[{id:'folder',name:'Drawings',folder:true},{id:'doc',name:'Sketch',folder:false,file_type:'notebook'}]",context);
 await vm.runInContext('browse()',context);
 assert.equal(el('usb-items').children.length,2);
 assert.equal(el('usb-items').children[0].className,'notebook-card usb-card');
 assert.equal(el('usb-items').children[0].children[2].textContent,'Open');
 assert.equal(el('usb-items').children[1].children[2].textContent,'Import');
 assert.equal(el('usb-setup').hidden,true);
});


test('USB previews read only visible cards and skip queued cards scrolled away',async()=>{
 const {context}=fixture();let observer,finish;const calls=[];
 const slots=[new Element(),new Element()];
 slots.forEach((slot,i)=>{slot.dataset.usbId=String(i);slot.append(new Element());});
 context.IntersectionObserver=class{constructor(callback){observer=callback;}observe(){}unobserve(){}disconnect(){}};
 context.document.querySelectorAll=()=>slots;
 context.thumbnail=async id=>{calls.push(id);await new Promise(resolve=>{finish=resolve;});return null;};
 vm.runInContext('usbCompanion={thumbnail};observeUsbPreviews()',context);
 assert.equal(calls.length,0);
 observer([{target:slots[0],isIntersecting:true},{target:slots[1],isIntersecting:true}]);
 await new Promise(resolve=>setImmediate(resolve));assert.deepEqual(calls,['0']);
 observer([{target:slots[1],isIntersecting:false}]);finish();
 await vm.runInContext('usbPreviewTask',context);assert.deepEqual(calls,['0']);
});


test('work indicator persists until all pending actions settle, including errors',async()=>{
 const {context,el}=fixture();
 vm.runInContext("requestApi=()=>new Promise((resolve,reject)=>{globalThis.finishWork=resolve;globalThis.failWork=reject;})",context);
 const pending=vm.runInContext("api('/api/upload',{})",context);
 assert.equal(el('work-status').hidden,false);
 context.failWork(new Error('test failure'));await assert.rejects(pending,/test failure/);
 assert.equal(el('work-status').hidden,true);
});

test('frame rate and resolution pickers update render settings and selected state',()=>{
 const {el,context}=fixture();
 for(const [id,values] of [['fps',['6','12','24','30']],['output-width',['468','702','1404','2106','2808']],['ordering',['layer','entry']]]){
  const buttons=values.map(value=>{const button=new Element();button.dataset.value=value;return button;});
  el(id).value=values[0];el(id+'-buttons').querySelectorAll=()=>buttons;
  vm.runInContext(`setupSettingPicker('${id}','${id}-buttons')`,context);
  buttons[1].onclick();assert.equal(el(id).value,values[1]);assert.equal(buttons[1].attrs['aria-pressed'],'true');
  assert.equal(buttons[0].attrs['aria-pressed'],'false');
 }
});

test('custom duration accepts fractional seconds and rejects values outside the supported range',()=>{
 const {el,context}=fixture();
 el('seconds').value='180.5';assert.equal(vm.runInContext('readDuration()',context),180.5);
 for(const value of ['', '0', '1.5', '-2', 'abc']){
  el('seconds').value=value;assert.throws(()=>vm.runInContext('readDuration()',context),/duration/i);
 }
});

test('duration warning appears only above two minutes',()=>{
 const {el}=fixture();
 el('seconds').value='120';el('seconds').oninput();assert.equal(el('duration-warning').hidden,true);
 el('seconds').value='121';el('seconds').oninput();assert.equal(el('duration-warning').hidden,false);
});

test('auto canvas includes off-page ink without changing relative stroke positions',()=>{
 const {context}=fixture();
 const result=vm.runInContext('fitCanvas({width:1404,height:1872,offset_x:702,offset_y:0},[-100,-30,1500,2100])',context);
 assert.equal(result.offset_x,802);assert.equal(result.offset_y,30);assert.equal(result.width,1600);assert.equal(result.height,2130);
 const crop=vm.runInContext('canvasCrop({width:1600,height:2130,offset_x:802,offset_y:30},[100,50,800,1000])',context);
 assert.equal(crop.width,800);assert.equal(crop.offset_x,702);assert.equal(crop.offset_y,-20);
});

test('replay settings restore custom duration, output width, crop offsets and ordering',()=>{
 const {el,context}=fixture();
 vm.runInContext("restoreReplaySettings({width:800,height:900,offset_x:123,offset_y:-45,seconds:180.5,fps:24,output_width:2106,ordering:'entry',allow_clipping:true})",context);
 assert.equal(Number(el('seconds').value),180.5);assert.equal(Number(el('output-width').value),2106);
 assert.equal(Number(el('offset-y').value),-45);assert.equal(el('ordering').value,'entry');assert.equal(el('allow-clipping').checked,true);
});

test('final image works without video encoding support and restores its mode',()=>{
 const {el,context}=fixture();
 vm.runInContext(`capabilities={hosted:true,ffmpeg:false};pageReady=true;$('canvas-clipping').hidden=true;$('output-kind').value='image';syncOutputKind();`,context);
 assert.equal(el('generate').disabled,false);
 assert.equal(el('generate').textContent,'Create image');
 assert.equal(el('fps').disabled,true);
 vm.runInContext(`restoreReplaySettings({output_kind:'image',rotation:90});`,context);
 assert.equal(el('output-kind').value,'image');
 vm.runInContext(`$('output-kind').value='video';syncOutputKind();`,context);
 assert.equal(el('generate').disabled,true);
 assert.equal(el('fps').disabled,false);
});

test('image mode hides timing selectors and output toggle restores them',()=>{
 const {el,context}=fixture();
 vm.runInContext(`capabilities={ffmpeg:true};$('output-kind').value='image';syncOutputKind();`,context);
 for(const id of ['duration-row','ordering-picker','fps-picker'])assert.equal(el(id).hidden,true);
 vm.runInContext(`$('output-kind').value='video';syncOutputKind();`,context);
 for(const id of ['duration-row','ordering-picker','fps-picker'])assert.equal(el(id).hidden,false);
});
test('custom duration input is visible only when Custom is selected',()=>{
 const {el,context}=fixture();
 vm.runInContext(`chooseDuration('12')`,context);assert.equal(el('custom-duration').hidden,true);
 vm.runInContext(`chooseDuration('custom')`,context);assert.equal(el('custom-duration').hidden,false);
 el('seconds').value='12';el('seconds').oninput();assert.equal(el('custom-duration').hidden,false);
 vm.runInContext(`chooseDuration('24')`,context);assert.equal(el('custom-duration').hidden,true);assert.equal(el('seconds').value,'24');
 vm.runInContext(`restoreReplaySettings({seconds:75})`,context);assert.equal(el('custom-duration').hidden,false);
});

test('gallery controls initialize at the real script startup position',()=>{
 const elements=new Map();const el=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
 const context=vm.createContext({document:{getElementById:el},window:{addEventListener(){}}});
 const source=readFileSync(new URL('../../src/rm_redraw/web/static/app.js',import.meta.url),'utf8');
 // Exercise synchronous control setup where production invokes start, not after evaluation.
 vm.runInContext(source.replace('safely(start)();','setupGallery();'),context);
 assert.equal(el('custom-duration').hidden,true);
});

test('selected page preview uses loading and failure states instead of no selection',()=>{
 const {el,context}=fixture();el('page').value='0';
 for(const state of ['queued','running','failed']){
  vm.runInContext(`selectionPreview={document:'1',page:'0',state:'${state}',error:'Example failure'};showNotebookPreview();`,context);
  assert.equal(el('empty').hidden,false);
  assert.notEqual(el('empty-title').textContent,'No page selected.');
  assert.equal(el('empty').attrs['aria-busy'],String(state!=='failed'));
 }
 assert.equal(el('empty-title').textContent,'Preview unavailable');
 vm.runInContext(`selectionPreview={document:'1',page:'0',state:'complete',url:'blob:preview'};showNotebookPreview();`,context);
 assert.equal(el('empty').hidden,true);
 el('page').value='';el('notebook-preview').removeAttribute=()=>{};
 vm.runInContext('selectionPreview=null;showNotebookPreview();',context);
 assert.equal(el('empty-title').textContent,'No page selected.');
});

test('crop handles resize, interior drag preserves size, and bounds clamp movement',()=>{
 const {context}=fixture();const run=code=>JSON.parse(vm.runInContext(`JSON.stringify(${code})`,context));
 assert.equal(vm.runInContext(`cropHandle([20,20,60,50],[20,20],5)`,context),'nw');
 assert.equal(vm.runInContext(`cropHandle([20,20,60,50],[50,40],5)`,context),'move');
 assert.deepEqual(run(`dragCrop([20,20,60,50],[30,30],[100,100],'move',100,100,10)`),[40,50,60,50]);
 assert.deepEqual(run(`dragCrop([20,20,60,50],[20,20],[10,5],'nw',100,100,10)`),[10,5,70,65]);
 assert.deepEqual(run(`dragCrop([20,20,60,50],[80,70],[0,0],'se',100,100,10)`),[20,20,10,10]);
});
test('crop rectangles round trip through every page rotation',()=>{
 const {context}=fixture();
 for(const rotation of [0,90,180,270])assert.equal(vm.runInContext(`JSON.stringify(rotateCrop(rotateCrop([10,20,30,40],100,200,${rotation}),${rotation%180?200:100},${rotation%180?100:200},${(360-rotation)%360}))`,context),'[10,20,30,40]');
});

test('locked crop ratios survive every resize handle and canvas boundaries',()=>{
 const {context}=fixture();
 for(const ratio of [1,4/5,9/16])for(const mode of ['nw','n','ne','e','se','s','sw','w','new']){
  const rect=JSON.parse(vm.runInContext(`JSON.stringify(dragCrop([20,20,40,40/${ratio}],[30,30],[500,500],'${mode}',200,200,2,${ratio}))`,context));
  assert.ok(Math.abs(rect[2]/rect[3]-ratio)<1e-10,mode);
  assert.ok(rect[0]>=0&&rect[1]>=0&&rect[0]+rect[2]<=200.00001&&rect[1]+rect[3]<=200.00001,mode);
 }
});
test('ratio presets fit inside existing selection and preserve its center',()=>{
 const {context}=fixture();
 assert.equal(vm.runInContext('JSON.stringify(fitCropRatio([10,20,100,100],4/5))',context),'[20,20,80,100]');
});

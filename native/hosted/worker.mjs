import {replayIndices,ReverseFrameCache} from './replay-frames.mjs';
import {rotateFrame} from './rotation.mjs';
import {instantiateRenderer} from './renderer.mjs';
let reader, renderer, anchorCore;
async function bytes(url){const r=await fetch(url);if(!r.ok)throw Error(`Could not load browser engine (${r.status})`);return new Uint8Array(await r.arrayBuffer());}
async function png(frame,maxSide=Infinity){
 const c=new OffscreenCanvas(frame.width,frame.height);c.getContext('2d').putImageData(new ImageData(new Uint8ClampedArray(frame.rgba),frame.width,frame.height),0,0);
 const scale=Math.min(1,maxSide/Math.max(frame.width,frame.height));
 if(scale===1)return c.convertToBlob({type:'image/png'});
 const small=new OffscreenCanvas(Math.max(1,Math.round(frame.width*scale)),Math.max(1,Math.round(frame.height*scale)));
 small.getContext('2d').drawImage(c,0,0,small.width,small.height);return small.convertToBlob({type:'image/png'});
}
async function execute(data,id){
 if(data.op==='match'){const {instantiateCore}=await import('/core.mjs');anchorCore??=await instantiateCore(await bytes('/replay-core.wasm'));return anchorCore.match(data.request);}
 if(data.op==='render'){
  const now=()=>globalThis.performance?.now()??Date.now();
  const started=now();const timings={staticMs:0,framesMs:0,previewMs:0,reverseCacheHits:0};
  renderer??=await instantiateRenderer(await bytes('/renderer.wasm'));
  const {request,frames,config}=data.prepared;
  const nativeFinal=renderer.render({...request,visibility:null});
  const final=rotateFrame(nativeFinal,config.rotation||0);
  const image=await png(final);timings.staticMs=now()-started;
  if(data.preview)return {image};
  if(data.still)return {image,frames:1,extension:'.png',timings:{...timings,totalMs:now()-started}};
  const {encodeReplay}=await import('/encoder.mjs');
  const indices=replayIndices(frames.length,config.fps,data.reverse_speed);
  const reverseCache=new ReverseFrameCache(indices.slice(frames.length));
  renderer.load?.(request);
  let lastPreview=-Infinity;
  const crop=data.crop;
  const width=crop?crop[2]:final.width,height=crop?crop[3]:final.height;
  function cropped(rgba){if(!crop)return rgba;const [x,y,w,h]=crop;const result=new Uint8Array(w*h*4);for(let row=0;row<h;row++)result.set(rgba.subarray(((row+y)*final.width+x)*4,((row+y)*final.width+x+w)*4),row*w*4);return result;}
  async function* produce(){for(let i=0;i<indices.length;i++){
   let rgba=i>=frames.length?reverseCache.take(indices[i]):null;
   if(rgba)timings.reverseCacheHits++;
   if(!rgba){
    const frameStart=now();
    const frame=renderer.frame?renderer.frame(frames[indices[i]]):renderer.render({...request,visibility:frames[indices[i]]});
    const rotated=rotateFrame(frame,config.rotation||0).rgba;
    if(i===frames.length-1 && !rotated.every((v,k)=>v===final.rgba[k]))throw Error('Final replay frame differs from static rendering');
    rgba=cropped(rotated);timings.framesMs+=now()-frameStart;
   }
   if(i<frames.length)reverseCache.put(indices[i],rgba);
   const preview=performance.now()-lastPreview>=1500;
   if(preview)lastPreview=performance.now();
   let previewImage;
   if(preview){const previewStart=now();previewImage=await png({width,height,rgba},384);timings.previewMs+=now()-previewStart;}
   postMessage({id,progress:i+1,total:indices.length,...(previewImage?{image:previewImage}:{})});yield rgba;
  }}
  const video=await encodeReplay({frames:produce(),width,height,fps:config.fps,frameCount:indices.length});
  return {image:crop?await png({width,height,rgba:cropped(final.rgba)}):image,video:new Blob([video.buffer],{type:video.mimeType}),extension:video.extension,frames:indices.length,timings:{...timings,totalMs:now()-started}};
 }
 const {instantiateReader}=await import('./reader.mjs');reader??=await instantiateReader(await bytes('/rmdoc.wasm'));
 const {raw,...args}=data;const result=reader.execute(raw,args);
 if(data.op==='prepare' && data.settings?.output_kind==='image'){result.frames=[];}
 else if(data.op==='prepare'){const {instantiateCore}=await import('/core.mjs');anchorCore??=await instantiateCore(await bytes('/replay-core.wasm'));result.frames=anchorCore.match({op:'schedule',page:result.request.page,fps:result.config.fps,seconds:result.config.seconds,ordering:result.config.ordering});}
 return result;
}
let queue=Promise.resolve();
self.onmessage=({data:{id,...data}})=>{queue=queue.then(async()=>{try{postMessage({id,result:await execute(data,id)});}catch(error){postMessage({id,error:error.message});}});};

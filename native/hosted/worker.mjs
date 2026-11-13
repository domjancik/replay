import {instantiateRenderer} from './renderer.mjs';
let python, renderer;
async function bytes(url){const r=await fetch(url);if(!r.ok)throw Error(`Could not load browser engine (${r.status})`);return new Uint8Array(await r.arrayBuffer());}
async function runtime(){
 if(!python){
  const {loadPyodide}=await import('/runtime/pyodide.mjs');
  python=await loadPyodide({indexURL:'/runtime/',packages:['numpy','pillow']});
  for(const name of ['engine.zip','rmscene-0.8.0-py3-none-any.whl','packaging-23.2-py3-none-any.whl']){
   python.FS.writeFile('/'+name,await bytes('/runtime/'+name));
  }
  python.runPython("import sys, json\nsys.path[:0]=['/engine.zip','/rmscene-0.8.0-py3-none-any.whl','/packaging-23.2-py3-none-any.whl']\nimport bridge");
 }
 return python;
}
async function png(frame){const c=new OffscreenCanvas(frame.width,frame.height);c.getContext('2d').putImageData(new ImageData(new Uint8ClampedArray(frame.rgba),frame.width,frame.height),0,0);return c.convertToBlob({type:'image/png'});}
async function execute(data,id){
 if(data.op==='render'){
  renderer??=await instantiateRenderer(await bytes('/renderer.wasm'));
  const {request,frames,config}=data.prepared;
  const final=renderer.render({...request,visibility:null});
  const image=await png(final);
  if(data.preview)return {image};
  const {encodeReplay}=await import('/encoder.mjs');
  const indices=frames.map((_,i)=>i);
  if(data.reverse_speed){for(let i=Math.max(0,frames.length-config.fps-2);i>=0;i-=data.reverse_speed)indices.push(i);if(indices.at(-1)!==0)indices.push(0);}
  const crop=data.crop;
  const width=crop?crop[2]:final.width,height=crop?crop[3]:final.height;
  function cropped(rgba){if(!crop)return rgba;const [x,y,w,h]=crop;const result=new Uint8Array(w*h*4);for(let row=0;row<h;row++)result.set(rgba.subarray(((row+y)*final.width+x)*4,((row+y)*final.width+x+w)*4),row*w*4);return result;}
  async function* produce(){for(let i=0;i<indices.length;i++){
   const rgba=renderer.render({...request,visibility:frames[indices[i]]}).rgba;
   if(i===frames.length-1 && !rgba.every((v,k)=>v===final.rgba[k]))throw Error('Final replay frame differs from static rendering');
   postMessage({id,progress:i+1,total:indices.length,...(i%config.fps===0?{image:await png({width,height,rgba:cropped(rgba)})}:{})});yield cropped(rgba);
  }}
  const video=await encodeReplay({frames:produce(),width,height,fps:config.fps,frameCount:indices.length});
  return {image:crop?await png({width,height,rgba:cropped(final.rgba)}):image,video:new Blob([video.buffer],{type:video.mimeType}),extension:video.extension,frames:indices.length};
 }
 const py=await runtime();py.globals.set('raw_js',data.raw);py.globals.set('args_json',JSON.stringify(data));
 try{return JSON.parse(py.runPython(`
a=json.loads(args_json)
raw=bytes(raw_js.to_py())
if a['op']=='inspect': result=bridge.inspect(raw)
elif a['op']=='info': result=bridge.info(bridge.page_bytes(raw,a['member']),a['page'])
elif a['op']=='prepare': result=bridge.prepare(bridge.page_bytes(raw,a['member']),a['page'],a['settings'])
json.dumps(result)
`));}finally{py.globals.delete('raw_js');py.runPython('del raw, a, result');}
}
let queue=Promise.resolve();
self.onmessage=({data:{id,...data}})=>{queue=queue.then(async()=>{try{postMessage({id,result:await execute(data,id)});}catch(error){postMessage({id,error:error.message});}});};

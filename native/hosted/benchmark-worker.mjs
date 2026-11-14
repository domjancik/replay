import {instantiateRenderer} from './renderer.mjs';
import {benchmarkScene} from './benchmark-scenes.mjs';
self.onmessage=async({data})=>{
 try{
  const response=await fetch('/renderer.wasm');if(!response.ok)throw Error('Could not load renderer');
  const renderer=await instantiateRenderer(await response.arrayBuffer());
  const {page,frames}=benchmarkScene(...data.scene);renderer.load({page});
  let final;const start=performance.now();
  for(const frame of frames.slice(data.start,data.end))final=renderer.frame(frame);
  postMessage({renderMs:performance.now()-start,memoryBytes:renderer.memoryBytes,frames:Math.min(data.end,frames.length)-data.start,finalSize:[final.width,final.height]});
 }catch(error){postMessage({error:error.message});}
};

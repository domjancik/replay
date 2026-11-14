import {benchmarkScene} from './benchmark-scenes.mjs';
import {readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {instantiateRenderer} from './renderer.mjs';
const output=process.argv[2]||'artifacts/mobile-performance/latest.json';
const wasm=await readFile(process.argv[3]||'native/redraw/target/wasm32-unknown-unknown/release/redraw.wasm');
const report=[];
for(const [name,width,layers,points,tool] of [['detailed-page',192,2,250,17],['pencil-replay',384,2,2,14],['many-layers',768,26,2,17]]){
 const {page,frames}=benchmarkScene(name,width,layers,points,tool);
 const runs=[];let hashes;
 for(let run=0;run<3;run++){
  const renderer=await instantiateRenderer(wasm),request={page};const start=performance.now();
  if(renderer.load)renderer.load(request);
  const digest=createHash('sha256');
  for(const visibility of frames){const f=renderer.frame?renderer.frame(visibility):renderer.render({...request,visibility});digest.update(f.rgba);}
  runs.push(performance.now()-start);hashes=digest.digest('hex');
  if(run===2)report.push({name,width,layers,points,frames:frames.length,ms:runs,medianMs:[...runs].sort((a,b)=>a-b)[1],wasmMemoryBytes:renderer.memoryBytes,sha256:hashes});
 }
}
await writeFile(output,JSON.stringify({runtime:process.version,platform:process.platform,report},null,2));console.log(JSON.stringify(report,null,2));

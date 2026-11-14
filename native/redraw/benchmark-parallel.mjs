import {Worker,isMainThread,parentPort,workerData} from 'node:worker_threads';
import {readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import assert from 'node:assert/strict';
import {instantiateRenderer} from './renderer.mjs';
import {benchmarkScene} from './benchmark-scenes.mjs';
const wasm=await readFile('native/redraw/target/wasm32-unknown-unknown/release/redraw.wasm');
async function run(request,frames){const renderer=await instantiateRenderer(wasm);renderer.load(request);const hashes=frames.map(v=>createHash('sha256').update(renderer.frame(v).rgba).digest('hex'));return {hashes,memory:renderer.memoryBytes};}
if(!isMainThread){parentPort.postMessage(await run(workerData.request,workerData.frames));}
else {
 const reports=[];
 for(const args of [['detailed-page',192,2,250,17],['pencil-replay',384,2,2,14],['many-layers',768,26,2,17]]){
  const {page,frames}=benchmarkScene(...args),runs=[];let last;
  for(let i=0;i<3;i++){
   let start=performance.now();const serial=await run({page},frames);const serialMs=performance.now()-start;
   start=performance.now();const parallel=await Promise.all([frames.slice(0,40),frames.slice(40)].map(chunk=>new Promise((resolve,reject)=>{const worker=new Worker(new URL(import.meta.url),{workerData:{request:{page},frames:chunk}});worker.on('message',resolve);worker.on('error',reject);worker.on('exit',code=>{if(code)reject(Error('worker failed '+code));});})));
   const parallelMs=performance.now()-start;assert.deepEqual(parallel.flatMap(r=>r.hashes),serial.hashes);runs.push({serialMs,parallelMs});last={serialMemory:serial.memory,parallelMemory:parallel.reduce((n,r)=>n+r.memory,0)};
  }
  reports.push({name:args[0],runs,...last,allFramesExact:true});
 }
 await writeFile('artifacts/mobile-performance/parallel.json',JSON.stringify(reports,null,2));console.log(JSON.stringify(reports,null,2));
}

import {instantiateRenderer} from './renderer.mjs';
import {readFile,writeFile} from 'node:fs/promises';
import assert from 'node:assert/strict';
const wasm=await readFile('native/renderer/target/wasm32-unknown-unknown/release/rm_renderer.wasm');
const cached=await instantiateRenderer(wasm),cold=await instantiateRenderer(wasm);
const page={page_id:'benchmark',paper_size:[192,256],groups:[{group_id:'a',visible:true},{group_id:'b',visible:true}],compositing_order:['a','b'],strokes:Array.from({length:40},(_,i)=>({stroke_id:String(i),group_id:i%2?'b':'a',rgba:[20,20,20,180],thickness_scale:2,tool_code:i%13===12?6:14,points:[{x:10,y:8+i*5,width:12,pressure:180},{x:175,y:20+i*5,width:18,pressure:230}]}))};
const requests=Array.from({length:180},(_,i)=>{const pos=Math.min(40,i/4);const count=Math.floor(pos);return {page,visibility:{completed_stroke_ids:page.strokes.slice(0,count).map(s=>s.stroke_id),active_stroke_id:count<40?String(count):null,active_progress:pos-count}};});
function run(renderer,reset){const start=performance.now();const outputs=requests.map((r,i)=>renderer.render({...r,page:reset?{...page,page_id:'cold'+i}:page}).rgba);return {ms:performance.now()-start,outputs};}
run(cached,false);run(cold,true);
const before=run(cold,true),after=run(cached,false);
after.outputs.forEach((rgba,i)=>assert.deepEqual(rgba,before.outputs[i]));
assert.deepEqual(cached.render({page}).rgba,after.outputs.at(-1));
// Backward and non-prefix visibility must still match a fresh identity.
for(const ids of [['3','7'],['0','1'],[],['2']]){const r={page,visibility:{completed_stroke_ids:ids,active_stroke_id:null,active_progress:0}};assert.deepEqual(cached.render(r).rgba,cold.render({...r,page:{...page,page_id:JSON.stringify(ids)}}).rgba);}
const report={frames:180,width:192,height:256,tools:'pencil and eraser, interleaved layers',coldCacheMs:before.ms,cachedMs:after.ms,speedup:before.ms/after.ms,allFramesExact:true,finalEqualsStatic:true};
console.log(JSON.stringify(report,null,2));await writeFile('artifacts/rust-renderer/prefix-cache-benchmark.json',JSON.stringify(report,null,2));

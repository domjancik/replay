import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {instantiateRenderer} from '../../native/redraw/renderer.mjs';
import {rotateFrame} from '../../native/hosted/rotation.mjs';
import {replayIndices,ReverseFrameCache} from '../../native/hosted/replay-frames.mjs';
import {benchmarkScene} from '../../native/redraw/benchmark-scenes.mjs';
test('worker uses prepared frames and cached reverse frames with exact rotated cropped output',async()=>{
 const wasm=readFileSync(new URL('../../native/redraw/target/wasm32-unknown-unknown/release/redraw.wasm',import.meta.url));
 const renderer=await instantiateRenderer(wasm),oracle=await instantiateRenderer(wasm);
 const {page,frames}=benchmarkScene('worker',64,2,2,14);
 let loads=0,frameCalls=0;const actual={...renderer,load(r){loads++;renderer.load(r);},frame(v){frameCalls++;return renderer.frame(v);}};
 const output=[],previews=[];
 const encodeReplay=async({frames})=>{for await(const frame of frames)output.push(frame);return {buffer:new Uint8Array([1]),mimeType:'video/mp4',extension:'.mp4'};};
 let source=readFileSync(new URL('../../native/hosted/worker.mjs',import.meta.url),'utf8').replace(/^import .*;\r?\n/gm,'').replace("const {encodeReplay}=await import('/encoder.mjs');",'');
 const context=vm.createContext({self:{},actual,rotateFrame,replayIndices,ReverseFrameCache,encodeReplay,performance,Blob,postMessage(){},previews});
 vm.runInContext(source+`;renderer=actual;png=async(frame,maxSide)=>{previews.push(maxSide);return new Blob([frame.rgba]);};`,context);
 context.input={op:'render',reverse_speed:4,crop:[2,2,60,60],prepared:{request:{page},frames,config:{fps:6,rotation:90}}};
 const result=await vm.runInContext('execute(input,1)',context);
 assert.equal(loads,1);assert.equal(frameCalls,frames.length); // all reverse frames fit the bounded cache
 assert.equal(result.frames,replayIndices(frames.length,6,4).length);
 const indices=replayIndices(frames.length,6,4);
 for(let i=0;i<indices.length;i++){
  const expected=rotateFrame(oracle.render({page,visibility:frames[indices[i]]}),90).rgba;
  const crop=new Uint8Array(60*60*4);for(let row=0;row<60;row++)crop.set(expected.subarray(((row+2)*64+2)*4,((row+2)*64+62)*4),row*60*4);
  assert.deepEqual(new Uint8Array(output[i]),crop);
 }
 assert.ok(previews.includes(384));
});

import {test} from 'node:test';
import assert from 'node:assert/strict';
import * as api from '../../native/hosted/browser-api.mjs';
test('grain preference reaches renderer and persisted job config, defaulting off',()=>{
 const prepared={request:{options:{viewport:{width:2808,height:3744}}},config:{}};
 assert.equal(typeof api.applyGrainPreference,'function');
 api.applyGrainPreference(prepared,{high_res_grain:true});
 assert.equal(prepared.request.options.high_res_grain,true);
 assert.equal(prepared.config.high_res_grain,true);
 api.applyGrainPreference(prepared,{});
 assert.equal(prepared.request.options.high_res_grain,false);
 assert.throws(()=>api.applyGrainPreference(prepared,{high_res_grain:'yes'}));
});

test('WASM refinement is opt-in and final prepared frame equals static output',async()=>{
 const {readFileSync}=await import('node:fs');
 const {instantiateRenderer}=await import('../../native/redraw/renderer.mjs');
 const renderer=await instantiateRenderer(readFileSync(new URL('../../native/redraw/target/wasm32-unknown-unknown/release/redraw.wasm',import.meta.url)));
 const request={page:{page_id:'grain',paper_size:[64,64],groups:[{group_id:'g',visible:true}],compositing_order:['g'],strokes:[{stroke_id:'s',group_id:'g',tool_code:14,rgba:[0,0,0,255],thickness_scale:1,points:[{x:8,y:20,width:40,pressure:128},{x:56,y:40,width:40,pressure:128}]}]},options:{viewport:{width:128,height:128}}};
 const base=renderer.render(request).rgba;
 request.options.high_res_grain=true;
 const final=renderer.render(request).rgba;
 assert.notDeepEqual(base,final);
 renderer.load(request);
 renderer.frame({active_stroke_id:'s',active_progress:.5,completed_stroke_ids:[]});
 assert.deepEqual(renderer.frame({completed_stroke_ids:['s']}).rgba,final);
});

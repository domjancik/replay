import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
const hash=bytes=>createHash('sha256').update(bytes).digest('hex');
import {readFileSync} from 'node:fs';
import {instantiateReader} from './reader.mjs';
import {instantiateRenderer} from '../redraw/renderer.mjs';
import {instantiateCore} from '../replay-core/core.mjs';
const root=process.argv[2]||'artifacts/rmdoc-parity';
const reader=await instantiateReader(readFileSync(new URL('./target/wasm32-unknown-unknown/release/rm_rmdoc.wasm',import.meta.url)));
const rb=readFileSync(new URL('../redraw/target/wasm32-unknown-unknown/release/redraw.wasm',import.meta.url));
const reference=await instantiateRenderer(rb),candidate=await instantiateRenderer(rb);
const core=await instantiateCore(readFileSync(new URL('../replay-core/target/wasm32-unknown-unknown/release/rm_replay_core.wasm',import.meta.url)));
let count=0,rejected=0;
for(const c of JSON.parse(readFileSync(`${root}/cases.json`,'utf8'))){
 if(process.argv[3]&&!c.name.startsWith(process.argv[3]))continue;
 if(!c.prepare){rejected++;continue;}
 const unknown=c.parsed.diagnostics.blocks.some(b=>b.unreadable&&![0,9,10].includes(b.block_type));if(unknown){rejected++;continue;}
 const actual=reader.execute(readFileSync(`${root}/${c.name}.rm`),{op:'prepare',page:c.args.page,settings:c.settings});
 console.log(`Rendering ${c.name.slice(0,12)} reference`);
 const expected=reference.render({...c.prepare.request,visibility:null});
 console.log(`Rendering ${c.name.slice(0,12)} candidate`);
 const rendered=candidate.render({...actual.request,visibility:null});
 assert.equal(hash(rendered.rgba),hash(expected.rgba),`${c.name}: parsed pixels differ`);
 const frames=core.match({op:'schedule',page:actual.request.page,fps:6,seconds:2,ordering:'entry'});
 const final=candidate.render({...actual.request,visibility:frames.at(-1)});
 assert.equal(hash(final.rgba),hash(rendered.rgba),`${c.name}: final/static differ`);
 count++;console.log(`Pixel parity ${count}: ${c.name.slice(0,12)}`);
}
console.log(`${count} pixel-identical outputs and final/static checks; ${rejected} cases outside successful prepare scope`);

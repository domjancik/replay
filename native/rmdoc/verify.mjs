import assert from 'node:assert/strict';
import {readFileSync,existsSync} from 'node:fs';
import {instantiateReader} from './reader.mjs';
const root=process.argv[2]||'artifacts/rmdoc-parity';
const binary=readFileSync(new URL('./target/wasm32-unknown-unknown/release/rm_rmdoc.wasm',import.meta.url));
assert.deepEqual(WebAssembly.Module.imports(await WebAssembly.compile(binary)),[],'Reader must be standalone');
const reader=await instantiateReader(binary);
const cases=JSON.parse(readFileSync(`${root}/cases.json`,'utf8'));
function compare(a,b,path=''){
 if(typeof a==='number'&&typeof b==='number'){assert.ok(Math.abs(a-b)<=1e-9*Math.max(1,Math.abs(b)),`${path}: ${a} != ${b}`);return;}
 if(Array.isArray(b)){assert.ok(Array.isArray(a),path);assert.equal(a.length,b.length,path);b.forEach((v,i)=>compare(a[i],v,`${path}[${i}]`));return;}
 if(b&&typeof b==='object'){
  // Diagnostic encoding and explanatory prose are implementation-specific.
  const ignored=new Set(['diagnostics','evidence','replay_evidence']);
  for(const key of Object.keys(b))if(!ignored.has(key))compare(a?.[key],b[key],`${path}.${key}`);return;
 }
 assert.deepEqual(a,b,path);
}
let count=0,projections=0;
for(const c of cases){
 const raw=readFileSync(`${root}/${c.name}.rm`);
 compare(reader.execute(raw,c.args),c.parsed,`${c.name}.parse`);count++;
 if(c.projected){
  const args={op:'project',page:c.args.page,layout:c.args.layout,paper_size:[1404,1872],source_affine:[1,0,0,1,702,0]};
  const unsupported=c.parsed.diagnostics.blocks.some(b=>b.unreadable&&![0,9,10].includes(b.block_type));
  if(unsupported)assert.throws(()=>reader.execute(raw,args),/Unsupported or unreadable geometry block/);
  else compare(reader.execute(raw,args),c.projected,`${c.name}.project`);
  projections++;
 }
 compare(reader.execute(raw,{op:'info',page:c.args.page}),c.info,`${c.name}.info`);count++;
 for(const op of ['prepare','anchors']){
  const args={op,page:c.args.page,settings:c.settings};
  const unsupported=c.parsed.diagnostics.blocks.some(b=>b.unreadable&&![0,9,10].includes(b.block_type));
  if(op==='prepare'&&unsupported&&!c[op+'_error'])assert.throws(()=>reader.execute(raw,args),/Unsupported or unreadable geometry block/,'Unknown geometry must not render silently');
  else if(c[op+'_error'])assert.throws(()=>reader.execute(raw,args),undefined,`${c.name}.${op} must reject`);
  else compare(reader.execute(raw,args),c[op],`${c.name}.${op}`);
  count++;
 }
}
console.log(`${cases.length} page cases, ${count} Python/Rust WASM comparisons passed`);

if(existsSync(`${root}/archives.json`))for(const a of JSON.parse(readFileSync(`${root}/archives.json`,'utf8')))compare(reader.execute(readFileSync(`${root}/${a.name}.rmdoc`),{op:'inspect'}),a.expected,`${a.name}.archive`);

console.log(`${projections} explicit-layout projections checked`);

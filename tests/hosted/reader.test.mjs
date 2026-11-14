import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {instantiateReader} from '../../native/rmdoc/reader.mjs';
const binary=readFileSync(new URL('../../native/rmdoc/target/wasm32-unknown-unknown/release/rm_rmdoc.wasm',import.meta.url));
test('reader WASM is self-contained and rejects future versions without poisoning next call',async()=>{
 assert.deepEqual(WebAssembly.Module.imports(await WebAssembly.compile(binary)),[]);
 const reader=await instantiateReader(binary);
 assert.throws(()=>reader.execute(Buffer.from('reMarkable .lines file, version=7          '),{op:'parse',page:'future'}),/version|header/i);
 const empty=Buffer.concat([Buffer.from('reMarkable .lines file, version=5          '),Buffer.alloc(4)]);
 const parsed=reader.execute(empty,{op:'parse',page:'blank'});
 assert.equal(parsed.page_id,'blank');assert.equal(parsed.strokes.length,0);
 assert.throws(()=>reader.execute(empty,{op:'prepare',page:'blank',settings:{}}));
 assert.equal(reader.execute(empty,{op:'info',page:'blank'}).strokes,0);
});

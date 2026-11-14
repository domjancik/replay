import assert from 'node:assert/strict';
import {test} from 'node:test';
import {deleteSavedNotebook} from '../../native/hosted/browser-api.mjs';
test('deletes only local archive and PDF atomically while keeping other notebooks and replays',async()=>{
 const operations=[];const db={transaction(){const tx={objectStore:()=>({delete:key=>operations.push(['delete',key]),put:(value,key)=>operations.push(['put',key,value])})};queueMicrotask(()=>tx.oncomplete());return tx;}};
 const docs=[{id:'one'},{id:'two'}];const jobs=[{document_id:'one',state:'complete'}];
 assert.deepEqual(await deleteSavedNotebook(db,docs,jobs,'one'),[{id:'two'}]);
 assert.deepEqual(operations.map(op=>op.slice(0,2)),[['delete','archive/one'],['delete','pdf/one'],['put','documents']]);
 assert.equal(docs.length,2);assert.equal(jobs.length,1);
 await assert.rejects(deleteSavedNotebook(db,docs,[{document_id:'one',state:'running'}],'one'),/Cancel/);
});

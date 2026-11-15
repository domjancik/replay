import {test} from 'node:test';
import assert from 'node:assert/strict';
import * as api from '../../native/hosted/browser-api.mjs';
test('original notebook download returns only the selected local archive',async()=>{
 assert.equal(typeof api.exportSavedNotebook,'function');
 const blob=new Blob(['archive']);let read;
 const result=await api.exportSavedNotebook([{id:'one'}],async key=>{read=key;return blob;},'one');
 assert.equal(read,'archive/one');assert.equal(result,blob);
 await assert.rejects(api.exportSavedNotebook([],async()=>{throw Error('must not read');},'unknown'),/not found/i);
 await assert.rejects(api.exportSavedNotebook([{id:'one'}],async()=>null,'one'),/missing/i);
});

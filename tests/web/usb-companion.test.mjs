import assert from 'node:assert/strict';
import {test} from 'node:test';
import {createUsbCompanion} from '../../src/rm_redraw/web/static/usb-companion.mjs';

test('companion stays idle until explicitly connected and uses fixed loopback only',async()=>{
 const calls=[];
 const client=createUsbCompanion({fetchImpl:async(url,options)=>{calls.push({url,options});return new Response(JSON.stringify(url.endsWith('/status')?{version:1,read_only:true}:[]));}});
 assert.equal(calls.length,0);
 await assert.rejects(()=>client.documents(),/Connect/);
 await client.connect('a'.repeat(43));await client.documents();
 assert.equal(calls[0].url,'http://127.0.0.1:8786/status');
 assert.equal(calls[1].url,'http://127.0.0.1:8786/documents?folder=');
 assert.equal(calls[0].options.credentials,'omit');
 assert.equal(calls[0].options.headers['X-Replay-USB-Token'],'a'.repeat(43));
 client.disconnect();await assert.rejects(()=>client.documents(),/Connect/);
});
test('errors and invalid archives are actionable without echoing secrets',async()=>{
 let mode='fail';
 const client=createUsbCompanion({fetchImpl:async()=>mode==='fail'?new Response('{"error":"Wrong site or key"}',{status:403}):new Response(JSON.stringify({version:1,read_only:true}))});
 await assert.rejects(()=>client.connect('b'.repeat(43)),/Wrong site or key/);
 mode='ok';await client.connect('b'.repeat(43));
 await assert.rejects(()=>client.download('../../etc'),/Invalid notebook/);
 await assert.rejects(()=>client.download('12345678-1234-1234-1234-123456789abc'),/archive/);
});

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


test('optional thumbnails support old companions and reject invalid images',async()=>{
 let supports=false,reads=0;
 const client=createUsbCompanion({fetchImpl:async(url)=>{
  if(url.endsWith('/status'))return new Response(JSON.stringify({version:1,read_only:true,thumbnails:supports}));
  reads++;return new Response('not png');
 }});
 const id='12345678-1234-1234-1234-123456789abc';
 await client.connect('a'.repeat(43));assert.equal(await client.thumbnail(id),null);assert.equal(reads,0);
 supports=true;await client.connect('a'.repeat(43));await assert.rejects(()=>client.thumbnail(id),/Invalid tablet thumbnail/);
 await assert.rejects(()=>client.thumbnail('../bad'),/Invalid notebook/);
});


test('valid PNG thumbnail is returned as bytes without notebook downloads',async()=>{
 const png=new Uint8Array(Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=','base64'));
 const paths=[];const client=createUsbCompanion({fetchImpl:async url=>{paths.push(url);return url.endsWith('/status')?new Response('{"version":1,"read_only":true,"thumbnails":true}'):new Response(png);}});
 await client.connect('a'.repeat(43));assert.deepEqual(await client.thumbnail('12345678-1234-1234-1234-123456789abc'),png);
 assert.equal(paths.length,2);assert.ok(paths[1].includes('/thumbnail?id='));
});

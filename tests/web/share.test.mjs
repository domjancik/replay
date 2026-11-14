import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
function fixture(navigator={}){
 const elements=new Map();const el=id=>{if(!elements.has(id))elements.set(id,{value:'',showModal(){this.open=true;},close(){this.open=false;}});return elements.get(id);};
 const context=vm.createContext({document:{getElementById:el},navigator,File,fetch:async()=>({ok:true,blob:async()=>new Blob(['ink'],{type:'image/png'})})});
 vm.runInContext(readFileSync(new URL('../../src/rm_redraw/web/static/app.js',import.meta.url),'utf8').replace('safely(start)();',''),context);
 vm.runInContext(`jobs=[{id:'one',state:'complete',kind:'image',name:'private title'}];selectedJob='one';`,context);
 return {context,el};
}
test('sharing prepares only the selected output, without publishing or exposing notebook titles',async()=>{
 let shared;
 const {context,el}=fixture({canShare:()=>true,share:async data=>{shared=data;}});
 await vm.runInContext('openShare()',context);
 assert.equal(shared,undefined);
 assert.equal(el('share-native').disabled,false);
 assert.match(el('share-caption').value,/#rmreplay/);
 assert.equal(el('share-caption').value.includes('private title'),false);
 await vm.runInContext('sharePrepared()',context);
 assert.equal(shared.files[0].name,'replay.png');
 assert.equal(shared.files[0].type,'image/png');
 assert.equal(shared.text,el('share-caption').value);
});
test('unsupported sharing offers download; cancellation never claims publication',async()=>{
 const {context,el}=fixture();await vm.runInContext('openShare()',context);
 assert.equal(el('share-native').disabled,true);
 assert.equal(el('share-download').href,'/media/one/static.png');
 assert.match(el('share-status').textContent,/Download/);
 const c=fixture({canShare:()=>true,share:async()=>{throw Object.assign(new Error(),{name:'AbortError'});}});
 await vm.runInContext('openShare();',c.context);await vm.runInContext('sharePrepared()',c.context);
 assert.match(c.el('share-status').textContent,/cancelled/i);
});

test('video sharing preserves the export format and edited caption',async()=>{
 let shared;
 const {context,el}=fixture({canShare:()=>true,share:async data=>{shared=data;}});
 context.fetch=async()=>({ok:true,blob:async()=>new Blob(['video'],{type:'video/webm'})});
 vm.runInContext(`jobs[0].kind='replay';jobs[0].extension='.webm';`,context);
 await vm.runInContext('openShare()',context);el('share-caption').value='My drawing #rmreplay';
 await vm.runInContext('sharePrepared()',context);
 assert.equal(shared.files[0].name,'replay.webm');assert.equal(shared.files[0].type,'video/webm');
 assert.equal(shared.text,'My drawing #rmreplay');
 assert.equal(el('share-download').href,'/media/one/replay.mp4');
});

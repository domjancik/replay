import assert from 'node:assert/strict';
import { test } from 'node:test';
import { setupCloud } from '../../src/rm_redraw/web/static/cloud-ui.mjs';
import { createVault } from '../../src/rm_redraw/web/static/cloud-vault.mjs';

function installGlobal(t, name, value) {
  const original = Object.getOwnPropertyDescriptor(globalThis, name);
  Object.defineProperty(globalThis, name, { value, configurable: true });
  t.after(() => {
    if (original) Object.defineProperty(globalThis, name, original);
    else delete globalThis[name];
  });
}

function fakeIndexedDB() {
  let record;
  return {
    open() {
      const request = { result: {
        close() {},
        transaction() {
          const txn = { objectStore: () => ({
            get() {
              const read = {};
              queueMicrotask(() => {
                read.result = structuredClone(record);
                read.onsuccess();
                txn.oncomplete();
              });
              return read;
            },
            add(value) { record = structuredClone(value); },
            delete() { record = undefined; },
          }) };
          return txn;
        },
      } };
      queueMicrotask(() => request.onsuccess());
      return request;
    },
  };
}

test('failed stale-vault deletion locks UI after either revoke or forget', async (t) => {
  for (const action of ['revoke', 'forget']) {
    await t.test(action, async (t) => {
      const indexedDB = fakeIndexedDB();
      installGlobal(t, 'indexedDB', indexedDB);
      const vault = createVault();
      const phrase = 'synthetic test passphrase';
      await vault.create(phrase, { deviceToken: 'old-device', cache: null });
      const elements = new Map();
      function element(id) {
        if (!elements.has(id)) {
          elements.set(id, {
            checked: false, disabled: false, value: '', textContent: '',
            showModal() {}, addEventListener() {}, querySelectorAll: () => [],
            replaceChildren() { this.cleared = true; },
          });
        }
        return elements.get(id);
      }
      installGlobal(t, 'document', { getElementById: element });
      installGlobal(t, 'window', { addEventListener() {} });
      let revokeCalls = 0;
      t.mock.method(globalThis, 'fetch', async (_path, options) => {
        assert.deepEqual(JSON.parse(options.body), { action: 'revoke', token: 'old-device' });
        revokeCalls++;
        return new Response('{}');
      });
      setupCloud({ sessionToken: () => 'test-session', importArchive() {} });
      t.mock.timers.enable({ apis: ['setTimeout'] });
      await element('cloud-open').onclick();
      element('cloud-passphrase').value = phrase;
      await element('cloud-unlock').onclick();
      assert.equal(element('cloud-refresh').disabled, false);
      element('cloud-items').cleared = false;

      await vault.forget();
      await vault.create(phrase, { deviceToken: 'new-device', cache: null });
      element('cloud-revoke-confirm').checked = true;
      await element(`cloud-${action}`).onclick();

      assert.match(element('cloud-status').textContent, /changed in another tab/);
      assert.equal(element('cloud-refresh').disabled, true);
      assert.equal(element('cloud-unlock').disabled, false);
      assert.equal(element('cloud-revoke-confirm').checked, false);
      assert.equal(element('cloud-items').cleared, true);
      assert.equal(revokeCalls, Number(action === 'revoke'));
      assert.equal((await vault.unlock(phrase)).deviceToken, 'new-device');
    });
  }
});

test('completed replay opens with its drawing as poster without resetting playback on poll', async () => {
  const {readFile} = await import('node:fs/promises');
  const {runInNewContext} = await import('node:vm');
  const source = await readFile(new URL('../../src/rm_redraw/web/static/app.js', import.meta.url), 'utf8');
  const elements = new Map();
  const context = {document: {getElementById(id) {
    if (!elements.has(id)) elements.set(id, {dataset: {}, pause() {}});
    return elements.get(id);
  }}};
  runInNewContext(source.replace('safely(start)();', ''), context);
  context.job = {id: 'synthetic', name: 'Drawing', page: 1, state: 'complete', frames: 10, expected_frames: 10};
  runInNewContext('showJob(job)', context);
  const video = elements.get('video');
  assert.equal(video.poster, '/media/synthetic/static.png');
  video.currentTime = 4;
  runInNewContext('showJob(job)', context);
  assert.equal(video.currentTime, 4);
  context.job.id = 'another';
  runInNewContext('showJob(job)', context);
  assert.equal(video.poster, '/media/another/static.png');
});

test('recent replay previews reuse static images and degrade to a placeholder', async () => {
  const {readFile} = await import('node:fs/promises');
  const {runInNewContext} = await import('node:vm');
  const source = await readFile(new URL('../../src/rm_redraw/web/static/app.js', import.meta.url), 'utf8');
  const context = {document: {createElement(tag) { return {tag, children: [], append(...items) { this.children.push(...items); }, replaceChildren(...items) { this.children = items; }}; }}};
  runInNewContext(source.replace('safely(start)();', ''), context);
  context.job = {id:'one',state:'queued'};
  const pending = runInNewContext('recentPreview(job)', context);
  assert.equal(pending.children.length, 0);
  context.job.state = 'complete';
  const ready = runInNewContext('recentPreview(job)', context);
  assert.equal(ready.children[0].src, '/media/one/static.png');
  assert.equal(ready.children[0].loading, 'lazy');
  assert.equal(runInNewContext('recentPreview(job)', context), ready);
  ready.children[0].onerror();
  assert.equal(ready.children.length, 0);
  assert.equal(ready.textContent, '—');
});
test('unlocked cloud notebooks appear in gallery and explicit lock clears them',async(t)=>{
 installGlobal(t,'indexedDB',fakeIndexedDB());
 const vault=createVault();await vault.create('synthetic long passphrase',{deviceToken:'test-device',cache:null,entries:[{id:'test-id',kind:'notebook',name:'Test notebook',path:'Drawings/Test notebook'}]});
 const elements=new Map();
 function make(){return {dataset:{},children:[],value:'',checked:false,disabled:false,textContent:'',handlers:{},querySelectorAll(){return [];},append(...children){this.children.push(...children);},replaceChildren(){this.children=[];},addEventListener(name,fn){this.handlers[name]=fn;},showModal(){},close(){this.handlers.close?.();}};}
 const el=id=>{if(!elements.has(id))elements.set(id,make());return elements.get(id);};
 installGlobal(t,'document',{getElementById:el,createElement:make});installGlobal(t,'window',{addEventListener(){}});
 t.mock.timers.enable({apis:['setTimeout']});
 let observe;let previewReads=0;
 installGlobal(t,'IntersectionObserver',class{constructor(callback){observe=callback;}observe(){}disconnect(){}});
 t.mock.method(globalThis,'fetch',async()=>{previewReads++;throw new Error('Synthetic unavailable cloud');});
 setupCloud({sessionToken:()=>'',importArchive(){}});
 await el('cloud-open').onclick();el('cloud-passphrase').value='synthetic long passphrase';await el('cloud-unlock').onclick();
 assert.equal(el('cloud-gallery').children.length,1);
 assert.equal(el('cloud-gallery').children[0].children[1].textContent,'Drawings/Test notebook');
 assert.equal(el('cloud-gallery-refresh').disabled,false);
 el('cloud-dialog').close();assert.equal(el('cloud-gallery').children.length,1);
 assert.equal(previewReads,1); // Unlock now refreshes automatically.
 observe([{target:el('cloud-gallery').children[0],isIntersecting:true}]);
 await new Promise(resolve=>setImmediate(resolve));assert.equal(previewReads,1);
 el('cloud-lock').onclick();assert.equal(el('cloud-gallery').children.length,0);assert.equal(el('cloud-gallery-refresh').disabled,true);
});

function cloudHarness(t, {savedMode=null, prepareError=null, storageError=false}={}) {
  const elements = new Map();
  const make = () => ({dataset:{}, children:[], value:'', checked:false, disabled:false, hidden:false, textContent:'', handlers:{},
    querySelectorAll(){return [];}, append(...items){this.children.push(...items);}, replaceChildren(...items){this.children=items;},
    addEventListener(name, fn){this.handlers[name]=fn;}, showModal(){this.open=true;}, close(){this.open=false;}});
  const el=id=>{if(!elements.has(id))elements.set(id,make());return elements.get(id);};
  installGlobal(t,'document',{getElementById:el,createElement:make,addEventListener(){}});
  installGlobal(t,'window',{addEventListener(){}});
  installGlobal(t,'navigator',{credentials:{create(){},get(){}}, storage:{persist:async()=>false}});
  const calls=[];
  const entries=[{id:'test',name:'Drawing',kind:'notebook'}];
  const vault={
    async mode(){if(storageError)throw new Error('Storage unavailable');return savedMode;},
    async exists(){if(storageError)throw new Error('Storage unavailable');return !!savedMode;},
    async preparePasskey(){calls.push('prepare');if(prepareError)throw new Error(prepareError);},
    async createPasskey(){calls.push('passkey');savedMode='passkey';},
    async create(){calls.push('password');savedMode='password';},
    async createUnprotected(_data,options){assert.equal(options.acknowledged,true);calls.push('unprotected');savedMode='unprotected';},
    async unlock(){calls.push('unlock');return {deviceToken:'test',entries};},
    async save(){calls.push('save');}, lock(){}, async forget(){savedMode=null;},
  };
  const client={async pair(){calls.push('pair');return 'test';},async list(){calls.push('list');return entries;},getCache(){return {};},
    setDeviceToken(){},lock(){},async preview(){calls.push('preview');return null;}};
  el('source-cloud').onclick=()=>calls.push('gallery');
  t.mock.timers.enable({apis:['setTimeout']});
  setupCloud({sessionToken:()=>'',importArchive(){},vault,clientFactory:()=>client});
  return {el,calls,vault,client};
}

test('first-time flow prefers passkey, then loads gallery automatically',async t=>{
  const {el,calls}=cloudHarness(t);
  await el('cloud-open').onclick();
  assert.equal(el('cloud-storage').value,'passkey');
  assert.equal(el('cloud-unlock').hidden,true);
  el('cloud-code').value='AB12CD34';
  await el('cloud-pair').onclick();
  assert.deepEqual(calls,['prepare','pair','passkey','gallery','list','save']);
  assert.equal(el('cloud-dialog').hidden,true);
  assert.equal(el('cloud-gallery').children.length,1);
  assert.equal(el('cloud-items').children.length,0);
});

test('session-only connects without saving even when browser storage is unavailable',async t=>{
  const {el,calls}=cloudHarness(t,{storageError:true});
  await el('cloud-open').onclick();
  el('cloud-storage').value='session';el('cloud-storage').onchange();el('cloud-code').value='AB12CD34';
  await el('cloud-pair').onclick();
  assert.deepEqual(calls,['pair','gallery','list']);
  assert.equal(el('cloud-lock').textContent,'End session');
  el('cloud-lock').onclick();
  assert.equal(el('cloud-gallery').children.length,0);
});

test('unprotected choice requires warning acknowledgement before pairing',async t=>{
  const {el,calls}=cloudHarness(t);await el('cloud-open').onclick();
  el('cloud-storage').value='unprotected';el('cloud-storage').onchange();el('cloud-code').value='AB12CD34';
  assert.equal(el('cloud-unprotected-warning').hidden,false);
  await el('cloud-pair').onclick();assert.deepEqual(calls,[]);
  el('cloud-unprotected-confirm').checked=true;await el('cloud-pair').onclick();
  assert.deepEqual(calls,['pair','unprotected','gallery','list','save']);
  assert.match(el('cloud-connection-state').textContent,/without protection/);
});

test('unsupported passkey offers password retry without consuming code or pairing',async t=>{
  const {el,calls}=cloudHarness(t,{prepareError:'This passkey cannot encrypt the connection'});
  await el('cloud-open').onclick();el('cloud-code').value='AB12CD34';await el('cloud-pair').onclick();
  assert.deepEqual(calls,['prepare']);assert.equal(el('cloud-code').value,'AB12CD34');
  assert.equal(el('cloud-password-fallback').hidden,false);
  el('cloud-password-fallback').onclick();
  el('cloud-passphrase').value='synthetic long password';el('cloud-confirm').value='synthetic long password';
  await el('cloud-pair').onclick();
  assert.deepEqual(calls,['prepare','pair','password','gallery','list','save']);
});

test('saved password connection shows only unlock and refreshes after opening cached gallery',async t=>{
  const {el,calls}=cloudHarness(t,{savedMode:'password'});await el('cloud-open').onclick();
  assert.equal(el('cloud-new').hidden,true);assert.equal(el('cloud-confirm-fields').hidden,true);
  el('cloud-passphrase').value='synthetic long password';await el('cloud-unlock').onclick();
  assert.deepEqual(calls,['unlock','gallery','list','save']);
  assert.equal(el('cloud-dialog').hidden,true);
});

test('thumbnail loading leaves connection status and notebook actions usable',async t=>{
  let observe;
  installGlobal(t,'IntersectionObserver',class {constructor(fn){observe=fn;} observe(){} disconnect(){}});
  const {el,calls}=cloudHarness(t);await el('cloud-open').onclick();
  el('cloud-storage').value='session';el('cloud-storage').onchange();el('cloud-code').value='AB12CD34';
  await el('cloud-pair').onclick();
  const row=el('cloud-gallery').children[0];const message=el('cloud-gallery-status').textContent;
  observe([{target:row,isIntersecting:true}]);await new Promise(resolve=>setImmediate(resolve));
  assert.equal(calls.filter(call=>call==='list').length,1);
  assert.equal(calls.filter(call=>call==='preview').length,1);
  assert.equal(el('cloud-gallery-status').textContent,message);
  assert.equal(el('cloud-gallery-refresh').disabled,false);
  assert.equal(row.children[2].textContent,'No preview available');
});

test('failed save can continue session-only without pairing twice',async t=>{
  const {el,calls,vault}=cloudHarness(t);
  vault.create=async()=>{throw new Error('Storage full');};
  await el('cloud-open').onclick();el('cloud-storage').value='password';el('cloud-storage').onchange();
  el('cloud-passphrase').value=el('cloud-confirm').value='synthetic password';el('cloud-code').value='AB12CD34';
  await el('cloud-pair').onclick();
  assert.match(el('cloud-status').textContent,/saving failed/);
  assert.equal(el('cloud-dialog').hidden,false);
  el('cloud-storage').value='session';el('cloud-storage').onchange();await el('cloud-pair').onclick();
  assert.equal(calls.filter(call=>call==='pair').length,1);
  assert.equal(el('cloud-dialog').hidden,true);
  assert.equal(el('cloud-gallery').children.length,1);
});

test('saved passkey and unprotected connections reopen without password fields',async t=>{
  for(const mode of ['passkey','unprotected'])await t.test(mode,async t=>{
    const {el,calls}=cloudHarness(t,{savedMode:mode});await el('cloud-open').onclick();
    assert.equal(el('cloud-password-fields').hidden,true);
    await el('cloud-unlock').onclick();
    assert.deepEqual(calls,['unlock','gallery','list','save']);
  });
});


test('failed saved-passkey unlock preserves the vault and shows recovery guidance inline',async t=>{
 const {el,vault}=cloudHarness(t,{savedMode:'passkey'});
 vault.unlock=async()=>{throw new Error('Passkey provider refused (NotAllowedError)');};
 await el('cloud-open').onclick();await el('cloud-unlock').onclick();
 assert.equal(el('cloud-dialog').hidden,false);
 assert.equal(el('cloud-unlock-help').hidden,false);
 assert.match(el('cloud-status').textContent,/provider refused/);
 assert.equal(await vault.mode(),'passkey');
 assert.equal(el('cloud-unlock').disabled,false);
});

test('cloud loading is visible and renders partial notebooks while awaiting completion', async t => {
  const {el,client}=cloudHarness(t,{savedMode:'password'});
  await el('cloud-open').onclick();
  let release, started;
  const waiting=new Promise(resolve=>{started=resolve;});
  const gate=new Promise(resolve=>{release=resolve;});
  client.list=async ({onProgress}={})=>{
    onProgress?.({completed:2,total:8,entries:[{id:'partial',name:'Available now',kind:'document'}]});
    started(); await gate; return [];
  };
  const pending=el('cloud-unlock').onclick();
  await waiting;
  try {
    assert.equal(el('cloud-gallery-status').hidden,false);
    assert.match(el('cloud-gallery-status').textContent,/2 of 8/);
    assert.equal(el('cloud-gallery').children[0].children[1].textContent,'Available now');
    assert.equal(el('cloud-gallery').children[0].children.at(-1).disabled,true);
  } finally {release();await pending;}
});

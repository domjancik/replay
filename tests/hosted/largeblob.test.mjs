import {test} from 'node:test';
import assert from 'node:assert/strict';

async function fixture({supported=true,written=true,corrupt=false,verified=true}={}) {
 const module=await import('../../native/hosted/largeblob-probe.mjs').catch(()=>null);
 assert.ok(module,'largeBlob probe must exist');
 let storedBlob;const calls=[];const id=new Uint8Array([4,5,6]);
 const credentials={
  async create(options){calls.push(options.publicKey);return {rawId:id.buffer,getClientExtensionResults:()=>({largeBlob:{supported}})};},
  async get(options){calls.push(options.publicKey);const ext=options.publicKey.extensions.largeBlob;
   if(ext.write&&written)storedBlob=new Uint8Array(ext.write).slice();
   const auth=new Uint8Array(37);auth[32]=verified?5:1;
   return {rawId:id.buffer,response:{authenticatorData:auth.buffer},getClientExtensionResults:()=>ext.write?{largeBlob:{written}}:{largeBlob:{blob:corrupt?new Uint8Array(32).buffer:storedBlob?.slice().buffer}}};
  },
 };
 return {probe:module.createLargeBlobProbe({credentials}),module,credentials,calls};
}
test('largeBlob can recover an AES key after reload without keeping the key in browser data',async()=>{
 const {probe,module,credentials,calls}=await fixture();
 const registered=await probe.register();const saved=await probe.write(registered);
 assert.equal(Object.hasOwn(saved,'key'),false);
 const restored=module.createLargeBlobProbe({credentials});
 assert.equal(await restored.read(JSON.parse(JSON.stringify(saved))),true);
 assert.deepEqual(calls[0].extensions,{largeBlob:{support:'required'}});
 assert.equal(calls[0].authenticatorSelection.residentKey,'required');
 assert.equal(calls[1].allowCredentials.length,1);
 assert.equal(calls[1].userVerification,'required');
 assert.deepEqual(calls[2].extensions,{largeBlob:{read:true}});
});
test('unsupported registration, rejected writes, corrupt reads and missing UV cannot pass',async()=>{
 for(const options of [{supported:false},{written:false},{corrupt:true},{verified:false}]){
  const {probe}=await fixture(options);
  if(options.supported===false){await assert.rejects(probe.register(),/support/);continue;}
  const record=await probe.register();
  if(options.written===false||options.verified===false){await assert.rejects(probe.write(record));continue;}
  await assert.rejects(probe.read(await probe.write(record)),/decrypt|operation/i);
 }
});

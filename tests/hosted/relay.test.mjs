import test from 'node:test';
import assert from 'node:assert/strict';
import {relayRequest} from '../../native/hosted/api/cloud-relay.mjs';
test('relay rejects cross-origin requests and unrecognized actions without upstream access',async()=>{
 let calls=0;const fetcher=()=>{calls++;throw Error('should not fetch');};
 const request=(payload,origin='https://evil.test')=>new Request('https://replay.test/api/cloud-relay',{method:'POST',headers:{origin,'content-type':'application/json'},body:JSON.stringify(payload)});
 assert.equal((await relayRequest(request({action:'root',token:'test'}),fetcher)).status,403);
 assert.equal((await relayRequest(request({action:'fetch',url:'https://evil.test'},'https://replay.test'),fetcher)).status,400);
 assert.equal(calls,0);
});
test('relay uses fixed provider URL and streams without storing credentials',async()=>{
 let target,options;
 const request=new Request('https://replay.test/api/cloud-relay',{method:'POST',headers:{origin:'https://replay.test','content-type':'application/json'},body:JSON.stringify({action:'root',token:'test'})});
 const response=await relayRequest(request,async(u,o)=>{target=u;options=o;return new Response('{"hash":"abc"}');});
 assert.equal(target,'https://internal.cloud.remarkable.com/sync/v4/root');
 assert.equal(options.redirect,'error');assert.equal(options.headers.Authorization,'Bearer test');
 assert.equal(response.headers.get('cache-control'),'no-store');assert.equal(await response.text(),'{"hash":"abc"}');
});

test('relay rejects inherited action names and unsafe file destinations',async()=>{
 for(const payload of [{action:'constructor'}, {action:'file',token:'test',hash:'0'.repeat(64),filename:'../secret'}]){
 const req=new Request('https://replay.test/api/cloud-relay',{method:'POST',headers:{origin:'https://replay.test','content-type':'application/json'},body:JSON.stringify(payload)});
 assert.equal((await relayRequest(req,()=>{throw Error('unexpected upstream');})).status,400);
 }
});

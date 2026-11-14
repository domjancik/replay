import {test} from 'node:test';
import assert from 'node:assert/strict';
import {replayIndices,ReverseFrameCache} from '../../native/hosted/replay-frames.mjs';
test('reverse plan skips final hold and reaches the first frame',()=>{
 assert.deepEqual(replayIndices(12,2,4),[0,1,2,3,4,5,6,7,8,9,10,11,8,4,0]);
});
test('reverse cache retains only needed frames within its byte budget and releases consumed frames',()=>{
 const cache=new ReverseFrameCache([4,2,0],8);
 cache.put(1,new Uint8Array(4));assert.equal(cache.bytes,0);
 cache.put(0,new Uint8Array([1,2,3,4]));cache.put(2,new Uint8Array(4));cache.put(4,new Uint8Array(4));
 assert.ok(cache.bytes<=8);assert.equal(cache.take(4).length,4);assert.ok(cache.bytes<=4);
});

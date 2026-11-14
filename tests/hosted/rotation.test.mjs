import assert from 'node:assert/strict';
import {test} from 'node:test';
import {rotateFrame} from '../../native/hosted/rotation.mjs';
test('quarter turns rotate exact RGBA pixels and swap dimensions',()=>{
 const frame={width:2,height:3,rgba:Uint8Array.from([1,2,3,4,5,6].flatMap(v=>[v,0,0,255]))};
 for(const [angle,expected] of [[0,[1,2,3,4,5,6]],[90,[5,3,1,6,4,2]],[180,[6,5,4,3,2,1]],[270,[2,4,6,1,3,5]]]){
  const out=rotateFrame(frame,angle);assert.deepEqual([...out.rgba].filter((_,i)=>i%4===0),expected);
  assert.equal(out.width,angle%180?3:2);assert.equal(out.height,angle%180?2:3);
 }
 assert.throws(()=>rotateFrame(frame,45),/rotation/i);
});

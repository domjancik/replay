import test from 'node:test';import assert from 'node:assert/strict';
import {validateReference,keepOperation} from '../../native/hosted/pdf-reference.mjs';
const OPS={transform:1,beginText:2,endText:3,showText:4,paintImageXObject:5,setTextRenderingMode:6};
test('native reference requires matching source geometry and removes whole text objects',()=>{
 const list={fnArray:[1,2,4,3,7],argsArray:[[.5,0,0,-.5,0,90],[],[],[],[]]};
 validateReference({list,OPS,view:[0,0,90,90],rotation:0,annotations:[]},[180,180]);
 assert.deepEqual(list.fnArray.map((_,i)=>keepOperation(i,list,OPS)),[true,false,false,false,true]);
 assert.throws(()=>validateReference({list,OPS,view:[0,0,90,90],rotation:0,annotations:[]},[360,360]),/canvas/);
});
test('unfiltered images, annotations and text clipping reject before matching',()=>{
 for(const list of [{fnArray:[5],argsArray:[[]]},{fnArray:[6],argsArray:[[4]]}])assert.throws(()=>validateReference({list,OPS,view:[0,0,90,90],rotation:0,annotations:[]},[180,180]));
});

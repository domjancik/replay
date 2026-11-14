import assert from 'node:assert/strict';
import {test} from 'node:test';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
test('final image renders once without video encoding or frame scheduling',async()=>{
 const source=readFileSync(new URL('../../native/hosted/worker.mjs',import.meta.url),'utf8').replace(/^import .*;\r?\n/gm,'');
 const context=vm.createContext({self:{},rotateFrame:frame=>frame});
 vm.runInContext(source+`;let calls=0;renderer={render(){calls++;return {width:2,height:2,rgba:new Uint8Array(16)};}};png=async()=> 'png';`,context);
 const result=await vm.runInContext(`execute({op:'render',still:true,prepared:{request:{},config:{},frames:[]}},1)`,context);
 assert.equal(result.image,'png');assert.equal(result.frames,1);assert.equal(result.video,undefined);
 assert.equal(vm.runInContext('calls',context),1);
});

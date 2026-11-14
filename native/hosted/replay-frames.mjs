export function replayIndices(count,fps,reverseSpeed=0){
 const indices=Array.from({length:count},(_,i)=>i);
 if(reverseSpeed){for(let i=Math.max(0,count-fps-2);i>=0;i-=reverseSpeed)indices.push(i);if(indices.at(-1)!==0)indices.push(0);}
 return indices;
}
// Keep the latest needed frames, which are consumed first during reverse.
export class ReverseFrameCache {
 constructor(indices,budget=16*1024*1024){this.needed=new Set(indices);this.budget=budget;this.frames=new Map();this.bytes=0;}
 put(index,rgba){
  if(!this.needed.has(index)||rgba.byteLength>this.budget||this.frames.has(index))return;
  while(this.bytes+rgba.byteLength>this.budget){const key=this.frames.keys().next().value;this.bytes-=this.frames.get(key).byteLength;this.frames.delete(key);}
  this.frames.set(index,rgba);this.bytes+=rgba.byteLength;
 }
 take(index){const frame=this.frames.get(index);if(frame){this.frames.delete(index);this.bytes-=frame.byteLength;}return frame;}
}

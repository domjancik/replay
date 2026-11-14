export function rotateFrame(frame,rotation=0){
 if(![0,90,180,270].includes(rotation))throw Error('Invalid page rotation');
 if(!rotation)return frame;
 const width=rotation%180?frame.height:frame.width,height=rotation%180?frame.width:frame.height;
 const rgba=new Uint8Array(frame.rgba.length);
 for(let y=0;y<frame.height;y++)for(let x=0;x<frame.width;x++){
  const dx=rotation===90?frame.height-1-y:rotation===180?frame.width-1-x:y;
  const dy=rotation===90?x:rotation===180?frame.height-1-y:frame.width-1-x;
  const source=(y*frame.width+x)*4,target=(dy*width+dx)*4;
  rgba.set(frame.rgba.subarray(source,source+4),target);
 }
 return {width,height,rgba};
}

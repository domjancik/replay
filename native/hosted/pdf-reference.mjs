const operationFilters=new WeakMap();
export function keepOperation(index,list,OPS){
 let state=operationFilters.get(list);
 if(!state){state={keep:[],depth:0};operationFilters.set(list,state);}
 for(let i=state.keep.length;i<list.fnArray.length;i++){
  const op=list.fnArray[i];if(op===OPS.beginText)state.depth++;
  state.keep.push(state.depth===0&&op!==OPS.endText);
  if(op===OPS.endText)state.depth--;
 }
 return state.keep[index];
}
export function validateReference({list,OPS,view,rotation,annotations},canvas){
 if(rotation||annotations.length)throw Error('Native anchor reference cannot contain rotation or annotations');
 const forbidden=['paintImageXObject','paintInlineImageXObject','paintImageMaskXObject','paintFormXObjectBegin','paintImageMaskXObjectGroup','paintImageXObjectRepeat','paintImageMaskXObjectRepeat','paintInlineImageXObjectGroup'].map(k=>OPS[k]).filter(v=>v!==undefined);
 for(let i=0;i<list.fnArray.length;i++){
  if(forbidden.includes(list.fnArray[i]))throw Error('Native anchor reference contains unfiltered images or XObjects');
  if(list.fnArray[i]===OPS.setTextRenderingMode&&list.argsArray[i][0]>=4)throw Error('Native anchor reference uses unsupported text clipping');
 }
 const source=list.fnArray.findIndex((op,i)=>{const a=list.argsArray[i];return op===OPS.transform&&a?.length===6&&a[1]===0&&a[2]===0&&a[0]>0&&a[3]<0&&Math.abs(a[0]+a[3])<1e-6;});
 if(source<0)throw Error('PDF has no native source-coordinate transform; attach the matching reMarkable export');
 const scale=1/list.argsArray[source][0];const expected=[(view[2]-view[0])*scale,(view[3]-view[1])*scale];
 if(canvas.some((n,i)=>Math.abs(n-expected[i])>3))throw Error(`Native PDF implies canvas ${expected.map(Math.round).join(' × ')}, not ${canvas.join(' × ')}`);
}
export async function nativeInkMask(blob,pageNumber,canvasSize){
 const pdfjs=await import('/pdfjs/pdf.mjs');pdfjs.GlobalWorkerOptions.workerSrc='/pdfjs/pdf.worker.mjs';
 const task=pdfjs.getDocument({data:new Uint8Array(await blob.arrayBuffer()),isEvalSupported:false,stopAtErrors:true,disableAutoFetch:true,wasmUrl:'/pdfjs/wasm/',standardFontDataUrl:'/pdfjs/standard_fonts/',cMapUrl:'/pdfjs/cmaps/',cMapPacked:true});
 try{
  const pdf=await task.promise;const page=await pdf.getPage(pageNumber);const list=await page.getOperatorList({annotationMode:pdfjs.AnnotationMode.DISABLE});
  validateReference({list,OPS:pdfjs.OPS,view:page.view,rotation:page.rotate,annotations:await page.getAnnotations()},canvasSize);
  const [width,height]=canvasSize;if(width*height>12_000_000)throw Error('Native reference exceeds 12 megapixels');
  const canvas=new OffscreenCanvas(width,height);const context=canvas.getContext('2d',{willReadFrequently:true});
  const base=page.getViewport({scale:1});const viewport=page.getViewport({scale:width/base.width});
  await page.render({canvas,canvasContext:context,viewport,transform:[1,0,0,height/viewport.height,0,0],annotationMode:pdfjs.AnnotationMode.DISABLE,operationsFilter:(index,operators)=>keepOperation(index,operators,pdfjs.OPS)}).promise;
  const pixels=context.getImageData(0,0,width,height).data;const mask=new Uint8Array(width*height);let count=0;
  for(let i=0;i<mask.length;i++){mask[i]=Number(Math.round(pixels[i*4]*.299+pixels[i*4+1]*.587+pixels[i*4+2]*.114)<245);count+=mask[i];}
  if(!count)throw Error('Native reference contains no visible vector ink');return {width,height,mask:Array.from(mask)};
 }finally{await task.destroy();}
}
export async function pdfPageCount(blob){
 const pdfjs=await import('/pdfjs/pdf.mjs');pdfjs.GlobalWorkerOptions.workerSrc='/pdfjs/pdf.worker.mjs';const task=pdfjs.getDocument({data:new Uint8Array(await blob.arrayBuffer()),isEvalSupported:false,stopAtErrors:true});try{return (await task.promise).numPages;}finally{await task.destroy();}
}

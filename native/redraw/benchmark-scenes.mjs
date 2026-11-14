export function benchmarkScene(name,width,layers,points,tool){
 const page={page_id:name,paper_size:[width,width],groups:Array.from({length:layers},(_,i)=>({group_id:String(i),visible:true})),compositing_order:Array.from({length:layers},(_,i)=>String(i)),strokes:Array.from({length:52},(_,i)=>({stroke_id:String(i),group_id:String(i%layers),rgba:[20,20,20,180],thickness_scale:2,tool_code:tool,points:Array.from({length:points},(_,j)=>({x:10+(width-20)*j/(points-1),y:10+i*(width-25)/52+Math.sin(j)*2,width:12,pressure:180}))}))};
 const frames=Array.from({length:80},(_,i)=>{const pos=Math.min(52,i*52/72),n=Math.floor(pos);return {completed_stroke_ids:page.strokes.slice(0,n).map(s=>s.stroke_id),active_stroke_id:n<52?String(n):null,active_progress:pos-n};});
 return {page,frames};
}

const run=document.getElementById('run'),cancel=document.getElementById('cancel'),status=document.getElementById('status'),results=document.getElementById('results');
const workers=new Set();let cancelled=false;
function job(scene,start,end){return new Promise((resolve,reject)=>{
 const worker=new Worker('/benchmark-worker.mjs',{type:'module'});workers.add(worker);
 const done=()=>{worker.terminate();workers.delete(worker);};
 worker.onmessage=({data})=>{done();data.error?reject(Error(data.error)):resolve(data);};
 worker.onerror=()=>{done();reject(Error('Benchmark worker failed'));};
 worker.postMessage({scene,start,end});
});}
cancel.onclick=()=>{cancelled=true;for(const worker of workers)worker.terminate();workers.clear();status.textContent='Cancelled. Reload to run again.';cancel.disabled=true;};
run.onclick=async()=>{
 run.disabled=true;cancel.disabled=false;results.textContent='';const report={userAgent:navigator.userAgent,logicalProcessors:navigator.hardwareConcurrency,results:[]};
 try{
  for(const scene of [['Detailed page',192,2,250,17],['Pencil replay',384,2,2,14],['Many layers',768,26,2,17]]){
   const samples=[];
   for(let repeat=0;repeat<3;repeat++){
    status.textContent=`${scene[0]}: run ${repeat+1} of 3…`;
    let start=performance.now();const single=await job(scene,0,80);const singleMs=performance.now()-start;if(cancelled)return;
    start=performance.now();const pair=await Promise.all([job(scene,0,40),job(scene,40,80)]);if(cancelled)return;
    samples.push({singleMs,twoWorkersMs:performance.now()-start,singleWasmBytes:single.memoryBytes,twoWorkersWasmBytes:pair.reduce((n,r)=>n+r.memoryBytes,0)});
   }
   report.results.push({scene:scene[0],samples});results.textContent=JSON.stringify(report,null,2);
  }
  status.textContent='Finished. Timings include worker startup and page transfer. WASM memory excludes browser and encoder buffers. Results stay on this device.';
 }catch(error){status.textContent=error.message;}finally{if(!cancelled){run.disabled=false;cancel.disabled=true;}}
};

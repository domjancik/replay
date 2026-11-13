const AUTH='https://webapp-prod.cloud.remarkable.engineering';
const SYNC='https://internal.cloud.remarkable.com';
const fields={pair:['action','code','device_id'],session:['action','token'],revoke:['action','token'],root:['action','token'],file:['action','token','hash','filename']};
const headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'};
const fail=(message,status)=>Response.json({error:message},{status,headers});
export async function relayRequest(request,fetcher=fetch){
 if(request.method!=='POST')return fail('POST required',405);
 if(request.headers.get('origin')!==new URL(request.url).origin)return fail('Same-origin request required',403);
 if(!request.headers.get('content-type')?.startsWith('application/json'))return fail('JSON required',415);
 let p;try{const reader=request.body.getReader();let size=0,chunks=[];for(;;){const {done,value}=await reader.read();if(done)break;size+=value.length;if(size>24000){await reader.cancel();return fail('Request too large',413);}chunks.push(value);}p=JSON.parse(new TextDecoder().decode(Buffer.concat(chunks)));}catch{return fail('Invalid JSON',400);}
 if(!p||!Object.hasOwn(fields,p.action)||Object.keys(p).sort().join()!==fields[p.action].slice().sort().join())return fail('Invalid cloud request fields',400);
 let url,method='GET',body;const upstream={};
 if(p.action==='pair'){
  if(typeof p.code!=='string'||!/^[a-z0-9]{8}$/i.test(p.code)||typeof p.device_id!=='string'||!/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i.test(p.device_id))return fail('Invalid pairing code or device ID',400);
  url=AUTH+'/token/json/2/device/new';method='POST';upstream['Content-Type']='application/json';body=JSON.stringify({code:p.code.toLowerCase(),deviceDesc:'desktop-macos',deviceID:p.device_id.toLowerCase()});
 }else{
  if(typeof p.token!=='string'||p.token.length>16384||! /^[A-Za-z0-9._~+/=-]+$/.test(p.token))return fail('Invalid token',400);
  upstream.Authorization='Bearer '+p.token;
  if(p.action==='session'||p.action==='revoke'){url=AUTH+(p.action==='session'?'/token/json/2/user/new':'/token/json/3/device/delete');method='POST';}
  else{
   let host=SYNC;try{const region=JSON.parse(Buffer.from(p.token.split('.')[1],'base64url')).tectonic;if(typeof region==='string'&&/^[a-z]{2,8}$/i.test(region))host=`https://${region.toLowerCase()}.tectonic.remarkable.com`;}catch{}
   if(p.action==='root'){url=host+'/sync/v4/root';upstream['rm-filename']='roothash';}
   else{if(typeof p.hash!=='string'||! /^[a-f0-9]{64}$/.test(p.hash)||typeof p.filename!=='string'||p.filename.length>255||! /^[A-Za-z0-9_.-]+(?:\/[A-Za-z0-9_.-]+)*$/.test(p.filename)||p.filename.split('/').some(x=>x==='.'||x==='..'))return fail('Invalid cloud file',400);url=host+'/sync/v3/files/'+p.hash;upstream['rm-filename']=p.filename;}
  }
 }
 try{
  const config={method,headers:upstream,body,redirect:'error',signal:AbortSignal.timeout(60000)};
  let r;try{r=await fetcher(url,config);}catch(error){if(!url.includes('.tectonic.remarkable.com/'))throw error;r=await fetcher(url.replace(/^https:\/\/[^/]+/,SYNC),config);}
  if(p.action==='root'&&r.status===404){await r.body?.cancel();r=await fetcher(url.replace('/v4/','/v3/'),config);}
  if(p.action==='revoke'&&(r.ok||[401,403].includes(r.status))){await r.body?.cancel();return Response.json({},{headers});}
  if(!r.ok){await r.body?.cancel();return fail('reMarkable Cloud rejected the request. Try unlocking or pairing again.',[400,401,403,429].includes(r.status)?r.status:502);}
  const limit=p.action==='file'?128*1024*1024:p.action==='root'?1024*1024:16384;
  if(Number(r.headers.get('content-length'))>limit){await r.body?.cancel();return fail('Cloud response exceeds the size limit',502);}
  let size=0;const stream=r.body.pipeThrough(new TransformStream({transform(chunk,controller){size+=chunk.length;if(size>limit)throw Error('Cloud response exceeds size limit');controller.enqueue(chunk);}}));
  return new Response(stream,{headers:{...headers,'Content-Type':p.action==='file'?'application/octet-stream':p.action==='root'?'application/json':'text/plain'}});
 }catch{return fail('Could not reach reMarkable Cloud. Try again shortly.',502);}
}
export default {fetch(request){return relayRequest(request);}};

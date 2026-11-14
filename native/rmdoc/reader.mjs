/** Standalone WASM notebook reader. No Python, WASI or renderer dependency. */
export async function instantiateReader(binary){
 const {instance}=await WebAssembly.instantiate(binary,{});const e=instance.exports;
 if(e.rm_doc_abi_version()!==1)throw Error('Unsupported notebook reader ABI');
 const encode=new TextEncoder(),decode=new TextDecoder();
 return {execute(raw,args){
  if(!(raw instanceof Uint8Array))throw TypeError('Notebook input must be bytes');
  const options=encode.encode(JSON.stringify(args));let rp=0,ap=0;
  try{
   rp=e.rm_doc_alloc(Math.max(raw.length,1));if(!rp)throw Error('Notebook exceeds reader memory budget');
   new Uint8Array(e.memory.buffer,rp,raw.length).set(raw);
   ap=e.rm_doc_alloc(options.length);if(!ap)throw Error('Reader options exceed memory budget');
   new Uint8Array(e.memory.buffer,ap,options.length).set(options);
   const code=e.rm_doc_call(rp,raw.length,ap,options.length);
   if(code)throw Error(decode.decode(new Uint8Array(e.memory.buffer,e.rm_doc_error_ptr(),e.rm_doc_error_len())));
   return JSON.parse(decode.decode(new Uint8Array(e.memory.buffer,e.rm_doc_output_ptr(),e.rm_doc_output_len())));
  }finally{if(ap)e.rm_doc_free(ap,options.length);if(rp)e.rm_doc_free(rp,Math.max(raw.length,1));}
 }};
}

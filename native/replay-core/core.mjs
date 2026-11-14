export async function instantiateCore(binary){
 const {instance}=await WebAssembly.instantiate(binary,{});const e=instance.exports;
 return {match(request){const bytes=new TextEncoder().encode(JSON.stringify(request));const ptr=e.rm_core_alloc(bytes.length);if(!ptr)throw Error('Anchor matching input exceeds 32 MiB');try{new Uint8Array(e.memory.buffer,ptr,bytes.length).set(bytes);const code=e.rm_core_render_json(ptr,bytes.length);const read=(p,n)=>new TextDecoder().decode(new Uint8Array(e.memory.buffer,p(),n()));if(code)throw Error(read(e.rm_core_error_ptr,e.rm_core_error_len));return JSON.parse(read(e.rm_core_output_ptr,e.rm_core_output_len));}finally{e.rm_core_free(ptr,bytes.length);}}};
}

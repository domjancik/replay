const endpoint='http://127.0.0.1:8786';
const uuid=/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/;
const maxBytes=128*1024*1024;
export function createUsbCompanion({fetchImpl=globalThis.fetch}={}){
  let key='',generation=0,thumbnails=false;
  const active=new Set();
  function disconnect(){key='';thumbnails=false;generation++;for(const controller of active)controller.abort();active.clear();}
  async function read(path,binary=false){
    if(!key)throw new Error('Connect the USB companion first.');
    const current=generation,controller=new AbortController();active.add(controller);
    const timeout=setTimeout(()=>controller.abort(),140000);
    try{
      const response=await fetchImpl(endpoint+path,{method:'GET',mode:'cors',credentials:'omit',cache:'no-store',redirect:'error',targetAddressSpace:'loopback',headers:{'X-Replay-USB-Token':key},signal:controller.signal});
      if(!response.ok){const data=await response.json();throw new Error(data.error || 'USB companion request failed.');}
      const reader=response.body.getReader(),chunks=[];let size=0;
      const limit=binary===true?maxBytes:4*1024*1024;
      try{while(true){const {value,done}=await reader.read();if(done)break;size+=value.length;if(size>limit)throw new Error('Companion response exceeds the size limit.');chunks.push(value);}}
      finally{await reader.cancel();reader.releaseLock();}
      if(current!==generation)throw new Error('USB companion disconnected.');
      const bytes=new Uint8Array(size);let offset=0;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length;}
      if(!binary)return JSON.parse(new TextDecoder().decode(bytes));
      if(binary==='png'){
        const view=new DataView(bytes.buffer);
        if(bytes.length<24 || bytes[0]!==137 || bytes[1]!==80 || bytes[2]!==78 || bytes[3]!==71 || view.getUint32(12)!==0x49484452)throw new Error('Invalid tablet thumbnail');
        const w=view.getUint32(16),h=view.getUint32(20);if(!w||!h||w>4096||h>4096||w*h>4194304)throw new Error('Oversized tablet thumbnail');
        return bytes;
      }
      if(bytes[0]!==0x50 || bytes[1]!==0x4b)throw new Error('Companion returned an invalid notebook archive.');
      return bytes;
    }catch(error){
      if(error instanceof TypeError || error.name==='AbortError')throw new Error('Cannot reach USB companion. Start it, check the allowed site, and allow browser local-network access if prompted.');
      throw error;
    }finally{clearTimeout(timeout);active.delete(controller);}
  }
  return {
    async connect(token){disconnect();if(!/^[A-Za-z0-9_-]{43}$/.test(token))throw new Error('Paste the connection key copied from the companion.');key=token;try{const status=await read('/status');if(status.version!==1 || status.read_only!==true)throw new Error('Unsupported USB companion version.');thumbnails=status.thumbnails===true;}catch(error){disconnect();throw error;}},
    disconnect,
    async thumbnail(id){if(!uuid.test(id))throw new Error('Invalid notebook ID');if(!thumbnails)return null;return read('/thumbnail?id='+encodeURIComponent(id),'png');},
    async documents(folder=''){if(folder && !uuid.test(folder))throw new Error('Invalid folder ID');const entries=await read('/documents?folder='+encodeURIComponent(folder));if(!Array.isArray(entries) || entries.some(e=>!uuid.test(e.id)||typeof e.name!=='string'||typeof e.folder!=='boolean'))throw new Error('Invalid companion notebook listing');return entries;},
    async download(id){if(!uuid.test(id))throw new Error('Invalid notebook ID');return read('/notebook?id='+encodeURIComponent(id),true);},
  };
}

// Diagnostic only: no cloud credentials, notebook access, or network requests.
const sample = new TextEncoder().encode('rePlay largeBlob local encryption probe v1');
function bytes(value, max, name) {
  if (!Array.isArray(value) || !value.length || value.length > max || value.some(n => !Number.isInteger(n) || n < 0 || n > 255)) throw new Error(`Invalid probe ${name}`);
  return new Uint8Array(value);
}
export function createLargeBlobProbe({credentials=globalThis.navigator?.credentials,crypto=globalThis.crypto}={}) {
  const random = size => crypto.getRandomValues(new Uint8Array(size));
  async function assertion(record, largeBlob) {
    const id=bytes(record.id,1024,'credential');
    const result=await credentials.get({publicKey:{challenge:random(32),allowCredentials:[{type:'public-key',id}],userVerification:'required',timeout:60000,extensions:{largeBlob}}});
    const actual=new Uint8Array(result?.rawId || []);
    if(actual.length!==id.length||!actual.every((n,i)=>n===id[i]))throw new Error('Unexpected probe credential');
    const auth=new Uint8Array(result.response?.authenticatorData || []);
    if(auth.length<37||(auth[32]&5)!==5)throw new Error('User presence and verification were not confirmed');
    return result.getClientExtensionResults()?.largeBlob;
  }
  return {
    async register() {
      if(!credentials?.create||!crypto?.subtle)throw new Error('WebAuthn is unavailable in this browser');
      const credential=await credentials.create({publicKey:{challenge:random(32),rp:{name:'rePlay largeBlob TEST'},user:{id:random(32),name:'rePlay largeBlob TEST',displayName:'rePlay largeBlob TEST'},pubKeyCredParams:[{type:'public-key',alg:-7},{type:'public-key',alg:-257}],authenticatorSelection:{residentKey:'required',userVerification:'required'},attestation:'none',timeout:60000,extensions:{largeBlob:{support:'required'}}}});
      if(credential?.getClientExtensionResults()?.largeBlob?.supported!==true)throw new Error('largeBlob is not supported by the selected browser/provider');
      const id=[...new Uint8Array(credential.rawId)];bytes(id,1024,'credential');
      return {version:1,id};
    },
    async write(record) {
      const secret=random(32);
      try {
        const key=await crypto.subtle.importKey('raw',secret,'AES-GCM',false,['encrypt']);
        const iv=random(12);
        const ciphertext=await crypto.subtle.encrypt({name:'AES-GCM',iv},key,sample);
        const result=await assertion(record,{write:secret});
        if(result?.written!==true)throw new Error('The provider did not confirm the largeBlob write');
        return {version:1,id:record.id,iv:[...iv],ciphertext:[...new Uint8Array(ciphertext)]};
      } finally { secret.fill(0); }
    },
    async read(record) {
      const iv=bytes(record.iv,12,'IV'),ciphertext=bytes(record.ciphertext,256,'ciphertext');
      if(iv.length!==12)throw new Error('Invalid probe IV');
      const result=await assertion(record,{read:true});
      if(!(result?.blob instanceof ArrayBuffer)||result.blob.byteLength!==32)throw new Error('Provider returned no 32-byte largeBlob');
      const secret=new Uint8Array(result.blob);
      try {
        const key=await crypto.subtle.importKey('raw',secret,'AES-GCM',false,['decrypt']);
        const plain=new Uint8Array(await crypto.subtle.decrypt({name:'AES-GCM',iv},key,ciphertext));
        if(plain.length!==sample.length||!plain.every((n,i)=>n===sample[i]))throw new Error('Probe decryption did not match');
        return true;
      } finally { secret.fill(0); }
    },
  };
}

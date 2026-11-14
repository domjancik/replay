import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createVault } from '../../src/rm_redraw/web/static/cloud-vault.mjs';

const passphrase = 'synthetic test passphrase';
const data = { deviceToken: 'synthetic-device-token', tree: [{ name: 'Synthetic notebook' }] };

function memoryStorage() {
  let record;
  return {
    async read() { return structuredClone(record); },
    async create(value) {
      if (record) return false;
      record = structuredClone(value);
      return true;
    },
    async replace(expectedIv, value) {
      if (!record || !record.iv.every((byte, index) => byte === expectedIv[index])) return false;
      record = structuredClone(value);
      return true;
    },
    async remove(expectedIv) {
      if (!record || !expectedIv || !record.iv.every((byte, index) => byte === expectedIv[index])) {
        return false;
      }
      record = undefined;
      return true;
    },
    corrupt() { record.ciphertext[0] ^= 1; },
    overwrite(value) { record = value; },
  };
}

test('persisted credentials and tree are encrypted and unlock after restart', async () => {
  const storage = memoryStorage();
  const vault = createVault({ storage });
  assert.equal(await vault.exists(), false);
  await assert.rejects(vault.create('too short', data), /12 to 1024/);
  await vault.create(passphrase, data);
  assert.equal(await vault.exists(), true);
  const record = await storage.read();
  assert.deepEqual(Object.keys(record).sort(), ['ciphertext', 'iv', 'salt', 'version']);
  assert.equal(record.version, 1);
  assert.equal(record.iv.length, 12);
  assert.equal(record.salt.length, 16);
  for (const text of [data.deviceToken, data.tree[0].name, passphrase]) {
    assert.equal(new TextDecoder().decode(record.ciphertext).includes(text), false);
  }
  const changed = { ...data, tree: [] };
  await vault.save(changed);
  assert.notDeepEqual((await storage.read()).iv, record.iv);
  assert.deepEqual((await storage.read()).salt, record.salt);
  vault.lock();
  await assert.rejects(vault.save(data), /locked/i);
  const fresh = createVault({ storage });
  await assert.rejects(fresh.unlock('incorrect passphrase'), /passphrase|corrupt/i);
  await assert.rejects(fresh.save(data), /locked/i);
  assert.deepEqual(await fresh.unlock(passphrase), changed);
  await fresh.forget();
  assert.equal(await fresh.exists(), false);
  await assert.rejects(fresh.save(data), /locked/i);
});

test('rejects corrupt ciphertext and malformed or oversized stored records', async () => {
  const storage = memoryStorage();
  const vault = createVault({ storage });
  await vault.create(passphrase, data);
  vault.lock();
  storage.corrupt();
  await assert.rejects(vault.unlock(passphrase), /passphrase|corrupt/i);
  const envelope = await storage.read();
  storage.overwrite({ ...envelope, deviceToken: data.deviceToken });
  await assert.rejects(vault.unlock(passphrase), /vault record/i);
  storage.overwrite({ ...envelope, version: 2 });
  await assert.rejects(vault.unlock(passphrase), /vault record/i);
  storage.overwrite({ ...envelope, ciphertext: new Uint8Array(9 * 1024 * 1024) });
  await assert.rejects(vault.unlock(passphrase), /vault record/i);
  await assert.rejects(vault.create(passphrase, { deviceToken: '' }), /payload/i);
});

test('locking before encryption completes prevents a pending save from replacing the record', async () => {
  const storage = memoryStorage();
  const webcrypto = globalThis.crypto;
  let enter;
  let resume;
  const entering = new Promise((resolve) => { enter = resolve; });
  const pause = new Promise((resolve) => { resume = resolve; });
  let pauseEncryption = false;
  const crypto = {
    getRandomValues: webcrypto.getRandomValues.bind(webcrypto),
    subtle: {
      importKey: webcrypto.subtle.importKey.bind(webcrypto.subtle),
      deriveKey: webcrypto.subtle.deriveKey.bind(webcrypto.subtle),
      async encrypt(...args) {
        if (pauseEncryption) {
          enter();
          await pause;
        }
        return webcrypto.subtle.encrypt(...args);
      },
    },
  };
  const vault = createVault({ storage, crypto });
  await vault.create(passphrase, data);
  const original = await storage.read();
  pauseEncryption = true;
  const saving = vault.save({ ...data, tree: [] });
  await entering;
  vault.lock();
  resume();
  await assert.rejects(saving, /lock/i);
  assert.deepEqual(await storage.read(), original);
  await assert.rejects(vault.save(data), /locked/i);
});

test('locking during unlock prevents the pending operation from exposing credentials', async () => {
  const storage = memoryStorage();
  await createVault({ storage }).create(passphrase, data);
  const read = storage.read;
  let resume;
  let started;
  const entered = new Promise((resolve) => { started = resolve; });
  storage.read = async () => {
    const record = await read();
    await new Promise((resolve) => { resume = resolve; started(); });
    return record;
  };
  const vault = createVault({ storage });
  const unlocking = vault.unlock(passphrase);
  await entered;
  vault.lock();
  resume();
  await assert.rejects(unlocking, /lock/i);
  await assert.rejects(vault.save(data), /locked/i);
});

test('forget cannot be undone by an in-flight create', async () => {
  const storage = memoryStorage();
  const create = storage.create;
  let resume;
  let started;
  const entered = new Promise((resolve) => { started = resolve; });
  storage.create = async (value) => {
    await new Promise((resolve) => { resume = resolve; started(); });
    return create(value);
  };
  const vault = createVault({ storage });
  const creating = vault.create(passphrase, data);
  await entered;
  const forgetting = vault.forget();
  resume();
  await assert.rejects(creating, /lock/i);
  await forgetting;
  assert.equal(await vault.exists(), false);
});

test('a stale unlocked tab cannot overwrite a later save or restore a forgotten vault', async () => {
  const storage = memoryStorage();
  const first = createVault({ storage });
  const other = createVault({ storage });
  await first.create(passphrase, data);
  await assert.rejects(other.create(passphrase, data), /already exists/i);
  await other.unlock(passphrase);
  await first.save({ ...data, tree: [] });
  await assert.rejects(other.save(data), /changed/i);
  other.lock();
  await other.unlock(passphrase);
  await first.forget();
  await assert.rejects(other.save(data), /changed/i);
  assert.equal(await other.exists(), false);
});

test('forget from a stale unlocked tab preserves a newer saved revision', async () => {
  const storage = memoryStorage();
  const first = createVault({ storage });
  const stale = createVault({ storage });
  await first.create(passphrase, data);
  await stale.unlock(passphrase);
  const changed = { ...data, tree: [] };
  await first.save(changed);
  await assert.rejects(stale.forget(), /changed/i);
  await assert.rejects(stale.save(data), /locked/i);
  assert.deepEqual(await first.unlock(passphrase), changed);
});

test('forget from a stale unlocked tab preserves a replacement vault', async () => {
  const storage = memoryStorage();
  const first = createVault({ storage });
  const stale = createVault({ storage });
  await first.create(passphrase, data);
  await stale.unlock(passphrase);
  await first.forget();
  const replacement = { ...data, deviceToken: 'replacement-device-token' };
  await first.create(passphrase, replacement);
  await assert.rejects(stale.forget(), /changed/i);
  assert.deepEqual(await first.unlock(passphrase), replacement);
});

test('forget while locked preserves any revision written after its read', async () => {
  const storage = memoryStorage();
  const first = createVault({ storage });
  const locked = createVault({ storage });
  await first.create(passphrase, data);
  const remove = storage.remove;
  let enter;
  let resume;
  const entered = new Promise((resolve) => { enter = resolve; });
  const paused = new Promise((resolve) => { resume = resolve; });
  storage.remove = async (expectedIv) => {
    enter();
    await paused;
    return remove(expectedIv);
  };
  const forgetting = locked.forget();
  await entered;
  const changed = { ...data, tree: [] };
  await first.save(changed);
  resume();
  await assert.rejects(forgetting, /changed/i);
  assert.deepEqual(await first.unlock(passphrase), changed);
  await locked.forget();
  assert.equal(await locked.exists(), false);
});

test('passkey encrypts, survives restart and never persists PRF output', async () => {
  const storage = memoryStorage();
  const secret = new Uint8Array(32).fill(73);
  const credentialId = new Uint8Array([1, 2, 3]);
  const calls = [];
  const credentials = {
    async create(options) { calls.push(options); return { rawId: credentialId.buffer, getClientExtensionResults: () => ({prf:{enabled:true}}) }; },
    async get(options) { calls.push(options); return { rawId: credentialId.buffer, getClientExtensionResults: () => ({prf:{results:{first:secret.slice().buffer}}}) }; },
  };
  const vault = createVault({storage, credentials});
  assert.equal(typeof vault.preparePasskey, 'function');
  await vault.preparePasskey();
  await vault.createPasskey(data);
  assert.equal(await vault.mode(), 'passkey');
  const record = await storage.read();
  assert.equal(JSON.stringify(record).includes(data.deviceToken), false);
  assert.equal(Object.hasOwn(record, 'key'), false);
  vault.lock();
  const fresh = createVault({storage, credentials});
  assert.deepEqual(await fresh.unlock(), data);
  await fresh.save({...data, tree:[]});
  assert.deepEqual((await fresh.unlock()).tree, []);
  assert.equal(calls[0].publicKey.authenticatorSelection.userVerification, 'required');
  assert.equal(calls[1].publicKey.userVerification, 'required');
  assert.deepEqual(calls[1].publicKey.allowCredentials[0].id, credentialId);
  assert.notDeepEqual(calls[1].publicKey.challenge, calls[2].publicKey.challenge);
  secret.fill(12);
  await assert.rejects(fresh.unlock(), /incorrect|corrupt/);
  await assert.rejects(fresh.save(data), /locked/);
});

test('unsupported or cancelled passkey never saves or silently falls back', async () => {
  for (const failure of ['unsupported', 'cancelled', 'wrong-id']) {
    const storage = memoryStorage();
    const credentials = {
      async create() {
        if (failure === 'cancelled') throw new DOMException('cancel', 'NotAllowedError');
        return {rawId: new Uint8Array([1]).buffer, getClientExtensionResults:()=>({prf:{enabled:failure !== 'unsupported'}})};
      },
      async get() {return {rawId:new Uint8Array([2]).buffer, getClientExtensionResults:()=>({prf:{results:{first:new Uint8Array(32).buffer}}})};},
    };
    const vault = createVault({storage, credentials});
    assert.equal(typeof vault.preparePasskey, 'function');
    await assert.rejects(vault.preparePasskey());
    assert.equal(await vault.exists(), false);
    await assert.rejects(vault.createPasskey(data), /passkey/i);
  }
});

test('unprotected persistence requires explicit acknowledgement and retains revision safety', async () => {
  const storage = memoryStorage();
  const vault = createVault({storage});
  assert.equal(typeof vault.createUnprotected, 'function');
  await assert.rejects(vault.createUnprotected(data), /acknowledge/i);
  assert.equal(await vault.exists(), false);
  await vault.createUnprotected(data, {acknowledged:true});
  assert.equal(await vault.mode(), 'unprotected');
  assert.equal((await storage.read()).data.deviceToken, data.deviceToken);
  const other = createVault({storage});
  assert.deepEqual(await other.unlock(), data);
  await vault.save({...data,tree:[]});
  await assert.rejects(other.save(data), /changed/);
  await vault.forget();
  assert.equal(await vault.exists(), false);
});

test('locking during a passkey prompt discards the result',async()=>{
  const storage=memoryStorage();let resume,entered;
  const started=new Promise(resolve=>{entered=resolve;});
  const credentials={
    async create(){await new Promise(resolve=>{resume=resolve;entered();});return {rawId:new Uint8Array([1]).buffer,getClientExtensionResults:()=>({prf:{enabled:true}})};},
    async get(){throw new Error('Should not evaluate PRF after locking');},
  };
  const vault=createVault({storage,credentials});const preparing=vault.preparePasskey();
  await started;vault.lock();resume();
  await assert.rejects(preparing,/locked/);await assert.rejects(vault.createPasskey(data),/passkey/);
  assert.equal(await vault.exists(),false);
});

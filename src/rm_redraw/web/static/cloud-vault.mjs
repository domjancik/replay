const VERSION = 1;
const ITERATIONS = 600_000;
const SALT_BYTES = 16;
const IV_BYTES = 12;
const TAG_BYTES = 16;
const MAX_PAYLOAD = 8 * 1024 * 1024;
const MAX_TOKEN = 16 * 1024;
const MIN_PASSPHRASE = 12;
const MAX_PASSPHRASE = 1024;
const DATABASE = 'rm-redraw-cloud-vault';
const STORE = 'vault';
const RECORD = 'cloud-profile';
const encoder = new TextEncoder();
const decoder = new TextDecoder('utf-8', { fatal: true });
const associatedData = encoder.encode('rm-redraw/cloud-vault/v1');

function equalBytes(left, right) {
  return left instanceof Uint8Array && right instanceof Uint8Array
    && left.length === right.length && left.every((byte, index) => byte === right[index]);
}

function openDatabase(indexedDB) {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DATABASE, VERSION);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE);
    request.onerror = () => reject(new Error('Could not open the browser vault storage'));
    let blocked = false;
    request.onblocked = () => {
      blocked = true;
      reject(new Error('Close other vault tabs and reopen the browser vault'));
    };
    request.onsuccess = () => {
      if (blocked) request.result.close();
      else resolve(request.result);
    };
  });
}

function indexedStorage(indexedDB) {
  async function transaction(mode, run) {
    if (!indexedDB) throw new Error('Browser vault storage is unavailable');
    const database = await openDatabase(indexedDB);
    try {
      return await new Promise((resolve, reject) => {
        const txn = database.transaction(STORE, mode);
        let result;
        txn.oncomplete = () => resolve(result);
        txn.onabort = () => reject(new Error('The browser vault storage operation failed'));
        run(txn.objectStore(STORE), (value) => { result = value; });
      });
    } finally {
      database.close();
    }
  }

  function change(expectedIv, mutate) {
    return transaction('readwrite', (store, setResult) => {
      const request = store.get(RECORD);
      request.onsuccess = () => {
        const matches = equalBytes(request.result?.iv, expectedIv);
        if (matches) mutate(store);
        setResult(matches);
      };
    });
  }

  return {
    read: () => transaction('readonly', (store, setResult) => {
      const request = store.get(RECORD);
      request.onsuccess = () => setResult(request.result);
    }),
    create: (record) => transaction('readwrite', (store, setResult) => {
      const request = store.get(RECORD);
      request.onsuccess = () => {
        const absent = request.result === undefined;
        if (absent) store.add(record, RECORD);
        setResult(absent);
      };
    }),
    replace: (expectedIv, record) => change(expectedIv, (store) => store.put(record, RECORD)),
    remove: (expectedIv) => change(expectedIv, (store) => store.delete(RECORD)),
  };
}

function validateRecord(record) {
  if (record?.version === 2) {
    const validIv = record.iv instanceof Uint8Array && record.iv.length === IV_BYTES;
    if (record.mode === 'unprotected' && validIv && Object.keys(record).length === 4) {
      serialize(record.data).fill(0);
      return;
    }
    if (record.mode === 'passkey' && validIv && Object.keys(record).length === 6
        && record.credentialId instanceof Uint8Array && record.credentialId.length > 0
        && record.credentialId.length <= 1024
        && record.salt instanceof Uint8Array && record.salt.length === SALT_BYTES
        && record.ciphertext instanceof Uint8Array && record.ciphertext.length > TAG_BYTES
        && record.ciphertext.length <= MAX_PAYLOAD + TAG_BYTES) return;
    throw new Error('The browser vault record is invalid or unsupported');
  }
  if (!record || typeof record !== 'object'
      || Object.keys(record).length !== 4 || record.version !== VERSION
      || !['version', 'salt', 'iv', 'ciphertext'].every((field) => Object.hasOwn(record, field))
      || !(record.salt instanceof Uint8Array) || record.salt.length !== SALT_BYTES
      || !(record.iv instanceof Uint8Array) || record.iv.length !== IV_BYTES
      || !(record.ciphertext instanceof Uint8Array)
      || record.ciphertext.length <= TAG_BYTES || record.ciphertext.length > MAX_PAYLOAD + TAG_BYTES) {
    throw new Error('The browser vault record is invalid or unsupported');
  }
}

function validatePayload(data) {
  if (!data || typeof data !== 'object' || Array.isArray(data)
      || !Object.hasOwn(data, 'deviceToken') || typeof data.deviceToken !== 'string'
      || !data.deviceToken.trim() || data.deviceToken.length > MAX_TOKEN) {
    throw new Error('The vault payload needs a valid device token');
  }
}

function serialize(data) {
  validatePayload(data);
  let json;
  try {
    json = JSON.stringify(data);
  } catch {
    throw new Error('The vault payload must be JSON serializable');
  }
  if (typeof json !== 'string' || json.length > MAX_PAYLOAD) {
    throw new Error('The vault payload exceeds the storage limit');
  }
  validatePayload(JSON.parse(json));
  const bytes = encoder.encode(json);
  if (bytes.length > MAX_PAYLOAD) {
    bytes.fill(0);
    throw new Error('The vault payload exceeds the storage limit');
  }
  return bytes;
}

function checkPassphrase(passphrase, minimum = 1) {
  if (typeof passphrase !== 'string'
      || passphrase.length < minimum || passphrase.length > MAX_PASSPHRASE
      || !passphrase.trim()) {
    throw new Error(`Enter a vault passphrase of ${minimum} to ${MAX_PASSPHRASE} characters`);
  }
}

async function deriveKey(crypto, passphrase, salt) {
  if (!crypto?.subtle) throw new Error('Browser encryption requires a secure origin');
  const password = encoder.encode(passphrase);
  let material;
  try {
    material = await crypto.subtle.importKey('raw', password, 'PBKDF2', false, ['deriveKey']);
  } finally {
    password.fill(0);
  }
  return crypto.subtle.deriveKey(
    { name: 'PBKDF2', hash: 'SHA-256', iterations: ITERATIONS, salt },
    material, { name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt'],
  );
}

function cipherParams(iv, protection) {
  const aad = protection?.mode === 'passkey'
    ? encoder.encode(JSON.stringify(['rePlay/cloud-vault/v2', 'passkey', [...protection.credentialId], [...protection.salt]]))
    : associatedData;
  return { name: 'AES-GCM', iv, additionalData: aad, tagLength: TAG_BYTES * 8 };
}

async function seal(crypto, key, salt, plaintext, protection) {
  const iv = crypto.getRandomValues(new Uint8Array(IV_BYTES));
  if (protection?.mode === 'unprotected') {
    return {version: 2, mode: 'unprotected', iv, data: JSON.parse(decoder.decode(plaintext))};
  }
  const ciphertext = await crypto.subtle.encrypt(cipherParams(iv, protection), key, plaintext);
  if (protection?.mode === 'passkey') {
    return {version: 2, mode: 'passkey', salt, iv, credentialId: protection.credentialId, ciphertext: new Uint8Array(ciphertext)};
  }
  return { version: VERSION, salt, iv, ciphertext: new Uint8Array(ciphertext) };
}

async function unseal(crypto, key, record) {
  let plaintext;
  try {
    plaintext = new Uint8Array(await crypto.subtle.decrypt(
      cipherParams(record.iv, record), key, record.ciphertext,
    ));
    const data = JSON.parse(decoder.decode(plaintext));
    validatePayload(data);
    return data;
  } catch {
    throw new Error('The passphrase is incorrect or the vault is corrupt');
  } finally {
    plaintext?.fill(0);
  }
}

async function passkeyOperation(stage, run) {
  try { return await run(); }
  catch (error) {
    const known = ['UnknownError', 'NotAllowedError', 'NotSupportedError', 'SecurityError', 'InvalidStateError', 'AbortError', 'NotReadableError'];
    const code = known.includes(error?.name) ? error.name : 'ProviderError';
    const advice = code === 'NotAllowedError' || code === 'AbortError'
      ? 'The browser or passkey provider did not complete the request. This can mean cancellation, timeout, or a Windows Hello/provider failure; it does not prove you cancelled. Retry once. If Windows reports a sign-in error, use a different provider or pair with password/session-only protection.'
      : 'Your browser or passkey provider could not complete the encryption request. Firefox-based browsers with Windows Hello can fail here. Try another browser or passkey provider, or use a password or session only.';
    throw new Error(`Passkey ${stage} failed (${code}). ${advice}`);
  }
}

async function passkeyKey(crypto, credentials, credentialId, salt) {
  const credential = await passkeyOperation('encryption check', () => credentials.get({publicKey: {
    challenge: crypto.getRandomValues(new Uint8Array(32)),
    allowCredentials: [{type: 'public-key', id: credentialId}],
    userVerification: 'required', timeout: 60000,
    extensions: {prf: {eval: {first: salt}}},
  }}));
  if (!credential || !equalBytes(new Uint8Array(credential.rawId), credentialId)) {
    throw new Error('The selected passkey does not match this connection');
  }
  const output = credential.getClientExtensionResults()?.prf?.results?.first;
  return derivePasskeyKey(crypto, output, salt);
}

async function derivePasskeyKey(crypto, output, salt) {
  if (!(output instanceof ArrayBuffer) || output.byteLength !== 32) {
    throw new Error('Passkey encryption check returned no PRF key. Signing in with a passkey and encrypting browser storage require different capabilities. Try another passkey provider, or choose a password or session only.');
  }
  const secret = new Uint8Array(output);
  try {
    const material = await crypto.subtle.importKey('raw', secret, 'HKDF', false, ['deriveKey']);
    return await crypto.subtle.deriveKey(
      {name: 'HKDF', hash: 'SHA-256', salt, info: encoder.encode('rePlay/cloud-vault/passkey/v2')},
      material, {name: 'AES-GCM', length: 256}, false, ['encrypt', 'decrypt'],
    );
  } finally { secret.fill(0); }
}

/**
 * Persist one encrypted cloud profile. The injected storage adapter must use
 * atomic create, replace, and remove operations. The caller owns plaintext returned by
 * unlock() and should release its references when locking the vault.
 */
export function createVault({
  storage = indexedStorage(globalThis.indexedDB), crypto = globalThis.crypto,
  credentials = globalThis.navigator?.credentials,
} = {}) {
  let session;
  let prepared;
  let pendingPasskey;
  let generation = 0;
  let pending = Promise.resolve();

  function lock() {
    generation += 1;
    session = undefined;
    prepared = undefined;
    pendingPasskey = undefined;
  }

  function enqueue(run) {
    const started = generation;
    const check = () => {
      if (generation !== started) throw new Error('The vault was locked during the operation');
    };
    const result = pending.then(() => run(check));
    pending = result.then(() => {}, () => {});
    return result;
  }

  return {
    async mode() {
      const record = await storage.read();
      if (record === undefined) return null;
      validateRecord(record);
      return record.version === 1 ? 'password' : record.mode;
    },

    async preparePasskey() {
      return enqueue(async (check) => {
        check();
        if (prepared) return;
        if (!credentials?.create || !credentials?.get || !crypto?.subtle) {
          throw new Error('Passkeys are unavailable here. Choose a password or session only.');
        }
        if (!pendingPasskey) {
          const salt = crypto.getRandomValues(new Uint8Array(SALT_BYTES));
          const credential = await passkeyOperation('creation', () => credentials.create({publicKey: {
            challenge: crypto.getRandomValues(new Uint8Array(32)), rp: {name: 'rePlay'},
            user: {id: crypto.getRandomValues(new Uint8Array(32)), name: 'rePlay cloud connection', displayName: 'rePlay cloud connection'},
            pubKeyCredParams: [{type: 'public-key', alg: -7}, {type: 'public-key', alg: -257}],
            authenticatorSelection: {residentKey: 'preferred', userVerification: 'required'},
            attestation: 'none', timeout: 60000, extensions: {prf: {eval: {first: salt}}},
          }}));
          check();
          const prf = credential?.getClientExtensionResults()?.prf;
          if (!prf?.enabled) {
            throw new Error('Passkey created, but the selected provider did not enable PRF encryption. A passkey can work for sign-in without supporting encrypted browser storage. Try another provider, or choose a password or session only.');
          }
          const credentialId = new Uint8Array(credential.rawId);
          if (!credentialId.length || credentialId.length > 1024) throw new Error('Invalid passkey identifier');
          pendingPasskey = {salt, credentialId};
          if (prf.results?.first) {
            const key = await derivePasskeyKey(crypto, prf.results.first, salt);
            check();
            // Registration output alone does not prove this provider can unlock later.
            const unlockKey = await passkeyKey(crypto, credentials, credentialId, salt);
            check();
            const iv = crypto.getRandomValues(new Uint8Array(12));
            const probe = await crypto.subtle.encrypt({name:'AES-GCM', iv}, key, new Uint8Array([1]));
            try { await crypto.subtle.decrypt({name:'AES-GCM', iv}, unlockKey, probe); }
            catch { throw new Error('This provider returned different encryption keys during setup and unlock. No connection was saved. Choose another provider or a password.'); }
            check();
            prepared = {key: unlockKey, salt, mode: 'passkey', credentialId};
            return;
          }
        }
        const {salt, credentialId} = pendingPasskey;
        const key = await passkeyKey(crypto, credentials, credentialId, salt);
        check();
        prepared = {key, salt, mode: 'passkey', credentialId};
      });
    },

    async createPasskey(data) {
      if (!prepared) throw new Error('Set up a passkey before saving the connection');
      const protection = prepared;
      return createProtected(data, protection);
    },

    async createUnprotected(data, {acknowledged = false} = {}) {
      if (acknowledged !== true) throw new Error('Acknowledge the risks of unprotected storage first');
      return createProtected(data, {mode: 'unprotected'});
    },
    async exists() {
      return (await storage.read()) !== undefined;
    },

    async create(passphrase, data) {
      checkPassphrase(passphrase, MIN_PASSPHRASE);
      const plaintext = serialize(data);
      try {
        await enqueue(async (check) => {
          check();
          if (await storage.read() !== undefined) throw new Error('A browser vault already exists');
          check();
          if (!crypto?.subtle) throw new Error('Browser encryption requires a secure origin');
          const salt = crypto.getRandomValues(new Uint8Array(SALT_BYTES));
          const key = await deriveKey(crypto, passphrase, salt);
          check();
          const record = await seal(crypto, key, salt, plaintext);
          check();
          const created = await storage.create(record);
          check();
          if (!created) throw new Error('A browser vault already exists');
          session = { key, salt, iv: record.iv };
        });
      } finally {
        plaintext.fill(0);
      }
    },

    async unlock(passphrase) {
      lock();
      return enqueue(async (check) => {
        check();
        const record = await storage.read();
        check();
        if (record === undefined) throw new Error('There is no saved browser vault');
        validateRecord(record);
        let key;
        if (record.version === 1) {
          checkPassphrase(passphrase);
          key = await deriveKey(crypto, passphrase, record.salt);
        } else if (record.mode === 'passkey') {
          if (!credentials?.get) throw new Error('Passkeys are unavailable in this browser');
          key = await passkeyKey(crypto, credentials, record.credentialId, record.salt);
        }
        check();
        const data = record.mode === 'unprotected' ? record.data : await unseal(crypto, key, record);
        check();
        session = { key, salt: record.salt, iv: record.iv, mode: record.mode, credentialId: record.credentialId };
        return data;
      });
    },

    async save(data) {
      if (!session) throw new Error('The vault is locked');
      const plaintext = serialize(data);
      try {
        await enqueue(async (check) => {
          check();
          if (!session) throw new Error('The vault is locked');
          const { key, salt, iv } = session;
          const record = await seal(crypto, key, salt, plaintext, session);
          check();
          const saved = await storage.replace(iv, record);
          check();
          if (!saved) {
            lock();
            throw new Error('The vault changed in another tab. Unlock it again.');
          }
          session = { ...session, iv: record.iv };
        });
      } finally {
        plaintext.fill(0);
      }
    },

    lock,

    async forget() {
      const expectedIv = session?.iv;
      lock();
      await enqueue(async () => {
        let iv = expectedIv;
        if (!iv) {
          const record = await storage.read();
          if (record === undefined) return;
          iv = record?.iv;
          if (!(iv instanceof Uint8Array) || iv.length !== IV_BYTES) {
            throw new Error('The browser vault record has no valid revision');
          }
        }
        if (!await storage.remove(iv)) {
          throw new Error('The vault changed in another tab. Review it before forgetting.');
        }
      });
    },
  };

  async function createProtected(data, protection) {
    const plaintext = serialize(data);
    try {
      await enqueue(async (check) => {
        check();
        if (await storage.read() !== undefined) throw new Error('A browser vault already exists');
        check();
        const record = await seal(crypto, protection.key, protection.salt, plaintext, protection);
        check();
        const created = await storage.create(record);
        check();
        if (!created) throw new Error('A browser vault already exists');
        session = {...protection, iv: record.iv};
        prepared = undefined;
        pendingPasskey = undefined;
      });
    } finally { plaintext.fill(0); }
  }
}

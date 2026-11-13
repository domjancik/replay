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

function cipherParams(iv) {
  return { name: 'AES-GCM', iv, additionalData: associatedData, tagLength: TAG_BYTES * 8 };
}

async function seal(crypto, key, salt, plaintext) {
  const iv = crypto.getRandomValues(new Uint8Array(IV_BYTES));
  const ciphertext = await crypto.subtle.encrypt(cipherParams(iv), key, plaintext);
  return { version: VERSION, salt, iv, ciphertext: new Uint8Array(ciphertext) };
}

async function unseal(crypto, key, record) {
  let plaintext;
  try {
    plaintext = new Uint8Array(await crypto.subtle.decrypt(
      cipherParams(record.iv), key, record.ciphertext,
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

/**
 * Persist one encrypted cloud profile. The injected storage adapter must use
 * atomic create, replace, and remove operations. The caller owns plaintext returned by
 * unlock() and should release its references when locking the vault.
 */
export function createVault({
  storage = indexedStorage(globalThis.indexedDB), crypto = globalThis.crypto,
} = {}) {
  let session;
  let generation = 0;
  let pending = Promise.resolve();

  function lock() {
    generation += 1;
    session = undefined;
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
      checkPassphrase(passphrase);
      lock();
      return enqueue(async (check) => {
        check();
        const record = await storage.read();
        check();
        if (record === undefined) throw new Error('There is no saved browser vault');
        validateRecord(record);
        const key = await deriveKey(crypto, passphrase, record.salt);
        check();
        const data = await unseal(crypto, key, record);
        check();
        session = { key, salt: record.salt, iv: record.iv };
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
          const record = await seal(crypto, key, salt, plaintext);
          check();
          const saved = await storage.replace(iv, record);
          check();
          if (!saved) {
            lock();
            throw new Error('The vault changed in another tab. Unlock it again.');
          }
          session = { key, salt, iv: record.iv };
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
}

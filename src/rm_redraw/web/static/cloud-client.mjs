// The unofficial sync protocol accepts byte-addressed and child-addressed
// indexes. See rmcloud-go v1.0.0, internal/domain/{index,hash}.go.
const encoder = new TextEncoder();
const decoder = new TextDecoder('utf-8', {fatal: true, ignoreBOM: true});
const MiB = 1024 * 1024;
const maxIndexBytes = 4 * MiB;
const maxMetadataBytes = MiB;
const maxArchiveBytes = 128 * MiB;
const maxEntries = 20000;
const maxCacheBytes = 5 * MiB;
const maxCacheEntries = 12000;
const maxTokenBytes = 16 * 1024;
const uuid = /^[\da-f]{8}(?:-[\da-f]{4}){3}-[\da-f]{12}$/i;
const hashPattern = /^[\da-f]{64}$/;
const compare = (a, b) => a < b ? -1 : a > b ? 1 : 0;

function validToken(token) {
  if (typeof token !== 'string' || token.length > maxTokenBytes || !/^[A-Za-z0-9._~+/=-]+$/.test(token)) {
    throw new Error('Invalid cloud token');
  }
  return token;
}

async function digest(bytes) {
  const hash = await globalThis.crypto.subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(hash), byte => byte.toString(16).padStart(2, '0')).join('');
}

function jsonObject(bytes) {
  let value;
  try {
    value = JSON.parse(decoder.decode(bytes));
  } catch {
    throw new Error('Malformed cloud JSON');
  }
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('Malformed cloud JSON object');
  }
  return value;
}

function indexNumber(field) {
  if (!/^\+?\d+$/.test(field) || !Number.isSafeInteger(Number(field))) {
    throw new Error('Invalid cloud index number');
  }
  return Number(field);
}

function parseIndex(bytes, owner) {
  const [version, ...lines] = decoder.decode(bytes).split(/\r\n|[\n\r\v\f\u0085\u2028\u2029]/u);
  let count;
  if (version.trim() === '4') {
    const header = lines.shift()?.trim().split(':');
    if (header?.length !== 4 || header[0] !== '0' || header[1] !== owner) {
      throw new Error('Invalid cloud index owner');
    }
    count = indexNumber(header[2]);
    indexNumber(header[3]);
  } else if (version.trim() !== '3') {
    throw new Error('Unsupported cloud index schema');
  }

  const entries = new Map();
  for (const raw of lines) {
    const line = raw.trim();
    if (!line) continue;
    const [hash, , name, subfiles, size, extra] = line.split(':');
    if (extra !== undefined || !hashPattern.test(hash) || !name || name.length > 512 || entries.has(name)) {
      throw new Error('Invalid or duplicate cloud index record');
    }
    indexNumber(subfiles);
    entries.set(name, {hash, name, size: indexNumber(size)});
    if (entries.size > maxEntries) throw new Error('Cloud index has too many entries');
  }
  if (count !== undefined && count !== entries.size) throw new Error('Cloud index count mismatch');
  return entries;
}

async function verifyIndex(bytes, hash, owner) {
  const entries = parseIndex(bytes, owner);
  if (await digest(bytes) === hash) return entries;

  // Go sorts strings by UTF-8 bytes. Unicode code point order is equivalent.
  const names = [...entries.keys()].sort((a, b) => {
    const aa = [...a];
    const bb = [...b];
    for (let i = 0; i < Math.min(aa.length, bb.length); i++) {
      const delta = aa[i].codePointAt(0) - bb[i].codePointAt(0);
      if (delta) return delta;
    }
    return aa.length - bb.length;
  });
  const children = new Uint8Array(names.length * 32);
  for (const [index, name] of names.entries()) {
    const childHash = entries.get(name).hash;
    for (let i = 0; i < 32; i++) children[index * 32 + i] = parseInt(childHash.slice(i * 2, i * 2 + 2), 16);
  }
  if (await digest(children) !== hash) throw new Error('Cloud index hash mismatch');
  return entries;
}

async function verifyBlob(bytes, {hash, size}) {
  if (await digest(bytes) !== hash) throw new Error('Cloud file hash mismatch');
  if (size > 0 && bytes.length !== size) throw new Error('Cloud file size mismatch');
  return bytes;
}

function safeMember(name) {
  const parts = name.split('/');
  if (name.length > 255 || parts.length > 12 || parts.some(part =>
    part.length > 128 || !/^[A-Za-z0-9_.-]+$/.test(part) || part.endsWith('.') ||
    /^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)/i.test(part))) {
    throw new Error('Unsafe cloud archive member path');
  }
  return parts;
}

function archiveMembers(index, id) {
  const paths = new Set();
  const directories = new Set();
  let size = 22;
  const members = [...index.values()].map(entry => {
    const parts = safeMember(entry.name).map(part => part.toLowerCase());
    const key = parts.join('/');
    if (paths.has(key) || directories.has(key)) throw new Error('Conflicting cloud archive member paths');
    paths.add(key);
    for (let i = 1; i < parts.length; i++) {
      const directory = parts.slice(0, i).join('/');
      if (paths.has(directory)) throw new Error('Conflicting cloud archive member paths');
      directories.add(directory);
    }
    if (key.endsWith('.content') && entry.name !== `${id}.content`) {
      throw new Error('Unexpected document metadata in cloud archive');
    }
    const nameBytes = encoder.encode(entry.name);
    size += 76 + nameBytes.length * 2 + entry.size;
    if (size > maxArchiveBytes) throw new Error('Cloud notebook exceeds 128 MiB');
    return {...entry, nameBytes};
  });
  if (!index.has(`${id}.metadata`) || !index.has(`${id}.content`) || !members.some(entry => entry.name.endsWith('.rm'))) {
    throw new Error('Cloud document has no notebook metadata or ink pages');
  }
  return members;
}

function visibleTree(records) {
  const visible = [];
  for (const record of records.values()) {
    const names = [];
    const visited = new Set();
    let next = record;
    while (next && !next.hidden && !visited.has(next.id) && names.length < 64) {
      names.unshift(next.name);
      if (next.parent === '') {
        visible.push({id: record.id, name: record.name, path: names.join('/'), kind: record.kind, parent: record.parent});
        break;
      }
      visited.add(next.id);
      next = records.get(next.parent);
      if (next?.kind !== 'folder') break;
    }
  }
  return visible.sort((a, b) => compare(a.path, b.path) || compare(a.id, b.id));
}

function readMetadata(bytes, id) {
  const {parent = '', visibleName, type, deleted, trashed} = jsonObject(bytes);
  if (!['CollectionType', 'DocumentType'].includes(type)) return null;
  const kind = type === 'CollectionType' ? 'folder' : 'document';
  const name = typeof visibleName === 'string' && visibleName.trim() ? visibleName.slice(0, 240) : id;
  const hidden = parent === 'trash' || Boolean(deleted || trashed);
  if (typeof parent !== 'string' || (!hidden && parent !== '' && !uuid.test(parent))) return null;
  return {id, name, parent, kind, hidden};
}

function cacheRowSize(row) {
  return encoder.encode(JSON.stringify(row)).length + 1;
}

function blobCache(snapshot) {
  const entries = new Map();
  let bytes = 0;
  function store(hash, filename, text) {
    const row = [hash, filename, text];
    const size = cacheRowSize(row);
    if (size > maxCacheBytes - 512) return;
    const key = `${hash}/${filename}`;
    const existing = entries.get(key);
    if (existing) {
      bytes -= existing.size;
      entries.delete(key);
    }
    while (entries.size >= maxCacheEntries || bytes + size > maxCacheBytes - 512) {
      const oldest = entries.keys().next().value;
      bytes -= entries.get(oldest).size;
      entries.delete(oldest);
    }
    entries.set(key, {row, size});
    bytes += size;
  }

  if (Array.isArray(snapshot?.blobs) && snapshot.blobs.length <= maxCacheEntries) {
    let scanned = 0;
    for (const row of snapshot.blobs) {
      if (!Array.isArray(row) || row.length !== 3) continue;
      const [hash, filename, text] = row;
      if (typeof hash !== 'string' || !hashPattern.test(hash) || typeof filename !== 'string' ||
        filename.length > 512 || typeof text !== 'string' || text.length > maxIndexBytes) continue;
      scanned += cacheRowSize(row);
      if (scanned > maxCacheBytes) break;
      store(hash, filename, text);
    }
  }
  return {
    store,
    lookup(hash, filename) { return entries.get(`${hash}/${filename}`)?.row[2]; },
    snapshot(scope) { return {version: 1, scope, blobs: [...entries.values()].map(({row}) => [...row])}; },
  };
}

const crcTable = Uint32Array.from({length: 256}, (_, byte) => {
  for (let bit = 0; bit < 8; bit++) byte = (byte >>> 1) ^ (byte & 1 ? 0xedb88320 : 0);
  return byte;
});

function crc32(bytes) {
  let value = 0xffffffff;
  for (const byte of bytes) value = (value >>> 8) ^ crcTable[(value ^ byte) & 0xff];
  return (value ^ 0xffffffff) >>> 0;
}

// Stored ZIP (32-bit fields), UTF-8 member names and a fixed valid DOS date.
function storedZip(files, size) {
  const out = new Uint8Array(size);
  const view = new DataView(out.buffer);
  const word = (offset, value) => view.setUint16(offset, value, true);
  const dword = (offset, value) => view.setUint32(offset, value, true);
  let local = 0;
  let central = size - 22 - files.reduce((sum, {nameBytes}) => sum + 46 + nameBytes.length, 0);
  const directory = central;
  for (const {nameBytes, data} of files) {
    const crc = crc32(data);
    dword(local, 0x04034b50);
    word(local + 4, 20);
    word(local + 6, 0x800);
    word(local + 12, 33);
    dword(local + 14, crc);
    dword(local + 18, data.length);
    dword(local + 22, data.length);
    word(local + 26, nameBytes.length);
    out.set(nameBytes, local + 30);
    out.set(data, local + 30 + nameBytes.length);

    dword(central, 0x02014b50);
    word(central + 4, 20);
    word(central + 6, 20);
    word(central + 8, 0x800);
    word(central + 14, 33);
    dword(central + 16, crc);
    dword(central + 20, data.length);
    dword(central + 24, data.length);
    word(central + 28, nameBytes.length);
    dword(central + 42, local);
    out.set(nameBytes, central + 46);
    local += 30 + nameBytes.length + data.length;
    central += 46 + nameBytes.length;
  }
  dword(central, 0x06054b50);
  word(central + 8, files.length);
  word(central + 10, files.length);
  dword(central + 12, central - directory);
  dword(central + 16, directory);
  return out;
}

export function createCloudClient({relay, cache, onCache} = {}) {
  if (typeof relay !== 'function') throw new TypeError('A cloud relay is required');
  let connection = new AbortController();
  let deviceToken;
  let sessionToken;
  let snapshot;
  let initialCache = cache;
  let documents = new Map();
  let listing;
  let previewDocuments = new Map();
  let downloading = false;

  function reset(token, preserveInitial = false) {
    connection.abort();
    connection = new AbortController();
    deviceToken = token;
    sessionToken = undefined;
    snapshot = undefined;
    documents = new Map();
    previewDocuments = new Map();
    listing = undefined;
    downloading = false;
    if (!preserveInitial) initialCache = undefined;
  }

  function setDeviceToken(token) {
    validToken(token);
    if (token !== deviceToken) reset(token, deviceToken === undefined);
  }

  function requireDevice() {
    if (!deviceToken) throw new Error('Cloud connection is locked');
    return deviceToken;
  }

  function check(signal) {
    if (signal.aborted) throw new Error('Cloud connection changed');
  }

  async function request(payload, signal, limit) {
    check(signal);
    let bytes;
    try {
      bytes = await relay(payload, {signal});
    } catch (error) {
      check(signal);
      throw error;
    }
    check(signal);
    if (!(bytes instanceof Uint8Array) || bytes.length > limit) throw new Error('Invalid or oversized cloud response');
    return bytes;
  }

  function sessionReads(device, signal, initialToken) {
    let token = initialToken;
    let renewal;
    let refreshed = false;
    const open = async () => {
      token = validToken(decoder.decode(await request({action: 'session', token: device}, signal, maxTokenBytes)));
    };
    return {
      open,
      token: () => token,
      async read(payload, limit) {
        if (renewal) await renewal;
        const alreadyRenewed = refreshed;
        try {
          return await request({...payload, token}, signal, limit);
        } catch (error) {
          if (alreadyRenewed || (error?.status !== 401 && error?.status !== 403)) throw error;
          if (!renewal) renewal = open().then(() => { refreshed = true; });
          await renewal;
          return request({...payload, token}, signal, limit);
        }
      },
    };
  }

  async function verifiedText(name, hash, limit, verify, blobs, read, signal) {
    const cached = blobs.lookup(hash, name);
    if (cached !== undefined) {
      try {
        const bytes = encoder.encode(cached);
        if (bytes.length <= limit) {
          const value = await verify(bytes);
          check(signal);
          return value;
        }
      } catch {
        check(signal);
      }
    }
    const bytes = await read({action: 'file', hash, filename: name}, limit);
    const value = await verify(bytes);
    check(signal);
    blobs.store(hash, name, decoder.decode(bytes));
    return value;
  }

  function fetchIndex(name, hash, owner, blobs, read, signal) {
    return verifiedText(name, hash, maxIndexBytes, bytes => verifyIndex(bytes, hash, owner), blobs, read, signal);
  }

  async function refresh(device, signal, onProgress) {
    const session = sessionReads(device, signal);
    await session.open();
    const scope = await digest(encoder.encode(device));
    const previous = snapshot ?? initialCache;
    const blobs = blobCache(previous?.version === 1 && previous.scope === scope ? previous : undefined);
    const {hash, generation} = jsonObject(await session.read({action: 'root'}, 65536));
    if (typeof hash !== 'string' || (hash !== '' && !hashPattern.test(hash)) ||
      !Number.isSafeInteger(generation) || generation < 0 || (hash === '' && generation !== 0)) {
      throw new Error('Invalid cloud root pointer');
    }
    const root = hash === '' ? new Map() : await fetchIndex('root.docSchema', hash, '.', blobs, session.read, signal);
    const records = new Map();
    const ids = [...root.keys()].filter(id => uuid.test(id));
    onProgress?.({completed: 0, total: ids.length, entries: []});
    for (let start = 0; start < ids.length; start += 2) {
      const batch = ids.slice(start, start + 2);
      const results = await Promise.allSettled(batch.map(async id => {
        const index = await fetchIndex(`${id}.docSchema`, root.get(id).hash, id, blobs, session.read, signal);
        const metadata = index.get(`${id}.metadata`);
        if (!metadata) return;
        const bytes = await verifiedText(metadata.name, metadata.hash, maxMetadataBytes,
          data => verifyBlob(data, metadata), blobs, session.read, signal);
        const record = readMetadata(bytes, id);
        if (record) records.set(id, record);
      }));
      const failed = results.find(result => result.status === 'rejected');
      if (failed) throw failed.reason;
      check(signal);
      previewDocuments = new Map(visibleTree(records).filter(entry => entry.kind === 'document').map(({id}) => [id, root.get(id)]));
      sessionToken = session.token();
      onProgress?.({completed: Math.min(start + 2, ids.length), total: ids.length, entries: visibleTree(records)});
    }
    check(signal);
    const tree = visibleTree(records);
    const nextSnapshot = blobs.snapshot(scope);
    documents = new Map(tree.filter(entry => entry.kind === 'document').map(({id}) => [id, root.get(id)]));
    sessionToken = session.token();
    initialCache = undefined;
    snapshot = nextSnapshot;
    onCache?.(getCache());
    return tree;
  }

  function getCache() {
    return snapshot ? structuredClone(snapshot) : null;
  }

  async function downloadDocument(id, selected, device, signal) {
    const session = sessionReads(device, signal, sessionToken);
    const blobs = blobCache(snapshot);
    const index = await fetchIndex(`${id}.docSchema`, selected.hash, id, blobs, session.read, signal);
    const members = archiveMembers(index, id);
    const content = index.get(`${id}.content`);
    const fetchFile = async (entry, limit) => {
      const data = await session.read({action: 'file', hash: entry.hash, filename: entry.name}, limit);
      await verifyBlob(data, entry);
      check(signal);
      return data;
    };
    const contentBytes = await fetchFile(content, maxMetadataBytes);
    const {fileType} = jsonObject(contentBytes);
    const hasEpub = members.some(entry => entry.name.toLowerCase().endsWith('.epub'));
    if (hasEpub || ![undefined, '', 'notebook', 'pdf'].includes(fileType)) {
      throw new Error('Select a notebook or an annotated PDF');
    }

    let size = 22;
    const files = [];
    for (const entry of members) {
      size += 76 + 2 * entry.nameBytes.length;
      if (size > maxArchiveBytes) throw new Error('Cloud notebook exceeds 128 MiB');
      const data = entry.name === content.name ? contentBytes : await fetchFile(entry, maxArchiveBytes - size);
      size += data.length;
      if (size > maxArchiveBytes) throw new Error('Cloud notebook exceeds 128 MiB');
      files.push({...entry, data});
    }
    sessionToken = session.token();
    return storedZip(files, size);
  }

  return {
    async pair(code) {
      if (typeof code !== 'string' || !/^[A-Za-z0-9]{8}$/.test(code)) throw new Error('Enter an 8-character cloud pairing code');
      reset();
      const {signal} = connection;
      const device_id = globalThis.crypto.randomUUID();
      const token = validToken(decoder.decode(await request({action: 'pair', code, device_id}, signal, maxTokenBytes)));
      check(signal);
      setDeviceToken(token);
      return token;
    },
    setDeviceToken,
    lock() { reset(); },
    getCache,
    async list({onProgress} = {}) {
      const device = requireDevice();
      if (downloading) throw new Error('Already downloading a cloud document');
      if (listing) return listing;
      const pending = refresh(device, connection.signal, onProgress);
      listing = pending;
      try {
        return await pending;
      } finally {
        if (listing === pending) { listing = undefined; previewDocuments = new Map(); }
      }
    },
    async preview(id) {
      const device = requireDevice();
      if (downloading) throw new Error('Wait for the current cloud request');
      const selected = (listing ? previewDocuments : documents).get(id);
      if (!selected) throw new Error('Select a visible cloud document');
      const {signal} = connection;
      const session = sessionReads(device, signal, sessionToken);
      const index = await fetchIndex(`${id}.docSchema`, selected.hash, id, blobCache(snapshot), session.read, signal);
      const candidates = [...index.values()].filter(entry =>
        entry.name.startsWith(`${id}.thumbnails/`) && entry.name.endsWith('.png') && entry.size <= 2 * MiB);
      candidates.sort((a, b) => compare(a.name, b.name));
      if (!candidates.length) return null;
      const entry = candidates[0];
      const bytes = await session.read({action: 'file', hash: entry.hash, filename: entry.name}, 2 * MiB);
      await verifyBlob(bytes, entry); check(signal);
      const header = [137, 80, 78, 71, 13, 10, 26, 10];
      if (bytes.length < 24 || !header.every((value, i) => bytes[i] === value) ||
          decoder.decode(bytes.subarray(12, 16)) !== 'IHDR') throw new Error('Invalid preview PNG');
      const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
      const width = view.getUint32(16), height = view.getUint32(20);
      if (!width || !height || width > 8192 || height > 8192 || width * height > 16 * 1024 * 1024) throw new Error('Oversized preview PNG');
      sessionToken = session.token();
      return bytes;
    },
    async download(id) {
      const device = requireDevice();
      if (listing) throw new Error('Wait for the cloud library refresh');
      const selected = documents.get(id);
      if (!selected) throw new Error('Select a visible cloud document');
      if (downloading) throw new Error('Already downloading a cloud document');
      const {signal} = connection;
      downloading = true;
      try {
        return await downloadDocument(id, selected, device, signal);
      } finally {
        if (!signal.aborted) downloading = false;
      }
    },
    async revoke() {
      const token = requireDevice();
      const {signal} = connection;
      await request({action: 'revoke', token}, signal, 65536);
      check(signal);
      reset();
    },
  };
}

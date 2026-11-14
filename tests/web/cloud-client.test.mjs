import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {test} from 'node:test';
import {createCloudClient} from '../../src/rm_redraw/web/static/cloud-client.mjs';

const encode = value => new TextEncoder().encode(value);
const decode = bytes => new TextDecoder().decode(bytes);
const sha256 = bytes => createHash('sha256').update(bytes).digest('hex');
const folder = '00112233-4455-4677-8899-aabbccddeeff';
const document = '11112233-4455-4677-8899-aabbccddeeff';
const hidden = '22112233-4455-4677-8899-aabbccddeeff';
const page = '33112233-4455-4677-8899-aabbccddeeff';

function fixture({badPath, oversized = false, fileType = 'notebook', hiddenParent = 'trash', documentParent = folder, thumbnail} = {}) {
  const files = new Map();
  const requests = [];
  let generation = 0;
  let root;

  function blob(filename, text, hash) {
    const bytes = encode(typeof text === 'string' ? text : JSON.stringify(text));
    const entry = {filename, hash: hash ?? sha256(bytes), size: bytes.length};
    files.set(`${entry.hash}/${filename}`, bytes);
    return entry;
  }

  function index(filename, members, owner, nodeAddress = true) {
    const lines = members.map(({hash, filename, size}) => `${hash}:0:${filename}:0:${size}`);
    const children = [...members].sort((a, b) => a.filename < b.filename ? -1 : 1);
    const node = Buffer.concat(children.map(entry => Buffer.from(entry.hash, 'hex')));
    const text = owner ? `4\n0:${owner}:${lines.length}:0\n` : '3\n';
    return blob(filename, text + lines.join('\n') + '\n', nodeAddress ? sha256(node) : undefined);
  }

  function refresh(visibleName = 'Notebook') {
    generation++;
    const folderMeta = blob(`${folder}.metadata`, {visibleName: 'Sketches', parent: '', type: 'CollectionType'});
    const docMeta = blob(`${document}.metadata`, {visibleName, parent: documentParent, type: 'DocumentType'});
    const hiddenMeta = blob(`${hidden}.metadata`, {visibleName: 'Hidden', parent: hiddenParent, type: 'DocumentType'});
    const content = blob(`${document}.content`, {fileType, pages: [page]});
    const ink = blob(`${document}/${page}.rm`, 'Synthetic ink');
    const members = [oversized ? {...ink, size: 128 * 1024 * 1024} : ink, docMeta, content];
    if (thumbnail) {
      const name = `${document}.thumbnails/${page}.png`;
      const entry = {filename: name, hash: sha256(thumbnail), size: thumbnail.length};
      files.set(`${entry.hash}/${name}`, thumbnail); members.push(entry);
    }
    if (badPath) members.push(blob(badPath, 'Escape'));
    const docIndex = index(`${document}.docSchema`, members, document);
    const folderIndex = index(`${folder}.docSchema`, [folderMeta], folder, false);
    const hiddenIndex = index(`${hidden}.docSchema`, [hiddenMeta]);
    root = index('root.docSchema', [docIndex, hiddenIndex, folderIndex].map(entry => ({
      ...entry, filename: entry.filename.replace('.docSchema', ''),
    })), '.');
    return {ink, docMeta};
  }

  const {ink, docMeta} = refresh();
  const relay = async payload => {
    requests.push(payload);
    if (payload.action === 'pair') return encode('synthetic-device');
    if (payload.action === 'session') return encode('synthetic-session');
    if (payload.action === 'root') return encode(JSON.stringify({hash: root.hash, generation}));
    if (payload.action === 'file') return files.get(`${payload.hash}/${payload.filename}`);
    if (payload.action === 'revoke') return new Uint8Array();
    assert.fail(`Unexpected action ${payload.action}`);
  };
  return {relay, requests, refresh, files, ink, docMeta};
}

function localEntries(bytes) {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const entries = new Map();
  let offset = 0;
  while (view.getUint32(offset, true) === 0x04034b50) {
    assert.equal(view.getUint16(offset + 8, true), 0);
    const size = view.getUint32(offset + 18, true);
    const length = view.getUint16(offset + 26, true);
    const name = decode(bytes.subarray(offset + 30, offset + 30 + length));
    const start = offset + 30 + length;
    const data = bytes.subarray(start, start + size);
    entries.set(name, {data, offset, crc: view.getUint32(offset + 14, true)});
    offset = start + size;
  }
  const directory = offset;
  for (const [name, {data, crc, offset: local}] of entries) {
    assert.equal(view.getUint32(offset, true), 0x02014b50);
    assert.equal(view.getUint32(offset + 16, true), crc);
    assert.equal(view.getUint32(offset + 20, true), data.length);
    assert.equal(view.getUint32(offset + 24, true), data.length);
    const length = view.getUint16(offset + 28, true);
    assert.equal(view.getUint32(offset + 42, true), local);
    assert.equal(decode(bytes.subarray(offset + 46, offset + 46 + length)), name);
    offset += 46 + length;
  }
  assert.equal(offset, bytes.length - 22);
  assert.equal(view.getUint32(bytes.length - 22, true), 0x06054b50);
  assert.equal(view.getUint16(bytes.length - 12, true), entries.size);
  assert.equal(view.getUint32(bytes.length - 10, true), offset - directory);
  assert.equal(view.getUint32(bytes.length - 6, true), directory);
  return entries;
}

test('pairs, lists verified visible metadata and downloads only the selected document', async () => {
  const {relay, requests, ink} = fixture();
  const client = createCloudClient({relay});
  assert.equal(await client.pair('abcdefgh'), 'synthetic-device');
  assert.match(requests[0].device_id, /^[\da-f]{8}-[\da-f]{4}-4[\da-f]{3}-[89ab][\da-f]{3}-[\da-f]{12}$/);
  assert.deepEqual(await client.list(), [
    {id: folder, name: 'Sketches', path: 'Sketches', kind: 'folder', parent: ''},
    {id: document, name: 'Notebook', path: 'Sketches/Notebook', kind: 'document', parent: folder},
  ]);
  assert.deepEqual(requests[1], {action: 'session', token: 'synthetic-device'});
  assert.equal(requests.some(request => request.filename?.endsWith('.rm') || request.filename?.endsWith('.content')), false);
  assert.throws(() => client.setDeviceToken('bad token'), /token/i);
  const archive = localEntries(await client.download(document));
  assert.equal(archive.size, 3);
  assert.equal(decode(archive.get(ink.filename).data), 'Synthetic ink');
  assert.equal(archive.get(ink.filename).crc, 0xaf03b5b8);
  assert.equal(requests.find(request => request.filename === ink.filename).token, 'synthetic-session');
  await assert.rejects(client.download(hidden), /visible/i);
  await client.revoke();
  assert.deepEqual(requests.at(-1), {action: 'revoke', token: 'synthetic-device'});
  assert.equal(client.getCache(), null);
  await assert.rejects(client.list(), /locked/i);
});

test('refreshes root, reuses only verified same-account content, and requests changed indexes', async () => {
  const {relay, requests, refresh} = fixture();
  const changes = [];
  const client = createCloudClient({relay, onCache: cache => changes.push(cache)});
  client.setDeviceToken('synthetic-device');
  await client.list();
  const cache = JSON.parse(JSON.stringify(client.getCache()));
  assert.deepEqual(cache, changes.at(-1));
  assert.doesNotMatch(JSON.stringify(cache), /synthetic-device|synthetic-session/);

  const restored = createCloudClient({relay, cache});
  restored.setDeviceToken('synthetic-device');
  requests.length = 0;
  await restored.list();
  assert.deepEqual(requests.map(request => request.action), ['session', 'root']);
  refresh('Renamed');
  requests.length = 0;
  assert.equal((await restored.list()).find(entry => entry.id === document).name, 'Renamed');
  assert.deepEqual(requests.filter(request => request.filename).map(request => request.filename), [
    'root.docSchema', `${document}.docSchema`, `${document}.metadata`,
  ]);

  const switched = createCloudClient({relay, cache});
  switched.setDeviceToken('another-device');
  requests.length = 0;
  await switched.list();
  assert.equal(requests.some(request => request.filename === `${folder}.metadata`), true);
  assert.notEqual(switched.getCache().scope, cache.scope);
});

test('rejects changed metadata and selected raw member bytes', async () => {
  const f = fixture();
  const client = createCloudClient({relay: f.relay});
  client.setDeviceToken('synthetic-device');
  const key = `${f.docMeta.hash}/${f.docMeta.filename}`;
  const original = f.files.get(key);
  f.files.set(key, encode('X'.repeat(original.length)));
  await assert.rejects(client.list(), /hash/i);
  assert.equal(client.getCache(), null);
  f.files.set(key, original);
  await client.list();
  f.files.set(`${f.ink.hash}/${f.ink.filename}`, encode('different ink'));
  await assert.rejects(client.download(document), /hash/i);
});

test('accepts older notebook metadata with an empty file type', async () => {
  const {relay} = fixture({fileType: ''});
  const client = createCloudClient({relay});
  client.setDeviceToken('synthetic-device');
  await client.list();
  assert.equal(localEntries(await client.download(document)).size, 3);
});

test('rejects unsupported documents and unsafe or oversized archives before requesting ink', async () => {
  for (const [options, error] of [
    [{badPath: '../escape.rm'}, /unsafe/i],
    [{badPath: `${document}/ink with spaces.rm`}, /unsafe/i],
    [{oversized: true}, /128 MiB/i],
    [{fileType: 'epub'}, /notebook|PDF/i],
  ]) {
    const {relay, requests} = fixture(options);
    const client = createCloudClient({relay});
    client.setDeviceToken('synthetic-device');
    await client.list();
    await assert.rejects(client.download(document), error);
    assert.equal(requests.some(request => request.filename?.endsWith('.rm')), false);
  }
});

test('rechecks persisted metadata hashes before showing cached names', async () => {
  const {relay, requests} = fixture();
  const client = createCloudClient({relay});
  client.setDeviceToken('synthetic-device');
  await client.list();
  const cache = client.getCache();
  const row = cache.blobs.find(([, filename]) => filename === `${document}.metadata`);
  row[2] = row[2].replace('Notebook', 'Tampered');
  const restored = createCloudClient({relay, cache});
  restored.setDeviceToken('synthetic-device');
  requests.length = 0;
  const list = await restored.list();
  assert.equal(list.find(entry => entry.id === document).name, 'Notebook');
  assert.deepEqual(requests.filter(request => request.filename).map(request => request.filename), [row[1]]);
});

test('limits library reads to two simultaneous relay requests', async () => {
  const f = fixture();
  let active = 0;
  let peak = 0;
  const client = createCloudClient({relay: async payload => {
    active++;
    peak = Math.max(peak, active);
    try {
      await new Promise(resolve => setTimeout(resolve, 0));
      return await f.relay(payload);
    } finally {
      active--;
    }
  }});
  client.setDeviceToken('synthetic-device');
  await client.list();
  assert.equal(peak, 2);
});

test('renews an expired user session once and retries only the same immutable file', async () => {
  const f = fixture();
  const inkRequests = [];
  let sessions = 0;
  let deniedToken = 'session-1';
  const client = createCloudClient({relay: async payload => {
    if (payload.action === 'session') return encode(`session-${++sessions}`);
    if (payload.filename === f.ink.filename) {
      inkRequests.push(payload);
      if (payload.token === deniedToken || deniedToken === 'all') {
        throw Object.assign(new Error('Session expired'), {status: 401});
      }
    }
    return f.relay(payload);
  }});
  client.setDeviceToken('synthetic-device');
  await client.list();
  assert.equal(localEntries(await client.download(document)).size, 3);
  assert.equal(sessions, 2);
  assert.deepEqual(inkRequests.map(request => [request.token, request.hash]), [
    ['session-1', f.ink.hash], ['session-2', f.ink.hash],
  ]);
  deniedToken = 'all';
  await assert.rejects(client.download(document), /session expired/i);
  assert.equal(sessions, 3);
});

test('retries a rejected root read even when session renewal returns the same token', async () => {
  const f = fixture();
  let rejected = false;
  const client = createCloudClient({relay: async payload => {
    if (payload.action === 'root' && !rejected) {
      rejected = true;
      throw Object.assign(new Error('Session refused'), {status: 403});
    }
    return f.relay(payload);
  }});
  client.setDeviceToken('synthetic-device');
  assert.equal((await client.list()).length, 2);
  assert.deepEqual(f.requests.slice(0, 3).map(request => request.action), ['session', 'session', 'root']);
});

test('rejects a second archive build and invalidates a pending download on lock', async () => {
  const f = fixture();
  let signal;
  let finish;
  let started;
  const fetchingContent = new Promise(resolve => { started = resolve; });
  const client = createCloudClient({relay: async (payload, options) => {
    if (payload.filename === `${document}.content`) {
      signal = options.signal;
      return new Promise(resolve => { finish = resolve; started(); });
    }
    return f.relay(payload);
  }});
  client.setDeviceToken('synthetic-device');
  await client.list();
  const download = client.download(document);
  await fetchingContent;
  const duplicate = client.download(document);
  client.lock();
  finish(encode('late content'));
  await assert.rejects(download, /connection changed/i);
  await assert.rejects(duplicate, /already downloading/i);
  assert.equal(signal.aborted, true);
});

test('locking or changing tokens invalidates a pending session', async () => {
  let finishSession;
  const relay = async ({action}) => {
    assert.equal(action, 'session');
    return new Promise(resolve => { finishSession = resolve; });
  };
  const client = createCloudClient({relay});
  for (const invalidate of [() => client.lock(), () => client.setDeviceToken('another-device')]) {
    client.setDeviceToken('synthetic-device');
    const listing = client.list();
    invalidate();
    finishSession(encode('late-session'));
    await assert.rejects(listing, /connection changed/i);
    assert.equal(client.getCache(), null);
  }
});

const previewPng = new Uint8Array(Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=', 'base64'));
test('preview fetches only bounded verified PNG and handles absent thumbnails', async () => {
  const f = fixture({thumbnail: previewPng});
  const client = createCloudClient({relay: f.relay});
  client.setDeviceToken('synthetic-device'); await client.list();
  assert.deepEqual(await client.preview(document), previewPng);
  assert.equal(f.requests.some(r => r.filename?.endsWith('.rm')), false);
  const key = [...f.files.keys()].find(k => k.endsWith('.png'));
  f.files.set(key, new Uint8Array(previewPng.length));
  await assert.rejects(client.preview(document), /hash/i);
  client.lock(); await assert.rejects(client.preview(document), /locked/i);
  const absent = createCloudClient({relay: fixture().relay});
  absent.setDeviceToken('synthetic-device'); await absent.list();
  assert.equal(await absent.preview(document), null);
});

test('preview rejects excessive decoded dimensions and non-PNG content', async () => {
  for (const invalid of [new Uint8Array(30), (() => {
    const bytes = previewPng.slice(); new DataView(bytes.buffer).setUint32(16, 100000); return bytes;
  })()]) {
    const client = createCloudClient({relay: fixture({thumbnail: invalid}).relay});
    client.setDeviceToken('synthetic-device'); await client.list();
    await assert.rejects(client.preview(document), /preview PNG/i);
  }
});

 test('reports verified partial notebooks before the full tree finishes', async () => {
  const f = fixture({hiddenParent: ''});
  let release, started;
  const waiting = new Promise(resolve => {started = resolve;});
  const gate = new Promise(resolve => {release = resolve;});
  const client = createCloudClient({relay: async payload => {
    if (payload.filename === `${folder}.docSchema`) {started(); await gate;}
    return f.relay(payload);
  }});
  client.setDeviceToken('synthetic-device');
  const updates = [];
  const pending = client.list({onProgress: update => updates.push(update)});
  await waiting;
  try {
    assert.equal(updates.at(-1)?.completed, 2);
    assert.equal(updates.at(-1)?.total, 3);
    assert.deepEqual(updates.at(-1)?.entries.map(entry => entry.id), [hidden]);
    assert.equal(client.getCache(), null);
  } finally {release(); await pending;}
  assert.equal(updates.at(-1).completed, 3);
  assert.equal(updates.at(-1).entries.length, 3);
 });

test('verified preview is available while later library metadata is pending', async () => {
 const f=fixture({documentParent:'',thumbnail:previewPng});
 let release,started;const gate=new Promise(r=>release=r),waiting=new Promise(r=>started=r);
 const client=createCloudClient({relay:async payload=>{
  if(payload.filename===`${folder}.docSchema`){started();await gate;}
  return f.relay(payload);
 }});
 client.setDeviceToken('synthetic-device');
 const pending=client.list();await waiting;
 try {assert.deepEqual(await client.preview(document),previewPng);}
 finally {release();await pending;}
});

import assert from 'node:assert/strict';
import { test } from 'node:test';
import { setupCloud } from '../../src/rm_redraw/web/static/cloud-ui.mjs';
import { createVault } from '../../src/rm_redraw/web/static/cloud-vault.mjs';

function installGlobal(t, name, value) {
  const original = Object.getOwnPropertyDescriptor(globalThis, name);
  Object.defineProperty(globalThis, name, { value, configurable: true });
  t.after(() => {
    if (original) Object.defineProperty(globalThis, name, original);
    else delete globalThis[name];
  });
}

function fakeIndexedDB() {
  let record;
  return {
    open() {
      const request = { result: {
        close() {},
        transaction() {
          const txn = { objectStore: () => ({
            get() {
              const read = {};
              queueMicrotask(() => {
                read.result = structuredClone(record);
                read.onsuccess();
                txn.oncomplete();
              });
              return read;
            },
            add(value) { record = structuredClone(value); },
            delete() { record = undefined; },
          }) };
          return txn;
        },
      } };
      queueMicrotask(() => request.onsuccess());
      return request;
    },
  };
}

test('failed stale-vault deletion locks UI after either revoke or forget', async (t) => {
  for (const action of ['revoke', 'forget']) {
    await t.test(action, async (t) => {
      const indexedDB = fakeIndexedDB();
      installGlobal(t, 'indexedDB', indexedDB);
      const vault = createVault();
      const phrase = 'synthetic test passphrase';
      await vault.create(phrase, { deviceToken: 'old-device', cache: null });
      const elements = new Map();
      function element(id) {
        if (!elements.has(id)) {
          elements.set(id, {
            checked: false, disabled: false, value: '', textContent: '',
            showModal() {}, addEventListener() {}, querySelectorAll: () => [],
            replaceChildren() { this.cleared = true; },
          });
        }
        return elements.get(id);
      }
      installGlobal(t, 'document', { getElementById: element });
      installGlobal(t, 'window', { addEventListener() {} });
      let revokeCalls = 0;
      t.mock.method(globalThis, 'fetch', async (_path, options) => {
        assert.deepEqual(JSON.parse(options.body), { action: 'revoke', token: 'old-device' });
        revokeCalls++;
        return new Response('{}');
      });
      setupCloud({ sessionToken: () => 'test-session', importArchive() {} });
      t.mock.timers.enable({ apis: ['setTimeout'] });
      await element('cloud-open').onclick();
      element('cloud-passphrase').value = phrase;
      await element('cloud-unlock').onclick();
      assert.equal(element('cloud-refresh').disabled, false);
      element('cloud-items').cleared = false;

      await vault.forget();
      await vault.create(phrase, { deviceToken: 'new-device', cache: null });
      element('cloud-revoke-confirm').checked = true;
      await element(`cloud-${action}`).onclick();

      assert.match(element('cloud-status').textContent, /changed in another tab/);
      assert.equal(element('cloud-refresh').disabled, true);
      assert.equal(element('cloud-unlock').disabled, false);
      assert.equal(element('cloud-revoke-confirm').checked, false);
      assert.equal(element('cloud-items').cleared, true);
      assert.equal(revokeCalls, Number(action === 'revoke'));
      assert.equal((await vault.unlock(phrase)).deviceToken, 'new-device');
    });
  }
});

test('completed replay opens with its drawing as poster without resetting playback on poll', async () => {
  const {readFile} = await import('node:fs/promises');
  const {runInNewContext} = await import('node:vm');
  const source = await readFile(new URL('../../src/rm_redraw/web/static/app.js', import.meta.url), 'utf8');
  const elements = new Map();
  const context = {document: {getElementById(id) {
    if (!elements.has(id)) elements.set(id, {dataset: {}, pause() {}});
    return elements.get(id);
  }}};
  runInNewContext(source.replace('safely(start)();', ''), context);
  context.job = {id: 'synthetic', name: 'Drawing', page: 1, state: 'complete', frames: 10, expected_frames: 10};
  runInNewContext('showJob(job)', context);
  const video = elements.get('video');
  assert.equal(video.poster, '/media/synthetic/static.png');
  video.currentTime = 4;
  runInNewContext('showJob(job)', context);
  assert.equal(video.currentTime, 4);
  context.job.id = 'another';
  runInNewContext('showJob(job)', context);
  assert.equal(video.poster, '/media/another/static.png');
});

test('recent replay previews reuse static images and degrade to a placeholder', async () => {
  const {readFile} = await import('node:fs/promises');
  const {runInNewContext} = await import('node:vm');
  const source = await readFile(new URL('../../src/rm_redraw/web/static/app.js', import.meta.url), 'utf8');
  const context = {document: {createElement(tag) { return {tag, children: [], append(...items) { this.children.push(...items); }, replaceChildren(...items) { this.children = items; }}; }}};
  runInNewContext(source.replace('safely(start)();', ''), context);
  context.job = {id:'one',state:'queued'};
  const pending = runInNewContext('recentPreview(job)', context);
  assert.equal(pending.children.length, 0);
  context.job.state = 'complete';
  const ready = runInNewContext('recentPreview(job)', context);
  assert.equal(ready.children[0].src, '/media/one/static.png');
  assert.equal(ready.children[0].loading, 'lazy');
  assert.equal(runInNewContext('recentPreview(job)', context), ready);
  ready.children[0].onerror();
  assert.equal(ready.children.length, 0);
  assert.equal(ready.textContent, '—');
});

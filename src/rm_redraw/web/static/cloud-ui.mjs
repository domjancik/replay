import { createVault } from './cloud-vault.mjs';
import { createCloudClient } from './cloud-client.mjs';

export function setupCloud({ sessionToken, importArchive }) {
  const $ = (id) => document.getElementById(id);
  const vault = createVault();
  let client = null, data = null, exists = false, busy = false, accountBusy = false, epoch = 0, idle;
  const status = (message) => { $('cloud-status').textContent = message; };
  function controls() {
    $('cloud-pair').disabled = busy || exists;
    $('cloud-code').disabled = busy || exists;
    $('cloud-unlock').disabled = busy || !exists || !!data;
    $('cloud-refresh').disabled = busy || !data;
    $('cloud-lock').disabled = !data || accountBusy;
    $('cloud-close').disabled = accountBusy;
    $('cloud-pair').textContent = data && !exists ? 'Save pairing' : 'Pair and remember';
    $('cloud-forget').disabled = busy || !exists || !$('cloud-revoke-confirm').checked;
    $('cloud-revoke').disabled = busy || !data || !$('cloud-revoke-confirm').checked;
    $('cloud-passphrase').disabled = busy || (!!data && exists);
    $('cloud-confirm').disabled = busy || exists;
    $('cloud-items').querySelectorAll('button').forEach((button) => { button.disabled = busy; });
  }
  function lock(message = 'Locked. Unlock with your vault passphrase.') {
    epoch++; clearTimeout(idle); client?.lock(); client = null; data = null; vault.lock();
    $('cloud-items').replaceChildren(); $('cloud-code').value = '';
    $('cloud-passphrase').value = ''; $('cloud-confirm').value = '';
    $('cloud-revoke-confirm').checked = false;
    status(message); controls();
  }
  function touch() {
    clearTimeout(idle);
    if (data && !accountBusy) idle = setTimeout(() => lock('Cloud vault locked after five minutes of inactivity.'), 300000);
  }
  async function relay(payload, { signal } = {}) {
    const response = await fetch('/api/cloud-relay', {
      method: 'POST', cache: 'no-store', signal,
      headers: { 'Content-Type': 'application/json', 'X-Replay-Token': sessionToken() },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      const error = new Error((await response.json()).error || 'Cloud request failed');
      error.status = response.status; throw error;
    }
    return new Uint8Array(await response.arrayBuffer());
  }
  function activate() {
    client = createCloudClient({ relay, cache: data.cache });
    client.setDeviceToken(data.deviceToken); touch();
  }
  async function action(fn, account = false) {
    if (busy) return;
    busy = true; accountBusy = account; if (account) clearTimeout(idle); controls();
    try { await fn(epoch); } catch (error) { status(error.message); }
    finally { busy = false; accountBusy = false; controls(); touch(); }
  }
  async function showList(current) {
    status('Refreshing cloud notebooks…');
    const entries = await client.list();
    if (current !== epoch || !data) return;
    data.cache = client.getCache(); data.entries = entries;
    await vault.save(data);
    if (current !== epoch) return;
    renderEntries(entries);
    status('Tree cached encrypted in this browser. Choose a notebook to import.');
  }
  async function removeVault(message) {
    let removed = false;
    try {
      await vault.forget();
      exists = false;
      removed = true;
    } finally {
      lock(removed ? message : undefined);
    }
  }
  function renderEntries(entries) {
    $('cloud-items').replaceChildren();
    for (const entry of entries.filter((item) => item.kind !== 'folder')) {
      const row = document.createElement('div'); row.className = 'usb-item';
      const label = document.createElement('span'); label.textContent = entry.path || entry.name;
      const button = document.createElement('button'); button.textContent = 'Import ink';
      button.onclick = () => action(async (generation) => {
        status('Downloading and verifying notebook in this browser…');
        await client.list();
        if (generation !== epoch) return;
        const archive = await client.download(entry.id);
        if (generation !== epoch) return;
        await importArchive(archive);
        $('cloud-dialog').close();
      });
      row.append(label, button); $('cloud-items').append(row);
    }
  }
  $('cloud-open').onclick = async () => {
    $('cloud-dialog').showModal();
    await action(async () => {
      exists = await vault.exists();
      status(data ? 'Unlocked. Refresh to browse.' : exists ? 'Unlock the saved browser pairing.' : 'Pair once and choose a vault passphrase. No CLI is needed.');
      controls();
    });
  };
  $('cloud-close').onclick = () => { if (!accountBusy) $('cloud-dialog').close(); };
  $('cloud-dialog').addEventListener('cancel', (event) => { if (accountBusy) event.preventDefault(); });
  $('cloud-dialog').addEventListener('close', () => lock('Cloud vault locked.'));
  $('cloud-dialog').addEventListener('keydown', touch);
  $('cloud-dialog').addEventListener('pointerdown', touch);
  window.addEventListener('pagehide', () => lock());
  $('cloud-lock').onclick = () => lock();
  $('cloud-revoke-confirm').onchange = controls;
  $('cloud-pair').onclick = () => action(async (generation) => {
    let passphrase = $('cloud-passphrase').value;
    if (passphrase.length < 12 || passphrase.length > 1024 || !passphrase.trim() || passphrase !== $('cloud-confirm').value) {
      throw new Error('Use a vault passphrase of at least 12 characters and repeat it exactly.');
    }
    const code = $('cloud-code').value.trim(); $('cloud-code').value = '';
    try {
      if (!data) {
        if (await vault.exists()) { exists = true; throw new Error('A pairing is already saved. Unlock it instead.'); }
        client = createCloudClient({ relay });
        const deviceToken = await client.pair(code);
        if (generation !== epoch) return;
        data = { deviceToken, cache: null };
      }
      try { await vault.create(passphrase, data); }
      catch { throw new Error('Cloud pairing succeeded, but browser storage failed. Keep this dialog open and retry Save pairing, or revoke access.'); }
      if (generation !== epoch) return;
      exists = true;
      const persistent = await navigator.storage?.persist?.();
      status(persistent ? 'Paired. Encrypted storage retained in this browser.' : 'Paired. Browser may clear storage; keep your vault passphrase.');
    } finally {
      passphrase = ''; $('cloud-passphrase').value = ''; $('cloud-confirm').value = '';
    }
  }, true);
  $('cloud-unlock').onclick = () => action(async (generation) => {
    let passphrase = $('cloud-passphrase').value; $('cloud-passphrase').value = '';
    try {
      const unlocked = await vault.unlock(passphrase);
      if (generation !== epoch) return;
      data = unlocked; activate(); renderEntries(data.entries || []);
      status('Unlocked. Showing saved tree; refresh to check for cloud changes.');
    } finally { passphrase = ''; }
  });
  $('cloud-refresh').onclick = () => action(showList);
  $('cloud-revoke').onclick = () => action(async (generation) => {
    if (!$('cloud-revoke-confirm').checked) return;
    await client.revoke();
    if (generation !== epoch) return;
    await removeVault('Cloud access revoked and browser vault removed. Imported local files remain.');
  }, true);
  $('cloud-forget').onclick = () => action(async () => {
    if (!$('cloud-revoke-confirm').checked) return;
    await removeVault('Browser vault removed. This does not revoke the cloud registration.');
  }, true);
  controls();
}

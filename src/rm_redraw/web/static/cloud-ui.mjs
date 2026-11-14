import { createVault } from './cloud-vault.mjs';
import { createCloudClient } from './cloud-client.mjs';

const STORAGE_HELP = {
  passkey: 'Requires a passkey provider with PRF encryption support. Ordinary passkey sign-in support is not enough; Windows Hello support varies. Setup may ask for a second confirmation. Password and session only are available if this fails.',
  password: 'Choose a browser unlock password, not your reMarkable password. It stays on this device.',
  session: 'Nothing about this connection is saved. Pair again after closing or reloading this tab.',
  unprotected: 'Reconnect without an unlock prompt. Only use this on a private, trusted browser.',
};

export function setupCloud({ sessionToken, importArchive, vault = createVault(), clientFactory = createCloudClient }) {
  const $ = (id) => document.getElementById(id);
  let client = null, data = null, savedMode = null, activeMode = null;
  let busy = false, accountBusy = false, epoch = 0, idle, passkeyFailed = false;
  let previewObserver = null, previewBusy = false;
  const previewUrls = new Set(), visiblePreviews = new Map(), attemptedPreviews = new Set();
  const hasPasskeys = !!globalThis.navigator?.credentials?.create && !!globalThis.navigator?.credentials?.get;
  $('cloud-storage').value = hasPasskeys ? 'passkey' : 'password';
  $('cloud-passkey-option').disabled = !hasPasskeys;

  function status(message) {
    $('cloud-status').textContent = message;
    if ($('cloud-gallery-status')) $('cloud-gallery-status').textContent = message;
  }
  function controls() {
    const connected = !!data && !!activeMode;
    const newConnection = !savedMode && !connected;
    const mode = savedMode || $('cloud-storage').value;
    $('cloud-heading').textContent = connected ? 'Your cloud connection' : savedMode ? 'Open your notebooks' : 'Connect reMarkable';
    $('cloud-new').hidden = !newConnection;
    $('cloud-password-fields').hidden = connected || mode !== 'password';
    $('cloud-confirm-fields').hidden = !newConnection || mode !== 'password';
    $('cloud-unprotected-warning').hidden = !newConnection || mode !== 'unprotected';
    $('cloud-storage-help').textContent = STORAGE_HELP[mode] || '';
    $('cloud-password-fallback').hidden = !newConnection || mode !== 'passkey' || !passkeyFailed;
    $('cloud-password-fallback').disabled = busy;
    $('cloud-pair').hidden = !newConnection;
    $('cloud-pair').disabled = busy;
    $('cloud-pair').textContent = data ? 'Save connection and continue' : 'Connect';
    $('cloud-code').disabled = busy || !!data;
    $('cloud-storage').disabled = busy;
    $('cloud-unprotected-confirm').disabled = busy;
    $('cloud-unlock').hidden = !savedMode || connected;
    $('cloud-unlock').disabled = busy;
    $('cloud-unlock').textContent = mode === 'passkey' ? 'Unlock with passkey' : mode === 'unprotected' ? 'Open notebooks' : 'Unlock connection';
    $('cloud-passphrase').disabled = busy;
    $('cloud-passphrase').autocomplete = savedMode ? 'current-password' : 'new-password';
    $('cloud-confirm').disabled = busy;
    $('cloud-connected').hidden = !connected;
    $('cloud-lock').disabled = !connected || accountBusy;
    $('cloud-lock').textContent = activeMode === 'session' ? 'End session' : activeMode === 'unprotected' ? 'Close connection' : 'Lock connection';
    $('cloud-close').disabled = accountBusy;
    $('cloud-refresh').disabled = busy || !connected;
    $('cloud-refresh').hidden = !connected;
    $('cloud-disconnect').hidden = !savedMode && !data;
    $('cloud-forget').hidden = !savedMode;
    $('cloud-forget').disabled = busy || !$('cloud-revoke-confirm').checked;
    $('cloud-revoke').hidden = !data;
    $('cloud-revoke').disabled = busy || !$('cloud-revoke-confirm').checked;
    $('cloud-connection-state').textContent = activeMode === 'unprotected'
      ? 'Connected · saved without protection on this browser'
      : activeMode === 'session' ? 'Connected · this session only'
      : connected ? `Connected · protected with ${activeMode === 'passkey' ? 'a passkey' : 'a password'}`
      : savedMode === 'unprotected' ? 'Saved without protection on this browser' : 'Connection locked';
    if ($('cloud-gallery-refresh')) $('cloud-gallery-refresh').disabled = busy || !connected;
    if ($('cloud-open')) $('cloud-open').textContent = connected ? 'Connection settings' : savedMode ? 'Open connection' : 'Connect reMarkable';
    $('cloud-gallery')?.querySelectorAll('button[data-import]').forEach(button => { button.disabled = busy; });
  }
  function clearPreviews() {
    previewObserver?.disconnect(); visiblePreviews.clear(); attemptedPreviews.clear();
    for (const url of previewUrls) URL.revokeObjectURL(url);
    previewUrls.clear();
  }
  function lock(message) {
    const previousMode = activeMode;
    clearPreviews(); epoch++; clearTimeout(idle);
    client?.lock(); client = null; data = null; activeMode = null; vault.lock();
    $('cloud-items').replaceChildren(); $('cloud-gallery')?.replaceChildren();
    $('cloud-code').value = ''; $('cloud-passphrase').value = ''; $('cloud-confirm').value = '';
    $('cloud-revoke-confirm').checked = false;
    $('cloud-unprotected-confirm').checked = false;
    status(message || (previousMode === 'session' ? 'Session ended. Pair again to reconnect.'
      : savedMode === 'unprotected' ? 'Connection closed. Its saved credentials are still unprotected.' : 'Connection locked. Open it to browse notebooks.'));
    controls();
  }
  function touch() {
    clearTimeout(idle);
    // Session-only has no saved secret to unlock; retain it until the tab closes.
    if (data && !accountBusy && ['password', 'passkey'].includes(activeMode)) {
      idle = setTimeout(() => lock('Connection locked after five minutes of inactivity.'), 300000);
    }
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
    client = clientFactory({relay, cache: data.cache});
    client.setDeviceToken(data.deviceToken);
  }
  async function action(fn, account = false) {
    if (busy) return;
    busy = true; accountBusy = account; if (account) clearTimeout(idle); controls();
    try { await fn(epoch); }
    catch (error) {
      status(error.name === 'NotAllowedError' ? 'Passkey setup or unlock was cancelled. Try again, or choose another connection option.' : error.message);
    } finally { busy = false; accountBusy = false; controls(); touch(); queueMicrotask(pumpPreviews); }
  }
  async function showList(current) {
    status('Loading notebooks…');
    const entries = await client.list();
    if (current !== epoch || !data) return;
    data.cache = client.getCache(); data.entries = entries;
    renderEntries(entries);
    if (savedMode) {
      try { await vault.save(data); }
      catch (error) {
        if (current === epoch) status(`Notebooks loaded, but the saved list could not be updated. ${error.message}`);
        return;
      }
    }
    if (current === epoch) status(entries.length ? 'Choose a notebook to open.' : 'No notebooks found in this cloud account.');
  }
  async function browse(current) {
    renderEntries(data.entries || []);
    $('source-cloud')?.onclick?.();
    $('cloud-dialog').close();
    try { await showList(current); }
    catch (error) {
      if (current === epoch) status(`Connected, but notebooks could not be refreshed. ${data?.entries?.length ? 'Showing the saved list. ' : ''}Use Refresh to retry.`);
    }
  }
  async function removeVault(message) {
    let removed = false;
    try { if (savedMode) await vault.forget(); savedMode = null; removed = true; }
    finally { lock(removed ? message : undefined); }
  }
  function pumpPreviews() {
    if (busy || previewBusy || !data || !activeMode) return;
    const next = [...visiblePreviews.entries()].find(([row]) => !attemptedPreviews.has(row.dataset.cloudId));
    if (next) { attemptedPreviews.add(next[0].dataset.cloudId); next[1](); }
  }
  function renderEntries(entries) {
    clearPreviews();
    $('cloud-items').replaceChildren();
    const target = $('cloud-gallery');
    if (!target) return;
    target.replaceChildren();
    if (typeof IntersectionObserver !== 'undefined') previewObserver = new IntersectionObserver(entries => {
      for (const entry of entries) {
        if (entry.isIntersecting) visiblePreviews.set(entry.target, entry.target.loadPreview);
        else visiblePreviews.delete(entry.target);
      }
      queueMicrotask(pumpPreviews);
    }, {root: null, rootMargin: '0px', threshold: 0});
    const renderedEpoch = epoch;
    for (const entry of entries.filter(item => item.kind !== 'folder')) {
      const row = document.createElement('div'); row.className = 'cloud-notebook-card'; row.dataset.cloudId = entry.id;
      const image = document.createElement('img'); image.className = 'notebook-thumbnail'; image.hidden = true;
      image.alt = `Notebook preview for ${entry.name}`;
      const label = document.createElement('span'); label.textContent = entry.path || entry.name;
      const previewStatus = document.createElement('small'); previewStatus.textContent = 'Preview loads when visible';
      const preview = document.createElement('button'); preview.textContent = 'Load preview'; preview.className = 'secondary';
      preview.onclick = async () => {
        if (busy || previewBusy || renderedEpoch !== epoch || !data) return;
        previewBusy = true; preview.disabled = true; previewStatus.textContent = 'Loading preview…';
        try {
          const bytes = await client.preview(entry.id);
          if (renderedEpoch !== epoch || !data || !target.children || !Array.from(target.children).includes(row)) return;
          if (!bytes) { previewStatus.textContent = 'No preview available'; return; }
          if (previewUrls.has(image.src)) { URL.revokeObjectURL(image.src); previewUrls.delete(image.src); }
          const url = URL.createObjectURL(new Blob([bytes], {type: 'image/png'})); previewUrls.add(url);
          image.onerror = () => { image.hidden = true; previewStatus.textContent = 'Preview unavailable'; };
          image.src = url; image.hidden = false; previewStatus.textContent = 'Notebook preview'; preview.hidden = true;
        } catch { if (renderedEpoch === epoch) previewStatus.textContent = 'Preview unavailable. You can still open this notebook.'; }
        finally { previewBusy = false; preview.disabled = false; queueMicrotask(pumpPreviews); }
      };
      const button = document.createElement('button'); button.textContent = 'Open notebook'; button.dataset.import = 'true';
      button.onclick = () => action(async generation => {
        status('Opening notebook…');
        await client.list();
        if (generation !== epoch) return;
        const archive = await client.download(entry.id);
        if (generation !== epoch) return;
        await importArchive(archive);
        $('cloud-dialog').close();
      });
      row.append(image, label, previewStatus, preview, button); target.append(row);
      if (previewObserver) { row.loadPreview = preview.onclick; previewObserver.observe(row); }
    }
  }
  $('cloud-open').onclick = async () => {
    $('cloud-dialog').showModal();
    await action(async () => {
      savedMode = await vault.mode();
      status(data ? 'Your cloud connection is ready.' : savedMode === 'unprotected' ? 'This connection is saved without protection. Open it to browse.'
        : savedMode ? 'Unlock your saved connection.' : 'Get a pairing code, then connect.');
    });
  };
  $('cloud-close').onclick = () => { if (!accountBusy) $('cloud-dialog').close(); };
  $('cloud-dialog').addEventListener('cancel', event => { if (accountBusy) event.preventDefault(); });
  $('cloud-dialog').addEventListener('close', touch);
  document.addEventListener?.('pointerdown', touch);
  document.addEventListener?.('keydown', touch);
  window.addEventListener('pagehide', () => lock());
  $('cloud-lock').onclick = () => lock();
  $('cloud-revoke-confirm').onchange = controls;
  $('cloud-storage').onchange = () => {
    if (!savedMode) vault.lock();
    $('cloud-unprotected-confirm').checked = false;
    $('cloud-passphrase').value = ''; $('cloud-confirm').value = ''; controls();
  };
  $('cloud-password-fallback').onclick = () => { $('cloud-storage').value = 'password'; $('cloud-storage').onchange(); };
  $('cloud-pair').onclick = () => action(async generation => {
    const mode = $('cloud-storage').value;
    if (!Object.hasOwn(STORAGE_HELP, mode)) throw new Error('Choose how to keep this connection.');
    let password = $('cloud-passphrase').value;
    const code = $('cloud-code').value.trim();
    if (!data && !/^[A-Za-z0-9]{8}$/.test(code)) throw new Error('Enter the 8-character pairing code from your reMarkable account.');
    if (mode === 'password' && (password.length < 12 || password.length > 1024 || !password.trim() || password !== $('cloud-confirm').value)) {
      throw new Error('Choose a password of at least 12 characters and repeat it exactly.');
    }
    if (mode === 'unprotected' && !$('cloud-unprotected-confirm').checked) throw new Error('Acknowledge the risks before saving without protection.');
    try {
      if (mode === 'passkey') {
        try { await vault.preparePasskey(); }
        catch (error) { passkeyFailed = true; throw error; }
      }
      if (generation !== epoch) return;
      if (mode !== 'session' && await vault.exists()) throw new Error('A connection is already saved. Reopen connection settings to unlock it.');
      if (generation !== epoch) return;
      if (!data) {
        client = clientFactory({relay});
        const deviceToken = await client.pair(code);
        if (generation !== epoch) return;
        $('cloud-code').value = '';
        data = {deviceToken, cache: null};
      }
      try {
        if (mode === 'passkey') await vault.createPasskey(data);
        else if (mode === 'password') await vault.create(password, data);
        else if (mode === 'unprotected') await vault.createUnprotected(data, {acknowledged: true});
      } catch {
        throw new Error('Connected, but saving failed. Retry, choose session only to continue, or disconnect below.');
      }
      if (generation !== epoch) return;
      activeMode = mode; savedMode = mode === 'session' ? null : mode;
      if (savedMode) {
        // Persistence is a best-effort browser hint, never a prerequisite to browsing.
        try { await navigator.storage?.persist?.(); } catch { /* Storage eviction still requires pairing again. */ }
      }
      if (generation === epoch) await browse(generation);
    } finally { password = ''; $('cloud-passphrase').value = ''; $('cloud-confirm').value = ''; }
  }, true);
  $('cloud-unlock').onclick = () => action(async generation => {
    let password = $('cloud-passphrase').value; $('cloud-passphrase').value = '';
    try {
      const unlocked = await vault.unlock(password);
      if (generation !== epoch) return;
      data = unlocked; activeMode = savedMode; activate(); await browse(generation);
    } finally { password = ''; }
  }, true);
  $('cloud-refresh').onclick = () => action(showList);
  $('cloud-revoke').onclick = () => action(async generation => {
    if (!$('cloud-revoke-confirm').checked) return;
    await client.revoke();
    if (generation === epoch) await removeVault('Disconnected from reMarkable. Imported notebooks and videos remain.');
  }, true);
  $('cloud-forget').onclick = () => action(async () => {
    if ($('cloud-revoke-confirm').checked) await removeVault('Saved connection removed. Its reMarkable registration has not been revoked.');
  }, true);
  controls();
}

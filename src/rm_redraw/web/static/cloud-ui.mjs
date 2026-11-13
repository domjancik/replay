import { createVault } from './cloud-vault.mjs';
import { createCloudClient } from './cloud-client.mjs';

export function setupCloud({ sessionToken, importArchive }) {
  const $ = (id) => document.getElementById(id);
  const vault = createVault();
  const previewUrls = new Set();
  let previewObserver=null;
  const visiblePreviews=new Map(), attemptedPreviews=new Set();
  function pumpPreviews(){
    if(busy || !data)return;
    const next=[...visiblePreviews.entries()].find(([row])=>!attemptedPreviews.has(row.dataset.cloudId));
    if(!next)return;
    attemptedPreviews.add(next[0].dataset.cloudId);next[1]();
  }
  function clearPreviews() {
    previewObserver?.disconnect();visiblePreviews.clear();attemptedPreviews.clear();
    for (const url of previewUrls) URL.revokeObjectURL(url);
    previewUrls.clear();
  }
  let client = null, data = null, exists = false, busy = false, accountBusy = false, epoch = 0, idle;
  const status = (message) => { $('cloud-status').textContent = message; if($('cloud-gallery-status'))$('cloud-gallery-status').textContent=message; };
  function controls() {
    $('cloud-pair').disabled = busy || exists;
    $('cloud-code').disabled = busy || exists;
    $('cloud-unlock').disabled = busy || !exists || !!data;
    $('cloud-refresh').disabled = busy || !data;
    if($('cloud-gallery-refresh'))$('cloud-gallery-refresh').disabled=busy || !data;
    if($('cloud-gallery-connect'))$('cloud-gallery-connect').textContent=data?'Connection settings':'Connect / unlock';
    $('cloud-lock').disabled = !data || accountBusy;
    $('cloud-close').disabled = accountBusy;
    $('cloud-pair').textContent = data && !exists ? 'Save pairing' : 'Pair and remember';
    $('cloud-forget').disabled = busy || !exists || !$('cloud-revoke-confirm').checked;
    $('cloud-revoke').disabled = busy || !data || !$('cloud-revoke-confirm').checked;
    $('cloud-passphrase').disabled = busy || (!!data && exists);
    $('cloud-confirm').disabled = busy || exists;
    for(const id of ['cloud-items','cloud-gallery'])$(id)?.querySelectorAll('button').forEach((button) => { button.disabled = busy; });
  }
  function lock(message = 'Locked. Unlock with your vault passphrase.') {
    clearPreviews();
    epoch++; clearTimeout(idle); client?.lock(); client = null; data = null; vault.lock();
    $('cloud-items').replaceChildren();$('cloud-gallery')?.replaceChildren(); $('cloud-code').value = '';
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
    finally { busy = false; accountBusy = false; controls(); touch(); queueMicrotask(pumpPreviews); }
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
    clearPreviews();
    $('cloud-items').replaceChildren();
    $('cloud-gallery')?.replaceChildren();
    if(typeof IntersectionObserver!=='undefined')previewObserver=new IntersectionObserver(entries=>{
      for(const entry of entries){
        if(entry.isIntersecting)visiblePreviews.set(entry.target,entry.target.loadPreview);
        else visiblePreviews.delete(entry.target);
      }
      queueMicrotask(pumpPreviews);
    },{root:null,rootMargin:'0px',threshold:0});
    for (const target of [$('cloud-items'),$('cloud-gallery')].filter(Boolean)) {
    for (const entry of entries.filter((item) => item.kind !== 'folder')) {
      const row = document.createElement('div'); row.className = target===$('cloud-gallery')?'cloud-notebook-card':'usb-item';
      const label = document.createElement('span'); label.textContent = entry.path || entry.name;
      const image = document.createElement('img'); image.className = 'notebook-thumbnail';
      image.alt = `Cloud thumbnail for ${entry.name}`; image.hidden = true;
      const preview = document.createElement('button'); preview.textContent = 'Preview';
      preview.className = 'secondary';
      preview.onclick = () => action(async (generation) => {
        status('Looking for a notebook thumbnail…');
        await client.list();
        if (generation !== epoch) return;
        const bytes = await client.preview(entry.id);
        if (generation !== epoch) return;
        if (!bytes) { status('No cloud thumbnail available for this notebook. You can still import it.'); return; }
        if (previewUrls.has(image.src)) { URL.revokeObjectURL(image.src); previewUrls.delete(image.src); }
        const url = URL.createObjectURL(new Blob([bytes], {type: 'image/png'})); previewUrls.add(url);
        image.onerror = () => { image.hidden = true; status('Thumbnail could not be displayed. You can still import this notebook.'); };
        image.src = url; image.hidden = false;
        status('Cloud thumbnail shown. It may represent a different page from the one you choose to animate.');
      });
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
      row.append(image, label, preview, button); target.append(row);
      if(previewObserver){row.dataset.cloudId=entry.id;row.loadPreview=()=>preview.onclick();previewObserver.observe(row);}
    }
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
  // Closing settings keeps the in-memory session usable by the gallery.
  // Explicit lock, page exit and the existing idle timeout still clear it.
  $('cloud-dialog').addEventListener('close', touch);
  $('cloud-library')?.addEventListener('pointerdown',touch);
  $('cloud-library')?.addEventListener('keydown',touch);
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
      $('source-cloud')?.onclick?.();
      if($('cloud-library'))$('cloud-dialog').close();
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

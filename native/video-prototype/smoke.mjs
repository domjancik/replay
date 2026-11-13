import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { createRequire } from 'node:module';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../../artifacts/video-prototype-20261113/', import.meta.url));
const site = join(root, 'site');
const { chromium } = createRequire(join(root, 'browser-qa', 'package.json'))('playwright');
const assets = new Map([
  ['/harness.html', 'text/html'],
  ['/harness.mjs', 'text/javascript'],
  ['/harness-worker.mjs', 'text/javascript'],
  ['/encoder.mjs', 'text/javascript'],
]);
const server = createServer(async (request, response) => {
  if (!assets.has(request.url)) {
    response.writeHead(404).end();
    return;
  }
  response.writeHead(200, { 'Content-Type': assets.get(request.url) });
  response.end(await readFile(join(site, request.url.slice(1))));
});
await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));

let browser;
try {
  const origin = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch({
    channel: 'chrome',
    ...(process.env.RM_REDRAW_VIDEO_CHROME ? { executablePath: process.env.RM_REDRAW_VIDEO_CHROME } : {}),
  });
  const page = await browser.newPage({ acceptDownloads: true });
  const unexpectedRequests = [];
  await page.route('**/*', (route) => {
    if (new URL(route.request().url()).origin === origin) return route.continue();
    unexpectedRequests.push(route.request().url());
    return route.abort();
  });
  await page.goto(`${origin}/harness.html`);
  const outputs = [];
  for (const container of ['mp4', 'webm']) {
    await page.locator('#format').selectOption(container);
    await page.locator('#start').click();
    await page.waitForFunction(() => !document.querySelector('#start').disabled);
    const status = await page.locator('#status').innerText();
    if (status.includes('No browser video encoder')) {
      outputs.push({ container, supported: false });
      continue;
    }
    assert.match(status, /29 frames/, status);
    await page.waitForFunction(() => document.querySelector('video').readyState >= 2);
    const player = await page.locator('video').evaluate(async (video) => {
      video.currentTime = 1;
      await new Promise((resolve) => video.addEventListener('seeked', resolve, { once: true }));
      await video.play();
      video.pause();
      return [video.videoWidth, video.videoHeight, video.duration];
    });
    assert.deepEqual(player.slice(0, 2), [96, 72]);
    assert.ok(Math.abs(player[2] - 29 / 12) < 0.02);
    const downloading = page.waitForEvent('download');
    await page.locator('#download').click();
    const download = await downloading;
    const path = join(root, download.suggestedFilename());
    await download.saveAs(path);
    const probe = JSON.parse(execFileSync('ffprobe', [
      '-v', 'error', '-count_frames', '-select_streams', 'v:0', '-show_entries',
      'stream=codec_name,width,height,r_frame_rate,nb_read_frames:format=duration,size', '-of', 'json', path,
    ], { encoding: 'utf8' }));
    const [stream] = probe.streams;
    assert.equal(stream.nb_read_frames, '29');
    assert.equal(stream.r_frame_rate, '12/1');
    assert.equal(stream.width, 96);
    assert.equal(stream.height, 72);
    assert.ok((container === 'mp4' ? ['h264'] : ['vp8', 'vp9']).includes(stream.codec_name));
    outputs.push({ container, supported: true, stream, format: probe.format, playbackAndSeek: true });
  }
  assert.ok(outputs.some((entry) => entry.supported), 'The test browser needs an encoding codec.');
  await page.locator('#format').selectOption('auto');
  await page.evaluate(() => {
    document.querySelector('#start').click();
    document.querySelector('#cancel').click();
  });
  await page.waitForFunction(() => document.querySelector('#status').value === 'Canceled');
  assert.equal(await page.locator('#download').isVisible(), false);
  assert.deepEqual(unexpectedRequests, []);
  console.log(JSON.stringify({ browser: browser.version(), outputs, canceled: true, remoteRequests: 0 }, null, 2));
} finally {
  await browser?.close();
  server.close();
}

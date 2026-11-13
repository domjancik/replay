import { readFile } from 'node:fs/promises';
import { createServer } from 'node:http';

const artifacts = new URL('../../../artifacts/rust-renderer/', import.meta.url);
const synthetic = new URL('synthetic/', artifacts);
const manifest = JSON.parse(await readFile(new URL('cases.json', synthetic), 'utf8'));
const cases = manifest.cases.filter(({ id }) => /^replay-(\d{3}|static)$/.test(id));
const assets = new Map([
  ['/', new URL('index.html', import.meta.url)],
  ['/app.mjs', new URL('app.mjs', import.meta.url)],
  ['/worker.mjs', new URL('worker.mjs', import.meta.url)],
  ['/renderer.mjs', new URL('../renderer.mjs', import.meta.url)],
  ['/renderer.wasm', new URL('target/wasm32-unknown-unknown/release/rm_renderer.wasm', artifacts)],
  ['/encoder.mjs', new URL('../../../artifacts/video-prototype-20261113/site/encoder.mjs', import.meta.url)],
  ...cases.flatMap(({ request, rgba }) => [
    [`/sample/${request}`, new URL(request, synthetic)],
    [`/sample/${rgba}`, new URL(rgba, synthetic)],
  ]),
]);
const types = { html: 'text/html', mjs: 'text/javascript', json: 'application/json', wasm: 'application/wasm' };

const server = createServer(async (request, response) => {
  const pathname = request.url.split('?')[0];
  if (request.method !== 'GET') return response.writeHead(405).end();
  if (pathname === '/sample/cases.json') {
    return response.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify(cases));
  }
  const asset = assets.get(pathname);
  if (!asset) return response.writeHead(404).end();
  try {
    const content = await readFile(asset);
    const contentType = types[asset.pathname.split('.').at(-1)] ?? 'application/octet-stream';
    response.writeHead(200, { 'Content-Type': contentType }).end(content);
  } catch {
    response.writeHead(500).end('Build the local WASM renderer and video probe, then retry.');
  }
});
server.listen(Number(process.argv[2] ?? 0), '127.0.0.1', () => {
  console.log(`http://127.0.0.1:${server.address().port}/`);
});

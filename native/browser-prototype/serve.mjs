import { readFile } from 'node:fs/promises';
import { createServer } from 'node:http';

const artifacts = new URL('../../artifacts/browser-prototype-20261113/', import.meta.url);
const runtime = new URL('pyodide/', artifacts);
const lock = JSON.parse(await readFile(new URL('pyodide-lock.json', runtime), 'utf8'));
const runtimeFiles = [
  'pyodide.mjs', 'pyodide.asm.js', 'pyodide.asm.wasm', 'pyodide-lock.json',
  'python_stdlib.zip', 'rmscene-0.8.0-py3-none-any.whl', 'packaging-23.2-py3-none-any.whl',
  lock.packages.numpy.file_name, lock.packages.pillow.file_name,
];
const assets = new Map([
  ['/', new URL('index.html', import.meta.url)],
  ['/encoder.mjs', new URL('../../artifacts/video-prototype-20261113/site/encoder.mjs', import.meta.url)],
  ...['replay.mjs', 'worker.mjs'].map((name) => [`/${name}`, new URL(name, import.meta.url)]),
  ...['engine.zip', 'synthetic.rmdoc', 'expected.rgba'].map((name) =>
    [`/data/${name}`, new URL(name, artifacts)]),
  ...runtimeFiles.map((name) => [`/data/pyodide/${name}`, new URL(name, runtime)]),
]);
const mime = new Map([
  ['html', 'text/html; charset=utf-8'],
  ['mjs', 'text/javascript; charset=utf-8'],
  ['js', 'text/javascript; charset=utf-8'],
  ['wasm', 'application/wasm'],
  ['json', 'application/json'],
]);
const server = createServer(async (request, response) => {
  const asset = assets.get(request.url.split('?')[0]);
  if (request.method !== 'GET' || !asset) {
    response.writeHead(404).end();
    return;
  }
  try {
    const content = await readFile(asset);
    response.writeHead(200, {
      'Content-Type': mime.get(asset.pathname.split('.').at(-1)) ?? 'application/octet-stream',
    }).end(content);
  } catch {
    response.writeHead(500).end('Generate the synthetic fixture and install the pinned runtime first.');
  }
});
server.listen(Number(process.argv[2] ?? 0), '127.0.0.1', () => {
  console.log(`http://127.0.0.1:${server.address().port}/`);
});

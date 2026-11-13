import { createRequire } from 'node:module';
import { copyFile, mkdir } from 'node:fs/promises';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const source = fileURLToPath(new URL('.', import.meta.url));
const root = fileURLToPath(new URL('../../artifacts/video-prototype-20261113/', import.meta.url));
const site = join(root, 'site');
const dependencies = join(root, 'dependencies');
const { build } = createRequire(join(dependencies, 'package.json'))('esbuild');

await mkdir(site, { recursive: true });
await build({
  entryPoints: [join(source, 'browser.mjs')],
  outfile: join(site, 'encoder.mjs'),
  nodePaths: [join(dependencies, 'node_modules')],
  platform: 'browser', format: 'esm', target: 'es2021', bundle: true,
  minify: true, legalComments: 'eof',
});
for (const name of ['harness.html', 'harness.mjs', 'harness-worker.mjs']) {
  await copyFile(join(source, name), join(site, name));
}
await copyFile(
  join(dependencies, 'node_modules', 'mediabunny', 'LICENSE'), join(site, 'MEDIABUNNY-LICENSE'),
);
console.log(site);

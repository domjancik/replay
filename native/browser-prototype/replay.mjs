const runtimeFiles = ['packaging-23.2-py3-none-any.whl', 'rmscene-0.8.0-py3-none-any.whl'];

export async function renderProbe(runtimeUrl, readAsset) {
  const start = performance.now();
  const { loadPyodide } = await import(new URL('pyodide.mjs', runtimeUrl));
  const pyodide = await loadPyodide({
    packages: ['numpy', 'pillow'],
    packageBaseUrl: runtimeUrl.protocol === 'file:' ? undefined : runtimeUrl.href,
  });
  const engineUrl = new URL('../engine.zip', runtimeUrl);
  const pageUrl = new URL('../synthetic.rmdoc', runtimeUrl);
  const paths = await Promise.all([
    ...runtimeFiles.map((file) => new URL(file, runtimeUrl)),
    engineUrl,
    pageUrl,
  ].map(async (url) => {
    const path = '/' + url.pathname.split('/').at(-1);
    pyodide.FS.writeFile(path, await readAsset(url));
    return path;
  }));
  const ready = performance.now();
  const manifest = JSON.parse(pyodide.runPython(`
import json
import sys
from pathlib import Path
sys.path[:0] = ${JSON.stringify(paths.slice(0, -1))}
from render_probe import render_probe
with open("/output.rgba", "wb") as output:
    manifest = render_probe(Path("/synthetic.rmdoc").read_bytes(), output)
json.dumps(manifest)
`));
  const rgba = pyodide.FS.readFile('/output.rgba');
  return {
    manifest: { ...manifest, pyodide: pyodide.version, startupMs: Math.round(ready - start) },
    rgba,
  };
}

const render = document.querySelector('#render');
const encode = document.querySelector('#encode');
const status = document.querySelector('#status');
const frame = document.querySelector('#frame');
const video = document.querySelector('#video');
const download = document.querySelector('#download');
let url;

function run(withVideo) {
  render.disabled = encode.disabled = true;
  frame.hidden = video.hidden = download.hidden = true;
  video.removeAttribute('src');
  video.load();
  if (url) URL.revokeObjectURL(url);
  status.value = 'Starting worker';
  const worker = new Worker('worker.mjs', { type: 'module' });
  function finish(message) {
    status.value = message;
    render.disabled = encode.disabled = false;
    worker.terminate();
  }
  worker.onmessage = ({ data }) => {
    if (data.error) return finish(data.error);
    if (data.progress) {
      status.value = `Rendering ${data.progress}/${data.frameCount}`;
      return;
    }
    frame.width = data.width;
    frame.height = data.height;
    frame.getContext('2d').putImageData(new ImageData(
      new Uint8ClampedArray(data.rgba.buffer), data.width, data.height,
    ), 0, 0);
    frame.hidden = false;
    if (data.video) {
      url = URL.createObjectURL(new Blob([data.video.buffer], { type: data.video.mimeType }));
      video.src = download.href = url;
      download.download = `rust-wasm-replay${data.video.extension}`;
      video.hidden = download.hidden = false;
    }
    const final = data.finalEqualsStatic ? 'matches' : 'differs from';
    finish(`${data.parityCount}/${data.caseCount} reference frames match. Final replay frame ${final} static. ${Math.round(data.elapsedMs)} ms.`);
  };
  worker.onerror = ({ message }) => finish(message);
  worker.postMessage({ encode: withVideo });
}

render.onclick = () => run(false);
encode.onclick = () => run(true);

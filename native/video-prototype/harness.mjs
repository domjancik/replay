const start = document.querySelector('#start');
const cancel = document.querySelector('#cancel');
const status = document.querySelector('#status');
const preview = document.querySelector('#preview');
const download = document.querySelector('#download');
const format = document.querySelector('#format');
let worker;
let videoUrl;

start.addEventListener('click', () => {
  preview.removeAttribute('src');
  preview.load();
  if (videoUrl) URL.revokeObjectURL(videoUrl);
  download.hidden = true;
  start.disabled = true;
  cancel.disabled = false;
  status.value = 'Starting';
  worker = new Worker('harness-worker.mjs', { type: 'module' });
  worker.addEventListener('error', (event) => done(`Worker error: ${event.message}`));
  worker.addEventListener('message', ({ data }) => {
    if (data.progress) {
      status.value = `${data.progress}/${data.frameCount} frames`;
    } else if (data.buffer) {
      videoUrl = URL.createObjectURL(new Blob([data.buffer], { type: data.mimeType }));
      preview.src = videoUrl;
      download.href = videoUrl;
      download.download = `synthetic-replay${data.extension}`;
      download.hidden = false;
      done(`${data.codec} · ${data.frameCount} frames · ${data.buffer.byteLength} bytes`);
    } else {
      done(data.error);
    }
  });
  worker.postMessage({ container: format.value });
});

cancel.addEventListener('click', () => {
  worker.postMessage({ cancel: true });
  cancel.disabled = true;
  status.value = 'Canceling';
});

function done(message) {
  worker.terminate();
  worker = undefined;
  start.disabled = false;
  cancel.disabled = true;
  status.value = message;
}

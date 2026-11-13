import {createBrowserApi} from './browser-api.mjs';
try{globalThis.replayBrowser=await createBrowserApi();await import('./app.js');}
catch(error){const notice=document.getElementById('notice');notice.hidden=false;notice.textContent='Could not start browser storage: '+error.message;}

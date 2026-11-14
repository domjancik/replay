import {createLargeBlobProbe} from './largeblob-probe.mjs';
const $=id=>document.getElementById(id),storageKey='replay-largeblob-test-v1';
const probe=createLargeBlobProbe();let record=null,busy=false;
const report=[];
function show(message){report.push(message);$('probe-status').textContent=report.join('\n');}
function controls(){ $('probe-register').disabled=busy||!!record;$('probe-write').disabled=busy||!record;$('probe-read').disabled=busy||!record?.ciphertext;$('probe-clear').disabled=busy; }
try{const saved=localStorage.getItem(storageKey);if(saved){record=JSON.parse(saved);show('Saved test restored. Read it again to check persistence across reloads.');}}
catch{show('Test storage could not be read. Clear this test to restart.');}
async function run(stage,fn){if(busy)return;busy=true;controls();show(`${stage}: waiting for your passkey provider...`);try{await fn();show(`${stage}: PASS`);}catch(error){const allowed=['UnknownError','NotAllowedError','NotSupportedError','SecurityError','InvalidStateError','AbortError','NotReadableError','OperationError'];const name=allowed.includes(error.name)?error.name:'Error';show(`${stage}: FAIL (${name}). ${error.name==='Error'?error.message:'The browser/provider did not complete this step. Cancellation or timeout can also cause failure.'}`);}finally{busy=false;controls();}}
$('probe-register').onclick=()=>run('Create with largeBlob required',async()=>{record=await probe.register();localStorage.setItem(storageKey,JSON.stringify(record));});
$('probe-write').onclick=()=>run('Write test key',async()=>{record=await probe.write(record);localStorage.setItem(storageKey,JSON.stringify(record));});
$('probe-read').onclick=()=>run('Read key and decrypt test message',async()=>{await probe.read(record);});
$('probe-clear').onclick=()=>{localStorage.removeItem(storageKey);record=null;show('Local test data cleared. To delete the TEST passkey, remove it in your passkey manager or Windows settings.');controls();};
controls();

import assert from 'node:assert/strict';import {readFileSync} from 'node:fs';import {instantiateCore} from './core.mjs';
const core=await instantiateCore(readFileSync(new URL('./target/wasm32-unknown-unknown/release/rm_replay_core.wasm',import.meta.url)));
const cases=JSON.parse(readFileSync('artifacts/rust-anchor-validation/cases.json','utf8'));
for(const c of cases){const [actual]=core.match(c.request);assert.equal(actual.accepted,c.expected.accepted,c.name);assert.equal(actual.reason,c.expected.reason,c.name);for(const key of ['translation_x','translation_y','capped_mean_distance_px','fraction_within_2px','native_fraction_within_5px'])assert.ok(Math.abs(actual.best_candidate[key]-c.expected.best_candidate[key])<1e-8,`${c.name} ${key}: ${actual.best_candidate[key]} != ${c.expected.best_candidate[key]}`);}
console.log(`${cases.length} Python/Rust WASM anchor fits match`);

const schedules=JSON.parse(readFileSync('artifacts/rust-anchor-validation/schedules.json','utf8'));
for(const c of schedules)assert.deepEqual(core.match(c.request),c.expected);
console.log(`${schedules.length} Python/Rust WASM replay schedules match`);

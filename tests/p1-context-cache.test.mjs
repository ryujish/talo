import assert from 'node:assert/strict';
import { cacheContext, clearContextCache } from '../lib/server/context-cache.ts';

clearContextCache();
const packet1 = { thinkalongSessionId: 's1', version: 1, system: '', decisions: [], messages: [] };
const packet2 = { ...packet1, version: 2 };
assert.equal(cacheContext(packet1, 'GPT', 'a1', 'm1'), packet1);
assert.equal(cacheContext({ ...packet1 }, 'GPT', 'a1', 'm1'), packet1);
assert.equal(cacheContext(packet2, 'GPT', 'a1', 'm1'), packet2);
assert.notEqual(cacheContext({ ...packet1 }, 'GPT', 'a1', 'm1'), packet1);
console.log('P1-1 context cache contract passed');

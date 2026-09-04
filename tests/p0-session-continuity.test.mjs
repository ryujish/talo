import assert from 'node:assert/strict';
import { createContextPacket } from '../lib/server/context-engine.ts';

const sessionId = 'session-1';
const packet = createContextPacket({
  thinkalongSessionId: sessionId,
  messages: [
    { id: '1', thinkingId: sessionId, thinkalongSessionId: sessionId, role: 'user', content: 'A', aiProvider: 'GPT', createdAt: '2026-08-21T00:00:00.000Z' },
    { id: '2', thinkingId: sessionId, thinkalongSessionId: sessionId, role: 'assistant', content: 'B', aiProvider: 'GPT', createdAt: '2026-08-21T00:00:01.000Z' },
    { id: '3', thinkingId: 'other', thinkalongSessionId: 'other', role: 'user', content: 'leak', createdAt: '2026-08-21T00:00:02.000Z' },
  ],
  prompt: 'C',
});

assert.equal(packet.thinkalongSessionId, sessionId);
assert.deepEqual(packet.messages.map(({ content }) => content), ['A', 'B', 'C']);
assert.equal(packet.version, 3);
console.log('P0-6 session continuity contract passed');

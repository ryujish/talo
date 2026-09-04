import assert from 'node:assert/strict';
import { createContextPacket } from '../lib/server/context-engine.ts';
import { recordDecision } from '../lib/server/decisions.ts';

const db = { users: [], sessions: [], thinkings: [], messages: [], attachments: [], insights: [], providerConnections: [], decisions: [], contextSnapshots: [], events: [], toolRuns: [], subAgentRuns: [] };
const base = { userId: 'user-1', thinkalongSessionId: 'session-1', status: 'confirmed', now: '2026-08-21T00:00:00.000Z' };
assert.ok(recordDecision(db, { ...base, id: 'decision-1', statement: 'GPT를 사용한다.' }).decision);
assert.ok(recordDecision(db, { ...base, id: 'decision-2', statement: 'Claude를 사용한다.', supersedesDecisionId: 'decision-1' }).decision);

assert.equal(db.decisions[0].status, 'superseded');
assert.equal(db.decisions[0].supersededByDecisionId, 'decision-2');
assert.equal(db.decisions[1].supersedesDecisionId, 'decision-1');

const packet = createContextPacket({ thinkalongSessionId: 'session-1', messages: [], decisions: db.decisions, prompt: '계속해' });
assert.deepEqual(packet.decisions, [{ id: 'decision-2', statement: 'Claude를 사용한다.' }]);
assert.equal(packet.version, 3);
console.log('P0-7 decision supersede contract passed');

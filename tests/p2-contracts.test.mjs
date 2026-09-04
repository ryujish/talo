import assert from 'node:assert/strict';
import { getInternalAgentInstruction } from '../lib/server/internal-agents.ts';
import { recordDecision } from '../lib/server/decisions.ts';

assert.match(getInternalAgentInstruction('critic'), /conflicts with confirmed decisions/);
const db = { users: [], sessions: [], thinkings: [], messages: [], attachments: [], insights: [], providerConnections: [], decisions: [], contextSnapshots: [], events: [], toolRuns: [], subAgentRuns: [] };
const base = { userId: 'u1', thinkalongSessionId: 's1', status: 'confirmed', topic: 'frontend', now: '2026-08-22T00:00:00.000Z' };
assert.ok(recordDecision(db, { ...base, id: 'd1', statement: 'React를 사용한다.' }).decision);
const conflict = recordDecision(db, { ...base, id: 'd2', statement: 'Flutter를 사용한다.' });
assert.equal(conflict.error, 'DECISION_CONFLICT');
assert.equal(conflict.conflictDecisionId, 'd1');
assert.ok(recordDecision(db, { ...base, id: 'd3', statement: 'Flutter를 사용한다.', supersedesDecisionId: 'd1' }).decision);
assert.deepEqual(db.events.map((event) => event.type), ['decision.created', 'decision.superseded', 'decision.created']);
console.log('P2 agent, event, and decision-conflict contracts passed');

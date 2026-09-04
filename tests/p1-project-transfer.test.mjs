import assert from 'node:assert/strict';
import { createProjectExport, importProject } from '../lib/server/project-transfer.ts';

const thinking = { id: 't1', thinkalongSessionId: 's1', userId: 'u1', title: 'T', prompt: 'P', aiProvider: 'GPT', selectedConnectionId: 'c', selectedModel: 'm', status: 'active', favorite: false, tags: [], answer: 'A', createdAt: 'now', updatedAt: 'now' };
const source = { users: [], sessions: [], thinkings: [thinking], messages: [{ id: 'm1', thinkingId: 't1', thinkalongSessionId: 's1', role: 'user', content: 'P', createdAt: 'now' }], attachments: [], insights: [], providerConnections: [], decisions: [], contextSnapshots: [], events: [], toolRuns: [], subAgentRuns: [] };
const target = { users: [], sessions: [], thinkings: [], messages: [], attachments: [], insights: [], providerConnections: [], decisions: [], contextSnapshots: [], events: [], toolRuns: [], subAgentRuns: [] };
const result = importProject(target, 'u2', createProjectExport(source, thinking));
assert.equal(result.thinking.userId, 'u2');
assert.equal(target.messages[0].thinkalongSessionId, 's1');
assert.equal(importProject(target, 'u2', createProjectExport(source, thinking)).error, 'IMPORT_CONFLICT');
console.log('P1-2 project transfer contract passed');

import assert from 'node:assert/strict';
import { inspectSessionContext, skills, tools } from '../lib/server/capabilities.ts';

assert.deepEqual(tools, [{ id: 'session.context.inspect', name: '현재 Context 범위 확인', risk: 'read' }]);
assert.equal(skills[0].agentRole, 'critic');
assert.deepEqual(skills[0].allowedTools, ['session.context.inspect']);
const db = { messages: [{ thinkalongSessionId: 's1' }, { thinkalongSessionId: 's2' }], decisions: [{ thinkalongSessionId: 's1', status: 'confirmed' }, { thinkalongSessionId: 's1', status: 'superseded' }], contextSnapshots: [{ thinkalongSessionId: 's1' }] };
assert.deepEqual(inspectSessionContext(db, 's1'), { messages: 1, decisions: 1, snapshots: 1 });
console.log('P3 tool and skill contracts passed');

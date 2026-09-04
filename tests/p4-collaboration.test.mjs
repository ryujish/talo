import assert from 'node:assert/strict';
import { generateCollaborativeThinking } from '../lib/server/collaboration.ts';

const calls = [];
const generate = async (input) => {
  calls.push(input);
  return { title: 't', answer: `${input.provider}:${calls.length}`, insight: 'i', tags: [] };
};
const context = { thinkalongSessionId: 's1', version: 1, system: 'shared', decisions: [], messages: [{ role: 'user', content: '질문' }] };
const primary = { provider: 'GPT', connectionId: 'gpt:1', model: 'gpt-test' };
const collaborator = { provider: 'OpenCode Zen', connectionId: 'oc:1', model: 'oc-test' };
const instruction = (role) => role;
const output = await generateCollaborativeThinking({ prompt: '질문', context, primary, collaborator }, generate, instruction);

assert.equal(calls.length, 3);
assert.strictEqual(calls[0].context.messages, calls[1].context.messages);
assert.match(calls[2].context.system, /Do not mention hidden workers/);
assert.deepEqual(output.contributions.map((item) => item.provider), ['GPT', 'OpenCode Zen']);
assert.equal(output.result.answer, 'GPT:3');
calls.length = 0;
const single = await generateCollaborativeThinking({ prompt: '질문', context, primary }, generate, instruction);
assert.equal(calls.length, 1);
assert.deepEqual(single.contributions, []);
console.log('P4 collaboration loop passed');

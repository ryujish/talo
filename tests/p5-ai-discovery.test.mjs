import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { discoverAiEnvironment } from '../lib/server/ai-discovery.ts';

test('AI discovery reports only auth plus executable pairs as available', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'talo-discovery-'));
  const bin = path.join(root, 'bin');
  await mkdir(path.join(root, '.codex'), { recursive: true });
  await mkdir(bin);
  await writeFile(path.join(root, '.codex', 'auth.json'), '{}');
  await writeFile(path.join(bin, 'codex'), '');
  const result = await discoverAiEnvironment({ home: root, env: {}, pathEntries: [bin] });
  assert.equal(result.find((item) => item.id === 'codex_cli')?.available, true);
  assert.equal(result.find((item) => item.id === 'opencode_cli')?.available, false);
});

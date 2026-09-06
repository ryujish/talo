import { access } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';

type DiscoveryInput = { home?: string; env?: NodeJS.ProcessEnv; pathEntries?: string[] };

async function exists(file: string) {
  return access(file).then(() => true, () => false);
}

async function executable(command: string, entries: string[]) {
  const candidates = process.platform === 'win32' ? [`${command}.exe`, `${command}.cmd`, command] : [command];
  return (await Promise.all(entries.flatMap((entry) => candidates.map((name) => exists(path.join(entry, name)))))).some(Boolean);
}

export async function discoverAiEnvironment(input: DiscoveryInput = {}) {
  const home = input.home ?? os.homedir();
  const env = input.env ?? process.env;
  const entries = input.pathEntries ?? (env.PATH ?? '').split(path.delimiter).filter(Boolean);
  const [codexAuth, opencodeAuth, agyAuth, codexCli, opencodeCli, agyCli] = await Promise.all([
    exists(path.join(home, '.codex', 'auth.json')),
    exists(path.join(home, '.local', 'share', 'opencode', 'auth.json')),
    exists(path.join(home, '.gemini', 'antigravity-cli')),
    executable('codex', entries), executable('opencode', entries), executable('agy', entries),
  ]);

  return [
    { id: 'codex_cli', provider: 'GPT', label: 'Codex CLI', model: 'gpt-5.6-sol', available: codexAuth && codexCli, source: 'oauth' },
    { id: 'opencode_cli', provider: 'OpenCode Zen', label: 'OpenCode CLI', model: 'opencode/big-pickle', available: opencodeAuth && opencodeCli, source: 'oauth' },
    { id: 'agy_cli', provider: 'Gemini', label: 'Google AGY', model: 'gemini-3.8-flash-high', available: agyAuth && agyCli, source: 'oauth' },
    { id: 'ollama_local', provider: 'Hermes Local', label: 'Ollama', model: env.OLLAMA_MODEL ?? 'hermes3', available: Boolean(env.OLLAMA_HOST), source: 'local' },
  ];
}

import type { AiProvider, ContextPacket } from '@/lib/types';

const cache = new Map<string, ContextPacket>();

const key = (sessionId: string, version: number, provider: AiProvider, connectionId: string, model: string) =>
  [sessionId, version, provider, connectionId, model].join(':');

export function cacheContext(packet: ContextPacket, provider: AiProvider, connectionId: string, model: string) {
  const prefix = `${packet.thinkalongSessionId}:`;
  for (const cacheKey of cache.keys()) {
    if (cacheKey.startsWith(prefix) && !cacheKey.startsWith(`${prefix}${packet.version}:`)) cache.delete(cacheKey);
  }
  const cacheKey = key(packet.thinkalongSessionId, packet.version, provider, connectionId, model);
  const existing = cache.get(cacheKey);
  if (existing) return existing;
  cache.set(cacheKey, packet);
  return packet;
}

// ponytail: process-local cache; move to shared storage only when multiple app instances are deployed.
export function clearContextCache() {
  cache.clear();
}

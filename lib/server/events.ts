import type { AppDatabase, DomainEvent } from '@/lib/types';

export function recordEvent(db: AppDatabase, event: DomainEvent) {
  db.events.push(event);
  return event;
}

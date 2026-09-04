import type { InternalAgentRole } from '@/lib/types';

const instructions: Record<InternalAgentRole, string> = {
  thinker: 'Develop the strongest answer from the supplied context.',
  critic: 'Find unsupported claims and conflicts with confirmed decisions.',
  synthesizer: 'Reconcile supported ideas without changing confirmed decisions.',
};

export function getInternalAgentInstruction(role: InternalAgentRole) {
  return instructions[role];
}

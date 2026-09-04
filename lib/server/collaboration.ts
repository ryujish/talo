import type { AiResult, GenerateThinkingInput } from '@/lib/server/ai';
import type { AiProvider, ContextPacket } from '@/lib/types';

export type CollaborationModel = {
  provider: AiProvider;
  connectionId: string;
  model: string;
  apiKey?: string;
};

export type CollaborationContribution = CollaborationModel & {
  answer: string;
};

type Generate = (input: GenerateThinkingInput) => Promise<AiResult>;
type AgentInstruction = (role: 'thinker' | 'synthesizer') => string;

export async function generateCollaborativeThinking(input: {
  prompt: string;
  context: ContextPacket;
  primary: CollaborationModel;
  collaborator?: CollaborationModel;
}, generate: Generate, instruction: AgentInstruction) {
  if (!input.collaborator) {
    return {
      result: await generate({ ...input.primary, prompt: input.prompt, context: input.context }),
      contributions: [] as CollaborationContribution[],
    };
  }

  const models = [input.primary, input.collaborator];
  const settled = await Promise.allSettled(models.map((model) => generate({
    ...model,
    prompt: input.prompt,
    context: { ...input.context, system: `${input.context.system}\n${instruction('thinker')}` },
  })));
  const contributions = settled.flatMap((item, index) => item.status === 'fulfilled'
    ? [{ ...models[index], answer: item.value.answer }]
    : []);

  if (!contributions.length) throw (settled[0] as PromiseRejectedResult).reason;

  const synthesisContext: ContextPacket = {
    ...input.context,
    system: [
      input.context.system,
      instruction('synthesizer'),
      'Return one answer as Think Along. Do not mention hidden workers or providers.',
      JSON.stringify(contributions.map(({ provider, model, answer }) => ({ provider, model, answer }))),
    ].join('\n\n'),
  };

  return {
    result: await generate({ ...input.primary, prompt: input.prompt, context: synthesisContext }),
    contributions,
  };
}

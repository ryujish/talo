import type { AiProvider, ContextPacket, ModelCapability, ProviderCatalogItem, ProviderId } from '@/lib/types';
import { parseHermesOutput, formatHermesSystemInstruction } from '@/lib/server/hermes-protocol';

export type GenerateThinkingInput = {
  prompt: string;
  provider: AiProvider;
  context: ContextPacket;
  apiKey?: string;
  model?: string;
};

export type AiResult = {
  title: string;
  answer: string;
  insight: string;
  tags: string[];
};

export type AiProviderStatus = {
  provider: AiProvider;
  connected: boolean;
  model: string;
  requiredEnv: string;
};

const providerConfig: Array<{
  id: ProviderId;
  label: AiProvider;
  env: string;
  modelEnv: string;
  defaultModel: string;
  models: ModelCapability[];
}> = [
  { id: 'openai', label: 'GPT', env: 'OPENAI_API_KEY', modelEnv: 'OPENAI_MODEL', defaultModel: 'gpt-5.6-terra', models: [{ id: 'gpt-5.6-terra', text: true, vision: true, structuredOutput: true, streaming: true }] },
  { id: 'anthropic', label: 'Claude', env: 'ANTHROPIC_API_KEY', modelEnv: 'ANTHROPIC_MODEL', defaultModel: 'claude-sonnet-5', models: [{ id: 'claude-sonnet-5', text: true, vision: true, files: true, streaming: true }] },
  { id: 'gemini', label: 'Gemini', env: 'GEMINI_API_KEY', modelEnv: 'GEMINI_MODEL', defaultModel: 'gemini-3.7-flash', models: [{ id: 'gemini-3.7-flash', text: true, vision: true, files: true, streaming: true }] },
  { id: 'xai', label: 'Grok', env: 'XAI_API_KEY', modelEnv: 'XAI_MODEL', defaultModel: 'grok-4.6', models: [{ id: 'grok-4.6', text: true, vision: true, streaming: true }] },
  { id: 'moonshot', label: 'Kimi', env: 'MOONSHOT_API_KEY', modelEnv: 'MOONSHOT_MODEL', defaultModel: 'kimi-k3', models: [{ id: 'kimi-k3', text: true, vision: true, streaming: true }, { id: 'kimi-k2.6', text: true, vision: true, streaming: true }] },
  { id: 'opencode', label: 'OpenCode Zen', env: 'OPENCODE_ZEN_API_KEY', modelEnv: 'OPENCODE_ZEN_MODEL', defaultModel: 'x-preview-f-free', models: [{ id: 'x-preview-f-free', text: true, streaming: true }] },
  { id: 'local', label: 'Hermes Local', env: 'HERMES_API_KEY', modelEnv: 'HERMES_MODEL', defaultModel: 'hermes-3-llama-3.1-8b', models: [{ id: 'hermes-3-llama-3.1-8b', text: true, streaming: true, tools: true }, { id: 'hermes-3-llama-3.1-70b', text: true, streaming: true, tools: true }] },
];

export function getProviderCatalog(): ProviderCatalogItem[] {
  return providerConfig.map((provider) => {
    const model = process.env[provider.modelEnv] || provider.defaultModel;
    return {
      id: provider.id,
      label: provider.label,
      connections: [{
        id: `${provider.id}:environment`,
        provider: provider.id,
        name: '서버 환경 계정',
        authKind: 'api_key',
        credentialRef: provider.env,
        status: process.env[provider.env] ? 'available' : 'unavailable',
        models: provider.models.some((item) => item.id === model) ? provider.models : [{ id: model, text: true }],
      }],
    };
  });
}

export function getAiProviderStatuses(): AiProviderStatus[] {
  return getProviderCatalog().map((provider) => {
    const connection = provider.connections[0];
    return { provider: provider.label, connected: connection.status === 'available', model: connection.models[0].id, requiredEnv: connection.credentialRef };
  });
}

export function resolveProviderSelection(provider: AiProvider, connectionId?: string, model?: string) {
  const catalog = getProviderCatalog().find((item) => item.label === provider)!;
  const fallback = catalog.connections[0];
  return {
    provider,
    connectionId: connectionId?.trim() || fallback.id,
    model: model?.trim() || fallback.models[0].id,
  };
}

function localAiResult(input: GenerateThinkingInput): AiResult {
  const compactPrompt = input.prompt.trim().replace(/\s+/g, ' ');
  const title = compactPrompt.length > 24 ? `${compactPrompt.slice(0, 24)}...` : compactPrompt || '새 Thinking';

  const providerTone: Record<AiProvider, string> = {
    GPT: '실행 계획 중심',
    Claude: '맥락 분석 중심',
    Gemini: '자료 탐색 중심',
    Grok: '실시간 추론 중심',
    Kimi: '긴 문맥과 에이전트 추론 중심',
    'OpenCode Zen': '검증된 다중 모델 전환 중심',
    'Hermes Local': '로컬 프라이버시 및 오프라인 추론 중심',
  };
  const tone = providerTone[input.provider] || '종합 분석 중심';

  return {
    title,
    answer: `${tone}으로 정리했습니다. 핵심 문제를 정의하고, 현재 맥락을 바탕으로 다음 액션을 3단계로 나눕니다. 1) 목표와 제약을 명확히 하기 2) 선택 가능한 대안을 비교하기 3) 가장 작은 실험부터 실행하기.`,
    insight: `이 질문은 ${tone} 사고 패턴에 가깝습니다. 반복되면 장기 목표나 관심사 변화 분석에 반영됩니다.`,
    tags: ['AI', input.provider, 'Thinking'],
  };
}

function normalizeJsonText(text: string) {
  return text
    .trim()
    .replace(/^```(?:json)?\s*/i, '')
    .replace(/\s*```$/, '')
    .trim();
}

function parseOpenAiText(text: string, input: GenerateThinkingInput): AiResult {
  // Check for Hermes-style scratchpad & tool tags
  const parsedHermes = parseHermesOutput(text);
  const targetText = parsedHermes.content || text;

  try {
    const parsed = JSON.parse(normalizeJsonText(targetText)) as Partial<AiResult>;
    return {
      title: parsed.title || localAiResult(input).title,
      answer: parsed.answer || targetText,
      insight: parsed.insight || (parsedHermes.scratchPad ? `추론 반영: ${parsedHermes.scratchPad.slice(0, 60)}...` : 'AI가 질문의 핵심 패턴을 분석했습니다.'),
      tags: parsed.tags?.length ? parsed.tags : ['AI', input.provider],
    };
  } catch {
    return {
      title: localAiResult(input).title,
      answer: targetText,
      insight: parsedHermes.scratchPad ? `추론 반영: ${parsedHermes.scratchPad.slice(0, 60)}...` : 'AI가 질문의 핵심 패턴을 분석했습니다.',
      tags: ['AI', input.provider],
    };
  }
}

export async function generateThinking(input: GenerateThinkingInput): Promise<AiResult> {
  if (input.provider === 'Claude') return generateWithClaude(input);
  if (input.provider === 'Gemini') return generateWithGemini(input);
  if (input.provider === 'Grok') return generateWithGrok(input);
  if (input.provider === 'Kimi') return generateWithCompatibleChat(input, 'https://api.moonshot.ai/v1/chat/completions', process.env.MOONSHOT_API_KEY, process.env.MOONSHOT_MODEL || 'kimi-k3');
  if (input.provider === 'OpenCode Zen') return generateWithOpenCodeZen(input);
  if (input.provider === 'Hermes Local') return generateWithHermesLocal(input);
  return generateWithOpenAi(input);
}

async function generateWithHermesLocal(input: GenerateThinkingInput): Promise<AiResult> {
  const localUrl = process.env.HERMES_API_URL || 'http://localhost:11434/v1/chat/completions';
  const apiKey = input.apiKey || process.env.HERMES_API_KEY || 'local';
  const model = input.model || process.env.HERMES_MODEL || 'hermes-3-llama-3.1-8b';

  const systemInstruction = [
    'You generate Think Along records. Return compact JSON with title, answer, insight, and tags. Korean output.',
    input.context.system,
    formatHermesSystemInstruction({}),
  ].join('\n\n');

  try {
    const response = await fetch(localUrl, {
      method: 'POST',
      headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model,
        messages: [
          { role: 'system', content: systemInstruction },
          { role: 'user', content: JSON.stringify(input.context) },
        ],
      }),
    });

    if (!response.ok) {
      if (input.apiKey) {
        const payload = (await response.json().catch(() => null)) as { error?: { message?: string } } | null;
        throw new Error(payload?.error?.message ?? `Hermes Local API 요청에 실패했습니다. (${response.status})`);
      }
      return localAiResult(input);
    }

    const data = (await response.json()) as { choices?: Array<{ message?: { content?: string } }> };
    const text = data.choices?.[0]?.message?.content ?? '';
    return text ? parseOpenAiText(text, input) : localAiResult(input);
  } catch (error) {
    if (input.apiKey && !(error instanceof Error && error.message.includes('fetch failed'))) {
      throw error;
    }
    return localAiResult(input);
  }
}

async function generateWithGrok(input: GenerateThinkingInput): Promise<AiResult> {
  const apiKey = input.apiKey || process.env.XAI_API_KEY;
  if (!apiKey) return localAiResult(input);
  const response = await fetch('https://api.x.ai/v1/responses', {
    method: 'POST',
    headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model: input.model || process.env.XAI_MODEL || 'grok-4.6',
      input: [
        'You generate Think Along records. Return compact JSON with title, answer, insight, and tags. Korean output.',
        input.context.system,
        JSON.stringify(input.context),
      ].join('\n\n'),
    }),
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { error?: { message?: string } } | null;
    if (response.status === 403) throw new Error('xAI API Key에 Grok 모델 또는 Responses API 권한이 없습니다. xAI Console에서 모델·엔드포인트 권한과 팀 결제 상태를 확인해주세요.');
    throw new Error(payload?.error?.message ?? `Grok API 요청에 실패했습니다. (${response.status})`);
  }
  const data = (await response.json()) as { output_text?: string; output?: Array<{ content?: Array<{ text?: string }> }> };
  const text = data.output_text ?? data.output?.flatMap((item) => item.content ?? []).find((item) => item.text)?.text ?? '';
  return text ? parseOpenAiText(text, input) : localAiResult(input);
}

async function generateWithCompatibleChat(input: GenerateThinkingInput, url: string, environmentKey: string | undefined, defaultModel: string): Promise<AiResult> {
  const apiKey = input.apiKey || environmentKey;
  if (!apiKey) return localAiResult(input);
  const response = await fetch(url, {
    method: 'POST',
    headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model: input.model || defaultModel,
      messages: [
        { role: 'system', content: ['You generate Think Along records. Return compact JSON with title, answer, insight, and tags. Korean output.', input.context.system].join('\n\n') },
        { role: 'user', content: JSON.stringify(input.context) },
      ],
    }),
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { error?: { message?: string } } | null;
    throw new Error(payload?.error?.message ?? `${input.provider} API 요청에 실패했습니다. (${response.status})`);
  }
  const data = (await response.json()) as { choices?: Array<{ message?: { content?: string } }> };
  const text = data.choices?.[0]?.message?.content ?? '';
  return text ? parseOpenAiText(text, input) : localAiResult(input);
}

async function generateWithOpenCodeZen(input: GenerateThinkingInput): Promise<AiResult> {
  const apiKey = input.apiKey || process.env.OPENCODE_ZEN_API_KEY;
  if (!apiKey) return localAiResult(input);

  const model = input.model || process.env.OPENCODE_ZEN_MODEL || 'x-preview-f-free';
  const prompt = [
    'You generate Think Along records. Return compact JSON with title, answer, insight, and tags. Korean output.',
    input.context.system,
    JSON.stringify(input.context),
  ].join('\n\n');
  const usesResponses = /^(gpt-|grok-|muse-spark)/.test(model);
  const response = await fetch(usesResponses ? 'https://opencode.ai/zen/v1/responses' : 'https://opencode.ai/zen/v1/chat/completions', {
    method: 'POST',
    headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(usesResponses
      ? { model, input: prompt }
      : { model, messages: [{ role: 'user', content: prompt }] }),
  });

  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { error?: { message?: string } } | null;
    const message = payload?.error?.message ?? `OpenCode Zen API 요청에 실패했습니다. (${response.status})`;
    throw new Error(/Endpoint is unavailable|Upstream request failed/i.test(message)
      ? '선택한 OpenCode Zen 모델을 일시적으로 사용할 수 없습니다. Big Pickle 또는 Ox Alpha로 바꾸어 다시 시도해주세요.'
      : message);
  }

  const data = (await response.json()) as { choices?: Array<{ message?: { content?: string } }>; output_text?: string; output?: Array<{ content?: Array<{ text?: string }> }> };
  const text = data.output_text ?? data.output?.flatMap((item) => item.content ?? []).find((item) => item.text)?.text ?? data.choices?.[0]?.message?.content ?? '';
  return text ? parseOpenAiText(text, input) : localAiResult(input);
}

async function generateWithOpenAi(input: GenerateThinkingInput): Promise<AiResult> {
  const apiKey = input.apiKey || process.env.OPENAI_API_KEY;
  if (!apiKey) return localAiResult(input);

  const response = await fetch('https://api.openai.com/v1/responses', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${apiKey}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      model: input.model || process.env.OPENAI_MODEL || 'gpt-5.6-terra',
      input: [
        {
          role: 'system',
          content: [
            'You generate Think Along records. Return compact JSON with title, answer, insight, and tags. Korean output.',
            input.context.system,
          ].join('\n\n'),
        },
        {
          role: 'user',
          content: JSON.stringify(input.context),
        },
      ],
      text: {
        format: {
          type: 'json_object',
        },
      },
    }),
  });

  if (!response.ok) {
    if (input.apiKey) {
      const payload = (await response.json().catch(() => null)) as { error?: { message?: string } } | null;
      throw new Error(payload?.error?.message ?? `OpenAI API 요청에 실패했습니다. (${response.status})`);
    }
    return localAiResult(input);
  }

  const data = (await response.json()) as {
    output_text?: string;
    output?: Array<{ content?: Array<{ text?: string }> }>;
  };
  const text =
    data.output_text ??
    data.output?.flatMap((item) => item.content ?? []).find((item) => item.text)?.text ??
    '';

  return text ? parseOpenAiText(text, input) : localAiResult(input);
}

async function generateWithClaude(input: GenerateThinkingInput): Promise<AiResult> {
  const apiKey = input.apiKey || process.env.ANTHROPIC_API_KEY;
  if (!apiKey) return localAiResult(input);

  const response = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: {
      'x-api-key': apiKey,
      'anthropic-version': '2023-06-01',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      model: input.model || process.env.ANTHROPIC_MODEL || 'claude-sonnet-5',
      max_tokens: 900,
      system: [
        'You generate Think Along records. Return compact JSON with title, answer, insight, and tags. Korean output.',
        input.context.system,
      ].join('\n\n'),
      messages: [
        {
          role: 'user',
          content: JSON.stringify(input.context),
        },
      ],
    }),
  });

  if (!response.ok) {
    if (input.apiKey) {
      const payload = (await response.json().catch(() => null)) as { error?: { message?: string } } | null;
      throw new Error(payload?.error?.message ?? `Claude API 요청에 실패했습니다. (${response.status})`);
    }
    return localAiResult(input);
  }

  const data = (await response.json()) as { content?: Array<{ text?: string }> };
  const text = data.content?.find((item) => item.text)?.text ?? '';
  return text ? parseOpenAiText(text, input) : localAiResult(input);
}

async function generateWithGemini(input: GenerateThinkingInput): Promise<AiResult> {
  const apiKey = input.apiKey || process.env.GEMINI_API_KEY;
  if (!apiKey) return localAiResult(input);

  const model = input.model || process.env.GEMINI_MODEL || 'gemini-3.7-flash';
  const response = await fetch(
    `https://generativelanguage.googleapis.com/v1beta/models/${model}:generateContent?key=${apiKey}`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        contents: [
          {
            role: 'user',
            parts: [
              {
                text: [
                  'You generate Think Along records. Return compact JSON with title, answer, insight, and tags. Korean output.',
                  input.context.system,
                  JSON.stringify(input.context),
                ].join('\n'),
              },
            ],
          },
        ],
      }),
    },
  );

  if (!response.ok) {
    if (input.apiKey) {
      const payload = (await response.json().catch(() => null)) as { error?: { message?: string } } | null;
      const message = payload?.error?.message ?? `Gemini API 요청에 실패했습니다. (${response.status})`;
      throw new Error(message.includes('high demand')
        ? 'Gemini 3.7 사용량이 일시적으로 많습니다. 잠시 후 다시 보내거나 Gemini 3.6 Flash를 선택해주세요.'
        : message);
    }
    return localAiResult(input);
  }

  const data = (await response.json()) as {
    candidates?: Array<{ content?: { parts?: Array<{ text?: string }> } }>;
  };
  const text = data.candidates?.[0]?.content?.parts?.find((item) => item.text)?.text ?? '';
  return text ? parseOpenAiText(text, input) : localAiResult(input);
}

import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import type { AiProvider, AppDatabase, Insight, Thinking, User } from '@/lib/types';

const dbPath = path.join(process.cwd(), 'data', 'db.json');

const now = () => new Date().toISOString();

const defaultSelections: Record<AiProvider, { connectionId: string; model: string }> = {
  GPT: { connectionId: 'openai:environment', model: process.env.OPENAI_MODEL || 'gpt-5.6-terra' },
  Claude: { connectionId: 'anthropic:environment', model: process.env.ANTHROPIC_MODEL || 'claude-sonnet-5' },
  Gemini: { connectionId: 'gemini:environment', model: process.env.GEMINI_MODEL || 'gemini-3.7-flash' },
  Grok: { connectionId: 'xai:environment', model: process.env.XAI_MODEL || 'grok-4.6' },
  Kimi: { connectionId: 'moonshot:environment', model: process.env.MOONSHOT_MODEL || 'kimi-k3' },
  'OpenCode Zen': { connectionId: 'opencode:environment', model: process.env.OPENCODE_ZEN_MODEL || 'x-preview-f-free' },
  'Hermes Local': { connectionId: 'local:environment', model: process.env.HERMES_MODEL || 'hermes-3-llama-3.1-8b' },
};

const demoUser: User = {
  id: 'usr_demo',
  email: 'alex@example.com',
  nickname: 'Alex',
  authProvider: 'email',
  interests: ['사업', '개발', '생산성'],
  defaultAiProvider: 'GPT',
  createdAt: now(),
  updatedAt: now(),
};

const demoThinkings: Thinking[] = [
  {
    id: 'th_business_plan',
    thinkalongSessionId: 'th_business_plan',
    userId: demoUser.id,
    title: '사업계획서',
    prompt: 'B2B AI 메모 앱의 초기 사업계획서 구조를 잡아줘',
    aiProvider: 'GPT',
    selectedConnectionId: defaultSelections.GPT.connectionId,
    selectedModel: defaultSelections.GPT.model,
    contextPolicy: { allowedProviders: ['GPT', 'Claude', 'Gemini', 'Grok', 'Kimi', 'OpenCode Zen'], includeDecisions: true, includeRecentMessages: true, routingMode: 'manual' },
    status: 'active',
    folder: 'Startup',
    favorite: true,
    tags: ['사업', 'MVP', 'Lean Canvas'],
    insight: '사업 아이디어를 실행 계획으로 전환하려는 패턴이 강합니다.',
    answer:
      '초기 전략은 1인 창업자와 소규모 팀을 대상으로 한 Thinking 저장소입니다. MVP는 인증, Thinking 생성, Timeline, Insight 리포트로 시작하는 것이 좋습니다.',
    createdAt: now(),
    updatedAt: now(),
  },
  {
    id: 'th_chart_analysis',
    thinkalongSessionId: 'th_chart_analysis',
    userId: demoUser.id,
    title: '카바나 차트 분석',
    prompt: '월별 전환율 데이터를 보고 병목을 찾아줘',
    aiProvider: 'Gemini',
    selectedConnectionId: defaultSelections.Gemini.connectionId,
    selectedModel: defaultSelections.Gemini.model,
    contextPolicy: { allowedProviders: ['GPT', 'Claude', 'Gemini', 'Grok', 'Kimi', 'OpenCode Zen'], includeDecisions: true, includeRecentMessages: true, routingMode: 'manual' },
    status: 'active',
    folder: 'Data',
    favorite: false,
    tags: ['분석', '데이터'],
    insight: '데이터를 근거로 의사결정하려는 질문이 증가했습니다.',
    answer: '전환율 하락 구간을 채널, 퍼널 단계, 캠페인 변경일 기준으로 나누어 보면 병목을 더 빨리 찾을 수 있습니다.',
    createdAt: now(),
    updatedAt: now(),
  },
];

const seedDatabase = (): AppDatabase => ({
  users: [demoUser],
  sessions: [],
  thinkings: demoThinkings,
  messages: demoThinkings.flatMap((thinking) => [
    {
      id: `${thinking.id}_msg_user`,
      thinkingId: thinking.id,
      thinkalongSessionId: thinking.id,
      role: 'user',
      content: thinking.prompt,
      aiProvider: thinking.aiProvider,
      createdAt: thinking.createdAt,
    },
    {
      id: `${thinking.id}_msg_assistant`,
      thinkingId: thinking.id,
      thinkalongSessionId: thinking.id,
      role: 'assistant',
      content: thinking.answer,
      aiProvider: thinking.aiProvider,
      createdAt: thinking.createdAt,
    },
  ]),
  attachments: [],
  insights: [
    {
      id: 'in_weekly_demo',
      userId: demoUser.id,
      period: 'weekly',
      title: '주간 인사이트',
      summary: '최근 30일 동안 사업 관련 질문이 28% 증가했어요.',
      patterns: ['사업 아이디어 관심 증가', '오전 9-11시 질문 집중', '데이터 분석 질문 증가'],
      recommendations: ['Lean Canvas 작성', 'MVP 제작 범위 정리', '초기 고객 인터뷰 질문 설계'],
      createdAt: now(),
    } satisfies Insight,
  ],
  providerConnections: [],
  decisions: [],
  contextSnapshots: [],
  events: [],
  toolRuns: [],
  subAgentRuns: [],
  skills: [],
});

export async function readDb(): Promise<AppDatabase> {
  await mkdir(path.dirname(dbPath), { recursive: true });

  try {
    const raw = await readFile(dbPath, 'utf8');
    const db = JSON.parse(raw) as AppDatabase;
    db.providerConnections ??= [];
    db.decisions ??= [];
    db.contextSnapshots ??= [];
    db.events ??= [];
    db.toolRuns ??= [];
    db.subAgentRuns ??= [];
    db.skills ??= [];
    for (const user of db.users) {
      if ((user.defaultAiProvider as string) === 'OpenRouter') user.defaultAiProvider = 'OpenCode Zen';
      if ((user.defaultAiProvider as string) === 'MiMo') user.defaultAiProvider = 'Kimi';
    }
    for (const thinking of db.thinkings) {
      if ((thinking.aiProvider as string) === 'OpenRouter') thinking.aiProvider = 'OpenCode Zen';
      if ((thinking.aiProvider as string) === 'MiMo') thinking.aiProvider = 'Kimi';
      thinking.thinkalongSessionId = thinking.id;
      const selection = defaultSelections[thinking.aiProvider] || defaultSelections.GPT;
      thinking.selectedConnectionId ??= selection.connectionId;
      thinking.selectedModel ??= selection.model;
      thinking.contextPolicy ??= { allowedProviders: ['GPT', 'Claude', 'Gemini', 'Grok', 'Kimi', 'OpenCode Zen', 'Hermes Local'], includeDecisions: true, includeRecentMessages: true, routingMode: 'manual' };
      thinking.contextPolicy.allowedProviders = thinking.contextPolicy.allowedProviders.map((provider) => (provider as string) === 'OpenRouter' ? 'OpenCode Zen' : (provider as string) === 'MiMo' ? 'Kimi' : provider);
      if (!thinking.contextPolicy.allowedProviders.includes('OpenCode Zen')) thinking.contextPolicy.allowedProviders.push('OpenCode Zen');
      if (!thinking.contextPolicy.allowedProviders.includes('Grok')) thinking.contextPolicy.allowedProviders.push('Grok');
      if (!thinking.contextPolicy.allowedProviders.includes('Kimi')) thinking.contextPolicy.allowedProviders.push('Kimi');
      if (!thinking.contextPolicy.allowedProviders.includes('Hermes Local')) thinking.contextPolicy.allowedProviders.push('Hermes Local');
      thinking.contextPolicy.routingMode = 'manual';
    }
    for (const message of db.messages) {
      message.thinkalongSessionId ??= message.thinkingId;
      if ((message.aiProvider as string) === 'OpenRouter') message.aiProvider = 'OpenCode Zen';
    }
    for (const attachment of db.attachments) attachment.thinkalongSessionId ??= attachment.thinkingId;
    return db;
  } catch {
    const seeded = seedDatabase();
    await writeDb(seeded);
    return seeded;
  }
}

export async function writeDb(db: AppDatabase): Promise<void> {
  await mkdir(path.dirname(dbPath), { recursive: true });
  await writeFile(dbPath, JSON.stringify(db, null, 2));
}

export async function updateDb<T>(mutator: (db: AppDatabase) => T | Promise<T>): Promise<T> {
  const db = await readDb();
  const result = await mutator(db);
  await writeDb(db);
  return result;
}

export function publicUser(user: User) {
  return {
    id: user.id,
    email: user.email,
    nickname: user.nickname,
    interests: user.interests,
    defaultAiProvider: user.defaultAiProvider,
  };
}

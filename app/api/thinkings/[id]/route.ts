import { NextResponse } from 'next/server';
import { requireUser } from '@/lib/server/auth';
import { readDb, updateDb } from '@/lib/server/db';
import type { AiProvider, ContextPolicy } from '@/lib/types';

type RouteContext = {
  params: Promise<{ id: string }>;
};

const validProviders: AiProvider[] = ['GPT', 'Claude', 'Gemini', 'Grok', 'Kimi', 'OpenCode Zen'];

export async function GET(request: Request, context: RouteContext) {
  const auth = await requireUser(request);
  if (!auth.user) return auth.response;

  const { id } = await context.params;
  const db = await readDb();
  const thinking = db.thinkings.find((item) => item.id === id && item.userId === auth.user.id);

  if (!thinking) {
    return NextResponse.json(
      { error: { code: 'THINKING_NOT_FOUND', message: 'Thinking을 찾을 수 없습니다.' } },
      { status: 404 },
    );
  }

  return NextResponse.json({
    thinking,
    messages: db.messages.filter((message) => message.thinkalongSessionId === thinking.thinkalongSessionId),
    attachments: db.attachments.filter((attachment) => attachment.thinkalongSessionId === thinking.thinkalongSessionId),
    decisions: db.decisions.filter((decision) => decision.thinkalongSessionId === thinking.thinkalongSessionId),
    events: db.events.filter((event) => event.thinkalongSessionId === thinking.thinkalongSessionId),
    toolRuns: db.toolRuns.filter((run) => run.thinkalongSessionId === thinking.thinkalongSessionId),
    subAgentRuns: db.subAgentRuns.filter((run) => run.thinkalongSessionId === thinking.thinkalongSessionId),
  });
}

export async function PATCH(request: Request, context: RouteContext) {
  const auth = await requireUser(request);
  if (!auth.user) return auth.response;

  const { id } = await context.params;
  const body = (await request.json().catch(() => null)) as {
    title?: string;
    tags?: string[];
    folder?: string;
    favorite?: boolean;
    aiProvider?: AiProvider;
    selectedConnectionId?: string;
    selectedModel?: string;
    contextPolicy?: ContextPolicy;
  } | null;

  const changesSelection =
    body?.aiProvider !== undefined ||
    body?.selectedConnectionId !== undefined ||
    body?.selectedModel !== undefined;
  if (
    changesSelection &&
    (!validProviders.includes(body?.aiProvider as AiProvider) ||
      !body?.selectedConnectionId?.trim() ||
      !body?.selectedModel?.trim())
  ) {
    return NextResponse.json(
      { error: { code: 'INVALID_MODEL_SELECTION', message: 'Provider, 계정, 모델을 함께 선택해주세요.' } },
      { status: 400 },
    );
  }
  if (body?.contextPolicy && (
    !Array.isArray(body.contextPolicy.allowedProviders) ||
    body.contextPolicy.allowedProviders.some((provider) => !validProviders.includes(provider)) ||
    typeof body.contextPolicy.includeDecisions !== 'boolean' ||
    typeof body.contextPolicy.includeRecentMessages !== 'boolean' ||
    body.contextPolicy.routingMode !== 'manual'
  )) return NextResponse.json({ error: { code: 'INVALID_CONTEXT_POLICY', message: 'Context 권한 설정을 확인해주세요.' } }, { status: 400 });

  const thinking = await updateDb((db) => {
    const item = db.thinkings.find((candidate) => candidate.id === id && candidate.userId === auth.user.id);
    if (!item) return null;

    item.title = body?.title?.trim() || item.title;
    item.tags = body?.tags ?? item.tags;
    item.folder = body?.folder ?? item.folder;
    item.favorite = body?.favorite ?? item.favorite;
    if (changesSelection) {
      item.aiProvider = body!.aiProvider!;
      item.selectedConnectionId = body!.selectedConnectionId!.trim();
      item.selectedModel = body!.selectedModel!.trim();
    }
    if (body?.contextPolicy) item.contextPolicy = body.contextPolicy;
    item.updatedAt = new Date().toISOString();
    return item;
  });

  if (!thinking) {
    return NextResponse.json(
      { error: { code: 'THINKING_NOT_FOUND', message: 'Thinking을 찾을 수 없습니다.' } },
      { status: 404 },
    );
  }

  return NextResponse.json({ thinking });
}

export async function DELETE(request: Request, context: RouteContext) {
  const auth = await requireUser(request);
  if (!auth.user) return auth.response;

  const { id } = await context.params;
  const thinking = await updateDb((db) => {
    const item = db.thinkings.find((candidate) => candidate.id === id && candidate.userId === auth.user.id);
    if (!item) return null;

    const sessionId = item.thinkalongSessionId;
    db.thinkings = db.thinkings.filter((candidate) => candidate.id !== id);
    db.messages = db.messages.filter((message) => message.thinkalongSessionId !== sessionId);
    db.attachments = db.attachments.filter((attachment) => attachment.thinkalongSessionId !== sessionId);
    db.decisions = db.decisions.filter((decision) => decision.thinkalongSessionId !== sessionId);
    db.contextSnapshots = db.contextSnapshots.filter((snapshot) => snapshot.thinkalongSessionId !== sessionId);
    db.events = db.events.filter((event) => event.thinkalongSessionId !== sessionId);
    db.toolRuns = db.toolRuns.filter((run) => run.thinkalongSessionId !== sessionId);
    db.subAgentRuns = db.subAgentRuns.filter((run) => run.thinkalongSessionId !== sessionId);
    return item;
  });

  if (!thinking) {
    return NextResponse.json(
      { error: { code: 'THINKING_NOT_FOUND', message: 'Thinking을 찾을 수 없습니다.' } },
      { status: 404 },
    );
  }

  return NextResponse.json({ thinking });
}

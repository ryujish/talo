import { randomUUID } from 'node:crypto';
import { NextResponse } from 'next/server';
import { generateThinking, resolveProviderSelection } from '@/lib/server/ai';
import { createContextPacket } from '@/lib/server/context-engine';
import { requireUser } from '@/lib/server/auth';
import { recordEvent } from '@/lib/server/events';
import { readDb, updateDb } from '@/lib/server/db';
import type { AiProvider, Attachment, ConversationMessage, Thinking } from '@/lib/types';

const validProviders: AiProvider[] = ['GPT', 'Claude', 'Gemini', 'Grok', 'Kimi', 'OpenCode Zen'];

export async function GET(request: Request) {
  const auth = await requireUser(request);
  if (!auth.user) return auth.response;

  const db = await readDb();
  const url = new URL(request.url);
  const status = url.searchParams.get('status') ?? 'active';
  const thinkings = db.thinkings
    .filter((thinking) => thinking.userId === auth.user.id && thinking.status === status)
    .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));

  return NextResponse.json({ thinkings });
}

export async function POST(request: Request) {
  const auth = await requireUser(request);
  if (!auth.user) return auth.response;

  const body = (await request.json().catch(() => null)) as {
    prompt?: string;
    aiProvider?: AiProvider;
    aiCredential?: {
      connectionId?: string;
      apiKey?: string;
      model?: string;
    };
    attachments?: Array<Pick<Attachment, 'type' | 'name' | 'url' | 'mimeType' | 'size'>>;
  } | null;

  if (!body?.prompt?.trim()) {
    return NextResponse.json(
      { error: { code: 'PROMPT_REQUIRED', message: 'Prompt를 입력해주세요.' } },
      { status: 400 },
    );
  }

  const aiProvider = validProviders.includes(body.aiProvider as AiProvider)
    ? (body.aiProvider as AiProvider)
    : auth.user.defaultAiProvider;
  const thinkingId = randomUUID();
  const contextPacket = createContextPacket({ thinkalongSessionId: thinkingId, messages: [], decisions: [], prompt: body.prompt });
  const selection = resolveProviderSelection(aiProvider, body.aiCredential?.connectionId, body.aiCredential?.model);
  let ai;
  try {
    ai = await generateThinking({
      prompt: body.prompt,
      provider: aiProvider,
      context: contextPacket,
      apiKey: body.aiCredential?.apiKey,
      model: selection.model,
    });
  } catch (error) {
    return NextResponse.json(
      {
        error: {
          code: 'AI_CONNECTION_FAILED',
          message: error instanceof Error ? error.message : 'AI 연결에 실패했습니다.',
        },
      },
      { status: 502 },
    );
  }
  const now = new Date().toISOString();
  const result = await updateDb<{ thinking: Thinking; messages: ConversationMessage[] }>((db) => {
    const thinking: Thinking = {
      id: thinkingId,
      thinkalongSessionId: thinkingId,
      userId: auth.user.id,
      title: ai.title,
      prompt: body.prompt!.trim(),
      aiProvider,
      selectedConnectionId: selection.connectionId,
      selectedModel: selection.model,
      contextPolicy: { allowedProviders: validProviders, includeDecisions: true, includeRecentMessages: true, routingMode: 'manual' },
      status: 'active',
      favorite: false,
      tags: ai.tags,
      insight: ai.insight,
      answer: ai.answer,
      sessionSummary: ai.insight,
      createdAt: now,
      updatedAt: now,
    };
    const messages: ConversationMessage[] = [
      {
        id: randomUUID(),
        thinkingId,
        thinkalongSessionId: thinkingId,
        role: 'user',
        content: thinking.prompt,
        aiProvider,
        connectionId: selection.connectionId,
        model: selection.model,
        contextVersion: contextPacket.version,
        createdAt: now,
      },
      {
        id: randomUUID(),
        thinkingId,
        thinkalongSessionId: thinkingId,
        role: 'assistant',
        content: ai.answer,
        aiProvider,
        connectionId: selection.connectionId,
        model: selection.model,
        contextVersion: contextPacket.version,
        executionStatus: 'succeeded',
        createdAt: now,
      },
    ];

    db.thinkings.push(thinking);
    db.messages.push(...messages);
    db.contextSnapshots.push({ id: randomUUID(), userId: auth.user.id, thinkalongSessionId: thinkingId, version: contextPacket.version, provider: aiProvider, connectionId: selection.connectionId, model: selection.model, packet: contextPacket, createdAt: now });
    recordEvent(db, { id: randomUUID(), userId: auth.user.id, thinkalongSessionId: thinkingId, type: 'model.executed', data: { provider: aiProvider, connectionId: selection.connectionId, model: selection.model, contextVersion: contextPacket.version }, createdAt: now });
    for (const attachment of body.attachments ?? []) {
      db.attachments.push({
        id: randomUUID(),
        thinkingId,
        thinkalongSessionId: thinkingId,
        type: attachment.type,
        name: attachment.name,
        url: attachment.url,
        mimeType: attachment.mimeType,
        size: attachment.size,
        createdAt: now,
      });
    }

    return { thinking, messages };
  });

  return NextResponse.json(result, { status: 201 });
}

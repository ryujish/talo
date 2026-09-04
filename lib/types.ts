export type AuthProvider = 'email' | 'google' | 'apple';
export type AiProvider = 'GPT' | 'Claude' | 'Gemini' | 'Grok' | 'Kimi' | 'OpenCode Zen' | 'Hermes Local';
export type ProviderId = 'openai' | 'anthropic' | 'gemini' | 'xai' | 'moonshot' | 'opencode' | 'local';
export type ConnectionStatus = 'unknown' | 'available' | 'unavailable';

export type ModelCapability = {
  id: string;
  text: true;
  vision?: boolean;
  files?: boolean;
  tools?: boolean;
  structuredOutput?: boolean;
  streaming?: boolean;
};

export type ProviderConnection = {
  id: string;
  userId?: string;
  provider: ProviderId;
  name: string;
  authKind: 'api_key' | 'oauth' | 'local';
  credentialRef: string;
  status: ConnectionStatus;
  models: ModelCapability[];
  lastErrorCode?: string;
  lastCheckedAt?: string;
};

export type ProviderCatalogItem = {
  id: ProviderId;
  label: AiProvider;
  connections: ProviderConnection[];
};
export type ThinkingStatus = 'active' | 'trashed' | 'deleted';
export type ExportFormat = 'markdown' | 'pdf' | 'word' | 'notion' | 'json';

export type User = {
  id: string;
  email: string;
  nickname: string;
  authProvider: AuthProvider;
  interests: string[];
  defaultAiProvider: AiProvider;
  createdAt: string;
  updatedAt: string;
};

export type Session = {
  id: string;
  userId: string;
  tokenHash: string;
  expiresAt: string;
  createdAt: string;
};

export type Attachment = {
  id: string;
  thinkingId: string;
  thinkalongSessionId: string;
  type: 'image' | 'file' | 'voice';
  name: string;
  url: string;
  mimeType?: string;
  size?: number;
  createdAt: string;
};

export type ConversationMessage = {
  id: string;
  thinkingId: string;
  thinkalongSessionId: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  aiProvider?: AiProvider;
  connectionId?: string;
  model?: string;
  contextVersion?: number;
  executionStatus?: 'succeeded' | 'failed';
  createdAt: string;
};

export type ContextMessage = Pick<ConversationMessage, 'role' | 'content'>;

export type DecisionStatus = 'reviewing' | 'confirmed' | 'superseded' | 'discarded';

export type DecisionMemory = {
  id: string;
  userId: string;
  thinkalongSessionId: string;
  statement: string;
  topic?: string;
  status: DecisionStatus;
  sourceMessageId?: string;
  supersedesDecisionId?: string;
  supersededByDecisionId?: string;
  createdAt: string;
  updatedAt: string;
};

export type ContextPacket = {
  thinkalongSessionId: string;
  version: number;
  system: string;
  summary?: string;
  decisions: Array<Pick<DecisionMemory, 'id' | 'statement'>>;
  messages: ContextMessage[];
};

export type RoutingMode = 'manual' | 'automatic';

export type ContextPolicy = {
  allowedProviders: AiProvider[];
  includeDecisions: boolean;
  includeRecentMessages: boolean;
  routingMode: RoutingMode;
};

export type InternalAgentRole = 'thinker' | 'critic' | 'synthesizer';

export type ToolId = 'session.context.inspect' | string;

export type ToolDefinition = {
  id: ToolId;
  name: string;
  risk: 'read' | 'write' | 'execute';
  description?: string;
  parameters?: Record<string, unknown>;
};

export type SkillId = 'decision-review' | string;

export type SkillDefinition = {
  id: SkillId;
  name: string;
  description?: string;
  guidelines?: string[];
  agentRole: InternalAgentRole;
  allowedTools: ToolId[];
  synthesizedFromSessionId?: string;
  createdAt?: string;
};

export type ToolRun = {
  id: string;
  userId: string;
  thinkalongSessionId: string;
  toolId: ToolId;
  status: 'succeeded' | 'failed';
  result?: Record<string, unknown>;
  createdAt: string;
};

export type SubAgentRun = {
  id: string;
  userId: string;
  thinkalongSessionId: string;
  role: InternalAgentRole;
  skillId?: SkillId;
  contextVersion: number;
  status: 'completed' | 'failed';
  output?: string;
  provider?: AiProvider;
  connectionId?: string;
  model?: string;
  createdAt: string;
};

export type DomainEvent = {
  id: string;
  userId: string;
  thinkalongSessionId: string;
  type: 'decision.created' | 'decision.superseded' | 'model.executed' | 'tool.executed' | 'subagent.completed' | 'skill.synthesized';
  data: Record<string, string | number | boolean | undefined>;
  createdAt: string;
};

export type Thinking = {
  id: string;
  thinkalongSessionId: string;
  userId: string;
  title: string;
  prompt: string;
  aiProvider: AiProvider;
  selectedConnectionId: string;
  selectedModel: string;
  contextPolicy: ContextPolicy;
  status: ThinkingStatus;
  folder?: string;
  favorite: boolean;
  tags: string[];
  insight?: string;
  answer: string;
  sessionSummary?: string;
  createdAt: string;
  updatedAt: string;
};

export type Insight = {
  id: string;
  userId: string;
  period: 'weekly' | 'monthly';
  title: string;
  summary: string;
  patterns: string[];
  recommendations: string[];
  createdAt: string;
};

export type ContextSnapshot = {
  id: string;
  userId: string;
  thinkalongSessionId: string;
  version: number;
  provider: AiProvider;
  connectionId: string;
  model: string;
  packet: ContextPacket;
  createdAt: string;
};

export type AppDatabase = {
  users: User[];
  sessions: Session[];
  thinkings: Thinking[];
  messages: ConversationMessage[];
  attachments: Attachment[];
  insights: Insight[];
  providerConnections: ProviderConnection[];
  decisions: DecisionMemory[];
  contextSnapshots: ContextSnapshot[];
  events: DomainEvent[];
  toolRuns: ToolRun[];
  subAgentRuns: SubAgentRun[];
  skills?: SkillDefinition[];
};

export type ApiError = {
  error: {
    code: string;
    message: string;
  };
};

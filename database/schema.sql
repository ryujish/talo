create table users (
  id text primary key,
  email text not null unique,
  nickname text not null,
  auth_provider text not null check (auth_provider in ('email', 'google', 'apple')),
  interests jsonb not null default '[]'::jsonb,
  default_ai_provider text not null check (default_ai_provider in ('GPT', 'Claude', 'Gemini')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table sessions (
  id text primary key,
  user_id text not null references users(id) on delete cascade,
  token_hash text not null unique,
  expires_at timestamptz not null,
  created_at timestamptz not null default now()
);

create table thinkings (
  id text primary key,
  user_id text not null references users(id) on delete cascade,
  title text not null,
  prompt text not null,
  ai_provider text not null check (ai_provider in ('GPT', 'Claude', 'Gemini')),
  status text not null default 'active' check (status in ('active', 'trashed', 'deleted')),
  folder text,
  favorite boolean not null default false,
  tags jsonb not null default '[]'::jsonb,
  insight text,
  answer text not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table conversation_messages (
  id text primary key,
  thinking_id text not null references thinkings(id) on delete cascade,
  role text not null check (role in ('user', 'assistant', 'system')),
  content text not null,
  ai_provider text check (ai_provider in ('GPT', 'Claude', 'Gemini')),
  created_at timestamptz not null default now()
);

create table attachments (
  id text primary key,
  thinking_id text not null references thinkings(id) on delete cascade,
  type text not null check (type in ('image', 'file', 'voice')),
  name text not null,
  url text not null,
  mime_type text,
  size integer,
  created_at timestamptz not null default now()
);

create table insights (
  id text primary key,
  user_id text not null references users(id) on delete cascade,
  period text not null check (period in ('weekly', 'monthly')),
  title text not null,
  summary text not null,
  patterns jsonb not null default '[]'::jsonb,
  recommendations jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);

create index idx_sessions_user_id on sessions(user_id);
create index idx_thinkings_user_status_updated on thinkings(user_id, status, updated_at desc);
create index idx_thinkings_user_favorite on thinkings(user_id, favorite);
create index idx_messages_thinking_created on conversation_messages(thinking_id, created_at);
create index idx_attachments_thinking_id on attachments(thinking_id);
create index idx_insights_user_created on insights(user_id, created_at desc);

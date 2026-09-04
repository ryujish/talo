# Think Along Product Workspace

This workspace contains the product-oriented Think Along app.

## Architecture Work

This copy is the active development Work for the unified-session architecture.

- Permanent product context: [`docs/PROJECT_CONTEXT.md`](docs/PROJECT_CONTEXT.md)
- P0 architecture and implementation plan: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- Read-only source baseline: `/Users/choisunghoon/Documents/Aitime/think-along`
- Active Work: `/Users/choisunghoon/Documents/Aitime/think-along_start`

## Run

```bash
npm install
npm run dev -- --port 3001
```

## Implemented

- Email session authentication with `think_along_session` cookie
- File-backed JSON storage in `data/db.json`
- Thinking create/list/detail/update/delete/continue API routes
- Search, Insight, and Export API routes
- OpenAPI draft in `docs/openapi.yaml`
- SQL schema draft in `database/schema.sql`
- AI provider adapter with real calls when API keys exist and local fallback otherwise

## Optional Environment

```bash
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4.1-mini
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-3-5-haiku-latest
GEMINI_API_KEY=
GEMINI_MODEL=gemini-1.5-flash
```

The previous Think Along prototype remains untouched in:

- `/Users/choisunghoon/Documents/Codex/2026-07-28/new-chat-2/work/source`
- `/Users/choisunghoon/Documents/Codex/2026-07-28/new-chat-2/outputs/think-along-prototype-snapshot`

# Gemini CLI System Instructions & Cost Optimization Rules

## 1. Model Routing & Sub-Agent Policy
- **Default Task / Main Implementation**: Use `gemini-2.5-flash`.
- **Sub-tasks / Exploration**: Delegate file searching, pattern matching, log checking, and raw data collecting to `gemini-2.5-flash-8b`.
- **Complex Architecture / Deep Debugging**: Switch to `gemini-2.5-pro` only for specific complex logic, and return to `gemini-2.5-flash` immediately after.
- **Thinking / Reasoning Budget**: Limit internal thinking/reasoning generation to low-to-medium effort (`--thinking-budget 10000` equivalent). Do not spend excess reasoning tokens on simple edits.

## 2. Context Management & Anti-Rot Rules
- Compress context when reaching approximately 50% capacity or upon completing research milestones.
- Keep only current goals, active decisions, and essential file paths; discard historical raw tool outputs.
- Never refactor code or modify critical state during an active context compaction.
- Wipe context completely when switching to an unrelated task.

## 3. Tool & MCP Execution Limits
- Keep active MCP connectors <= 10 per project (total active tools <= 80).
- Prefer lightweight CLI execution over heavy MCP schemas where applicable.

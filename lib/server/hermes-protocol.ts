import type { ToolDefinition } from '@/lib/types';

export type HermesToolCall = {
  toolId: string;
  arguments: Record<string, unknown>;
};

export type ParsedHermesOutput = {
  scratchPad?: string;
  toolCalls: HermesToolCall[];
  content: string;
  raw: string;
};

/**
 * Parses Hermes-style XML tags (<scratch_pad>, <tool_call>) from model responses.
 */
export function parseHermesOutput(rawText: string): ParsedHermesOutput {
  const text = rawText || '';
  
  // Extract scratchpad (internal reflection/planning)
  let scratchPad: string | undefined;
  const scratchPadMatch = text.match(/<scratch_pad>([\s\S]*?)<\/scratch_pad>/i);
  if (scratchPadMatch) {
    scratchPad = scratchPadMatch[1].trim();
  }

  // Extract tool calls
  const toolCalls: HermesToolCall[] = [];
  const toolCallRegex = /<tool_call>([\s\S]*?)<\/tool_call>/gi;
  let match: RegExpExecArray | null;
  while ((match = toolCallRegex.exec(text)) !== null) {
    const rawPayload = match[1].trim();
    try {
      const parsed = JSON.parse(rawPayload);
      if (parsed && typeof parsed === 'object') {
        const toolId = parsed.name || parsed.id || parsed.toolId || 'session.context.inspect';
        const args = parsed.arguments || parsed.args || parsed.parameters || {};
        toolCalls.push({
          toolId: String(toolId),
          arguments: typeof args === 'object' && args !== null ? (args as Record<string, unknown>) : {},
        });
      }
    } catch {
      // Fallback if payload is formatted as plain name or malformed json
      if (rawPayload) {
        toolCalls.push({
          toolId: rawPayload.replace(/[^a-zA-Z0-9_.-]/g, ''),
          arguments: {},
        });
      }
    }
  }

  // Clean the main content by removing <scratch_pad> and <tool_call> blocks
  const cleanedContent = text
    .replace(/<scratch_pad>[\s\S]*?<\/scratch_pad>/gi, '')
    .replace(/<tool_call>[\s\S]*?<\/tool_call>/gi, '')
    .trim();

  return {
    scratchPad,
    toolCalls,
    content: cleanedContent,
    raw: text,
  };
}

/**
 * Generates prompt instructions for Hermes-3 and open-weight models
 * defining the standard XML tool calling schema and scratchpad protocol.
 */
export function formatHermesSystemInstruction(options: {
  tools?: ToolDefinition[];
  guidelines?: string[];
}): string {
  const lines: string[] = [
    '## Operational Protocol',
    'You have access to a reasoning scratchpad and tools.',
    'Use <scratch_pad>...</scratch_pad> for internal planning, goal tracking, and reviewing confirmed decisions before acting.',
  ];

  if (options.guidelines && options.guidelines.length > 0) {
    lines.push('', '## Learned Guidelines (Closed Learning Loop):');
    for (const rule of options.guidelines) {
      lines.push(`- ${rule}`);
    }
  }

  if (options.tools && options.tools.length > 0) {
    lines.push('', '## Available Tools (Hermes Standard):');
    lines.push('To call a tool, output XML tag <tool_call>{"name": "<tool_name>", "arguments": { ... }}</tool_call>.');
    lines.push('The environment will execute the function and provide <tool_response>...</tool_response>.');
    lines.push('');
    for (const tool of options.tools) {
      lines.push(`- Tool: \`${tool.id}\` (${tool.name})`);
      if (tool.description) lines.push(`  Description: ${tool.description}`);
      lines.push(`  Risk Level: ${tool.risk}`);
      if (tool.parameters) {
        lines.push(`  Parameters: ${JSON.stringify(tool.parameters)}`);
      }
    }
  }

  return lines.join('\n');
}

/**
 * Formats tool execution results into a Hermes standard <tool_response> block.
 */
export function formatHermesToolResponse(toolId: string, result: unknown): string {
  const payload = JSON.stringify({ name: toolId, result });
  return `<tool_response>\n${payload}\n</tool_response>`;
}

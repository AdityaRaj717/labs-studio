#!/usr/bin/env node
// The MCP shim: defines tools and forwards calls to the engine. No browser code, and nothing
// here writes to stdout, which belongs to the protocol.
import fs from 'fs';
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import {
  CallToolRequestSchema,
  ListResourcesRequestSchema,
  ListToolsRequestSchema,
  ReadResourceRequestSchema,
} from '@modelcontextprotocol/sdk/types.js';
import { callTool, ensureEngine, VERSION } from './shim/client.js';
import { INSTRUCTIONS, TOOLS } from './shim/tools.js';
import { toErrorPayload } from './utils/errors.js';

const GUIDE_URI = 'flow://guide';
const guide = () => fs.readFileSync(new URL('./shim/guide.md', import.meta.url), 'utf8');

const server = new Server(
  { name: 'google-flow-browser-mcp', version: VERSION },
  { capabilities: { tools: {}, resources: {} }, instructions: INSTRUCTIONS },
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: TOOLS }));
server.setRequestHandler(ListResourcesRequestSchema, async () => ({
  resources: [{ uri: GUIDE_URI, name: 'Flow guide', mimeType: 'text/markdown' }],
}));
server.setRequestHandler(ReadResourceRequestSchema, async () => ({
  contents: [{ uri: GUIDE_URI, mimeType: 'text/markdown', text: guide() }],
}));

server.setRequestHandler(CallToolRequestSchema, async (request, extra) => {
  const { name, arguments: args, _meta } = request.params;
  const token = _meta?.progressToken;
  const onProgress = token === undefined ? undefined : (note) => extra.sendNotification({
    method: 'notifications/progress',
    params: { progressToken: token, ...note },
  });
  try {
    return await callTool(ensureEngine, name, args, onProgress);
  } catch (err) {
    return { content: [{ type: 'text', text: JSON.stringify(toErrorPayload(err)) }], isError: true };
  }
});

await server.connect(new StdioServerTransport());

#!/usr/bin/env node
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  ErrorCode,
  McpError,
} from '@modelcontextprotocol/sdk/types.js';
import { logger } from './utils/logger.js';
import { launchKiaraProfile, navigateToFlow } from './browser/launch-profile.js';
import { getPage, getBrowser, setBrowser, closeBrowser as closeBrowserConnection } from './browser/connect.js';
import { verifyAccount as checkAccount } from './browser/account-check.js';
import { handleFlowStatus } from './tools/flow-status.js';
import { handleGenerateImage } from './tools/generate-image.js';
import { handleOpenProject, handleListProjects, handleRenameProject, handleDeleteProject } from './tools/open-project.js';
import { handleGenerateVideo } from './tools/generate-video.js';
import { handleDownloadLatest } from './tools/download-latest.js';
import { handleCreateCharacter, handleListCharacters } from './tools/create-character.js';
import { handleImportCharacter } from './tools/import-character.js';
import { handleCreateScene, handleListScenes } from './tools/create-scene.js';
import { handleOpenToolsGallery } from './tools/open-tools-gallery.js';
import { handleUseGridArchitect } from './tools/grid-architect.js';
import { handleUseFlowTool } from './tools/use-flow-tool.js';
import { jobQueue } from './queue/job-queue.js';
import { takeScreenshot } from './utils/screenshots.js';
import fs from 'fs';
import path from 'path';

// A character or place for flow_generate_image: a name in this project, or { name, project }.
const CHARACTER_REF = {
  oneOf: [{ type: 'string' }, { type: 'object', properties: { name: { type: 'string' }, project: { type: 'string', description: 'Title of the Flow project that holds it.' } }, required: ['name'] }],
};

const TOOL_DEFINITIONS = [
  {
    name: 'flow_connect',
    description: 'Launch Chrome with the configured Google profile, connect CDP, navigate to Google Flow, and verify account.',
    inputSchema: {
      type: 'object',
      properties: {
        headless: { type: 'boolean', description: 'Launch in headless mode (not recommended, Google Flow needs visible browser).', default: false },
        open_flow: { type: 'boolean', description: 'Auto-navigate to Google Flow after connection.', default: true },
      },
    },
  },
  {
    name: 'flow_disconnect',
    description: 'Close the browser and clean up the MCP connection to Google Flow.',
    inputSchema: { type: 'object', properties: {} },
  },
  {
    name: 'flow_status',
    description: 'Check current connection status: browser connected, Flow page loaded, account verified, job queue state.',
    inputSchema: {
      type: 'object',
      properties: {
        full: { type: 'boolean', description: 'Return full status with screenshot.', default: false },
      },
    },
  },
  {
    name: 'flow_account_check',
    description: 'Verify the logged-in Google account matches the configured expected email (Profile 3).',
    inputSchema: { type: 'object', properties: {} },
  },
  {
    name: 'flow_generate_image',
    description: '⚠️ CES IMAGES CONSOMMENT DES CRÉDITS. Generates images through the agent chat of the Flow project. Sets the Agent settings of the project (aspect, count, model), uploads reference images as ingredients, sends the prompt. auto_confirm=false (default): prepares only and returns "ready_for_confirmation", nothing generated. auto_confirm=true: also sets "Confirm before generating: Never" for that project, presses Start generation, waits for the agent, and downloads every image at full size through the Flow Download media action. Errors carry a code: NOT_LOGGED_IN, MANUAL_VERIFICATION_REQUIRED, GOOGLE_LIMIT_REACHED, GENERATION_REFUSED, UNKNOWN_UI_CHANGE, ...',
    inputSchema: {
      type: 'object',
      properties: {
        prompt: { type: 'string', description: 'The text prompt for image generation.' },
        model: { type: 'string', description: 'Image model: Nano Banana 2.1 (default), Nano Banana Pro, Nano Banana 2 Lite. "Nano Banana 2" is accepted as 2.1.', default: 'Nano Banana 2.1' },
        auto_confirm: { type: 'boolean', description: '⚠️ CRÉDITS. false (default): prepare only. true: generate (spends credits).', default: false },
        ratio: { type: 'string', description: 'Aspect ratio: 1:1, 16:9, 9:16, 4:3, 3:4.', default: '1:1' },
        count: { type: 'number', description: 'Number of images, 1-4 (Agent settings x1-x4).', default: 1 },
        download_size: { type: 'string', description: 'Download size: 1K (original), 2K (upscaled), 4K (upscaled, higher plans only).', default: '1K' },
        reference_images: { type: 'array', items: { type: 'string' }, description: 'Paths to reference images, uploaded as ingredients (optional).' },
        characters: { type: 'array', items: CHARACTER_REF, description: 'Flow characters to add as ingredients by name (picker > Characters). A string is a character of this project; { name, project } takes one from another project by its title.' },
        scenes: { type: 'array', items: CHARACTER_REF, description: 'Places made with flow_create_scene, added the same way.' },
        brand: { type: 'string', description: 'Brand context for automatic model selection: premium, standard.' },
        project_name: { type: 'string', description: 'Name for the project (will reuse existing project with same campaign, or create new).' },
        campaign: { type: 'string', description: 'Campaign identifier for project matching (e.g., "ete-2026", "nouvelle-collection").' },
        project_url: { type: 'string', description: 'Flow project URL to generate in (from flow_open_project). Wins over campaign / project_name. PROJECT_NOT_FOUND if it no longer exists.' },
        output_folder: { type: 'string', description: 'Folder to save the downloaded images into (created if missing).' },
        filename: { type: 'string', description: 'Base file name without extension (e.g. "IMG-001"). Several images get _v1, _v2 suffixes.' },
        wait_ms: { type: 'number', description: 'How long this call waits for the result before returning status "running" (default toolResponseBudgetMs, 40000).' },
        timeout_ms: { type: 'number', description: 'Give up if the agent has not finished after this long (default 300000).' },
      },
      required: ['prompt'],
    },
  },
  {
    name: 'flow_open_project',
    description: 'Open a Flow project in the shared tab, creating it when missing. url: a stored project URL (optional). name: the title the project should have (set when it differs). create_if_missing (default true): when url is empty or Flow says the project is gone, create a new project. Returns { url, created, title }. PROJECT_NOT_FOUND when gone and create_if_missing is false. Free: generates nothing.',
    inputSchema: {
      type: 'object',
      properties: {
        url: { type: 'string', description: 'Flow project URL (https://flow.google.com/project/<id>).' },
        name: { type: 'string', description: 'Project title to set.' },
        create_if_missing: { type: 'boolean', description: 'Create a new project when url is empty or gone.', default: true },
      },
    },
  },
  {
    name: 'flow_list_projects',
    description: 'List Flow projects from the Flow home page: [{ title, url }]. query filters titles. Free.',
    inputSchema: { type: 'object', properties: { query: { type: 'string', description: 'Only titles containing this text.' } } },
  },
  {
    name: 'flow_rename_project',
    description: 'Set the title of a Flow project. Returns { url, title }. PROJECT_NOT_FOUND if gone. Free.',
    inputSchema: { type: 'object', properties: { url: { type: 'string' }, name: { type: 'string' } }, required: ['url', 'name'] },
  },
  {
    name: 'flow_delete_project',
    description: '⚠️ PERMANENT. Deletes a Flow project with all its clips, ingredients and prompts. Only acts with confirm: true, which an agent must pass only after the user explicitly agreed to delete that project.',
    inputSchema: { type: 'object', properties: { url: { type: 'string' }, confirm: { type: 'boolean', default: false } }, required: ['url'] },
  },
  {
    name: 'flow_generate_video',
    description: 'Set up a video generation in Google Flow. Fills prompt, selects Omni Flash or Veo model, configures settings. NOTE: Does NOT click final Generate (paid feature — stops at ready-to-generate).',
    inputSchema: {
      type: 'object',
      properties: {
        prompt: { type: 'string', description: 'The text prompt for video generation.' },
        model: { type: 'string', description: 'Model: Omni Flash, Veo 2, Nano Banana 2.', default: 'Omni Flash' },
        ratio: { type: 'string', description: 'Aspect ratio: 16:9, 9:16, 1:1.', default: '16:9' },
        duration: { type: 'number', description: 'Target duration in seconds.', default: 5 },
        reference_images: { type: 'array', items: { type: 'string' }, description: 'Paths to reference images (optional).' },
        project_name: { type: 'string', description: 'Name for the project (will reuse existing project with same campaign, or create new).' },
        campaign: { type: 'string', description: 'Campaign identifier for project matching (e.g., "ete-2026", "nouvelle-collection").' },
      },
      required: ['prompt'],
    },
  },
  {
    name: 'flow_download_latest',
    description: 'Download the most recently generated file from Google Flow.',
    inputSchema: { type: 'object', properties: {} },
  },
  {
    name: 'flow_list_characters',
    description: 'List the characters in a Flow project (its Characters section): [{ name }]. details: true also opens each one and returns kind ("person" or "place"), info and url. Free.',
    inputSchema: {
      type: 'object',
      properties: {
        project_url: { type: 'string', description: 'Flow project URL.' },
        details: { type: 'boolean', default: false },
      },
      required: ['project_url'],
    },
  },
  {
    name: 'flow_create_character',
    description: 'Create a named character in a Flow project. With images: images[0] is a local file (uploaded) or the name of an image already in the project (e.g. "MD_02.jpg"); the character is that image and nothing is generated (free). With only a prompt: Flow generates a portrait, which spends credits, so it only runs with auto_confirm: true (otherwise returns ready_for_confirmation). An existing character with the same name is reused. info: the Character info the Flow agent reads.',
    inputSchema: {
      type: 'object',
      properties: {
        project_url: { type: 'string', description: 'Flow project URL.' },
        name: { type: 'string', description: 'Character name (how prompts refer to it).' },
        prompt: { type: 'string', description: 'Description to generate a portrait from (credits) when no images are given.' },
        images: { type: 'array', items: { type: 'string' }, description: 'Local image path or project image name. Only the first is used.' },
        info: { type: 'string', description: 'Character info (personality, look) for the Flow agent.' },
        format: { type: 'boolean', description: 'Press the Flow Format button first: rewrites the prompt into a studio portrait prompt (free).', default: false },
        auto_confirm: { type: 'boolean', description: '⚠️ CREDITS for prompt-only characters.', default: false },
        from_project_title: { type: 'string', description: 'Take images[0] from this other project (its title) through Add from project.' },
      },
      required: ['project_url', 'name'],
    },
  },
  {
    name: 'flow_import_character',
    description: 'Copy a character (or place) from another Flow project: downloads its portrait and creates a character with the same name and info in project_url. Flow cannot paste characters across projects. Free.',
    inputSchema: {
      type: 'object',
      properties: {
        project_url: { type: 'string', description: 'Target Flow project URL.' },
        from_project_url: { type: 'string', description: 'Source Flow project URL.' },
        name: { type: 'string', description: 'Character name in the source project.' },
      },
      required: ['project_url', 'from_project_url', 'name'],
    },
  },
  {
    name: 'flow_list_scenes',
    description: 'List the scenes (reusable places) in a Flow project: characters whose info marks them as a place. The Flow Scenes section holds video timelines and is not used. Free.',
    inputSchema: { type: 'object', properties: { project_url: { type: 'string' } }, required: ['project_url'] },
  },
  {
    name: 'flow_create_scene',
    description: 'Create a reusable place (the bunker, a street) as a Flow character marked as a place, so prompts can add it by name like a character. Same arguments as flow_create_character; images make it free, a prompt alone generates (credits, auto_confirm).',
    inputSchema: {
      type: 'object',
      properties: {
        project_url: { type: 'string' },
        name: { type: 'string' },
        prompt: { type: 'string' },
        images: { type: 'array', items: { type: 'string' } },
        info: { type: 'string', description: 'Description of the place.' },
        auto_confirm: { type: 'boolean', default: false },
        from_project_title: { type: 'string' },
      },
      required: ['project_url', 'name'],
    },
  },
  {
    name: 'flow_open_tools_gallery',
    description: 'Open the Google Flow Tools Gallery and list available tools.',
    inputSchema: { type: 'object', properties: {} },
  },
  {
    name: 'flow_use_grid_architect',
    description: 'Open Grid Architect in Google Flow, fill theme prompt, shot prompts, engine, ratio, and visual logic settings. Supports batch shot generation for brand campaigns.',
    inputSchema: {
      type: 'object',
      properties: {
        theme_prompt: { type: 'string', description: 'Overall theme prompt for the grid.' },
        shot_prompts: { type: 'array', items: { type: 'string' }, description: 'Array of individual shot prompts for the grid.' },
        engine: { type: 'string', description: 'Engine/model for the grid.', default: 'Nano Banana 2' },
        ratio: { type: 'string', description: 'Aspect ratio for all shots.', default: '16:9' },
        visual_logic: { type: 'string', description: 'Visual logic type: None, Colour Pop, Side by Side, etc.' },
        references: { type: 'array', items: { type: 'string' }, description: 'Paths to reference images.' },
        project_name: { type: 'string', description: 'Name for the project (will reuse existing project with same campaign, or create new).' },
        campaign: { type: 'string', description: 'Campaign identifier for project matching (e.g., "ete-2026", "nouvelle-collection").' },
      },
      required: ['theme_prompt'],
    },
  },
  {
    name: 'flow_use_tool',
    description: 'Open any tool by name in Google Flow and optionally fill its configuration parameters.',
    inputSchema: {
      type: 'object',
      properties: {
        tool_name: { type: 'string', description: 'Name of the tool to open (e.g. Grid Architect, Image Generation).' },
        params: { type: 'object', description: 'Optional configuration parameters for the tool.' },
        project_name: { type: 'string', description: 'Name for the project (will reuse existing project with same campaign, or create new).' },
        campaign: { type: 'string', description: 'Campaign identifier for project matching (e.g., "ete-2026", "nouvelle-collection").' },
      },
      required: ['tool_name'],
    },
  },
  {
    name: 'flow_screenshot',
    description: 'Take a screenshot of the current Google Flow page.',
    inputSchema: {
      type: 'object',
      properties: {
        name: { type: 'string', description: 'Custom name for the screenshot file.', default: 'manual' },
      },
    },
  },
  {
    name: 'flow_queue_status',
    description: 'Check the job queue: active job, pending queue, completed and failed job history.',
    inputSchema: {
      type: 'object',
      properties: {
        history_limit: { type: 'number', description: 'Number of recent history entries to return.', default: 5 },
      },
    },
  },
];

async function handleToolCall(name, args) {
  logger.info('Tool called', { tool: name, args: args ? JSON.stringify(args).substring(0, 200) : 'none' });

  switch (name) {
    case 'flow_connect': {
      const result = await launchKiaraProfile(args?.headless || false);
      if (result.browser) setBrowser(result.browser);
      const page = getPage();
      let oauthRequired = false;
      if (args?.open_flow !== false) {
        const navResult = await navigateToFlow(page);
        if (navResult && navResult.authenticated === false) {
          oauthRequired = true;
        }
      }
      const url = page.url();
      let accountCheck = null;
      try {
        accountCheck = await checkAccount(page);
      } catch (e) {
        accountCheck = { verified: false, error: e.message };
      }
      if (oauthRequired) {
        return { content: [{ type: 'text', text: JSON.stringify({
          status: 'oauth_required',
          message: 'Google Flow requires OAuth authentication. Open Chrome Profile 3 manually once:\n'
            + '  1. Launch: google-chrome --profile-directory="Profile 3"\n'
            + '  2. Navigate to: https://labs.google/fx/tools/flow/tools/grid-architect\n'
            + '  3. Complete the Google sign-in (one time)\n'
            + '  4. Retry this MCP tool in headless mode',
          browserType: 'Chrome Profile 3',
          account: accountCheck?.account || 'verified-account',
          url: page.url().substring(0, 100),
          accountVerified: accountCheck,
        }, null, 2) }] };
      }
      return { content: [{ type: 'text', text: JSON.stringify({
        status: 'connected',
        browserType: 'Chrome Profile 3',
        account: accountCheck?.account || 'verified-account',
        url: page.url(),
        accountVerified: accountCheck,
      }, null, 2) }] };
    }

    case 'flow_disconnect': {
      await closeBrowserConnection();
      return { content: [{ type: 'text', text: JSON.stringify({ status: 'disconnected' }) }] };
    }

    case 'flow_status': {
      const status = await handleFlowStatus();
      return { content: [{ type: 'text', text: JSON.stringify(status, null, 2) }] };
    }

    case 'flow_account_check': {
      const page = getPage();
      const result = await checkAccount(page);
      return { content: [{ type: 'text', text: JSON.stringify(result, null, 2) }] };
    }

    case 'flow_generate_image': {
      const result = await handleGenerateImage(args);
      return { content: [{ type: 'text', text: JSON.stringify(result, null, 2) }] };
    }

    case 'flow_open_project': {
      const result = await handleOpenProject(args || {});
      return { content: [{ type: 'text', text: JSON.stringify(result, null, 2) }] };
    }

    case 'flow_list_projects':
    case 'flow_rename_project':
    case 'flow_delete_project': {
      const fn = { flow_list_projects: handleListProjects, flow_rename_project: handleRenameProject, flow_delete_project: handleDeleteProject }[name];
      const result = await fn(args || {});
      return { content: [{ type: 'text', text: JSON.stringify(result, null, 2) }] };
    }

    case 'flow_generate_video': {
      const result = await handleGenerateVideo(args);
      return { content: [{ type: 'text', text: JSON.stringify(result, null, 2) }] };
    }

    case 'flow_download_latest': {
      const result = await handleDownloadLatest(args);
      return { content: [{ type: 'text', text: JSON.stringify(result, null, 2) }] };
    }

    case 'flow_list_characters':
    case 'flow_create_character':
    case 'flow_import_character':
    case 'flow_list_scenes':
    case 'flow_create_scene': {
      const fn = {
        flow_list_characters: handleListCharacters, flow_create_character: handleCreateCharacter,
        flow_import_character: handleImportCharacter, flow_list_scenes: handleListScenes, flow_create_scene: handleCreateScene,
      }[name];
      const result = await fn(args || {});
      return { content: [{ type: 'text', text: JSON.stringify(result, null, 2) }] };
    }

    case 'flow_open_tools_gallery': {
      const result = await handleOpenToolsGallery(args);
      return { content: [{ type: 'text', text: JSON.stringify(result, null, 2) }] };
    }

    case 'flow_use_grid_architect': {
      const result = await handleUseGridArchitect(args);
      return { content: [{ type: 'text', text: JSON.stringify(result, null, 2) }] };
    }

    case 'flow_use_tool': {
      const result = await handleUseFlowTool(args);
      return { content: [{ type: 'text', text: JSON.stringify(result, null, 2) }] };
    }

    case 'flow_screenshot': {
      const { getPage } = await import('./browser/connect.js');
      const page = getPage();
      const ss = await takeScreenshot(page, args?.name || 'manual');
      return { content: [{ type: 'text', text: JSON.stringify({ screenshot: ss, message: 'Screenshot saved.' }) }] };
    }

    case 'flow_queue_status': {
      return { content: [{ type: 'text', text: JSON.stringify(jobQueue.getStatus(args?.history_limit), null, 2) }] };
    }

    default:
      throw new McpError(ErrorCode.MethodNotFound, `Unknown tool: ${name}`);
  }
}

const server = new Server(
  { name: 'google-flow-browser-mcp', version: '1.0.0' },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: TOOL_DEFINITIONS,
}));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  try {
    return await handleToolCall(request.params.name, request.params.arguments);
  } catch (error) {
    logger.error('Tool execution error', { tool: request.params.name, error: error.message });
    if (error instanceof McpError) throw error;
    const message = error.message || 'Unknown error';
    const isBlocking = message.includes('MUST') || message.includes('cannot') || message.includes('blocked')
      || ['NOT_LOGGED_IN', 'MANUAL_VERIFICATION_REQUIRED', 'GOOGLE_LIMIT_REACHED', 'WRONG_GOOGLE_ACCOUNT'].includes(error.code);
    return {
      content: [{ type: 'text', text: JSON.stringify({
        error: true,
        message,
        code: isBlocking ? 'BLOCKING' : 'ERROR',
        error_code: error.code || null,
        needsManualIntervention: isBlocking,
      }, null, 2) }],
      isError: true,
    };
  }
});

const transport = new StdioServerTransport();
await server.connect(transport);
logger.info('Google Flow Browser MCP server running on stdio');

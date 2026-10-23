import { fileURLToPath } from 'url';
import path from 'path';
import fs from 'fs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const FLOW_HOME = path.resolve(__dirname, '..', '..');

// Config file: FLOW_MCP_CONFIG, else config/flow.config.json, else the example
// (the example holds working defaults, so a fresh checkout runs without a config).
const candidates = [
  process.env.FLOW_MCP_CONFIG,
  path.join(FLOW_HOME, 'config', 'flow.config.json'),
  path.join(FLOW_HOME, 'config', 'flow.config.example.json'),
].filter(Boolean);
const configPath = candidates.find((p) => fs.existsSync(p)) || candidates[0];
let config;

try {
  const raw = fs.readFileSync(configPath, 'utf-8');
  config = JSON.parse(raw);
} catch (err) {
  console.error(`[CONFIG] Failed to load config from ${configPath}: ${err.message}`);
  config = {};
}

// Environment overrides set by the host app (Labs Studio).
if (process.env.FLOW_CDP_PORT) config.cdpPort = Number(process.env.FLOW_CDP_PORT);
if (process.env.FLOW_CHROME_PATH) config.chromePath = process.env.FLOW_CHROME_PATH;
if (process.env.FLOW_CHROME_PROFILE_DIR) config.chromeProfileDir = process.env.FLOW_CHROME_PROFILE_DIR;
if (process.env.FLOW_DATA_DIR) config.dataDir = process.env.FLOW_DATA_DIR;
if (process.env.FLOW_EXPECTED_ACCOUNT !== undefined) config.expectedAccount = process.env.FLOW_EXPECTED_ACCOUNT;

export default config;

export function get(key, fallback = undefined) {
  return config[key] !== undefined ? config[key] : fallback;
}

export function getFlowHome() {
  return config.flowHome ? path.resolve(FLOW_HOME, config.flowHome) : FLOW_HOME;
}

// Where the server writes: projects file, outputs, logs, screenshots.
export function getDataDir() {
  return config.dataDir ? path.resolve(FLOW_HOME, config.dataDir) : getFlowHome();
}

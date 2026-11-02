import fs from 'fs';

const capabilities = JSON.parse(fs.readFileSync(new URL('../../config/capabilities.json', import.meta.url), 'utf8'));

export const getCapabilities = () => structuredClone(capabilities);

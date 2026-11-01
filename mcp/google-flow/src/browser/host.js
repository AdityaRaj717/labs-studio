// testHost: the fake Flow's host:port, by explicit option or FLOW_TEST_HOST. Never set outside tests.
export function isFlowHost(url, { testHost = process.env.FLOW_TEST_HOST } = {}) {
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    return false;
  }
  if (parsed.protocol === 'https:' && parsed.host === 'flow.google.com') return true;
  return Boolean(testHost) && parsed.host === testHost;
}

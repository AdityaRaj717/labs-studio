import { connect } from './mcp.mjs';
const { call, client } = await connect();
const s = await call('flow_status');
console.log('balance', s.balance, 'month', s.ledger?.monthTotal);
await client.close(); process.exit(0);

import { createError, ErrorCodes } from '../utils/errors.js';

const STAGES = ['reference', 'still', 'animation'];
const ACTIVE = ['generating', 'regenerating'];
const CAN_APPROVE = ['pending_review', 'approved', 'rejected', 'failed'];
const CAN_REJECT = ['pending_review', 'approved'];
const CAN_REGENERATE = CAN_APPROVE;
const COUNTED = ['planned', 'generating', 'pending_review', 'approved', 'rejected', 'regenerating', 'failed'];
const MAX_LISTED = 20; // keeps the concise status small whatever the Production's size

const conflict = (message, details) => createError(ErrorCodes.REVIEW_CONFLICT, message, details);

function newItem(row, stage, seq) {
  return {
    id: row.id,
    seq,
    stage,
    kind: row.kind,
    name: row.name ?? row.id,
    prompt: row.prompt,
    refs: row.refs ?? [],
    start: row.start ?? null,
    end: row.end ?? null,
    settings: row.settings,
    estimate: row.estimate ?? 0,
    state: 'planned',
    approved_take: null,
    takes: [],
    last_error: null,
  };
}

// reused: { <itemId>: { file, sha256 } }, already copied by the caller.
export function newProduction(plan, { id, runId, flowProjectUrl, maxCredits = null, gates, referenceMode = 'ingredient', reused = {}, at = null }) {
  const rows = [
    ...plan.references.map((row) => [row, 'reference']),
    ...plan.shots.filter(({ kind }) => kind === 'still').map((row) => [row, 'still']),
    ...plan.shots.filter(({ kind }) => kind === 'animation').map((row) => [row, 'animation']),
  ];
  const items = rows.map(([row, stage], i) => {
    const item = newItem(row, stage, i + 1);
    const from = reused[row.id];
    if (from) {
      item.state = 'approved';
      item.approved_take = 1;
      item.takes.push({
        n: 1, of_take: null, key: null, job_id: null, prompt: row.prompt, refs_used: [], start_used: null, end_used: null,
        status: 'done', file: from.file, original: null, sha256: from.sha256, audio_streams: null, quoted_credits: 0, credits_at_risk: false,
        verdict: 'approved', actor: 'reuse', at, note: null, from_state: 'planned',
      });
    }
    return item;
  });
  return {
    id,
    plan_id: plan.plan_id,
    run_id: runId,
    name: plan.name,
    mode: plan.mode,
    style: plan.style ?? null,
    ratio: plan.ratio,
    flow_project_url: flowProjectUrl ?? null,
    reference_mode: referenceMode,
    gates: { references: true, stills: true, ...gates },
    budget: { max_credits: maxCredits, spent: 0 },
    paused: null,
    cancelled: false,
    last_seq: 0,
    items,
  };
}

const itemOf = (production, id) => {
  const item = production.items.find((candidate) => candidate.id === id);
  if (!item) throw createError(ErrorCodes.ITEM_NOT_FOUND, `No item ${id}`, { item: id });
  return item;
};

const takeOf = (item, n) => {
  const take = item.takes.find((candidate) => candidate.n === n);
  if (!take) throw conflict(`${item.id} has no take ${n}`, { item: item.id, take: n });
  return take;
};

function activeTake(item, n, event) {
  const take = takeOf(item, n);
  if (take.status !== 'generating' || !ACTIVE.includes(item.state)) throw conflict(`${event} on ${item.id} take ${n}, which is ${take.status}, item ${item.state}`, { item: item.id, take: n });
  return take;
}

function startTake(production, { item: id, n, of_take = null, key, prompt, refs_used = [], start_used = null, end_used = null }) {
  const item = itemOf(production, id);
  const regenerating = CAN_REGENERATE.includes(item.state);
  if (item.state !== 'planned' && !regenerating) throw conflict(`${id} is ${item.state}, a take can't start`, { item: id, state: item.state });
  if (n !== item.takes.length + 1) throw conflict(`${id}: take ${n} is not the next one`, { item: id, take: n });
  item.takes.push({
    n, of_take, key, job_id: null, prompt: prompt ?? item.prompt, refs_used, start_used, end_used,
    status: 'generating', file: null, original: null, sha256: null, audio_streams: null, quoted_credits: 0, credits_at_risk: false,
    verdict: null, actor: null, at: null, note: null, from_state: item.state,
  });
  item.prompt = prompt ?? item.prompt;
  item.state = regenerating ? 'regenerating' : 'generating';
  item.last_error = null;
}

function reviewProblem(item, { take: n }, verdict) {
  const take = item.takes.find((candidate) => candidate.n === n);
  if (!take) return `no take ${n}`;
  if (take.status !== 'done') return `take ${n} is ${take.status}`;
  if (verdict === 'approved') {
    if (item.approved_take === n && item.state === 'approved') return null;
    return CAN_APPROVE.includes(item.state) ? null : `item is ${item.state}`;
  }
  if (take.verdict === 'rejected' && item.approved_take !== n && !ACTIVE.includes(item.state)) return null;
  return CAN_REJECT.includes(item.state) ? null : `item is ${item.state}`;
}

function review(production, { items, verdict, actor, note = null, at }) {
  // All checked first: one illegal Item changes nothing.
  const problems = items.flatMap((entry) => {
    const item = itemOf(production, entry.id);
    const reason = reviewProblem(item, entry, verdict);
    return reason ? [{ id: entry.id, take: entry.take, state: item.state, reason }] : [];
  });
  if (problems.length) throw conflict(`Can't ${verdict === 'approved' ? 'approve' : 'reject'}: ${problems.map(({ id, reason }) => `${id} ${reason}`).join('; ')}`, { items: problems });
  for (const { id, take: n } of items) {
    const item = itemOf(production, id);
    const take = takeOf(item, n);
    const repeat = take.verdict === verdict && (verdict === 'approved' ? item.approved_take === n && item.state === 'approved' : item.approved_take !== n);
    if (repeat) continue;
    Object.assign(take, { verdict, actor, at, note });
    if (verdict === 'approved') {
      item.approved_take = n;
      item.state = 'approved';
    } else {
      if (item.approved_take === n) item.approved_take = null;
      item.state = item.approved_take === null ? 'rejected' : 'approved';
    }
  }
}

const REDUCERS = {
  take_started: startTake,
  take_queued(production, { item, n, job_id }) {
    takeOf(itemOf(production, item), n).job_id = job_id;
  },
  take_done(production, { item: id, n, file, original = null, sha256 = null, audio_streams = null, quoted_credits }) {
    const item = itemOf(production, id);
    const take = activeTake(item, n, 'take_done');
    Object.assign(take, { status: 'done', file, original, sha256, audio_streams, quoted_credits: quoted_credits ?? take.quoted_credits });
    item.state = 'pending_review';
    item.last_error = null;
  },
  take_failed(production, { item: id, n, code, message, credits_at_risk = false, file = null }) {
    const item = itemOf(production, id);
    const take = activeTake(item, n, 'take_failed');
    Object.assign(take, { status: 'failed', credits_at_risk, file });
    item.state = item.state === 'regenerating' && item.approved_take !== null ? 'approved' : 'failed';
    item.last_error = { code, message, take: n };
  },
  take_aborted(production, { item: id, n, code = null }) {
    const item = itemOf(production, id);
    const take = activeTake(item, n, 'take_aborted');
    take.status = 'aborted';
    item.state = take.from_state;
    item.last_error = code ? { code, message: 'Stopped before it reached Flow', take: n } : null;
  },
  // attempt makes it safe to apply twice after a crash: one attempt, one spend.
  credits_spent(production, { item, n, credits, attempt = 1 }) {
    const take = takeOf(itemOf(production, item), n);
    if ((take.spent_attempt ?? 0) >= attempt) return;
    take.spent_attempt = attempt;
    take.quoted_credits = (take.quoted_credits ?? 0) + credits;
    production.budget.spent += credits;
  },
  reviewed: review,
  budget_set(production, { max_credits }) {
    production.budget.max_credits = max_credits;
  },
  estimate_set(production, { item, credits }) {
    itemOf(production, item).estimate = credits;
  },
  character_created(production, { item, take, name }) {
    Object.assign(itemOf(production, item), { character: { take, name } });
  },
  paused(production, { reason, code = null, quoted = null, estimate = null, item = null }) {
    production.paused = { reason, code, quoted, estimate, item };
  },
  resumed(production) {
    production.paused = null;
  },
  cancelled(production) {
    production.cancelled = true;
    production.paused = null;
  },
};

export function applyEvent(production, event) {
  const reducer = REDUCERS[event.type];
  if (!reducer) throw createError(ErrorCodes.INTERNAL_ERROR, `Unknown production event ${event.type}`);
  const next = structuredClone(production);
  reducer(next, event);
  return next;
}

const latestUsable = (item) => item.takes.filter(({ status, verdict }) => status === 'done' && verdict !== 'rejected').at(-1) ?? null;

// The Take of a dependency that counts now, or null.
function usable(production, id, gate) {
  const item = itemOf(production, id);
  if (item.approved_take !== null) return takeOf(item, item.approved_take);
  return gate ? null : latestUsable(item);
}

function depsOf({ gates }, item) {
  if (item.stage === 'animation' && item.start) {
    return { start: item.start, end: item.end, refs: [], gate: gates.stills };
  }
  return { start: null, end: item.stage === 'animation' ? item.end : null, refs: item.refs, gate: gates.references };
}

export function waitingOn(production, itemId) {
  const item = itemOf(production, itemId);
  const { start, end, refs, gate } = depsOf(production, item);
  const frameGate = production.gates.stills;
  return [
    ...refs.filter((id) => !usable(production, id, gate)),
    ...[start, end].filter((id) => id && !usable(production, id, frameGate)),
  ];
}

const used = (production, id, gate) => {
  const take = usable(production, id, gate);
  return { item: id, take: take.n, file: take.file };
};

export function depsFor(production, itemId) {
  const item = itemOf(production, itemId);
  const { start, end, refs, gate } = depsOf(production, item);
  const frameGate = production.gates.stills;
  return {
    refs_used: refs.map((id) => used(production, id, gate)),
    start_used: start ? used(production, start, frameGate) : null,
    end_used: end ? used(production, end, frameGate) : null,
  };
}

const runnable = (production) => production.items
  .filter((item) => item.state === 'planned' && waitingOn(production, item.id).length === 0)
  .sort((a, b) => STAGES.indexOf(a.stage) - STAGES.indexOf(b.stage) || a.seq - b.seq);

const anyActive = ({ items }) => items.some((item) => ACTIVE.includes(item.state));

export function nextItem(production) {
  if (production.paused || production.cancelled || anyActive(production)) return null;
  return runnable(production)[0]?.id ?? null;
}

// Information only: nothing here changes an Item.
export function staleItems(production) {
  return production.items.flatMap((item) => {
    if (item.approved_take === null) return [];
    const { refs_used: refs, start_used: start, end_used: end } = takeOf(item, item.approved_take);
    const because = [...refs, start, end].filter(Boolean).filter(({ item: dep, take }) => {
      const now = itemOf(production, dep).approved_take;
      return now !== null && now !== take;
    }).map(({ item: dep }) => dep);
    return because.length ? [{ item: item.id, because }] : [];
  });
}

function statusOf(production) {
  if (production.cancelled) return 'cancelled';
  if (production.paused) return 'paused';
  const { items } = production;
  if (items.length && items.every(({ state }) => state === 'approved')) return 'complete';
  if (anyActive(production) || runnable(production).length) return 'running';
  if (items.some(({ state }) => state === 'pending_review')) return 'waiting_review';
  return 'needs_action';
}

function nextAction(production, status) {
  const { items, paused } = production;
  if (status === 'paused') {
    if (paused.reason === 'quote_drift') return `Flow quoted ${paused.quoted} credits for ${paused.item}, above its estimate. flow_job_control resume with accept_quote: true proceeds at that price.`;
    if (paused.reason === 'budget') return `Flow quoted ${paused.quoted} credits for ${paused.item}, past max_credits. flow_job_control set_budget raises the cap.`;
    return 'Deal with the reason in paused, then flow_job_control resume with this run_id.';
  }
  if (status === 'waiting_review') return `Tell the owner ${items.filter(({ state }) => state === 'pending_review').length} items wait for review. Approve only when told to.`;
  if (status === 'needs_action') {
    const stuck = items.find(({ state }) => state === 'failed' || state === 'rejected');
    return stuck ? `${stuck.id} is ${stuck.state}. flow_production_regenerate retries it, with a new prompt if needed.` : 'Nothing can run. Check flow_production_status.';
  }
  if (status === 'running') return 'Wait with flow_wait on run_id.';
  return null;
}

export function summary(production) {
  const stages = Object.fromEntries(STAGES.map((stage) => {
    const items = production.items.filter((item) => item.stage === stage);
    const counts = Object.fromEntries(COUNTED.map((state) => [state, items.filter((item) => item.state === state).length]));
    return [stage, { total: items.length, ...counts }];
  }));
  const planned = production.items.filter(({ state }) => state === 'planned').reduce((sum, { estimate }) => sum + estimate, 0);
  const blocked = production.items.filter(({ state }) => state === 'planned').flatMap(({ id }) => waitingOn(production, id));
  const status = statusOf(production);
  return {
    status,
    paused: production.paused,
    stages,
    credits: { max: production.budget.max_credits, spent: production.budget.spent, planned },
    waiting_on: [...new Set(blocked)].slice(0, MAX_LISTED),
    stale: staleItems(production).slice(0, MAX_LISTED),
    next_action: nextAction(production, status),
  };
}

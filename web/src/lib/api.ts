/**
 * api.ts
 * ------
 * Typed client for the FastAPI control plane.
 *
 * The API lives on a separate host — a Next.js server cannot hold a trading
 * loop, and this app deliberately does not try. Every call sends credentials
 * so the HttpOnly session cookie travels with it.
 */

/**
 * Where to send calls.
 *
 * An **empty** value is meaningful and is not a missing one: it means the API
 * is reachable at this origin, because `next.config.ts` is rewriting `/api/*`
 * to it. `${BASE}${path}` then yields a relative URL. That mode exists so the
 * session cookie is first-party — see the `API_PROXY` note in `next.config.ts`
 * for why Safari and Firefox make it necessary.
 */
const BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }

  /** A 401 means the session lapsed; the UI redirects rather than retrying. */
  get isUnauthorized(): boolean {
    return this.status === 401;
  }

  /**
   * The request never reached the API. Status 0, because there was no
   * response to take one from.
   */
  get isUnreachable(): boolean {
    return this.status === 0;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers ?? {}),
      },
    });
  } catch {
    // `fetch` rejects with a bare `TypeError: Failed to fetch` for every
    // transport-level failure, and the browser deliberately withholds the
    // reason — a page must not be able to probe what it cannot reach.
    //
    // That message is the single most likely thing an operator sees after a
    // deploy, and on its own it is useless. The API host being down and CORS
    // rejecting the origin are indistinguishable from here, so name both,
    // along with the URL actually being called: "Failed to fetch" sends people
    // looking at their password, and the address bar is where the answer is.
    throw new ApiError(
      0,
      BASE === ""
        ? `Cannot reach the API through this site's /api proxy. The API is ` +
          `either down, or API_PROXY was set without NEXT_PUBLIC_API_BASE ` +
          `naming it, so the rewrite has nowhere to forward to.`
        : `Cannot reach the API at ${BASE}. Either it is not running, or its ` +
          `CORS_ORIGINS does not include this page's origin ` +
          `(${typeof window === "undefined" ? "unknown" : window.location.origin}).`,
    );
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* response had no JSON body; statusText is the best we have */
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

// ---------------------------------------------------------------------------
// Types — mirror src/api/schemas.py
// ---------------------------------------------------------------------------

export interface StrategyDescriptor {
  name: string;
  version: string;
  description: string;
  source: string;
  universe: string[];
  warmup_sessions: number;
  params: Record<string, unknown>;
  params_schema: JsonSchema;
  /** Multiple-testing counter: how many times these dice have been rolled. */
  backtest_count: number;
}

export interface JsonSchema {
  properties?: Record<string, JsonSchemaProperty>;
  required?: string[];
  [key: string]: unknown;
}

export interface JsonSchemaProperty {
  type?: string;
  title?: string;
  description?: string;
  default?: unknown;
  minimum?: number;
  maximum?: number;
  exclusiveMinimum?: number;
  exclusiveMaximum?: number;
  items?: { type?: string };
  enum?: unknown[];
}

export type PortfolioMode = "paper" | "live";

/**
 * A live account snapshot.
 *
 * Every money field is nullable, and that is load-bearing: the API returns
 * null rather than 0 when no marks exist. Zero equity and unknown equity are
 * different states, and a UI that renders the second as the first shows a flat
 * line at zero where it should say "no data".
 */
export interface Portfolio {
  mode: PortfolioMode;
  as_of: string | null;
  equity: number | null;
  cash: number | null;
  daily_pnl: number | null;
  cumulative_pnl: number | null;
  drawdown_pct: number | null;
  peak_equity: number | null;
  positions: PortfolioPosition[];
  note?: string;
}

export interface PortfolioPosition {
  symbol: string;
  qty: number;
  /** Average *purchase* price, not a mark — the API does not know a current price. */
  avg_entry_price: number | null;
}

export interface PortfolioMark {
  session: string;
  equity: number;
  cash: number;
  daily_pnl: number;
  cumulative_pnl: number;
  drawdown_pct: number;
}

export interface PortfolioHistory {
  mode: PortfolioMode;
  count: number;
  marks: PortfolioMark[];
}

export interface BacktestMetrics {
  start: string | null;
  end: string | null;
  n_sessions: number;
  initial_equity: number;
  total_return: number;
  cagr: number;
  volatility: number;
  sharpe: number;
  sharpe_stderr: number;
  sharpe_is_significant: boolean;
  sortino: number;
  max_drawdown: number;
  /** When the worst drawdown began and ended — depth without dates cannot
   * answer "was that 2008, or was that us?". */
  max_drawdown_start: string | null;
  max_drawdown_end: string | null;
  calmar: number;
  exposure: number;
  n_rebalances: number;
  n_fills: number;
  total_commission: number;
  turnover_annual: number;
  final_equity: number;
  /** First session the whole universe existed. Metrics before it are not the strategy. */
  effective_start: string | null;
  cost_stress_multiplier: number;
  /** Sessions per year used to annualise. 252 = NYSE; a 24/7 venue is 365. */
  periods_per_year: number;
}

export interface BacktestRun {
  id: string;
  strategy_name: string;
  strategy_version: string;
  params: Record<string, unknown>;
  universe: string[];
  start_session: string;
  end_session: string;
  initial_cash: number;
  data_source: string;
  cost_model: Record<string, number>;
  decision_lag_sessions: number;
  engine_version: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  metrics: BacktestMetrics | null;
  error: string | null;
  created_at: string | null;
  finished_at: string | null;
}

export interface EquityPoint {
  session: string;
  equity: number;
  cash: number;
  drawdown_pct: number;
}

export interface BacktestOrder {
  session: string;
  symbol: string;
  side: string;
  qty: number;
  price: number;
  notional: number;
  commission: number;
  reason: string;
}

export interface SystemStatus {
  trading_enabled: boolean;
  kill_reason: string | null;
  updated_by: string;
  updated_at: string | null;
  live_trading_enabled: boolean;
  /** The third, independent gate. */
  alpaca_allow_live: boolean;
  broker_configured: boolean;
  jobs: Record<string, number>;
  /**
   * Heartbeat rows. `status` is the *stored* value and is only ever written as
   * 'alive', so it says nothing about liveness on its own — a row outlives the
   * process that wrote it. Use `stale`, which the API derives from the
   * heartbeat's age against the database clock.
   */
  workers: {
    worker_id: string;
    last_seen: string;
    status: string;
    age_seconds: number;
    stale: boolean;
  }[];
  database_ok: boolean;
}

export interface JobSummary {
  id: string;
  kind: string;
  status: string;
  attempts: number;
  max_attempts: number;
  error: string | null;
  created_at: string | null;
  finished_at: string | null;
}

export interface CreateBacktestBody {
  strategy: string;
  params?: Record<string, unknown>;
  start?: string;
  end?: string;
  initial_cash?: number;
  data_source?: string;
  slippage_bps?: number;
  cost_stress?: number;
  min_trade_usd?: number;
  max_weight_per_asset?: number;
}

// ---------------------------------------------------------------------------
// The AI programme
// ---------------------------------------------------------------------------

/**
 * One configuration item from the operating prompt's section 2.
 *
 * `value` is nullable and the null is load-bearing: it means TBD, and the UI
 * renders it as TBD rather than blank or zero. A value nobody supplied is
 * never invented, at any layer.
 */
export interface ProgrammeConfigItem {
  key: string;
  value: string | null;
  is_critical: boolean;
  notes: string;
  updated_by: string;
  updated_at: string | null;
}

export interface ProgrammeConfig {
  items: ProgrammeConfigItem[];
  critical_unknowns: string[];
  unknowns: string[];
}

/** Where a criterion's answer came from. Absent means the criterion is unmet. */
export interface GateEvidence {
  table: string;
  row_id: string;
  value: unknown;
}

export interface GateCriterion {
  id: string;
  description: string;
  met: boolean;
  detail: string;
  evidence: GateEvidence | null;
}

/**
 * A gate's verdict.
 *
 * `requires_human` is not a UI preference. Stage 5 is canary production, the
 * first stage at which the programme's own decision exposes capital, and the
 * operating prompt forbids a model from changing capital allocation.
 */
export interface GateResult {
  from_stage: number;
  to_stage: number;
  from_stage_name: string;
  to_stage_name: string;
  passed: boolean;
  requires_human: boolean;
  criteria: GateCriterion[];
}

export interface Hypothesis {
  id: string;
  ref: string;
  title: string;
  owner: string;
  card: Record<string, string>;
  status: "open" | "accepted" | "rejected" | "superseded";
  parent_ref: string | null;
  /** Multiple-testing counter: how many configurations this idea has spawned. */
  variants_tried: number;
  origin: "model" | "operator";
  model: string;
  decision: string | null;
  decision_rationale: string;
  created_at: string;
  decided_at: string | null;
  candidates?: Candidate[];
}

export interface Candidate {
  id: string;
  hypothesis_id: string;
  hypothesis_ref: string;
  hypothesis_title: string;
  hypothesis_origin: "model" | "operator";
  strategy_name: string;
  params: Record<string, unknown>;
  universe: string[];
  start_session: string;
  end_session: string;
  data_source: string;
  stage: number;
  stage_name?: string;
  stage_entered_at: string;
  status: "active" | "held" | "rejected" | "retired";
  /** Set by any synthetic-sourced evidence, never cleared. Gate 2→3 refuses it. */
  evidence_is_synthetic: boolean;
  deployment_id: string | null;
  notes: string;
  created_at: string;
  experiments?: Experiment[];
  gate?: GateResult | null;
}

export interface Experiment {
  id: string;
  ref: string;
  hypothesis_id: string;
  candidate_id: string;
  kind: string;
  code_commit: string;
  dataset_manifest: Record<string, unknown>;
  seed: number | null;
  universe: string[];
  cost_assumptions: Record<string, unknown>;
  /** Fixed before the run and immutable after. Rendered above the outcome. */
  preregistered_criteria: { metric: string; op: string; value: number }[];
  backtest_run_id: string | null;
  walkforward_run_id: string | null;
  status: string;
  outcome: Record<string, unknown>;
  conclusion: "pass" | "fail" | "inconclusive" | null;
  error: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface ProgrammeRun {
  id: string;
  trigger: "scheduled" | "manual";
  status: string;
  actions: Record<string, unknown>[];
  model: string;
  error: string | null;
  requested_by: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

/**
 * A defect on the record.
 *
 * Whether it *blocks* is not a field: it is `status === "open"` and a blocking
 * severity and a role holding a veto, and the API returns those two vocabularies
 * alongside the list so the page applies the same rule the gate does rather
 * than a copy of it that can drift.
 */
export interface Finding {
  id: string;
  ref: string;
  candidate_id: string | null;
  raised_by: string;
  severity: "low" | "medium" | "high" | "critical";
  title: string;
  detail_md: string;
  remediation: string;
  status: "open" | "remediated" | "accepted" | "withdrawn";
  opened_at: string;
  closed_at: string | null;
  closed_by: string | null;
  close_note: string;
}

export interface RoleDescriptor {
  key: string;
  title: string;
  holds_veto: boolean;
}

export interface FindingsPage {
  findings: Finding[];
  veto_roles: string[];
  blocking_severities: string[];
  roles: RoleDescriptor[];
}

/** One specialist's view. Commentary: nothing here is read by a gate. */
export interface RoleAssessment {
  id: number;
  role: string;
  verdict: "support" | "concern" | "object" | "abstain";
  summary: string;
  evidence: Record<string, unknown>;
  stage: number;
  model: string;
  created_at: string;
}

/**
 * One shadow session.
 *
 * `equity` is the derived book's value, not a P&L. The opening balance is a
 * fixed notional and the window is weeks, so a return computed from it would
 * carry a standard error several times its own size.
 */
export interface ShadowSession {
  session: string;
  rebalanced: boolean;
  target_weights: Record<string, number>;
  order_intents: Record<string, unknown>[];
  risk_events: Record<string, unknown>[];
  rationale: string;
  equity: number | null;
  /** Buys the simulated venue trimmed. A real venue rejects these outright. */
  underfunded: Record<string, unknown>[];
  error: string | null;
  created_at: string;
}

export interface ShadowHistory {
  sessions: ShadowSession[];
  required: number;
}

export interface ProgrammeStatus {
  enabled: boolean;
  /** Already clamped and fail-closed by the API; render it as authoritative. */
  max_auto_stage: number;
  autonomy_hard_cap: number;
  open_findings: number;
  blocking_findings: number;
  runner: {
    last_seen: string;
    status: string;
    age_seconds: number;
    stale: boolean;
  } | null;
  last_run: ProgrammeRun | null;
  critical_unknowns: string[];
  unknown_count: number;
}

export interface PipelineBoard {
  stages: { stage: number; name: string }[];
  first_human_gated_stage: number;
  candidates: Candidate[];
}

// ---------------------------------------------------------------------------
// Calls
// ---------------------------------------------------------------------------

export const api = {
  login: (password: string) =>
    request<{ token: string; expires_in: number }>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ password }),
    }),

  logout: () => request<{ status: string }>("/api/v1/auth/logout", { method: "POST" }),

  me: () => request<{ subject: string; expires_at: number }>("/api/v1/auth/me"),

  strategies: () => request<StrategyDescriptor[]>("/api/v1/strategies"),

  strategy: (name: string) =>
    request<StrategyDescriptor>(`/api/v1/strategies/${encodeURIComponent(name)}`),

  createBacktest: (body: CreateBacktestBody) =>
    request<{ run_id: string; job_id: string; status: string }>("/api/v1/backtests", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  backtests: (params?: { strategy?: string; status?: string; limit?: number }) => {
    const query = new URLSearchParams();
    if (params?.strategy) query.set("strategy", params.strategy);
    if (params?.status) query.set("status", params.status);
    if (params?.limit) query.set("limit", String(params.limit));
    const suffix = query.toString() ? `?${query}` : "";
    return request<BacktestRun[]>(`/api/v1/backtests${suffix}`);
  },

  backtest: (id: string) => request<BacktestRun>(`/api/v1/backtests/${id}`),

  equity: (id: string) => request<EquityPoint[]>(`/api/v1/backtests/${id}/equity`),

  orders: (id: string) => request<BacktestOrder[]>(`/api/v1/backtests/${id}/orders`),

  portfolio: (mode: PortfolioMode = "paper") =>
    request<Portfolio>(`/api/v1/portfolio?mode=${mode}`),

  portfolioHistory: (mode: PortfolioMode = "paper") =>
    request<PortfolioHistory>(`/api/v1/portfolio/history?mode=${mode}`),

  systemStatus: () => request<SystemStatus>("/api/v1/system/status"),

  kill: (reason: string) =>
    request<SystemStatus>("/api/v1/system/kill", {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),

  resume: (note: string) =>
    request<SystemStatus>("/api/v1/system/resume", {
      method: "POST",
      // The API requires this exact string. Re-enabling trading should be a
      // deliberate act, not a toggle.
      body: JSON.stringify({ confirm: "ENABLE TRADING", note }),
    }),

  jobs: (status?: string) =>
    request<JobSummary[]>(`/api/v1/system/jobs${status ? `?status=${status}` : ""}`),

  /**
   * Ask the API to run queued research jobs itself.
   *
   * Only does anything on a deployment with no worker process — a serverless
   * host, where nothing long-lived can exist and a submitted backtest would
   * otherwise stay queued indefinitely. Anywhere a worker runs, the endpoint
   * answers 404 and the worker has already picked the job up.
   *
   * Callers should treat every failure as uninteresting: this is a nudge, not
   * a dependency, and the page it is called from works without it.
   */
  drain: () => request<{ ran: number }>("/api/v1/system/drain", { method: "POST" }),

  // -------------------------------------------------------------------------
  // The AI programme
  //
  // POST rather than PUT for the two mutations that would read better as PUT.
  // The API's CORS policy allows GET, POST, DELETE and OPTIONS, and this app
  // is deployed to a different origin from the API, so a PUT would be refused
  // at the browser's preflight and would fail only in production.
  // -------------------------------------------------------------------------

  programmeStatus: () =>
    request<ProgrammeStatus>("/api/v1/programme/status"),

  setProgrammeEnabled: (enabled: boolean, reason: string, confirm = "") =>
    request<ProgrammeStatus>("/api/v1/programme/enabled", {
      method: "POST",
      body: JSON.stringify({ enabled, reason, confirm }),
    }),

  requestTick: () =>
    request<{ run_id: string; status: string }>("/api/v1/programme/tick", {
      method: "POST",
    }),

  programmeRuns: (limit = 20) =>
    request<ProgrammeRun[]>(`/api/v1/programme/runs?limit=${limit}`),

  programmeConfig: () => request<ProgrammeConfig>("/api/v1/programme/config"),

  setProgrammeConfig: (values: Record<string, string>) =>
    request<ProgrammeConfig>("/api/v1/programme/config", {
      method: "POST",
      body: JSON.stringify({ values }),
    }),

  hypotheses: (status?: string) =>
    request<Hypothesis[]>(
      `/api/v1/programme/hypotheses${status ? `?status=${status}` : ""}`,
    ),

  hypothesis: (ref: string) =>
    request<Hypothesis>(`/api/v1/programme/hypotheses/${ref}`),

  pipeline: () => request<PipelineBoard>("/api/v1/programme/candidates"),

  candidate: (id: string) =>
    request<Candidate>(`/api/v1/programme/candidates/${id}`),

  gate: (id: string) =>
    request<GateResult>(`/api/v1/programme/candidates/${id}/gate`),

  /**
   * Confirm a promotion the gate has already passed.
   *
   * Answers 409 with the unmet criteria when it has not. The operator cannot
   * override a failed gate from here, and the API would refuse if this tried.
   */
  promote: (id: string, rationale: string) =>
    request<{ candidate_id: string; stage: number; stage_name: string }>(
      `/api/v1/programme/candidates/${id}/promote`,
      { method: "POST", body: JSON.stringify({ confirm: "PROMOTE", rationale }) },
    ),

  rejectCandidate: (id: string, rationale: string) =>
    request<{ status: string }>(`/api/v1/programme/candidates/${id}/reject`, {
      method: "POST",
      body: JSON.stringify({ rationale }),
    }),

  holdCandidate: (id: string, rationale: string) =>
    request<{ status: string }>(`/api/v1/programme/candidates/${id}/hold`, {
      method: "POST",
      body: JSON.stringify({ rationale }),
    }),

  experiment: (ref: string) =>
    request<Experiment>(`/api/v1/programme/experiments/${ref}`),

  findings: (params?: { candidateId?: string; onlyOpen?: boolean }) => {
    const query = new URLSearchParams();
    if (params?.candidateId) query.set("candidate_id", params.candidateId);
    if (params?.onlyOpen) query.set("only_open", "true");
    const suffix = query.toString() ? `?${query}` : "";
    return request<FindingsPage>(`/api/v1/programme/findings${suffix}`);
  },

  raiseFinding: (body: {
    candidate_id?: string | null;
    raised_by: string;
    severity: string;
    title: string;
    detail?: string;
    remediation?: string;
  }) =>
    request<{ id: string; ref: string }>("/api/v1/programme/findings", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  /**
   * Close a finding. The only route by which one is ever closed — the schema
   * refuses any `closed_by` that does not name an operator, and this endpoint
   * is the only code that produces one.
   */
  closeFinding: (ref: string, status: string, note: string) =>
    request<{ ref: string; status: string; closed_by: string }>(
      `/api/v1/programme/findings/${ref}/close`,
      { method: "POST", body: JSON.stringify({ status, note }) },
    ),

  shadow: (candidateId: string) =>
    request<ShadowHistory>(`/api/v1/programme/candidates/${candidateId}/shadow`),

  assessments: (candidateId: string) =>
    request<RoleAssessment[]>(
      `/api/v1/programme/candidates/${candidateId}/assessments`,
    ),

  setAutonomy: (maxAutoStage: number, reason: string, confirm = "") =>
    request<{ requested: number; effective: number; hard_cap: number }>(
      "/api/v1/programme/autonomy",
      {
        method: "POST",
        body: JSON.stringify({
          max_auto_stage: maxAutoStage,
          reason,
          confirm,
        }),
      },
    ),
};

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------

export const fmtPct = (value: number, digits = 2) =>
  `${(value * 100).toFixed(digits)}%`;

export const fmtUsd = (value: number) =>
  value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  });

export const fmtNum = (value: number, digits = 3) => value.toFixed(digits);

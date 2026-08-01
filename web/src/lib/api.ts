/**
 * api.ts
 * ------
 * Typed client for the FastAPI control plane.
 *
 * The API lives on a separate host — a Next.js server cannot hold a trading
 * loop, and this app deliberately does not try. Every call sends credentials
 * so the HttpOnly session cookie travels with it.
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
      `Cannot reach the API at ${BASE}. Either it is not running, or its ` +
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

"""
schemas.py
----------
Request and response models.

These are the contract the frontend generates its TypeScript client from, so
field names here become field names there. Response models carry the honesty
fields — ``effective_start``, ``sharpe_stderr``, ``cost_stress_multiplier``,
``backtest_count`` — because a UI can only display what the API sends, and a
Sharpe delivered without its error bar will be read as a fact.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field, field_validator

from src.db.repos.backtests import DEFAULT_COST_MODEL


class LoginRequest(BaseModel):
    password: str = Field(min_length=1)


class LoginResponse(BaseModel):
    token: str
    expires_in: int


class StrategyDescriptor(BaseModel):
    name: str
    version: str
    description: str
    source: str
    universe: list[str]
    warmup_sessions: int
    params: dict[str, Any]
    params_schema: dict[str, Any]
    #: How many backtests this strategy has accumulated — a multiple-testing
    #: counter, shown so the research loop cannot quietly launder noise.
    #: Required: a builder that forgot to count would otherwise report that no
    #: dice had been rolled, the most flattering count there is.
    backtest_count: int


class CreateBacktestRequest(BaseModel):
    strategy: str
    params: dict[str, Any] = Field(default_factory=dict)
    start: date = date(1999, 1, 1)
    end: date | None = None
    initial_cash: float = Field(default=100_000.0, gt=0)
    data_source: str = "synthetic"
    #: The cost defaults are the worker's own (``DEFAULT_COST_MODEL``), so a
    #: request that names none is recorded and run at the same values as one
    #: the programme queues.
    slippage_bps: float = Field(
        default=DEFAULT_COST_MODEL["slippage_bps"], ge=0, le=500
    )
    #: Re-run at 3x and check the sign does not flip before trusting a result.
    cost_stress: float = Field(
        default=DEFAULT_COST_MODEL["stress_multiplier"], ge=0.0, le=20.0
    )
    min_trade_usd: float = Field(default=DEFAULT_COST_MODEL["min_trade_usd"], ge=0)
    max_weight_per_asset: float = Field(
        default=DEFAULT_COST_MODEL["max_weight_per_asset"], gt=0, le=1.0
    )

    @field_validator("data_source")
    @classmethod
    def _known_source(cls, value: str) -> str:
        allowed = {"synthetic", "yfinance"}
        if value not in allowed:
            raise ValueError(f"data_source must be one of {sorted(allowed)}")
        return value


class CreateBacktestResponse(BaseModel):
    run_id: str
    job_id: str
    status: str


class BacktestMetrics(BaseModel):
    """
    A run's figures, as the engine stored them and nothing else.

    Every field is nullable and defaults to ``None``. The engine writes the
    whole set for a run it finishes (``PerformanceMetrics.to_dict``), so on a
    current row no default fires; they are for a row without the key — written
    by an older engine, or by hand — and for that row there is nothing to
    report. The API reported something anyway: 252 sessions a year, no fills, a
    Sharpe of 0.0 with a standard error of 0.0, costs at 1x. Each was a
    measurement nobody made, served in the shape of one, and a page cannot
    render "not measured" for a value it was handed as a number (CLAUDE.md: an
    unmeasured metric is never zero; a genuine zero stays a zero, and arrives
    as one). ``tests/integration/test_unmeasured_is_null.py`` serves such a row;
    ``tests/unit/test_metrics_contract.py`` holds the page's types to this.
    """

    start: str | None = None
    end: str | None = None
    n_sessions: int | None = None
    initial_equity: float | None = None
    total_return: float | None = None
    cagr: float | None = None
    volatility: float | None = None
    sharpe: float | None = None
    sharpe_stderr: float | None = None
    #: The engine's own verdict, ``PerformanceMetrics.sharpe_is_significant``.
    #: ``None`` is not ``False``: "not significant" is a finding about a
    #: measured Sharpe, and there may be no Sharpe to find it about.
    sharpe_is_significant: bool | None = None
    sortino: float | None = None
    max_drawdown: float | None = None
    #: When the worst drawdown began and ended. A research UI that shows the
    #: depth but not the dates cannot answer "was that 2008 or was that us?".
    max_drawdown_start: str | None = None
    max_drawdown_end: str | None = None
    calmar: float | None = None
    exposure: float | None = None
    n_rebalances: int | None = None
    #: Every fill the run made; the capped ``/orders`` page is a slice of it.
    n_fills: int | None = None
    total_commission: float | None = None
    turnover_annual: float | None = None
    final_equity: float | None = None
    #: First session the whole universe was tradeable. A Sharpe measured before
    #: this is not the Sharpe of the strategy.
    effective_start: str | None = None
    #: The cost assumption the figures were produced under. Never supplied
    #: here: 1x for a row that does not say is the cheapest cost the system
    #: runs, so the guess that flatters every figure beside it.
    cost_stress_multiplier: float | None = None
    #: Sessions per year used to annualise. 252 is the NYSE year; a venue that
    #: never closes has 365. Quoting an annualised figure without it is one of
    #: the honesty rules, so the field has to survive serialisation — pydantic
    #: drops anything it does not declare, which is how it went missing between
    #: the engine computing it and the API returning it. Nor is it guessed: 252
    #: for a row that does not say asserts the NYSE year of a run nobody asked,
    #: and for a venue that never closes moves volatility and the Sharpe by
    #: about a fifth.
    periods_per_year: int | None = None


class BacktestRun(BaseModel):
    id: str
    strategy_name: str
    strategy_version: str
    params: dict[str, Any]
    universe: list[str]
    start_session: str
    end_session: str
    initial_cash: float
    data_source: str
    cost_model: dict[str, Any]
    decision_lag_sessions: int
    engine_version: str
    status: str
    metrics: BacktestMetrics | None = None
    error: str | None = None
    created_at: str | None = None
    finished_at: str | None = None

    @property
    def is_synthetic(self) -> bool:
        return self.data_source == "synthetic"


class EquityPoint(BaseModel):
    session: str
    equity: float
    cash: float
    drawdown_pct: float


class BacktestOrder(BaseModel):
    session: str
    symbol: str
    side: str
    qty: float
    price: float
    notional: float
    commission: float
    reason: str


class VenueCancel(BaseModel):
    """
    The kill switch's cancel at the venue, for the stop in force.

    ``status`` is the job's — ``queued``, ``running``, ``succeeded`` or
    ``failed`` — or ``not_queued`` when this stop has none: engaged before the
    switch learned to cancel, or the queue refused it. A queued job with an
    ``error`` failed an attempt and is waiting to try again.
    """

    status: str
    requested_at: str | None = None
    finished_at: str | None = None
    attempts: int = 0
    max_attempts: int = 0
    error: str | None = None
    #: Per venue, set on success: ``mode`` and ``reached``; for a venue
    #: reached, ``cancelled`` (the cancels the last attempt made — earlier
    #: attempts are in the audit log), ``still_open`` (this system's orders,
    #: empty on success) and ``foreign_open`` (orders it did not place, left
    #: alone); for one not reached, the ``reason``.
    venues: list[dict[str, Any]] = Field(default_factory=list)


class SystemStatus(BaseModel):
    trading_enabled: bool
    kill_reason: str | None = None
    updated_by: str = ""
    updated_at: str | None = None
    #: The environment-level gate. Both this and ``trading_enabled`` must be
    #: true before a live order can be placed.
    live_trading_enabled: bool = False
    #: The third, independent gate. Reported separately because an operator who
    #: sees only LIVE_TRADING_ENABLED would reasonably conclude that flipping
    #: it is sufficient — which is exactly the misunderstanding this gate
    #: exists to prevent.
    alpaca_allow_live: bool = False
    broker_configured: bool = False
    jobs: dict[str, int] = Field(default_factory=dict)
    workers: list[dict[str, Any]] = Field(default_factory=list)
    database_ok: bool = True
    #: Set while the switch is engaged, and ``None`` while trading is enabled:
    #: what became of the cancel this stop queued at the venue.
    venue_cancel: VenueCancel | None = None


class KillSwitchRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class ReleaseKillSwitchRequest(BaseModel):
    #: Must be the literal string below. Re-enabling trading should be a
    #: deliberate act, not a misclick on a toggle.
    confirm: str
    note: str = ""

    @field_validator("confirm")
    @classmethod
    def _must_confirm(cls, value: str) -> str:
        if value != "ENABLE TRADING":
            raise ValueError(
                "confirm must be exactly 'ENABLE TRADING' to re-enable trading"
            )
        return value


class SystemConfigurationRequest(BaseModel):
    """
    The five settings that decide what the programme sends and how often.

    ``extra="forbid"`` for the same reason ``RiskLimitsRequest`` forbids unknown
    keys: a mistyped field that is silently dropped leaves the operator looking
    at a page that says their change was saved and a runner that never saw it.

    Every field is required. A partial update would mean validating one setting
    against four stored ones, and the validity of ``effort`` depends on which
    model is chosen — so the four have to be checked as a set or not at all.
    Nothing here is range-checked by pydantic on purpose: the rules live in
    ``src.programme.models`` because the runner applies exactly the same ones
    when it reads the row back, and two copies of a rule is one copy too many.
    """

    model_config = {"extra": "forbid"}

    provider: str
    model: str
    effort: str
    max_tokens: int
    tick_seconds: int


class SetSecretRequest(BaseModel):
    """
    A credential, on its way in and never on its way out.

    ``extra="forbid"`` and a single field, so there is no shape in which a
    caller can smuggle a second value alongside the one being stored.

    No ``max_length``: a vendor decides how long its tokens are and a ceiling
    guessed here would reject a valid credential for no reason. The minimum
    exists because an empty secret is a cleared secret, and clearing has its own
    endpoint — a blank submission is far more likely to be a mistyped paste than
    an intention, and storing it would leave a row that reads as configured.
    """

    model_config = {"extra": "forbid"}

    value: str = Field(min_length=1)


class JobSummary(BaseModel):
    id: str
    kind: str
    status: str
    attempts: int
    max_attempts: int
    error: str | None = None
    created_at: str | None = None
    finished_at: str | None = None

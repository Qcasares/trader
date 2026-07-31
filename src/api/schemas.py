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
    backtest_count: int = 0


class CreateBacktestRequest(BaseModel):
    strategy: str
    params: dict[str, Any] = Field(default_factory=dict)
    start: date = date(1999, 1, 1)
    end: date | None = None
    initial_cash: float = Field(default=100_000.0, gt=0)
    data_source: str = "synthetic"
    slippage_bps: float = Field(default=5.0, ge=0, le=500)
    #: Re-run at 3x and check the sign does not flip before trusting a result.
    cost_stress: float = Field(default=1.0, ge=0.0, le=20.0)
    min_trade_usd: float = Field(default=25.0, ge=0)
    max_weight_per_asset: float = Field(default=1.0, gt=0, le=1.0)

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
    start: str | None = None
    end: str | None = None
    n_sessions: int = 0
    total_return: float = 0.0
    cagr: float = 0.0
    volatility: float = 0.0
    sharpe: float = 0.0
    sharpe_stderr: float = 0.0
    sharpe_is_significant: bool = False
    sortino: float = 0.0
    max_drawdown: float = 0.0
    calmar: float = 0.0
    exposure: float = 0.0
    n_rebalances: int = 0
    n_fills: int = 0
    total_commission: float = 0.0
    turnover_annual: float = 0.0
    final_equity: float = 0.0
    #: First session the whole universe was tradeable. A Sharpe measured before
    #: this is not the Sharpe of the strategy.
    effective_start: str | None = None
    cost_stress_multiplier: float = 1.0


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


class SystemStatus(BaseModel):
    trading_enabled: bool
    kill_reason: str | None = None
    updated_by: str = ""
    updated_at: str | None = None
    #: The environment-level gate. Both this and ``trading_enabled`` must be
    #: true before a live order can be placed.
    live_trading_enabled: bool = False
    broker_configured: bool = False
    jobs: dict[str, int] = Field(default_factory=dict)
    workers: list[dict[str, Any]] = Field(default_factory=list)
    database_ok: bool = True


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


class JobSummary(BaseModel):
    id: str
    kind: str
    status: str
    attempts: int
    max_attempts: int
    error: str | None = None
    created_at: str | None = None
    finished_at: str | None = None

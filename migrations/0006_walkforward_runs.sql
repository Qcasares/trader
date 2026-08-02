-- 0006_walkforward_runs.sql
--
-- Persist walk-forward studies, so "walk-forward before deployment" can be
-- checked rather than merely recommended.
--
-- The plan lists walk-forward as the mitigation for its risk 7 — that a
-- research UI is an overfitting machine, and edit-params/rerun/look-at-Sharpe
-- is precisely how people fool themselves. The engine implemented the study
-- and the CLI could run it, but nothing stored the result, so the deployment
-- gate had nothing to consult and the mitigation existed only as advice.
--
-- What is stored is deliberately the *judgement*, not just the numbers:
-- `is_robust` is the study's own verdict, and `degradation` is the headline —
-- how much performance evaporated once parameters had to be chosen in advance.
-- Storing folds as JSONB keeps the detail without a second table for something
-- only ever read whole.

CREATE TABLE IF NOT EXISTS walkforward_runs (
    id              UUID PRIMARY KEY,
    backtest_run_id UUID REFERENCES backtest_runs(id) ON DELETE CASCADE,
    strategy_name   TEXT    NOT NULL,
    -- The base parameters the study varied around. Compared against a
    -- deployment's params so a study of one configuration cannot vouch for a
    -- different one.
    params          JSONB   NOT NULL DEFAULT '{}'::JSONB,
    param_grid      JSONB   NOT NULL DEFAULT '{}'::JSONB,
    start_session   DATE    NOT NULL,
    end_session     DATE    NOT NULL,
    train_months    INT     NOT NULL,
    test_months     INT     NOT NULL,
    data_source     TEXT    NOT NULL,

    status          TEXT    NOT NULL DEFAULT 'queued',
    -- The verdict. NULL until the study completes.
    is_robust       BOOLEAN,
    degradation     NUMERIC,
    mean_is_sharpe  NUMERIC,
    mean_oos_sharpe NUMERIC,
    n_folds         INT,
    folds           JSONB   NOT NULL DEFAULT '[]'::JSONB,
    metrics         JSONB   NOT NULL DEFAULT '{}'::JSONB,
    error           TEXT,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,

    CONSTRAINT walkforward_status_check
        CHECK (status IN ('queued', 'running', 'succeeded', 'failed'))
);

CREATE INDEX IF NOT EXISTS idx_walkforward_strategy
    ON walkforward_runs (strategy_name, status);

COMMENT ON COLUMN walkforward_runs.is_robust IS
    'The study''s verdict: out-of-sample performance survived fixing the '
    'parameters in advance. NULL until it completes.';

COMMENT ON COLUMN walkforward_runs.degradation IS
    'mean in-sample Sharpe minus mean out-of-sample Sharpe. Large means the '
    'parameters were fitted to noise.';

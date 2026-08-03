-- 0007_programme.sql
--
-- The AI programme spine: the tables the model writes to, and the tables the
-- gate engine reads to decide whether a stage has been earned.
--
-- One rule governs the shape of all of it: the model never asserts a number.
-- It writes hypothesis cards and proposes configurations. Every figure that
-- appears in a programme artefact is read from a row the deterministic engine
-- wrote, in `backtest_runs`, `walkforward_runs` or `daily_marks`. So nothing
-- here stores a performance metric the model produced; `experiments.outcome`
-- is copied from an engine row at completion, and it carries the identifier of
-- the row it was copied from.
--
-- Two guarantees are schema facts rather than policies:
--
--   * `hypotheses` cannot be deleted from. "Never delete failed hypotheses
--     from the ledger" is worth nothing if a DELETE succeeds, and the whole
--     point of a research ledger is that the failures stay in it. The rule
--     turns DELETE into a no-op rather than an error, because a caller that
--     tries is a bug to find in a test, not an outage to cause in production.
--
--   * `experiments.preregistered_criteria` cannot be updated after insert. A
--     column that can be edited once the result is known prevents nothing, and
--     "prevent research results from being selected retrospectively" is the
--     one integrity control that everything else in the programme rests on.

-- =========================================================================
-- Programme configuration
-- =========================================================================

-- The programme's own configuration. NULL means TBD, and TBD is what the UI
-- renders: a value nobody supplied is never invented, which is the first rule
-- the operating prompt states about this table.
CREATE TABLE IF NOT EXISTS programme_config (
    key         TEXT PRIMARY KEY,
    value       TEXT,
    -- Whether an absent value blocks useful work. The distinction exists so
    -- the programme is not paralysed by an unset reporting timezone while
    -- still refusing to guess a risk limit.
    is_critical BOOLEAN NOT NULL DEFAULT FALSE,
    notes       TEXT NOT NULL DEFAULT '',
    updated_by  TEXT NOT NULL DEFAULT 'migration',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO programme_config (key, is_critical, notes) VALUES
    ('programme_name',              FALSE, 'Identifies the programme in reports'),
    ('base_currency',               TRUE,  'Every figure is quoted in this'),
    ('initial_capital',             TRUE,  'Sizes every position'),
    ('target_capital',              FALSE, 'Objective, not a control'),
    ('markets',                     TRUE,  'Permitted markets'),
    ('instruments',                 TRUE,  'Permitted instruments'),
    ('exclusions',                  FALSE, 'Excluded instruments'),
    ('trading_horizon',             TRUE,  'Primary holding horizon'),
    ('minimum_decision_interval',   TRUE,  'Floor on rebalance frequency'),
    ('maximum_holding_period',      FALSE, 'Ceiling on holding period'),
    ('long_only_or_long_short',     TRUE,  'Permitted structure'),
    ('target_volatility',           TRUE,  'Target annual volatility'),
    ('maximum_drawdown',            TRUE,  'Hard halting limit'),
    ('maximum_daily_loss',          TRUE,  'Hard halting limit'),
    ('maximum_gross_exposure',      TRUE,  'Hard limit'),
    ('maximum_net_exposure',        TRUE,  'Hard limit'),
    ('maximum_position_exposure',   TRUE,  'Hard limit'),
    ('maximum_concentration',       FALSE, 'Sector or factor ceiling'),
    ('maximum_participation_rate',  FALSE, 'Market participation ceiling'),
    ('minimum_liquidity',           FALSE, 'Minimum average daily liquidity'),
    ('broker',                      TRUE,  'Primary broker'),
    ('secondary_broker',            FALSE, 'Failover broker'),
    ('research_engine',             FALSE, 'Vectorised research engine'),
    ('trading_engine',              FALSE, 'Event-driven engine'),
    ('platform',                    FALSE, 'Hosting platform'),
    ('experiment_tracking',         FALSE, 'Experiment tracking platform'),
    ('model_registry',              FALSE, 'Model registry'),
    ('data_store',                  FALSE, 'Canonical data store'),
    ('operational_database',        FALSE, 'Operational database'),
    ('timezone',                    FALSE, 'Reporting timezone'),
    ('regulatory_regime',           TRUE,  'Applicable regulatory regime'),
    ('deployment_policy',           TRUE,  'How strategies reach production'),
    ('approval_requirements',       TRUE,  'Which decisions need a human')
ON CONFLICT (key) DO NOTHING;

-- =========================================================================
-- The research ledger
-- =========================================================================

CREATE TABLE IF NOT EXISTS hypotheses (
    id            UUID PRIMARY KEY,
    -- Human-facing identifier, H-0001. Stable across renames of anything else.
    ref           TEXT UNIQUE NOT NULL,
    title         TEXT NOT NULL,
    owner         TEXT NOT NULL DEFAULT '',
    -- The card: economic mechanism, why the opportunity persists, universe,
    -- horizon, entry and exit concept, expected risks, turnover, capacity,
    -- data requirements, alternative explanations, simplest credible baseline,
    -- falsification test, and the acceptance and rejection criteria. Stored
    -- whole because it is only ever read whole.
    card          JSONB NOT NULL DEFAULT '{}'::JSONB,
    -- open | accepted | rejected | superseded. Never deleted; see the rule
    -- below. A rejected hypothesis stays visible in the UI on purpose.
    status        TEXT NOT NULL DEFAULT 'open',
    -- Relationship to prior hypotheses, so a revision does not read as a new
    -- idea and inflate the count of things tried.
    parent_ref    TEXT,
    -- How many variants were tried under this hypothesis. Reported alongside
    -- any result, because a Sharpe selected from twenty attempts is not the
    -- same evidence as a Sharpe from one.
    variants_tried INT NOT NULL DEFAULT 0,
    -- 'model' or 'operator'. Rendered as a badge; model output is output.
    origin        TEXT NOT NULL DEFAULT 'operator',
    model         TEXT NOT NULL DEFAULT '',
    decision      TEXT,
    decision_rationale TEXT NOT NULL DEFAULT '',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    decided_at    TIMESTAMPTZ,
    CONSTRAINT hypotheses_status_check
        CHECK (status IN ('open', 'accepted', 'rejected', 'superseded')),
    CONSTRAINT hypotheses_origin_check
        CHECK (origin IN ('model', 'operator'))
);

CREATE INDEX IF NOT EXISTS idx_hypotheses_status
    ON hypotheses (status, created_at DESC);

-- The ledger is append-only. DO INSTEAD NOTHING rather than a raising trigger:
-- the property wanted is "the row is still there afterwards", and a test
-- asserts exactly that.
CREATE OR REPLACE RULE hypotheses_no_delete AS
    ON DELETE TO hypotheses DO INSTEAD NOTHING;

-- =========================================================================
-- Candidates: a hypothesis instantiated as one testable configuration
-- =========================================================================

CREATE TABLE IF NOT EXISTS candidates (
    id            UUID PRIMARY KEY,
    hypothesis_id UUID NOT NULL REFERENCES hypotheses(id),
    strategy_name TEXT NOT NULL,
    params        JSONB NOT NULL DEFAULT '{}'::JSONB,
    universe      TEXT[] NOT NULL DEFAULT '{}',
    start_session DATE NOT NULL,
    end_session   DATE NOT NULL,
    data_source   TEXT NOT NULL,

    -- The promotion lifecycle, 0 concept through 8 retired.
    stage         INT NOT NULL DEFAULT 0,
    stage_entered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- active | held | rejected | retired
    status        TEXT NOT NULL DEFAULT 'active',

    -- Set true the moment any synthetic-sourced experiment is recorded against
    -- this candidate, and never cleared. Gate 2 -> 3 refuses it.
    --
    -- Synthetic evidence is permitted through the research stages because no
    -- result in this repository is a real backtest: the equity data hosts are
    -- blocked by this environment's egress policy, so requiring real data at
    -- gate 1 -> 2 would leave the pipeline unexercisable. It is refused at the
    -- gate that precedes anything resembling operation, which is where the API
    -- already refuses it for walk-forward studies and deployments.
    evidence_is_synthetic BOOLEAN NOT NULL DEFAULT FALSE,

    -- Populated only once a candidate reaches a stage that operates.
    deployment_id UUID REFERENCES deployments(id),
    notes         TEXT NOT NULL DEFAULT '',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT candidates_stage_check CHECK (stage BETWEEN 0 AND 8),
    CONSTRAINT candidates_status_check
        CHECK (status IN ('active', 'held', 'rejected', 'retired'))
);

CREATE INDEX IF NOT EXISTS idx_candidates_stage
    ON candidates (status, stage, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_candidates_hypothesis
    ON candidates (hypothesis_id);

-- =========================================================================
-- Experiments
-- =========================================================================

CREATE TABLE IF NOT EXISTS experiments (
    id            UUID PRIMARY KEY,
    ref           TEXT UNIQUE NOT NULL,
    hypothesis_id UUID NOT NULL REFERENCES hypotheses(id),
    candidate_id  UUID NOT NULL REFERENCES candidates(id),

    -- baseline | backtest | cost_stress | parameter_neighbourhood |
    -- benchmark | replication | walkforward
    kind          TEXT NOT NULL,

    -- Reproducibility: everything needed to run this again and get the same
    -- answer. The operating prompt lists these; they are columns rather than
    -- prose so a missing one is visible.
    code_commit   TEXT NOT NULL DEFAULT '',
    dataset_manifest JSONB NOT NULL DEFAULT '{}'::JSONB,
    seed          INT,
    universe      TEXT[] NOT NULL DEFAULT '{}',
    train_start   DATE,
    train_end     DATE,
    test_start    DATE,
    test_end      DATE,
    cost_assumptions JSONB NOT NULL DEFAULT '{}'::JSONB,

    -- The acceptance and rejection criteria, fixed before the run. Immutable
    -- after insert; see the trigger below.
    preregistered_criteria JSONB NOT NULL,

    -- Where the answer came from. The engine wrote these rows; this table only
    -- points at them.
    backtest_run_id    UUID REFERENCES backtest_runs(id) ON DELETE SET NULL,
    walkforward_run_id UUID REFERENCES walkforward_runs(id) ON DELETE SET NULL,
    job_id             UUID,

    status        TEXT NOT NULL DEFAULT 'planned',
    -- Metrics copied from the engine row at completion, so an artefact can be
    -- rendered without re-deriving them, and so a later edit to the engine row
    -- is visible as a divergence rather than silently rewriting history.
    outcome       JSONB NOT NULL DEFAULT '{}'::JSONB,
    -- pass | fail | inconclusive, decided by evaluating `outcome` against
    -- `preregistered_criteria`. Never decided by a model.
    conclusion    TEXT,
    error         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at   TIMESTAMPTZ,

    CONSTRAINT experiments_status_check
        CHECK (status IN ('planned', 'queued', 'running', 'succeeded', 'failed')),
    CONSTRAINT experiments_conclusion_check
        CHECK (conclusion IS NULL OR conclusion IN ('pass', 'fail', 'inconclusive'))
);

CREATE INDEX IF NOT EXISTS idx_experiments_candidate
    ON experiments (candidate_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_experiments_kind
    ON experiments (candidate_id, kind, status);

-- Preregistration is only preregistration if it cannot be revised once the
-- answer is known. This raises rather than silently ignoring, because a caller
-- editing it is trying to do the one thing the column exists to prevent, and
-- should hear about it.
CREATE OR REPLACE FUNCTION experiments_preregistration_is_immutable()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.preregistered_criteria IS DISTINCT FROM OLD.preregistered_criteria THEN
        RAISE EXCEPTION
            'preregistered_criteria is immutable after insert (experiment %)',
            OLD.ref;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_experiments_preregistration ON experiments;
CREATE TRIGGER trg_experiments_preregistration
    BEFORE UPDATE ON experiments
    FOR EACH ROW EXECUTE FUNCTION experiments_preregistration_is_immutable();

-- =========================================================================
-- Gate evaluations
-- =========================================================================

-- Append-only. Every judgement the gate engine made, including the ones that
-- refused, because "the gate said no on Tuesday" is the record that makes a
-- promotion on Thursday auditable.
CREATE TABLE IF NOT EXISTS gate_evaluations (
    id           BIGSERIAL PRIMARY KEY,
    candidate_id UUID NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    from_stage   INT NOT NULL,
    to_stage     INT NOT NULL,
    -- One object per criterion: id, description, met, and the evidence — table
    -- name, row id, value. A criterion with no evidence is not met.
    criteria     JSONB NOT NULL DEFAULT '[]'::JSONB,
    passed       BOOLEAN NOT NULL,
    requires_human BOOLEAN NOT NULL DEFAULT FALSE,
    -- Whether this evaluation resulted in a promotion, and who confirmed it.
    -- NULL approver on a promoted row means the gate engine promoted it
    -- automatically, which is only permitted where requires_human is false.
    promoted     BOOLEAN NOT NULL DEFAULT FALSE,
    approved_by  TEXT,
    evaluator    TEXT NOT NULL DEFAULT 'gate_engine',
    evaluated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_gate_evaluations_candidate
    ON gate_evaluations (candidate_id, evaluated_at DESC);

-- =========================================================================
-- Decision log
-- =========================================================================

CREATE TABLE IF NOT EXISTS programme_decisions (
    id           UUID PRIMARY KEY,
    ref          TEXT UNIQUE NOT NULL,
    subject_type TEXT NOT NULL,
    subject_id   TEXT NOT NULL,
    -- One of the permitted decisions: reject, revise, hold, promote_validation,
    -- promote_shadow, promote_paper, promote_canary, increase_capital,
    -- maintain_capital, reduce_capital, suspend, retire.
    decision     TEXT NOT NULL,
    rationale_md TEXT NOT NULL DEFAULT '',
    -- Row identifiers backing the decision. Prose without these is an opinion.
    evidence     JSONB NOT NULL DEFAULT '{}'::JSONB,
    -- 'gate_engine' or 'operator:<name>'. Never a bare model.
    made_by      TEXT NOT NULL,
    code_version TEXT NOT NULL DEFAULT '',
    unresolved   JSONB NOT NULL DEFAULT '[]'::JSONB,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_programme_decisions_subject
    ON programme_decisions (subject_type, subject_id, created_at DESC);

-- =========================================================================
-- Runner ticks
-- =========================================================================

-- One row per pass of the programme process. A row inserted with
-- status = 'requested' is how the UI asks for an immediate tick: the API must
-- not run one inline, for the same reason it never runs a backtest inline, and
-- the programme runner is a different process from the worker so it cannot use
-- the `jobs` queue without the worker trying to claim its work.
CREATE TABLE IF NOT EXISTS programme_runs (
    id           UUID PRIMARY KEY,
    trigger      TEXT NOT NULL DEFAULT 'scheduled',
    status       TEXT NOT NULL DEFAULT 'requested',
    -- What the tick did: gates evaluated, promotions, experiments enqueued,
    -- hypotheses proposed. Read whole by the UI.
    actions      JSONB NOT NULL DEFAULT '[]'::JSONB,
    model        TEXT NOT NULL DEFAULT '',
    error        TEXT,
    requested_by TEXT NOT NULL DEFAULT 'scheduler',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at   TIMESTAMPTZ,
    finished_at  TIMESTAMPTZ,

    CONSTRAINT programme_runs_trigger_check
        CHECK (trigger IN ('scheduled', 'manual')),
    CONSTRAINT programme_runs_status_check
        CHECK (status IN ('requested', 'running', 'succeeded', 'failed', 'skipped'))
);

-- The claim query only ever looks at requested rows.
CREATE INDEX IF NOT EXISTS idx_programme_runs_requested
    ON programme_runs (created_at) WHERE status = 'requested';
CREATE INDEX IF NOT EXISTS idx_programme_runs_recent
    ON programme_runs (created_at DESC);

-- =========================================================================
-- The programme kill switch
-- =========================================================================

-- Fail closed, exactly like `trading_enabled`: a missing row, an unreadable
-- value or a database error all mean disabled. A control that defaults to "go"
-- when it cannot determine the answer is not a control, and that argument does
-- not weaken because the thing being controlled writes rows rather than orders.
INSERT INTO system_flags (key, value, updated_by)
VALUES ('programme_enabled', 'false'::JSONB, 'migration')
ON CONFLICT (key) DO NOTHING;

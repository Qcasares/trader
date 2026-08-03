-- 0008_programme_governance.sql
--
-- The controls, added before the autonomy they control.
--
-- Slice 1 built a gate engine that reads evidence. That is enough to stop a
-- candidate with missing rows and useless against a candidate whose rows all
-- exist and whose *reasoning* is wrong — a universe quietly selected after the
-- fact, a cost model nobody challenged, a result concentrated in six months of
-- 2020. The operating prompt's answer is a set of specialist roles, some of
-- which may veto, and that is what this migration stores.
--
-- The load-bearing decision is that a veto is a row, not an opinion. A role
-- raises a finding with a severity; a hard-coded rule maps open high-severity
-- findings from a veto-holding role to a blocked gate. No prose is consulted at
-- any point, and no amount of subsequent argument clears a finding.
--
-- Which brings us to the rule that matters most here:
--
--   **A model cannot close its own finding.** `findings_closed_by_an_operator`
--   refuses any transition out of `open` unless `closed_by` names an operator.
--   Without it, the whole arrangement is theatre: a role that can both raise
--   and retract a blocking finding has not vetoed anything, and the tick that
--   raised it on Monday would be free to withdraw it on Tuesday when it got in
--   the way.

-- =========================================================================
-- Specialist assessments
-- =========================================================================

-- One row per role per look. Append-only, and deliberately not deduplicated:
-- the record wanted is "what each role thought, and when", including the times
-- they disagreed with each other and with themselves a week later.
--
-- Nothing here is consulted by a gate. A verdict is commentary; only a finding
-- has force. That separation is what stops "the risk officer was broadly
-- positive" from becoming an input to a promotion.
CREATE TABLE IF NOT EXISTS role_assessments (
    id            BIGSERIAL PRIMARY KEY,
    candidate_id  UUID NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    -- One of the twelve in src/programme/roles.py.
    role          TEXT NOT NULL,
    -- support | concern | object | abstain.
    --
    -- `abstain` exists so a role with nothing to say says so, rather than
    -- manufacturing a view to fill the column. Artificial consensus and
    -- artificial dissent are both failures of the same kind.
    verdict       TEXT NOT NULL,
    summary       TEXT NOT NULL DEFAULT '',
    -- Row identifiers the role was shown. A view formed on no evidence is
    -- visible as an empty object rather than indistinguishable from one that
    -- read everything.
    evidence      JSONB NOT NULL DEFAULT '{}'::JSONB,
    stage         INT NOT NULL,
    model         TEXT NOT NULL DEFAULT '',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT role_assessments_verdict_check
        CHECK (verdict IN ('support', 'concern', 'object', 'abstain'))
);

CREATE INDEX IF NOT EXISTS idx_role_assessments_candidate
    ON role_assessments (candidate_id, created_at DESC);

-- =========================================================================
-- Findings
-- =========================================================================

CREATE TABLE IF NOT EXISTS findings (
    id            UUID PRIMARY KEY,
    ref           TEXT UNIQUE NOT NULL,
    -- NULL for a programme-wide finding that blocks nothing in particular.
    candidate_id  UUID REFERENCES candidates(id) ON DELETE CASCADE,
    raised_by     TEXT NOT NULL,
    -- low | medium | high | critical. Only the last two block, and only from a
    -- role that holds a veto; see src/programme/gates.py.
    severity      TEXT NOT NULL,
    title         TEXT NOT NULL,
    detail_md     TEXT NOT NULL DEFAULT '',
    remediation   TEXT NOT NULL DEFAULT '',
    -- open | remediated | accepted | withdrawn.
    --
    -- `accepted` is a deliberate, recorded decision to proceed with a known
    -- defect, and it is not the same as fixing one. Collapsing the two would
    -- make the register describe a programme with no outstanding problems,
    -- which is the one state it must never be able to describe falsely.
    status        TEXT NOT NULL DEFAULT 'open',
    opened_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at     TIMESTAMPTZ,
    closed_by     TEXT,
    close_note    TEXT NOT NULL DEFAULT '',

    CONSTRAINT findings_severity_check
        CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    CONSTRAINT findings_status_check
        CHECK (status IN ('open', 'remediated', 'accepted', 'withdrawn')),

    -- The rule this table exists for.
    --
    -- A finding leaves `open` only when an operator says so, by name. The
    -- programme runner writes `programme:<role>` into `raised_by` and can
    -- never write a matching `closed_by`, because the API is the only thing
    -- that sets one and it always prefixes the session subject.
    CONSTRAINT findings_closed_by_an_operator CHECK (
        status = 'open'
        OR (closed_by IS NOT NULL AND closed_by LIKE 'operator:%')
    )
);

CREATE INDEX IF NOT EXISTS idx_findings_open
    ON findings (candidate_id, severity) WHERE status = 'open';
CREATE INDEX IF NOT EXISTS idx_findings_recent
    ON findings (opened_at DESC);

-- =========================================================================
-- The autonomy ceiling
-- =========================================================================

-- How far the runner may promote a candidate without an operator.
--
-- Zero means it may evaluate gates, queue experiments and record judgements,
-- and promote nothing. That is the default, and it is the value a missing or
-- unreadable row is read as — the same fail-closed rule as every other control
-- here, for the same reason.
--
-- It is a ceiling, not a permission: `FIRST_HUMAN_GATED_STAGE` in
-- src/programme/gates.py caps it regardless of what is stored, so setting this
-- to 8 does not let a model promote anything into production. Two independent
-- limits rather than one, because a single number in a database row is one
-- mistaken UPDATE away from being wrong.
INSERT INTO system_flags (key, value, updated_by)
VALUES ('programme_max_auto_stage', '0'::JSONB, 'migration')
ON CONFLICT (key) DO NOTHING;

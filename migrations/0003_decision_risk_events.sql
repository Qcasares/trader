-- 0003_decision_risk_events.sql
--
-- Record what the risk gate did to a live decision.
--
-- Until now the live path did not run `apply_risk` at all — it reimplemented a
-- subset of `Driver.step` inline and left the gate out — so there was nothing
-- to store. With the gate restored to the live path, two columns are needed to
-- keep the decision auditable:
--
--   raw_target_weights  what the strategy asked for, before the gate
--   risk_events         the ordered list of interventions, binding or not
--
-- Both, not one. `target_weights` alone cannot answer "did a limit change this
-- answer, or merely get evaluated?", and that is the only question worth
-- asking when a live decision looks different from its backtest.
--
-- Additive and defaulted, so existing rows stay valid: a decision made before
-- this migration genuinely had no recorded gate output, and an empty array is
-- the honest representation of that rather than a fabricated one.

ALTER TABLE decisions
    ADD COLUMN IF NOT EXISTS raw_target_weights JSONB NOT NULL DEFAULT '{}'::JSONB,
    ADD COLUMN IF NOT EXISTS risk_events        JSONB NOT NULL DEFAULT '[]'::JSONB;

COMMENT ON COLUMN decisions.raw_target_weights IS
    'Strategy output before the risk gate. Compare with target_weights to see '
    'whether a limit bound.';

COMMENT ON COLUMN decisions.risk_events IS
    'Ordered risk-gate interventions: {code, severity, message, symbol, binding}.';

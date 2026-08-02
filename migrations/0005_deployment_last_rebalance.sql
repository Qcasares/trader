-- 0005_deployment_last_rebalance.sql
--
-- Give the rebalance schedule somewhere to live.
--
-- `Strategy.should_rebalance(session, last_rebalance)` returns True whenever
-- `last_rebalance` is None — that is how a backtest's very first session gets
-- to trade. A backtest then keeps the value in memory as it walks, so the
-- schedule works.
--
-- The live path read it from `deployment["last_rebalance"]`. That column did
-- not exist, so the lookup returned None on every single job, and
-- `should_rebalance` returned True on every single session.
--
-- A monthly strategy therefore rebalanced *daily* in live trading — roughly
-- 21x the intended turnover and 21x the cost — while the backtest that
-- authorised it rebalanced twelve times a year. Not a disabled safety limit:
-- a different strategy from the one that was validated.
--
-- Nullable with no default. NULL means "has never rebalanced", which is
-- exactly what a new deployment is and exactly what should_rebalance already
-- treats as permission to trade.

ALTER TABLE deployments ADD COLUMN IF NOT EXISTS last_rebalance DATE;

COMMENT ON COLUMN deployments.last_rebalance IS
    'Session of the most recent rebalance. NULL = never. Read by '
    'Strategy.should_rebalance; a live process is rebuilt every session and '
    'has no memory of its own.';

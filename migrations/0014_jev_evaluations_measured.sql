-- 0014_jev_evaluations_measured.sql
--
-- Phase C9 of docs/08-jev-integration.md, the evaluation harness: what an
-- evaluation of Jev measured, and the rules no row of one may break. Additive
-- only. 0012 created `jev_evaluations` and is applied and checksummed, so
-- nothing in it is edited; everything C9 needs is here. The table has no
-- production rows: nothing has written one before `jev_eval evaluate --record`.
--
-- What an evaluation is
-- ~~~~~~~~~~~~~~~~~~~~~
-- One question of one registered set, at one version, measured against one
-- labeller's labels, for one pinned model, over one split of the items
-- (`split`, `all` or the held-out `test`), under the analysis plans in force
-- (`analysis_plan_hash`, which names the global plan and the set's own). The
-- figures are design section 10.1's, binding: counts of what was answered;
-- accuracy over the valid answers and over every item, each with its Wilson
-- interval; per-class figures; the Brier score with its bootstrap interval
-- and the climatology beside it; both baselines and Jev's paired difference
-- from each; a threshold searched on the development split only and measured
-- on the test split; the flip rates of the re-asks, stratum by stratum; and
-- how far another labeller agrees with this one.
--
-- An unmeasured figure is NULL, never zero
-- ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
-- Every measurement is nullable and NULL means not measured, as in 0012:
-- an accuracy over no valid answer, a flip rate over no pair, a threshold
-- nobody may choose. A count is a count, and 0 is 0. Each CHECK below is
-- NULL-tolerant — a NULL measurement passes it — except where a rule is
-- about NULL itself: a flip rate is measured exactly when it has pairs, a
-- figure carries its interval, and a threshold arrives with its whole group
-- or not at all. CHECKs that compare a measurement with something are written
-- with `num_nulls`, `COALESCE` or `IS NOT DISTINCT FROM` wherever a bare
-- comparison would let a NULL through a rule it must not pass: SQL's
-- three-valued logic makes `NULL OR FALSE` NULL, and a NULL CHECK passes.
--
-- A threshold never rests on an upper bound
-- ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
-- TypeSafe discloses no training cutoff (docs/08, fact 6), so an item dated on
-- or before the model's first observation, or not dated at all, may be in its
-- training data, and an evaluation holding one is an upper bound. The harness
-- computes `possibly_in_training`; nobody types it. A threshold chosen on
-- such an evaluation would be calibrated on what the model may have
-- memorised, so `NOT possibly_in_training OR threshold IS NULL` refuses one
-- whatever writes it. The README's titles are undated, so an evaluation
-- against its grouping is always an upper bound and never carries a
-- threshold.
--
-- The model is pinned
-- ~~~~~~~~~~~~~~~~~~~
-- A figure measured on `jev-latest` belongs to no model anybody can name, so
-- the column takes a versioned id only, as `jev_catalogue.PINNED_MODEL` does:
-- `[0-9]` rather than `\d`, and PostgreSQL's `$`, which matches only at the
-- end of the string, so neither a Unicode digit nor a trailing newline passes.
--
-- Columns beyond design C9's block
-- ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
-- `n_other_plans` and `n_plan_unknown`: labelled items set apart because their
-- answer was recorded under analysis plans other than those in force, or
-- under plans the queue cannot name (docs/08, C7+C8, "The plans an answer was
-- recorded under"). Neither is scored, and neither is in `n`; a count the row
-- did not keep is one the report could not show.
--
-- `gate_ci_level`: the one-sided level the row's gates were judged at — the
-- threshold's search and the test a baseline is beaten by — beside
-- `ci_level`, the two-sided level of every interval the row reports, the
-- paired differences' bootstrap intervals among them. A row says what level
-- each of its figures was computed at, rather than leaving it to the plan in
-- force when it is read.
--
-- `vs_<baseline>_jev_right_only` and `vs_<baseline>_baseline_right_only`: of
-- the scored items, those Jev got right and the baseline wrong, and the other
-- way round. Jev beats a baseline only by the exact one-sided sign test of
-- these at the gate level (McNemar's, exact); the items both got right or
-- both wrong say nothing about which is better, and a percentile bootstrap
-- of the difference over a few such items understates their uncertainty.
-- The difference is these two counts over `n`, and a CHECK holds it so.
--
-- `flip_rate_not_compared`, `flip_rate_low_margin_not_compared` and
-- `flip_rate_near_threshold_not_compared`: the re-asks sampled under the plan
-- in force whose pair could not be compared — a re-ask, or its canonical
-- answer, refused whole, a tie, failed or refused before it was sent. A flip
-- rate is over the pairs both of whose answers were measured, and a re-ask
-- left out of both counts would make a vendor that malformed every second
-- re-ask read as though it had been asked half as often.

ALTER TABLE jev_evaluations
    ADD COLUMN split TEXT NOT NULL DEFAULT 'all'
        CONSTRAINT jev_evaluations_split_check CHECK (split IN ('all', 'test')),
    ADD COLUMN analysis_plan_hash TEXT,
    ADD COLUMN keyword_baseline_ref TEXT,
    ADD COLUMN answers_sha256 TEXT,
    ADD COLUMN ci_level DOUBLE PRECISION,
    ADD COLUMN gate_ci_level DOUBLE PRECISION,
    ADD COLUMN n_valid INT,
    ADD COLUMN n_escape INT,
    ADD COLUMN n_invalid INT,
    ADD COLUMN n_not_asked INT,
    ADD COLUMN n_contested INT,
    ADD COLUMN n_distinct_states INT,
    ADD COLUMN n_other_plans INT,
    ADD COLUMN n_plan_unknown INT,
    ADD COLUMN accuracy_all_items DOUBLE PRECISION,
    ADD COLUMN accuracy_all_items_wilson_low DOUBLE PRECISION,
    ADD COLUMN accuracy_all_items_wilson_high DOUBLE PRECISION,
    ADD COLUMN per_class JSONB,
    ADD COLUMN brier_reference DOUBLE PRECISION,
    ADD COLUMN threshold_outcome TEXT
        CONSTRAINT jev_evaluations_threshold_outcome_check
        CHECK (threshold_outcome IN ('not_attempted', 'none_found', 'chosen')),
    ADD COLUMN threshold_statistic TEXT,
    ADD COLUMN threshold_target DOUBLE PRECISION,
    ADD COLUMN threshold_dataset_sha256 TEXT,
    ADD COLUMN n_at_threshold INT,
    ADD COLUMN accuracy_at_threshold DOUBLE PRECISION,
    ADD COLUMN accuracy_at_threshold_wilson_low DOUBLE PRECISION,
    ADD COLUMN accuracy_at_threshold_wilson_high DOUBLE PRECISION,
    ADD COLUMN vs_majority_diff DOUBLE PRECISION,
    ADD COLUMN vs_majority_diff_low DOUBLE PRECISION,
    ADD COLUMN vs_majority_diff_high DOUBLE PRECISION,
    ADD COLUMN vs_majority_jev_right_only INT,
    ADD COLUMN vs_majority_baseline_right_only INT,
    ADD COLUMN vs_keyword_diff DOUBLE PRECISION,
    ADD COLUMN vs_keyword_diff_low DOUBLE PRECISION,
    ADD COLUMN vs_keyword_diff_high DOUBLE PRECISION,
    ADD COLUMN vs_keyword_jev_right_only INT,
    ADD COLUMN vs_keyword_baseline_right_only INT,
    ADD COLUMN flip_rate_n INT,
    ADD COLUMN flip_rate_not_compared INT,
    ADD COLUMN flip_rate_low_margin DOUBLE PRECISION,
    ADD COLUMN flip_rate_low_margin_n INT,
    ADD COLUMN flip_rate_low_margin_not_compared INT,
    ADD COLUMN flip_rate_near_threshold DOUBLE PRECISION,
    ADD COLUMN flip_rate_near_threshold_n INT,
    ADD COLUMN flip_rate_near_threshold_not_compared INT,
    ADD COLUMN flip_median_lag_hours DOUBLE PRECISION,
    ADD COLUMN labeller_agreement DOUBLE PRECISION,
    ADD COLUMN labeller_kappa DOUBLE PRECISION,
    ADD COLUMN labeller_agreement_n INT;

ALTER TABLE jev_evaluations
    -- Every proportion is a probability, 0012's columns as well as these. A
    -- threshold is a margin, the lead of one option over the next, so it is
    -- one too.
    ADD CONSTRAINT jev_evaluations_proportions CHECK (
        accuracy BETWEEN 0 AND 1
        AND accuracy_wilson_low BETWEEN 0 AND 1
        AND accuracy_wilson_high BETWEEN 0 AND 1
        AND balanced_accuracy BETWEEN 0 AND 1
        AND threshold BETWEEN 0 AND 1
        AND coverage_at_threshold BETWEEN 0 AND 1
        AND majority_baseline_accuracy BETWEEN 0 AND 1
        AND keyword_baseline_accuracy BETWEEN 0 AND 1
        AND flip_rate BETWEEN 0 AND 1
        AND accuracy_all_items BETWEEN 0 AND 1
        AND accuracy_all_items_wilson_low BETWEEN 0 AND 1
        AND accuracy_all_items_wilson_high BETWEEN 0 AND 1
        AND threshold_target BETWEEN 0 AND 1
        AND accuracy_at_threshold BETWEEN 0 AND 1
        AND accuracy_at_threshold_wilson_low BETWEEN 0 AND 1
        AND accuracy_at_threshold_wilson_high BETWEEN 0 AND 1
        AND flip_rate_low_margin BETWEEN 0 AND 1
        AND flip_rate_near_threshold BETWEEN 0 AND 1
        AND labeller_agreement BETWEEN 0 AND 1
    ),
    -- The two-sided level every interval the row reports was computed at,
    -- and the one-sided level its gates were judged at.
    ADD CONSTRAINT jev_evaluations_ci_level CHECK (
        ci_level > 0 AND ci_level < 1
        AND gate_ci_level > 0 AND gate_ci_level < 1
    ),
    -- A Choice's Brier score sums a squared error over its options, at most 2;
    -- a Noul's is at most 1. Its climatology is one.
    ADD CONSTRAINT jev_evaluations_brier_range CHECK (
        brier BETWEEN 0 AND 2
        AND brier_ci_low BETWEEN 0 AND 2
        AND brier_ci_high BETWEEN 0 AND 2
        AND brier_reference BETWEEN 0 AND 2
    ),
    ADD CONSTRAINT jev_evaluations_kappa_range CHECK (labeller_kappa BETWEEN -1 AND 1),
    -- A paired difference is its discordant items: Jev right where the
    -- baseline was wrong, less the other way round, over n. The three are
    -- present together, and the point is their arithmetic, to well within
    -- what a double's rounding of a mean could move.
    ADD CONSTRAINT jev_evaluations_differences_from_their_items CHECK (
        num_nulls(vs_majority_diff, vs_majority_jev_right_only,
                  vs_majority_baseline_right_only) IN (0, 3)
        AND (num_nulls(vs_majority_diff, vs_majority_jev_right_only,
                       vs_majority_baseline_right_only) > 0
             OR abs(vs_majority_diff * n
                    - (vs_majority_jev_right_only
                       - vs_majority_baseline_right_only)) < 1e-6)
        AND num_nulls(vs_keyword_diff, vs_keyword_jev_right_only,
                      vs_keyword_baseline_right_only) IN (0, 3)
        AND (num_nulls(vs_keyword_diff, vs_keyword_jev_right_only,
                       vs_keyword_baseline_right_only) > 0
             OR abs(vs_keyword_diff * n
                    - (vs_keyword_jev_right_only
                       - vs_keyword_baseline_right_only)) < 1e-6)
    ),
    -- Jev's accuracy over every item less a baseline's, both proportions.
    ADD CONSTRAINT jev_evaluations_differences_range CHECK (
        vs_majority_diff BETWEEN -1 AND 1
        AND vs_majority_diff_low BETWEEN -1 AND 1
        AND vs_majority_diff_high BETWEEN -1 AND 1
        AND vs_keyword_diff BETWEEN -1 AND 1
        AND vs_keyword_diff_low BETWEEN -1 AND 1
        AND vs_keyword_diff_high BETWEEN -1 AND 1
    ),
    -- An interval holds its estimate, where all three are present.
    ADD CONSTRAINT jev_evaluations_intervals_hold_their_estimates CHECK (
        (num_nulls(accuracy_wilson_low, accuracy, accuracy_wilson_high) > 0
         OR (accuracy_wilson_low <= accuracy
             AND accuracy <= accuracy_wilson_high))
        AND (num_nulls(accuracy_all_items_wilson_low, accuracy_all_items,
                       accuracy_all_items_wilson_high) > 0
             OR (accuracy_all_items_wilson_low <= accuracy_all_items
                 AND accuracy_all_items <= accuracy_all_items_wilson_high))
        AND (num_nulls(accuracy_at_threshold_wilson_low, accuracy_at_threshold,
                       accuracy_at_threshold_wilson_high) > 0
             OR (accuracy_at_threshold_wilson_low <= accuracy_at_threshold
                 AND accuracy_at_threshold <= accuracy_at_threshold_wilson_high))
        AND (num_nulls(brier_ci_low, brier, brier_ci_high) > 0
             OR (brier_ci_low <= brier AND brier <= brier_ci_high))
        AND (num_nulls(vs_majority_diff_low, vs_majority_diff,
                       vs_majority_diff_high) > 0
             OR (vs_majority_diff_low <= vs_majority_diff
                 AND vs_majority_diff <= vs_majority_diff_high))
        AND (num_nulls(vs_keyword_diff_low, vs_keyword_diff,
                       vs_keyword_diff_high) > 0
             OR (vs_keyword_diff_low <= vs_keyword_diff
                 AND vs_keyword_diff <= vs_keyword_diff_high))
    ),
    -- And a figure carries its interval: never one without the other, as a
    -- Sharpe is never rendered without its standard error (CLAUDE.md).
    ADD CONSTRAINT jev_evaluations_estimates_carry_their_intervals CHECK (
        num_nulls(accuracy_wilson_low, accuracy, accuracy_wilson_high) IN (0, 3)
        AND num_nulls(accuracy_all_items_wilson_low, accuracy_all_items,
                      accuracy_all_items_wilson_high) IN (0, 3)
        AND num_nulls(accuracy_at_threshold_wilson_low, accuracy_at_threshold,
                      accuracy_at_threshold_wilson_high) IN (0, 3)
        AND num_nulls(brier_ci_low, brier, brier_ci_high) IN (0, 3)
        AND num_nulls(vs_majority_diff_low, vs_majority_diff,
                      vs_majority_diff_high) IN (0, 3)
        AND num_nulls(vs_keyword_diff_low, vs_keyword_diff,
                      vs_keyword_diff_high) IN (0, 3)
    ),
    -- Every count of items or pairs inside the n scored items is between 0
    -- and n. The three counts of items set outside n — contested, answered
    -- under other plans, plan unknown — are counts, and only that.
    ADD CONSTRAINT jev_evaluations_counts_within_n CHECK (
        n_valid BETWEEN 0 AND n
        AND n_escape BETWEEN 0 AND n
        AND n_invalid BETWEEN 0 AND n
        AND n_not_asked BETWEEN 0 AND n
        AND n_distinct_states BETWEEN 0 AND n
        AND n_at_threshold BETWEEN 0 AND n
        AND flip_rate_n BETWEEN 0 AND n
        AND flip_rate_low_margin_n BETWEEN 0 AND n
        AND flip_rate_near_threshold_n BETWEEN 0 AND n
        AND labeller_agreement_n BETWEEN 0 AND n
        AND vs_majority_jev_right_only >= 0
        AND vs_majority_baseline_right_only >= 0
        AND vs_majority_jev_right_only + vs_majority_baseline_right_only <= n
        AND vs_keyword_jev_right_only >= 0
        AND vs_keyword_baseline_right_only >= 0
        AND vs_keyword_jev_right_only + vs_keyword_baseline_right_only <= n
        -- Each scored item's canonical request is re-asked at most once, in
        -- one stratum, so every re-ask of the two strata is within n.
        AND flip_rate_not_compared >= 0
        AND flip_rate_low_margin_not_compared >= 0
        AND flip_rate_near_threshold_not_compared >= 0
        AND flip_rate_n + flip_rate_not_compared + flip_rate_low_margin_n
            + flip_rate_low_margin_not_compared <= n
        AND flip_rate_near_threshold_n + flip_rate_near_threshold_not_compared <= n
    ),
    ADD CONSTRAINT jev_evaluations_counts_outside_n CHECK (
        n_contested >= 0 AND n_other_plans >= 0 AND n_plan_unknown >= 0
    ),
    -- Every scored item was answered validly, answered invalidly, or not
    -- asked; an escape is a valid answer.
    ADD CONSTRAINT jev_evaluations_answers_add_up CHECK (
        (num_nulls(n_valid, n_invalid, n_not_asked) > 0
         OR n_valid + n_invalid + n_not_asked = n)
        AND n_escape <= n_valid
    ),
    -- A flip rate is measured exactly when it has pairs, and its median lag
    -- is the uniform stratum's: a number of hours, which neither NaN nor
    -- Infinity is. PostgreSQL orders NaN above every number, so `>= 0` alone
    -- admits it; `< 'Infinity'` refuses both.
    ADD CONSTRAINT jev_evaluations_flip_rates_need_pairs CHECK (
        (flip_rate IS NOT NULL) = COALESCE(flip_rate_n > 0, FALSE)
        AND (flip_rate_low_margin IS NOT NULL)
            = COALESCE(flip_rate_low_margin_n > 0, FALSE)
        AND (flip_rate_near_threshold IS NOT NULL)
            = COALESCE(flip_rate_near_threshold_n > 0, FALSE)
        AND (flip_median_lag_hours IS NULL
             OR (flip_median_lag_hours >= 0
                 AND flip_median_lag_hours < 'Infinity'::float8
                 AND COALESCE(flip_rate_n > 0, FALSE)))
    ),
    -- A threshold arrives with its whole group — the margin, what it was
    -- searched to reach, the dataset it was searched on and how many test
    -- items it covers — exactly when one was chosen, and with nothing of it
    -- otherwise, a row of 0012's shape included.
    ADD CONSTRAINT jev_evaluations_threshold_whole CHECK (
        num_nulls(threshold, threshold_statistic, threshold_target,
                  threshold_dataset_sha256, n_at_threshold)
        = CASE WHEN threshold_outcome IS NOT DISTINCT FROM 'chosen' THEN 0 ELSE 5 END
    ),
    -- Nothing is measured at a threshold nobody chose: no coverage, no
    -- accuracy, and no re-ask counted near it — so no flip rate near it
    -- either, a rate being measured exactly when its pairs are (above).
    -- Within one chosen, a coverage or an accuracy over no test item stays
    -- NULL.
    ADD CONSTRAINT jev_evaluations_at_threshold_needs_one CHECK (
        threshold_outcome IS NOT DISTINCT FROM 'chosen'
        OR num_nulls(coverage_at_threshold, accuracy_at_threshold,
                     accuracy_at_threshold_wilson_low,
                     accuracy_at_threshold_wilson_high,
                     flip_rate_near_threshold_n,
                     flip_rate_near_threshold_not_compared) = 6
    ),
    ADD CONSTRAINT jev_evaluations_no_threshold_on_an_upper_bound CHECK (
        NOT possibly_in_training OR threshold IS NULL
    ),
    ADD CONSTRAINT jev_evaluations_model_is_pinned CHECK (
        model ~ '^jev-[0-9]+\.[0-9]+\.[0-9]+$'
    );

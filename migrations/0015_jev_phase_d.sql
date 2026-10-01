-- 0015_jev_phase_d.sql
-- Phase D's schema. Additive, but for one CHECK of 0014's replaced whole and
-- jev_requests' provenance CHECK widened under its own name, as 0013 did.
--
-- Phase D of docs/08-jev-integration.md, its first pull request (D1), as
-- docs/09-jev-phase-d-design.md section 7 gives it. Nothing in it calls Jev
-- or switches anything on: the arming switch is seeded off, and no code reads
-- it to act until D4. 0012, 0013 and 0014 are applied and checksummed, so
-- nothing in them is edited; every change phase D needs is here.
--
-- Who wrote a finding
-- ~~~~~~~~~~~~~~~~~~~
-- Until now a finding said who raised it (`raised_by`, a role's key) but not
-- who wrote it: the programme's model through the tick, or an operator through
-- the API, who may raise one under any role's name. From here every finding
-- names its writer in `origin`: 'model', 'operator', or 'jev' — the card
-- check's finding, raised only from D4, and held never to block. The rows
-- already stored read 'unknown', which means raised before this migration by a
-- writer nobody can now prove, and nothing else: the default exists only to
-- give them that, and is dropped at once, so an insert that names no writer
-- fails on NOT NULL, and a trigger refuses one that names 'unknown'. A
-- backfill from `audit_log` would be a guess, since the API writes a finding
-- and its audit row as two statements. Every comparison of `origin` in a
-- trigger is NULL-safe, because a BEFORE trigger runs before NOT NULL is
-- checked, and an insert naming no origin must fail on the column, not on a
-- trigger's message.
--
-- What was raised stays raised
-- ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
-- 0008's CHECK needs an operator to close a finding, and admits `open` always,
-- so it never stopped a closed finding from being reopened, a finding from
-- being edited, or one from being deleted — a blocking veto included, with
-- its candidate's delete cascading to it. Now only the closure's columns
-- change, a closed finding is never reopened, and DELETE and TRUNCATE are
-- refused with an exception, as the Jev ledger refuses them: no writer removes
-- a finding, and a candidate's delete, which would cascade to its findings,
-- fails with them.
--
-- Provenance `system`
-- ~~~~~~~~~~~~~~~~~~~
-- A job error's skeleton (phase D3) is this system's own records, computed in
-- code, which can quote an outsider: a library's exception repeating a
-- vendor's reply. Not `internal`, which the phase F signal loader is to trust.
-- A request may carry it; a signal may not, so `jev_signals_provenance_check`
-- is left as 0013 wrote it, and no answer recorded as `system` can ever rest
-- under a signal (`jev_signals_rest_on_their_answer` holds a signal's
-- provenance to its request's).
--
-- Plan version 2's flips
-- ~~~~~~~~~~~~~~~~~~~~~~
-- A flip rate now counts every canonical request of the question under the
-- pin, labelled or not (docs/09, section 3.2, M2), so its pair counts are no
-- longer bounded by the n scored items. Every other conjunct of 0014's rule is
-- kept, word for word, and the flip counts keep being counts.

-- =========================================================================
-- Who wrote each finding, and what was raised stays raised
-- =========================================================================
ALTER TABLE findings
    ADD COLUMN origin TEXT NOT NULL DEFAULT 'unknown',
    ADD COLUMN source_request_id BIGINT REFERENCES jev_requests (id);

-- The default existed to give the rows already stored 'unknown', which is
-- what it means: raised before 0015, by a writer nobody can now prove. Every
-- row from here on names its writer, or the insert fails.
ALTER TABLE findings ALTER COLUMN origin DROP DEFAULT;

ALTER TABLE findings
    ADD CONSTRAINT findings_origin_check
        CHECK (origin IN ('unknown', 'model', 'operator', 'jev')),
    -- A finding Jev's answer raised says so in its raiser, and only it does.
    ADD CONSTRAINT findings_jev_is_raised_by_jev
        CHECK ((origin = 'jev') = (raised_by LIKE 'jev:%')),
    -- It names the request it rests on, and only it does. What that request
    -- must be is the trigger's below: this CHECK only says one is named.
    ADD CONSTRAINT findings_jev_names_its_request
        CHECK ((origin = 'jev') = (source_request_id IS NOT NULL)),
    -- It can never block, whatever VETO_ROLES holds.
    ADD CONSTRAINT findings_jev_never_blocks
        CHECK (origin <> 'jev' OR severity IN ('low', 'medium')),
    -- It belongs to a candidate.
    ADD CONSTRAINT findings_jev_is_on_a_candidate
        CHECK (origin <> 'jev' OR candidate_id IS NOT NULL);

-- One finding per candidate per answer, so a retried follow-up adds nothing.
CREATE UNIQUE INDEX IF NOT EXISTS findings_one_per_jev_answer
    ON findings (candidate_id, raised_by, source_request_id)
    WHERE origin = 'jev';

CREATE OR REPLACE FUNCTION findings_origin_is_known() RETURNS trigger AS $$
BEGIN
    IF NEW.origin IS NOT DISTINCT FROM 'unknown' THEN
        RAISE EXCEPTION
            'a finding raised from migration 0015 on names its writer (finding %)',
            NEW.ref;
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;
CREATE TRIGGER trg_findings_origin_is_known
    BEFORE INSERT ON findings
    FOR EACH ROW EXECUTE FUNCTION findings_origin_is_known();

-- (revised: D-HMB-11) A Jev finding rests on a valid `true` to a canonical
-- guardrail.card request, as jev_signals_rest_on_their_answer holds a signal
-- to its answer. Refused here rather than left to the foreign key, which
-- checks later, with a newer snapshot.
CREATE OR REPLACE FUNCTION findings_jev_rests_on_its_answer() RETURNS trigger AS $$
DECLARE
    origin RECORD;
BEGIN
    IF NEW.origin IS DISTINCT FROM 'jev' THEN
        RETURN NEW;
    END IF;
    SELECT r.status, r.lane, r.question_set
      INTO origin
      FROM jev_requests r
     WHERE r.id = NEW.source_request_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'findings: request % is not visible to this transaction',
            NEW.source_request_id
            USING ERRCODE = 'foreign_key_violation';
    END IF;
    IF NOT (origin.status = 'ok'
            AND origin.lane <> 'probe'
            AND origin.question_set = 'guardrail.card'
            AND NEW.raised_by = 'jev:' || origin.question_set
            AND EXISTS (SELECT 1 FROM jev_answers a
                         WHERE a.request_id = NEW.source_request_id
                           AND a.question_key = 'performance_claim'
                           AND a.valid
                           AND a.argmax = 'true'))
    THEN
        RAISE EXCEPTION
            'findings: a Jev finding rests on a valid true answer to a canonical guardrail.card request (request %)',
            NEW.source_request_id;
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;
CREATE TRIGGER trg_findings_jev_rests_on_its_answer
    BEFORE INSERT ON findings
    FOR EACH ROW EXECUTE FUNCTION findings_jev_rests_on_its_answer();

-- Only the closure columns change, and a closed finding is never reopened;
-- 0008's CHECK still needs an operator to close, and admits `open` always,
-- which is why the reopen is refused here (revised: D-SAFE-6). Compared
-- whole, so a column a later migration adds is covered.
CREATE OR REPLACE FUNCTION findings_keep_what_was_raised() RETURNS trigger AS $$
BEGIN
    IF (to_jsonb(NEW) - ARRAY['status', 'closed_at', 'closed_by', 'close_note'])
       IS DISTINCT FROM
       (to_jsonb(OLD) - ARRAY['status', 'closed_at', 'closed_by', 'close_note'])
    THEN
        RAISE EXCEPTION 'a finding changes only by its closure (finding %)', OLD.ref;
    END IF;
    IF OLD.status IS DISTINCT FROM 'open' AND NEW.status IS NOT DISTINCT FROM 'open' THEN
        RAISE EXCEPTION 'a closed finding is never reopened (finding %)', OLD.ref;
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;
CREATE TRIGGER trg_findings_keep_what_was_raised
    BEFORE UPDATE ON findings
    FOR EACH ROW EXECUTE FUNCTION findings_keep_what_was_raised();

-- (revised: D-SAFE-6) What was raised stays raised: no writer removes a
-- finding, a blocking veto included, and a candidate's delete, which would
-- cascade to its findings, fails with them. Raised rather than skipped, as
-- the Jev ledger's refusals are, and TRUNCATE by a statement trigger, which a
-- row trigger never sees.
CREATE OR REPLACE FUNCTION findings_refuse_removal() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'findings keeps what was raised: % is refused', TG_OP
        USING HINT = 'Close the finding instead; only an operator can.';
END $$ LANGUAGE plpgsql;
CREATE TRIGGER trg_findings_no_delete
    BEFORE DELETE ON findings
    FOR EACH ROW EXECUTE FUNCTION findings_refuse_removal();
CREATE TRIGGER trg_findings_no_truncate
    BEFORE TRUNCATE ON findings
    FOR EACH STATEMENT EXECUTE FUNCTION findings_refuse_removal();

-- =========================================================================
-- The card check's arming switch, off
-- =========================================================================
INSERT INTO system_flags (key, value, updated_by)
VALUES ('jev_arm_card_check', 'false'::JSONB, 'migration')
ON CONFLICT (key) DO NOTHING;

-- =========================================================================
-- Provenance `system` (revised: D-SAFE-5): this system's own records,
-- computed in code, which can quote an outsider. A request may carry it; a
-- signal may not, so jev_signals_provenance_check is left as 0013 wrote it,
-- and jev_signals_rest_on_their_answer, which holds a signal's provenance to
-- its request's, can never admit a signal on a `system` request.
-- =========================================================================
ALTER TABLE jev_requests DROP CONSTRAINT jev_requests_provenance_check;
ALTER TABLE jev_requests ADD CONSTRAINT jev_requests_provenance_check
    CHECK (provenance IN ('web', 'internal', 'operator', 'model', 'system'));

-- =========================================================================
-- Plan v2 (M2): a flip rate counts the set's population, so its pair counts
-- are no longer bounded by the n scored items. Every other conjunct of
-- 0014's rule is kept, word for word.
-- =========================================================================
ALTER TABLE jev_evaluations
    DROP CONSTRAINT jev_evaluations_counts_within_n,
    ADD CONSTRAINT jev_evaluations_counts_within_n CHECK (
        n_valid BETWEEN 0 AND n
        AND n_escape BETWEEN 0 AND n
        AND n_invalid BETWEEN 0 AND n
        AND n_not_asked BETWEEN 0 AND n
        AND n_distinct_states BETWEEN 0 AND n
        AND n_at_threshold BETWEEN 0 AND n
        AND labeller_agreement_n BETWEEN 0 AND n
        AND vs_majority_jev_right_only >= 0
        AND vs_majority_baseline_right_only >= 0
        AND vs_majority_jev_right_only + vs_majority_baseline_right_only <= n
        AND vs_keyword_jev_right_only >= 0
        AND vs_keyword_baseline_right_only >= 0
        AND vs_keyword_jev_right_only + vs_keyword_baseline_right_only <= n
    ),
    ADD CONSTRAINT jev_evaluations_flip_counts_are_counts CHECK (
        flip_rate_n >= 0
        AND flip_rate_low_margin_n >= 0
        AND flip_rate_near_threshold_n >= 0
        AND flip_rate_not_compared >= 0
        AND flip_rate_low_margin_not_compared >= 0
        AND flip_rate_near_threshold_not_compared >= 0
    );

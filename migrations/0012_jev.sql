-- 0012_jev.sql
--
-- The Jev ledger, and the switches that keep it dark.
--
-- Jev is TypeSafe AI's "System One" model: it takes a piece of state and a set
-- of typed questions and returns a probability for each. Phase B of
-- docs/08-jev-integration.md builds everything needed to make one recorded,
-- validated call, and switches none of it on. Nothing on the order path reads
-- these tables, and nothing here lets anything do so.
--
-- One fact about the model shapes almost every rule below: Jev is not
-- deterministic. There is no seed, no temperature and no idempotency key, and
-- byte-identical requests have been seen to flip a label. An answer is an event
-- that happened once, not a function that can be called again to check it, so
-- the only honest way to use one is to record it once and replay the record
-- forever. That makes these tables a ledger, and a ledger is worth exactly as
-- much as the guarantee that nobody can tidy it.
--
-- Append-only, loudly
-- ~~~~~~~~~~~~~~~~~~~
-- Every Jev table refuses UPDATE, DELETE and TRUNCATE with an exception.
-- `hypotheses` turns a DELETE into a silent no-op, because there the property
-- wanted is only that the row is still there afterwards. Here a caller editing
-- an answer is rewriting what the model said, and should hear so at once rather
-- than believe it succeeded. TRUNCATE is refused as well because a row trigger
-- never sees it: "cannot be deleted a row at a time" is not the guarantee
-- "cannot be deleted".
--
-- `web_documents` allows exactly one change: `quarantined` from false to true,
-- with a reason, touching nothing else. Quarantine is one-way for the reason a
-- model cannot close its own finding. A document that carried instructions
-- once is read again on the next pass, and a screen it could talk its way back
-- out of is not a screen.
--
-- The database's clock, not the writer's
-- ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
-- `available_at` on `jev_requests` and `jev_signals` is overwritten by a BEFORE
-- INSERT trigger, whatever the caller passes. It answers "from when could
-- anything have read this", and a column the writer chooses cannot answer that:
-- a backfilled signal stamped with yesterday's date is a look-ahead with a
-- plausible face. The stamp is `clock_timestamp()`, the moment of the insert,
-- rather than `now()`, the moment the transaction began, because a transaction
-- held open across a decision cutoff would otherwise date a row before it
-- existed. Later is the safe direction: it can turn a live signal into a
-- backfilled one and never the reverse. A row is readable only once its
-- transaction commits, which is later again, so even this is a lower bound.
--
-- `jev_signals.backfilled` is generated from that stamp and the decision
-- cutoff, so whether a signal was live is derived by the database and written
-- by nobody. Postgres computes a generated column after the BEFORE triggers
-- have run, which is what makes it read the stamp rather than the value the
-- caller offered.
--
-- One operational consequence: a data-only logical restore fires the stamp and
-- rewrites every `available_at` to the moment of the restore. Restore data with
-- `--disable-triggers`. A full restore creates the triggers after loading the
-- rows, and a physical backup never runs them.
--
-- Record once
-- ~~~~~~~~~~~
-- `jev_requests_canonical` allows one `ok` row per request hash. The probe lane
-- is outside it, because asking identical questions again is the probe's whole
-- purpose: it measures how often the answer moves. Rows that are not `ok` are
-- outside it too, because a failure is an event to record rather than an answer
-- to replay, and a request that failed yesterday may be asked again today.
--
-- `questions` is `json`, not `jsonb`. `jsonb` keeps object keys in an order of
-- its own, and the order of a question's options is part of the question: it is
-- inside the request hash, and reordering the options of an ambiguous question
-- has been seen to move its probabilities. A record that reordered them would
-- describe a request nobody sent, and its hash would no longer recompute from
-- its own row. `state` stays `jsonb`: its keys are sorted before it is hashed,
-- so their order carries nothing.
--
-- A row whose status came from validating a response — `ok` or `invalid` —
-- carries a 2xx status and the body it was validated from. The plain
-- comparison would admit a NULL status, because a CHECK that evaluates to NULL
-- passes, so the constraint says IS NOT NULL as well. A request that could not
-- be made, a 422 among them, is an `error`: `invalid` is a fact about Jev's
-- answer, and a malformed request of ours recorded as one would count against
-- the model on the status page. An `ok` row was answered by the model that was
-- asked. The response names its model and it can differ from the pin; the
-- validator refuses a mismatch, and this makes the canonical record unable to
-- hold one anyway, since a replay would present it as the pinned model's
-- answer.
--
-- A refused row records a request that was never sent, so it got no response:
-- the daily budget counts only rows that record a call, and a call recorded as
-- refused would be one the budget never saw. And nothing a response carries —
-- a body, a request id, the model that answered — is stored without the status
-- of the response it came in. The status is what tells "no response at all"
-- from "a response without the request-id header", and a body with no response
-- could only be text this system wrote itself, such as an exception message:
-- SDK releases before 0.7.1 could echo the API key into one.
--
-- What an answer must be to count
-- ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
-- An answer that fails validation is stored with its reason and read as not
-- measured, never as zero. The schema holds the other side of that line: a row
-- marked valid is a measurement, so it carries its value, the argmax and margin
-- this system recomputed, and no reason; and a valid Choice is its own argmax.
-- On `jev-1.13.0` the vendor's `choice` is sometimes 0.01 below another
-- option's probability (SDK issue #15). The validator refuses those, and the
-- CHECK is there so that a validator which stopped refusing them could not
-- write one as valid.
--
-- A signal is where an answer would reach the engine, from phase F, so what a
-- signal says about its origin is checked against the request it came from
-- rather than taken on its writer's word. The lane, the provenance and the
-- pack must be the request's own, and `measured` needs a valid answer to a
-- canonical request: `ok`, outside the probe lane, answered by the model the
-- signal names. The decision path's loader is to trust
-- `provenance = 'internal'`, and a provenance the writer could simply claim
-- would reopen the prompt-injection route that filter exists to close. A
-- mismatch raises rather than being corrected, like every other refusal here:
-- a writer that got its origin wrong has a bug worth hearing about.
--
-- Evidence that remembers where it came from
-- ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
-- `candidates.evidence_uses_model_signals` is set once and never cleared, by
-- trigger. `evidence_is_synthetic` means the same by convention; this one is a
-- schema fact from the start, because evidence a model's answers shaped does
-- not become clean when a later run happens not to use them.
--
-- `backtest_runs` and `walkforward_runs` gain signal-provenance columns: how
-- many of the signals served were live, backfilled after the model's release,
-- and backfilled before it, and which models and packs served them. NULL means
-- the run used no model signal, so the five are all NULL or all present. A run
-- that recorded its live signals and not its backfilled ones has told half of
-- the one thing these columns exist to say.
--
-- `deployments.evidence_class` is `walkforward`, which every deployment is
-- today, or `forward_experiment`: one admitted on evidence collected going
-- forward, because a walk-forward over historical Jev labels is not a clean test
-- when the model's weights may already know the history. A forward experiment
-- is paper only and never on `default`, the owner the worker trades, by CHECK,
-- so relaxing either takes a new migration rather than an UPDATE.
--
-- Switches, all off
-- ~~~~~~~~~~~~~~~~~
-- Seeded rather than left absent, and read fail-closed by
-- src/programme/flags.py exactly like `programme_enabled`: a missing row, an
-- unreadable value or a database error reads as off, and a model the catalogue
-- refuses means no call. The master switch and every area start off. The model
-- is pinned to `jev-1.13.0` and never an alias such as `jev-latest`, whose
-- answers can change with nothing here changing. The budget of 500 requests a
-- day bounds a runaway loop rather than a bill: at the $0.042 per million input
-- tokens published when this was written, 500 requests would cost about $1.18
-- even if every one reached the 56,000-token ceiling this repository allows.
-- The state ceiling of 8,000 tokens sits far below the vendor's 32,000 for
-- state plus the longest question, so an oversized state is refused here rather
-- than sent. Hypotheses and findings go as titles only until an operator
-- switches `jev_send_internal_detail` on.

-- =========================================================================
-- Shared trigger functions
-- =========================================================================

-- Raises rather than skipping. Used as a row trigger on UPDATE and DELETE and
-- as a statement trigger on TRUNCATE, so TG_OP names whichever was tried.
CREATE OR REPLACE FUNCTION jev_refuse_change()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION '% is append-only: % is refused', TG_TABLE_NAME, TG_OP
        USING HINT = 'The ledger keeps what happened. Record a new row instead.';
END;
$$ LANGUAGE plpgsql;

-- The moment of the insert, whatever the caller passed. See the header for why
-- this is clock_timestamp() and not now().
CREATE OR REPLACE FUNCTION jev_stamp_available_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.available_at := clock_timestamp();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- =========================================================================
-- Requests: every question put to Jev, and every refusal to put one
-- =========================================================================

CREATE TABLE IF NOT EXISTS jev_requests (
    id                   BIGSERIAL PRIMARY KEY,
    -- sha256 of the canonical {model, state, questions}: state keys sorted,
    -- question and option order preserved. The key a replay is found by.
    request_hash         TEXT NOT NULL,
    state_hash           TEXT NOT NULL,
    -- Which versioned question set asked, and the hash of its exact text, so a
    -- stored answer is tied to the wording that produced it.
    question_set         TEXT NOT NULL,
    question_set_version INT  NOT NULL,
    pack_hash            TEXT NOT NULL,
    lane                 TEXT NOT NULL,
    -- Who could have written the state: the open web, this system's own code,
    -- or an operator. The decision path's loader, from phase F, reads
    -- `internal` alone.
    provenance           TEXT NOT NULL,
    subject_type         TEXT NOT NULL,
    subject_id           TEXT NOT NULL,
    -- The instant the state describes, which is not the instant it was sent.
    as_of                TIMESTAMPTZ NOT NULL,
    state                JSONB NOT NULL,
    -- json, not jsonb: see the header. Option order is part of the request.
    questions            JSON  NOT NULL,
    model_requested      TEXT NOT NULL,
    -- The model the response says answered. It can differ from the pin, which
    -- is why both are kept and the validator compares them.
    model_answered       TEXT,
    -- NULL means no request id came back: there was no HTTP response at all,
    -- or there was one without the header. `http_status` tells the two apart.
    vendor_request_id    TEXT,
    -- NULL only when there was no HTTP response.
    http_status          INT,
    status               TEXT NOT NULL,
    error_class          TEXT,
    error_kind           TEXT,
    -- The response body, verbatim. A 403 whose body is not JSON, possibly a
    -- content block, has to survive as exactly what arrived.
    raw_body             TEXT,
    input_tokens         INT,
    output_tokens        INT,
    latency_ms           INT,
    requested_at         TIMESTAMPTZ NOT NULL,
    -- Overwritten on insert by jev_stamp_available_at().
    available_at         TIMESTAMPTZ NOT NULL,

    CONSTRAINT jev_requests_lane_check CHECK (lane IN (
        'research', 'guardrail', 'findings', 'ops', 'signals', 'decision', 'probe'
    )),
    CONSTRAINT jev_requests_provenance_check
        CHECK (provenance IN ('web', 'internal', 'operator')),
    CONSTRAINT jev_requests_status_check CHECK (status IN (
        'ok', 'invalid', 'error', 'refused_budget', 'refused_limits', 'refused_model'
    )),
    CONSTRAINT jev_requests_validated_has_its_body CHECK (
        status NOT IN ('ok', 'invalid')
        OR (http_status IS NOT NULL
            AND http_status BETWEEN 200 AND 299
            AND raw_body IS NOT NULL)
    ),
    CONSTRAINT jev_requests_ok_is_the_model_asked CHECK (
        status <> 'ok' OR model_answered IS NOT DISTINCT FROM model_requested
    ),
    CONSTRAINT jev_requests_refused_got_no_response CHECK (
        status NOT IN ('refused_budget', 'refused_limits', 'refused_model')
        OR http_status IS NULL
    ),
    CONSTRAINT jev_requests_evidence_needs_a_response CHECK (
        http_status IS NOT NULL
        OR (vendor_request_id IS NULL AND raw_body IS NULL AND model_answered IS NULL)
    )
);

-- Record once, replay forever. See the header for what is outside it and why.
CREATE UNIQUE INDEX IF NOT EXISTS jev_requests_canonical
    ON jev_requests (request_hash)
    WHERE status = 'ok' AND lane <> 'probe';

-- Every row for a request, canonical or not: the probe lane's flip rate is a
-- comparison between them.
CREATE INDEX IF NOT EXISTS idx_jev_requests_hash
    ON jev_requests (request_hash);
-- The daily budget and the status page both count from UTC midnight.
CREATE INDEX IF NOT EXISTS idx_jev_requests_available_at
    ON jev_requests (available_at);
CREATE INDEX IF NOT EXISTS idx_jev_requests_lane
    ON jev_requests (lane, id DESC);

DROP TRIGGER IF EXISTS trg_jev_requests_available_at ON jev_requests;
CREATE TRIGGER trg_jev_requests_available_at
    BEFORE INSERT ON jev_requests
    FOR EACH ROW EXECUTE FUNCTION jev_stamp_available_at();

DROP TRIGGER IF EXISTS trg_jev_requests_append_only ON jev_requests;
CREATE TRIGGER trg_jev_requests_append_only
    BEFORE UPDATE OR DELETE ON jev_requests
    FOR EACH ROW EXECUTE FUNCTION jev_refuse_change();

DROP TRIGGER IF EXISTS trg_jev_requests_no_truncate ON jev_requests;
CREATE TRIGGER trg_jev_requests_no_truncate
    BEFORE TRUNCATE ON jev_requests
    FOR EACH STATEMENT EXECUTE FUNCTION jev_refuse_change();

-- =========================================================================
-- Answers: one row per question asked, valid or not
-- =========================================================================

CREATE TABLE IF NOT EXISTS jev_answers (
    id             BIGSERIAL PRIMARY KEY,
    request_id     BIGINT NOT NULL REFERENCES jev_requests(id),
    question_key   TEXT NOT NULL,
    question_type  TEXT NOT NULL,
    noul           DOUBLE PRECISION,
    choice         TEXT,
    score          DOUBLE PRECISION,
    probabilities  JSONB,
    -- How concentrated the distribution is, not how likely the answer is to be
    -- right. Jev's Noul has no confidence at all, so a Noul row holds none: a
    -- number here would be one the vendor never sent.
    confidence     DOUBLE PRECISION,
    -- Recomputed by this system from the probabilities, never copied from the
    -- vendor: its `choice` is sometimes not the argmax (SDK issue #15).
    argmax         TEXT,
    margin         DOUBLE PRECISION,
    -- An invalid answer is recorded with its reason and read downstream as not
    -- measured, never as zero.
    valid          BOOLEAN NOT NULL,
    invalid_reason TEXT,

    CONSTRAINT jev_answers_one_per_question UNIQUE (request_id, question_key),
    CONSTRAINT jev_answers_question_type_check
        CHECK (question_type IN ('noul', 'choice', 'score')),
    CONSTRAINT jev_answers_invalid_says_why CHECK (
        valid OR btrim(COALESCE(invalid_reason, '')) <> ''
    ),
    -- A valid answer with a reason would read as a warning nobody acted on.
    CONSTRAINT jev_answers_reason_means_invalid
        CHECK (NOT valid OR invalid_reason IS NULL),
    CONSTRAINT jev_answers_noul_has_no_confidence
        CHECK (question_type <> 'noul' OR confidence IS NULL),
    -- Valid means measured: the value, and what this system recomputed from it.
    -- A valid row with any of these NULL would be a measurement of nothing.
    CONSTRAINT jev_answers_valid_is_measured CHECK (
        NOT valid
        OR (argmax IS NOT NULL
            AND margin IS NOT NULL
            AND CASE question_type
                    WHEN 'noul' THEN noul IS NOT NULL
                    WHEN 'choice' THEN choice IS NOT NULL
                                       AND probabilities IS NOT NULL
                                       AND confidence IS NOT NULL
                    WHEN 'score' THEN score IS NOT NULL
                                      AND probabilities IS NOT NULL
                                      AND confidence IS NOT NULL
                    ELSE FALSE
                END)
    ),
    -- See the header: SDK issue #15.
    CONSTRAINT jev_answers_valid_choice_is_its_argmax CHECK (
        NOT valid OR question_type <> 'choice' OR choice IS NOT DISTINCT FROM argmax
    )
);

DROP TRIGGER IF EXISTS trg_jev_answers_append_only ON jev_answers;
CREATE TRIGGER trg_jev_answers_append_only
    BEFORE UPDATE OR DELETE ON jev_answers
    FOR EACH ROW EXECUTE FUNCTION jev_refuse_change();

DROP TRIGGER IF EXISTS trg_jev_answers_no_truncate ON jev_answers;
CREATE TRIGGER trg_jev_answers_no_truncate
    BEFORE TRUNCATE ON jev_answers
    FOR EACH STATEMENT EXECUTE FUNCTION jev_refuse_change();

-- =========================================================================
-- Web documents: what the research lane read, as it was read
-- =========================================================================

-- Filled from phase C. Excerpts only, never whole pages, one row per distinct
-- content per source, so a page that changes is a new snapshot rather than an
-- edit of the old one.
CREATE TABLE IF NOT EXISTS web_documents (
    id                BIGSERIAL PRIMARY KEY,
    source            TEXT NOT NULL,
    url               TEXT NOT NULL,
    fetched_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at      TIMESTAMPTZ,
    content_sha256    TEXT NOT NULL,
    title             TEXT,
    excerpt           TEXT NOT NULL,
    quarantined       BOOLEAN NOT NULL DEFAULT FALSE,
    quarantine_reason TEXT,

    CONSTRAINT web_documents_one_snapshot UNIQUE (source, content_sha256),
    -- A quarantine says why, and only a quarantine has a reason: a reason on a
    -- document still in use would read as a warning nobody acted on.
    CONSTRAINT web_documents_quarantine_says_why CHECK (
        NOT quarantined OR btrim(COALESCE(quarantine_reason, '')) <> ''
    ),
    CONSTRAINT web_documents_reason_means_quarantined
        CHECK (quarantined OR quarantine_reason IS NULL)
);

-- The one permitted UPDATE. Everything else about the row is compared whole,
-- through to_jsonb, so a column added by a later migration is protected
-- without anyone remembering to list it here.
CREATE OR REPLACE FUNCTION web_documents_quarantine_only()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.quarantined IS FALSE
       AND NEW.quarantined IS TRUE
       AND btrim(COALESCE(NEW.quarantine_reason, '')) <> ''
       AND (to_jsonb(NEW) - 'quarantined'::text - 'quarantine_reason'::text)
           = (to_jsonb(OLD) - 'quarantined'::text - 'quarantine_reason'::text)
    THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'web_documents is append-only: the one change allowed is to quarantine an unquarantined document, with a reason (document %)', OLD.id
        USING HINT = 'Quarantine is one-way. A changed page is a new snapshot.';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_web_documents_quarantine_only ON web_documents;
CREATE TRIGGER trg_web_documents_quarantine_only
    BEFORE UPDATE ON web_documents
    FOR EACH ROW EXECUTE FUNCTION web_documents_quarantine_only();

DROP TRIGGER IF EXISTS trg_web_documents_no_delete ON web_documents;
CREATE TRIGGER trg_web_documents_no_delete
    BEFORE DELETE ON web_documents
    FOR EACH ROW EXECUTE FUNCTION jev_refuse_change();

DROP TRIGGER IF EXISTS trg_web_documents_no_truncate ON web_documents;
CREATE TRIGGER trg_web_documents_no_truncate
    BEFORE TRUNCATE ON web_documents
    FOR EACH STATEMENT EXECUTE FUNCTION jev_refuse_change();

-- =========================================================================
-- Signals: what the engine may one day read, frozen as recorded
-- =========================================================================

-- Written from phase C, read from phase F, and only ever through one loader
-- whose filter is fixed: lane 'decision', provenance 'internal', available by
-- the decision's cutoff. Frozen outright, because a signal that could be edited
-- after its cutoff would be a look-ahead with a row id.
CREATE TABLE IF NOT EXISTS jev_signals (
    signal          TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    session         DATE NOT NULL,
    -- `measured` is the only status that carries a value. The others are why
    -- there is none, and each is read as not measured, never as a default.
    status          TEXT NOT NULL,
    value           TEXT,
    answer_id       BIGINT REFERENCES jev_answers(id),
    -- These four must match the answer's request, checked on insert by
    -- jev_signals_rest_on_their_answer().
    lane            TEXT NOT NULL,
    provenance      TEXT NOT NULL,
    pack_hash       TEXT NOT NULL,
    model           TEXT NOT NULL,
    -- The latest moment the signal could have been known and still used by the
    -- decision for `session`.
    decision_cutoff TIMESTAMPTZ NOT NULL,
    -- Overwritten on insert by jev_stamp_available_at().
    available_at    TIMESTAMPTZ NOT NULL,
    backfilled      BOOLEAN GENERATED ALWAYS AS (available_at > decision_cutoff) STORED,

    PRIMARY KEY (signal, symbol, session),
    CONSTRAINT jev_signals_status_check
        CHECK (status IN ('measured', 'abstain', 'invalid', 'missing')),
    -- The same vocabularies as jev_requests. The loader matches them exactly,
    -- and a lane spelt any other way would be a signal that silently never
    -- loads.
    CONSTRAINT jev_signals_lane_check CHECK (lane IN (
        'research', 'guardrail', 'findings', 'ops', 'signals', 'decision', 'probe'
    )),
    CONSTRAINT jev_signals_provenance_check
        CHECK (provenance IN ('web', 'internal', 'operator')),
    CONSTRAINT jev_signals_measured_has_its_answer CHECK (
        status <> 'measured' OR (value IS NOT NULL AND answer_id IS NOT NULL)
    )
);

-- What a signal says about where it came from is checked against where it came
-- from. See the header. Both tables it reads are frozen, so a check made once,
-- on insert, holds for the life of the row.
CREATE OR REPLACE FUNCTION jev_signals_rest_on_their_answer()
RETURNS TRIGGER AS $$
DECLARE
    origin RECORD;
BEGIN
    -- No answer, no origin to compare: `missing` and friends carry no value,
    -- and the CHECK refuses a `measured` signal without one.
    IF NEW.answer_id IS NULL THEN
        RETURN NEW;
    END IF;

    SELECT a.valid, r.status, r.lane, r.provenance, r.pack_hash, r.model_answered
      INTO origin
      FROM jev_answers a
      JOIN jev_requests r ON r.id = a.request_id
     WHERE a.id = NEW.answer_id;
    IF NOT FOUND THEN
        -- The foreign key reports a missing answer in its own words.
        RETURN NEW;
    END IF;

    IF NEW.lane IS DISTINCT FROM origin.lane
       OR NEW.provenance IS DISTINCT FROM origin.provenance
       OR NEW.pack_hash IS DISTINCT FROM origin.pack_hash
    THEN
        RAISE EXCEPTION 'jev_signals: a signal carries the lane, provenance and pack of the request its answer came from (answer %)', NEW.answer_id
            USING HINT = 'Copy them from the request; they are not the writer''s to choose.';
    END IF;

    IF NEW.status = 'measured'
       AND NOT (origin.valid
                AND origin.status = 'ok'
                AND origin.lane <> 'probe'
                AND NEW.model IS NOT DISTINCT FROM origin.model_answered)
    THEN
        RAISE EXCEPTION 'jev_signals: only a valid answer to a canonical request, from the model the signal names, is a measurement (answer %)', NEW.answer_id
            USING HINT = 'Record it as invalid or abstain: not measured, never a default.';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_jev_signals_available_at ON jev_signals;
CREATE TRIGGER trg_jev_signals_available_at
    BEFORE INSERT ON jev_signals
    FOR EACH ROW EXECUTE FUNCTION jev_stamp_available_at();

DROP TRIGGER IF EXISTS trg_jev_signals_rest_on_their_answer ON jev_signals;
CREATE TRIGGER trg_jev_signals_rest_on_their_answer
    BEFORE INSERT ON jev_signals
    FOR EACH ROW EXECUTE FUNCTION jev_signals_rest_on_their_answer();

DROP TRIGGER IF EXISTS trg_jev_signals_append_only ON jev_signals;
CREATE TRIGGER trg_jev_signals_append_only
    BEFORE UPDATE OR DELETE ON jev_signals
    FOR EACH ROW EXECUTE FUNCTION jev_refuse_change();

DROP TRIGGER IF EXISTS trg_jev_signals_no_truncate ON jev_signals;
CREATE TRIGGER trg_jev_signals_no_truncate
    BEFORE TRUNCATE ON jev_signals
    FOR EACH STATEMENT EXECUTE FUNCTION jev_refuse_change();

-- =========================================================================
-- Labels: the ground truth a threshold is measured against
-- =========================================================================

-- Labelled by a person, `operator:<name>`, or by a dataset at a fixed hash,
-- `source:<dataset>@<sha>`. Never by a model: a label Jev wrote about its own
-- answers would measure agreement with itself. A prefix with nothing after it
-- is refused, because a label attributed to nobody is not attributed.
CREATE TABLE IF NOT EXISTS jev_labels (
    id                   BIGSERIAL PRIMARY KEY,
    question_set         TEXT NOT NULL,
    question_set_version INT  NOT NULL,
    question_key         TEXT NOT NULL,
    subject_type         TEXT NOT NULL,
    subject_id           TEXT NOT NULL,
    label                TEXT NOT NULL,
    labelled_by          TEXT NOT NULL,
    labelled_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    note                 TEXT,

    CONSTRAINT jev_labels_by_a_person_or_a_dataset CHECK (
        labelled_by LIKE 'operator:_%' OR labelled_by LIKE 'source:_%@_%'
    ),
    -- One label per labeller per item. Two labellers may disagree, and the
    -- disagreement is itself a measurement worth keeping.
    CONSTRAINT jev_labels_once_per_labeller UNIQUE (
        question_set, question_set_version, question_key,
        subject_type, subject_id, labelled_by
    )
);

DROP TRIGGER IF EXISTS trg_jev_labels_append_only ON jev_labels;
CREATE TRIGGER trg_jev_labels_append_only
    BEFORE UPDATE OR DELETE ON jev_labels
    FOR EACH ROW EXECUTE FUNCTION jev_refuse_change();

DROP TRIGGER IF EXISTS trg_jev_labels_no_truncate ON jev_labels;
CREATE TRIGGER trg_jev_labels_no_truncate
    BEFORE TRUNCATE ON jev_labels
    FOR EACH STATEMENT EXECUTE FUNCTION jev_refuse_change();

-- =========================================================================
-- Evaluations: what a threshold is allowed to rest on
-- =========================================================================

-- Per question set, question and model, on this repository's own labels. No
-- threshold may be used until one of these beats both baselines on enough
-- items; until then every lane is suggestion-only.
--
-- Every measurement is nullable, and NULL means not measured. Zero is a
-- measurement, and reporting an unmeasured flip rate or accuracy as 0.00 is the
-- flattering lie the honesty rules exist to prevent. `possibly_in_training` is
-- required rather than defaulted: an evaluation on data the model may have seen
-- is an upper bound, and has to say which it is.
CREATE TABLE IF NOT EXISTS jev_evaluations (
    id                         BIGSERIAL PRIMARY KEY,
    question_set               TEXT NOT NULL,
    question_set_version       INT  NOT NULL,
    question_key               TEXT NOT NULL,
    model                      TEXT NOT NULL,
    dataset_ref                TEXT NOT NULL,
    dataset_sha256             TEXT NOT NULL,
    possibly_in_training       BOOLEAN NOT NULL,
    n                          INT  NOT NULL,
    n_per_class                JSONB NOT NULL,
    accuracy                   DOUBLE PRECISION,
    accuracy_wilson_low        DOUBLE PRECISION,
    accuracy_wilson_high       DOUBLE PRECISION,
    balanced_accuracy          DOUBLE PRECISION,
    brier                      DOUBLE PRECISION,
    brier_ci_low               DOUBLE PRECISION,
    brier_ci_high              DOUBLE PRECISION,
    threshold                  DOUBLE PRECISION,
    coverage_at_threshold      DOUBLE PRECISION,
    majority_baseline_accuracy DOUBLE PRECISION,
    keyword_baseline_accuracy  DOUBLE PRECISION,
    flip_rate                  DOUBLE PRECISION,
    calibration_bins           JSONB,
    code_commit                TEXT NOT NULL,
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT jev_evaluations_n_check CHECK (n >= 0)
);

CREATE INDEX IF NOT EXISTS idx_jev_evaluations_lookup
    ON jev_evaluations (question_set, question_set_version, question_key, model,
                        created_at DESC);

DROP TRIGGER IF EXISTS trg_jev_evaluations_append_only ON jev_evaluations;
CREATE TRIGGER trg_jev_evaluations_append_only
    BEFORE UPDATE OR DELETE ON jev_evaluations
    FOR EACH ROW EXECUTE FUNCTION jev_refuse_change();

DROP TRIGGER IF EXISTS trg_jev_evaluations_no_truncate ON jev_evaluations;
CREATE TRIGGER trg_jev_evaluations_no_truncate
    BEFORE TRUNCATE ON jev_evaluations
    FOR EACH STATEMENT EXECUTE FUNCTION jev_refuse_change();

-- =========================================================================
-- Candidates: model-signal evidence is sticky
-- =========================================================================

ALTER TABLE candidates
    ADD COLUMN IF NOT EXISTS evidence_uses_model_signals BOOLEAN NOT NULL DEFAULT FALSE;

-- Raises rather than ignoring, for the reason the preregistration trigger in
-- 0007 does: a caller clearing it is attempting the one thing the column
-- exists to prevent. Setting it, and every other update, passes.
CREATE OR REPLACE FUNCTION candidates_model_signal_evidence_is_sticky()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.evidence_uses_model_signals IS TRUE
       AND NEW.evidence_uses_model_signals IS NOT TRUE THEN
        RAISE EXCEPTION
            'evidence_uses_model_signals cannot be cleared once set (candidate %)',
            OLD.id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_candidates_model_signal_evidence ON candidates;
CREATE TRIGGER trg_candidates_model_signal_evidence
    BEFORE UPDATE ON candidates
    FOR EACH ROW EXECUTE FUNCTION candidates_model_signal_evidence_is_sticky();

-- =========================================================================
-- Runs: which model signals a result was built on
-- =========================================================================

ALTER TABLE backtest_runs
    ADD COLUMN IF NOT EXISTS signals_live INT,
    ADD COLUMN IF NOT EXISTS signals_backfilled_post_release INT,
    ADD COLUMN IF NOT EXISTS signals_backfilled_pre_release INT,
    ADD COLUMN IF NOT EXISTS signal_models TEXT[],
    ADD COLUMN IF NOT EXISTS signal_pack_hashes TEXT[];

ALTER TABLE backtest_runs
    ADD CONSTRAINT backtest_runs_signal_provenance_whole CHECK (
        num_nulls(signals_live, signals_backfilled_post_release,
                  signals_backfilled_pre_release, signal_models,
                  signal_pack_hashes) IN (0, 5)
    ),
    ADD CONSTRAINT backtest_runs_signal_counts_non_negative CHECK (
        signals_live >= 0
        AND signals_backfilled_post_release >= 0
        AND signals_backfilled_pre_release >= 0
    );

ALTER TABLE walkforward_runs
    ADD COLUMN IF NOT EXISTS signals_live INT,
    ADD COLUMN IF NOT EXISTS signals_backfilled_post_release INT,
    ADD COLUMN IF NOT EXISTS signals_backfilled_pre_release INT,
    ADD COLUMN IF NOT EXISTS signal_models TEXT[],
    ADD COLUMN IF NOT EXISTS signal_pack_hashes TEXT[];

ALTER TABLE walkforward_runs
    ADD CONSTRAINT walkforward_runs_signal_provenance_whole CHECK (
        num_nulls(signals_live, signals_backfilled_post_release,
                  signals_backfilled_pre_release, signal_models,
                  signal_pack_hashes) IN (0, 5)
    ),
    ADD CONSTRAINT walkforward_runs_signal_counts_non_negative CHECK (
        signals_live >= 0
        AND signals_backfilled_post_release >= 0
        AND signals_backfilled_pre_release >= 0
    );

-- =========================================================================
-- Deployments: a forward experiment is paper, and never the operator's book
-- =========================================================================

ALTER TABLE deployments
    ADD COLUMN IF NOT EXISTS evidence_class TEXT NOT NULL DEFAULT 'walkforward';

ALTER TABLE deployments
    ADD CONSTRAINT deployments_evidence_class_check
        CHECK (evidence_class IN ('walkforward', 'forward_experiment')),
    ADD CONSTRAINT deployments_forward_experiment_is_paper CHECK (
        evidence_class <> 'forward_experiment'
        OR (mode = 'paper' AND owner_id <> 'default')
    );

-- =========================================================================
-- The switches, every one off
-- =========================================================================

INSERT INTO system_flags (key, value, updated_by, updated_at) VALUES
    ('jev_enabled',              'false'::jsonb,        'migration', NOW()),
    ('jev_model',                '"jev-1.13.0"'::jsonb, 'migration', NOW()),
    ('jev_area_research',        'false'::jsonb,        'migration', NOW()),
    ('jev_area_ops',             'false'::jsonb,        'migration', NOW()),
    ('jev_area_findings',        'false'::jsonb,        'migration', NOW()),
    ('jev_area_guardrails',      'false'::jsonb,        'migration', NOW()),
    ('jev_area_signals',         'false'::jsonb,        'migration', NOW()),
    ('jev_area_decisions',       'false'::jsonb,        'migration', NOW()),
    ('jev_daily_request_budget', '500'::jsonb,          'migration', NOW()),
    ('jev_max_state_tokens',     '8000'::jsonb,         'migration', NOW()),
    ('jev_send_internal_detail', 'false'::jsonb,        'migration', NOW())
ON CONFLICT (key) DO NOTHING;

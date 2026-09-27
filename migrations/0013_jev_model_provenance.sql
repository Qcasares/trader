-- 0013_jev_model_provenance.sql
--
-- Phase C of docs/08-jev-integration.md, its first pull request: a fourth
-- provenance, and the indexes the lane's new reads stand on. Additive only.
-- 0012 is applied and checksummed, so nothing in it is edited; every change it
-- needs is here.
--
-- Provenance `model`
-- ~~~~~~~~~~~~~~~~~~
-- 0012 knew three places a request's state could have come from: `web`, which
-- an outsider can write; `internal`, computed in code from this system's own
-- rows; and `operator`, typed by a person. Phase C will ask Jev about text the
-- programme's own generative model wrote — the titles of the hypotheses it
-- proposes — and that text is none of the three. Recorded as `internal` it
-- would pass the one filter the phase F signal loader is to trust, and that
-- loader must never have to know that `internal` sometimes means "written by
-- a generative model". So it is `model`, and `internal` keeps meaning computed
-- in code.
--
-- Each CHECK is dropped and added again under its own name, because
-- tests/integration/test_jev_schema.py reads the vocabulary back by that name,
-- and a constraint renamed here would be a vocabulary nobody checks. Every row
-- already stored carries one of the three older values, so the new constraints
-- validate on the rows they find. DDL fires no row trigger, so the append-only
-- triggers do not stand in the way: they refuse edits to rows, not to the
-- rules rows are held to.
--
-- The road's reads
-- ~~~~~~~~~~~~~~~~
-- `jev_lane.ask` now asks the ledger, before it sends anything, whether the
-- vendor has refused what it is about to send: an authentication failure
-- today, a 422 for this set, version and model, a content block on this very
-- text, and, for a web set, whether the text is quarantined and whether it has
-- a clean answer from the injection screen. Each has an index here, so a road
-- that grows a check per ask does not grow a scan per ask.
--
-- A document's address is its excerpt
-- ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
-- The web gate finds quarantined text by `content_sha256`, looking up the
-- sha256 of exactly the excerpt it is about to send (`jev_hash.text_sha256`).
-- A writer that hashed anything else — the text before normalising, the raw
-- title, the page — would leave a quarantined document invisible to the gate,
-- and the text in it would be sent. So the address is the excerpt's, by
-- CHECK, rather than by every future writer's care. `sha256` over the UTF-8
-- bytes, as hex, is what Python's `hashlib.sha256(text.encode()).hexdigest()`
-- writes. Added while `web_documents` is empty everywhere: nothing writes it
-- until phase C's web ingest.

ALTER TABLE jev_requests DROP CONSTRAINT jev_requests_provenance_check;
ALTER TABLE jev_requests ADD CONSTRAINT jev_requests_provenance_check
    CHECK (provenance IN ('web', 'internal', 'operator', 'model'));

ALTER TABLE jev_signals DROP CONSTRAINT jev_signals_provenance_check;
ALTER TABLE jev_signals ADD CONSTRAINT jev_signals_provenance_check
    CHECK (provenance IN ('web', 'internal', 'operator', 'model'));

-- A content block is remembered by the state it blocked, and a screen's
-- answer is found by the state it screened.
CREATE INDEX IF NOT EXISTS idx_jev_requests_state_hash
    ON jev_requests (state_hash);

-- The standing refusals: an authentication failure since UTC midnight, a 422
-- for a set, a content block. Partial, because nearly every row has no error.
CREATE INDEX IF NOT EXISTS idx_jev_requests_error_kind
    ON jev_requests (error_kind, available_at)
    WHERE error_kind IS NOT NULL;

-- What a set was asked about a subject: a 422's set and version, and from
-- phase C's later pull requests the join from a label to its answer, which
-- content-addressed subjects make exact.
CREATE INDEX IF NOT EXISTS idx_jev_requests_subject
    ON jev_requests (question_set, question_set_version, subject_type, subject_id);

-- Whether a text is quarantined, under any source. Partial, because the gate
-- reads quarantined documents only; the one-snapshot constraint, on
-- (source, content_sha256), cannot serve a lookup by content alone.
CREATE INDEX IF NOT EXISTS idx_web_documents_content_quarantined
    ON web_documents (content_sha256)
    WHERE quarantined;

ALTER TABLE web_documents ADD CONSTRAINT web_documents_content_is_its_excerpt
    CHECK (content_sha256 = encode(sha256(convert_to(excerpt, 'UTF8')), 'hex'));

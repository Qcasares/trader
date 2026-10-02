"""
jev_chips.py
------------
What phase E may show beside a finding, computed when the page is read and
stored nowhere: a suggested reviewer, a suggested severity, and a pointer to
an older finding the newer one repeats (docs/09, sections 6.1 and 6.4).

Pure: the standard library and ``jev_redact``, itself pure, and nothing else,
so the API may import it and a test may run every function on random
registers with no database. Nothing here reads the ledger, a finding or an
answer: phase E reads them and hands over what a chip is computed from. Phase
D shows no finding chip anywhere — the harness's ``suggestions`` prints a
finding's statuses, never a severity, route or duplicate chip (docs/09,
section 9.3) — so these are the functions phase E's contract binds, tested
now. The one chip phase D prints is code's for a failed job
(:func:`code_cause`, :func:`job_error_shape`): ``preview`` and
``suggestions`` show it beside each job, code's own table's entry and never
Jev's.

Friction, never its release
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Each chip can only add to what a reader weighs before closing a finding,
never take from it (docs/09, section 6.4, item 3):

* **A severity chip only escalates** (:func:`severity_chip`): it appears only
  where Jev's suggestion is more serious than the severity recorded. A lower
  suggestion offered beside a finding is advice to wave it through (design
  M5).
* **A route chip never argues against a veto** (:func:`route_chip`): on a
  finding that blocks, a suggested reviewer is shown only when the role it
  names holds a veto. A reviewer without one, beside a veto that blocks,
  would argue the veto was raised outside its role's mandate and invite a
  close as ``accepted`` or ``withdrawn`` (design M24, D-SAFE-3). On a finding
  that blocks nothing, any role may be suggested.
* **A duplicate chip points only from a newer finding to an older one, on the
  same candidate, that blocks at least as much** (:func:`duplicate_chips`),
  so closing every finding a duplicate chip marks unblocks nothing (design
  M4). Code's alone, by exact title: whether Jev should judge two titles the
  same is left open (docs/08 open item 71).

The escape and an answer that was not valid make no chip, and an unknown is
never shown as a value (item 5): what a missing chip means is phase E's to
say, as "not measured" or "Jev: unclear".

A chip is labels and numbers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A :class:`Chip` carries a role key, a severity or a finding's ref, the
probability and margin the answer gave, the set version, the model that
answered and the request it was recorded by — never a title, a detail or any
other text — and whether code or Jev made it, so phase E can tell the two
apart (item 4). ``tests/unit/test_jev_chips.py``.

The copies
~~~~~~~~~~
Which roles hold a veto and which severities block are ``gates``'s, and the
twelve roles and the four severities ``roles``'; both load pydantic, which
this module may not. The values are copied here, and
``tests/unit/test_jev_chips.py::TestTheCopies`` holds each equal to its
original, and :func:`blocks` to ``gates.FindingFact.blocks`` on every
combination, so a change there fails here until it is made in both.

Code first, for a failed job (phase D3)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Before Jev may be asked why a job failed, code reads the error:
:func:`code_cause` places it by :data:`JOB_ERROR_SHAPES`, the shapes this
system's own raise sites write, and returns ``None`` only for the error of a
triaged kind (``jev_redact.TRIAGED_KINDS``: research and ingest) that no shape
places — the residue, the one thing ``ops.job_error`` may be asked about, and
then only as a skeleton (``jev_redact.skeleton``), never the message, and only
one holding enough words of the vocabulary to be worth asking about
(:func:`residue_skeleton`, the one rule an error is read by wherever it may
become state) (docs/09, section 4.5). Every other kind's unplaced error is
``unclassified``: a venue's, the shadow replay's and the programme's own are
code's to place or no one's, and are never sent. The shapes are pinned by
:data:`GOLDEN_SHAPES_SHA256` and named, by their hash, in the ops set's plan.
A reconciliation discrepancy, a data-health alert and an ingest's partial
result are structured rows every field of which code computed, so their
chips (:func:`reconciliation_chip`, :func:`data_health_chips`,
:func:`ingest_chips`) are code's alone, and nothing about them is sent at
all. None of these corrects, retries or changes anything: a chip is a label.
``tests/unit/test_jev_chips.py::TestCodeFirst`` and
``::test_reconciliation_and_data_health_chips_cover_every_shape``.

The one module this one loads is ``jev_redact``, pure as this is, for the
triaged kinds and the input bound (``test_import_boundaries.py``).
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from src.programme import jev_redact

#: Roles whose finding stops a promotion: ``gates.VETO_ROLES``, copied.
VETO_ROLES: frozenset[str] = frozenset(
    {
        "independent_risk",
        "independent_validation",
        "compliance",
        "data_engineering",
        "platform",
        "operations",
        "adversarial_review",
    }
)

#: Severities that block: ``gates.BLOCKING_SEVERITIES``, copied.
BLOCKING_SEVERITIES: frozenset[str] = frozenset({"high", "critical"})

#: The severities a finding is recorded at, least serious first:
#: ``roles.SEVERITIES``, copied, in its order.
SEVERITIES: tuple[str, ...] = ("low", "medium", "high", "critical")

#: The twelve specialist roles, by key, in ``roles.ROLES``' order: the
#: options ``findings.owner`` suggests a reviewer from, its escape aside.
ROLE_KEYS: tuple[str, ...] = (
    "quant_research",
    "data_engineering",
    "machine_learning",
    "portfolio_construction",
    "independent_risk",
    "execution",
    "platform",
    "independent_validation",
    "compliance",
    "operations",
    "adversarial_review",
    "programme_director",
)

#: Who made a chip: Jev's answer, or code alone.
ChipSource = Literal["jev", "code"]

#: What a chip suggests: a reviewer, a severity, or an older finding.
ChipKind = Literal["route", "severity", "duplicate"]


@dataclass(frozen=True, slots=True)
class FindingView:
    """
    A finding as a chip reads it: what decides whether it blocks, its
    candidate, its title, which only :func:`duplicate_chips` compares and no
    chip carries, and when it was raised.
    """

    ref: str
    raised_by: str
    severity: str
    status: str
    candidate_id: str | None
    title: str
    opened_at: datetime


@dataclass(frozen=True, slots=True)
class Suggestion:
    """
    One Jev answer as a chip reads it: the option it chose (``None`` for an
    answer that chose none), whether it was valid, the probability of that
    option and the answer's margin, and where it came from — the set's
    version, the model that answered and the request it was recorded by.
    """

    value: str | None
    valid: bool
    probability: float | None
    margin: float | None
    question_set_version: int
    model_answered: str
    request_id: int


@dataclass(frozen=True, slots=True)
class Chip:
    """
    What phase E may show beside one finding: labels and numbers, and never
    text. ``value`` is a role key, a severity or, for a duplicate, the older
    finding's ref; the rest says what it rests on, ``None`` for a chip code
    made.
    """

    kind: ChipKind
    source: ChipSource
    finding_ref: str
    value: str
    probability: float | None = None
    margin: float | None = None
    question_set_version: int | None = None
    model_answered: str | None = None
    request_id: int | None = None


def blocks(finding: FindingView) -> bool:
    """
    Whether ``finding`` halts a promotion, by ``gates.FindingFact.blocks``'
    rule: open, high or critical, and raised by a role holding a veto.
    """
    return (
        finding.status == "open"
        and finding.severity in BLOCKING_SEVERITIES
        and finding.raised_by in VETO_ROLES
    )


def _from_jev(kind: ChipKind, finding: FindingView, answer: Suggestion) -> Chip:
    assert answer.value is not None
    return Chip(
        kind=kind,
        source="jev",
        finding_ref=finding.ref,
        value=answer.value,
        probability=answer.probability,
        margin=answer.margin,
        question_set_version=answer.question_set_version,
        model_answered=answer.model_answered,
        request_id=answer.request_id,
    )


def severity_chip(finding: FindingView, answer: Suggestion) -> Chip | None:
    """
    A suggested severity, only where it is more serious than the one
    recorded: a valid answer naming one of :data:`SEVERITIES` ranked above
    the finding's. ``None`` for a suggestion at or below it, for the escape,
    for an answer that was not valid, and for a finding recorded at a
    severity this module does not know, which no suggestion can be compared
    with.
    """
    if not answer.valid or answer.value not in SEVERITIES:
        return None
    if finding.severity not in SEVERITIES:
        return None
    if SEVERITIES.index(answer.value) <= SEVERITIES.index(finding.severity):
        return None
    return _from_jev("severity", finding, answer)


def route_chip(finding: FindingView, answer: Suggestion) -> Chip | None:
    """
    A suggested reviewer: a valid answer naming one of the twelve roles. On a
    finding that blocks (:func:`blocks`), only a role in :data:`VETO_ROLES`,
    so no reviewer without a veto is set beside a veto that blocks; on one
    that blocks nothing, any of them. ``None`` for the escape and for an
    answer that was not valid.
    """
    if not answer.valid or answer.value not in ROLE_KEYS:
        return None
    if blocks(finding) and answer.value not in VETO_ROLES:
        return None
    return _from_jev("route", finding, answer)


def normalised_title(title: str) -> str:
    """
    A title as a duplicate is judged by: NFKC-folded, case-folded, its
    whitespace collapsed to single spaces and trimmed. Exact otherwise, so
    two titles count as one only where nothing but those differs.
    """
    folded = unicodedata.normalize("NFKC", title).casefold()
    return re.sub(r"\s+", " ", folded).strip()


def _blocks_at_least_as_much(older: FindingView, newer: FindingView) -> bool:
    """
    Whether closing ``newer`` leaves ``older`` holding everything it held:
    blocking wherever the newer blocks, open wherever the newer is open, and
    recorded at least as serious, a severity this module does not know
    comparing with none.
    """
    if newer.severity not in SEVERITIES or older.severity not in SEVERITIES:
        return False
    if SEVERITIES.index(older.severity) < SEVERITIES.index(newer.severity):
        return False
    if newer.status == "open" and older.status != "open":
        return False
    return blocks(older) or not blocks(newer)


def _order(finding: FindingView) -> tuple[datetime, str]:
    return finding.opened_at, finding.ref


def duplicate_chips(findings: Sequence[FindingView]) -> list[Chip]:
    """
    Code's duplicate chips over a register: for each finding, at most one,
    pointing to the earliest older finding — by ``opened_at``, then ``ref`` —
    on the same candidate, never none, whose title is the same once
    normalised (:func:`normalised_title`), and which blocks at least as much
    (:func:`_blocks_at_least_as_much`). A finding a chip points from is the
    newer of two; closing every one of them leaves each candidate blocked
    exactly as before, by the older findings they point to.
    """
    ordered = sorted(findings, key=_order)
    chips: list[Chip] = []
    for position, newer in enumerate(ordered):
        if newer.candidate_id is None:
            continue
        title = normalised_title(newer.title)
        for older in ordered[:position]:
            if (
                older.candidate_id == newer.candidate_id
                and _order(older) < _order(newer)
                and normalised_title(older.title) == title
                and _blocks_at_least_as_much(older, newer)
            ):
                chips.append(
                    Chip(
                        kind="duplicate",
                        source="code",
                        finding_ref=newer.ref,
                        value=older.ref,
                    )
                )
                break
    return chips


# ---------------------------------------------------------------------------
# Phase D3: code first for a failed job, and code's own chips
# ---------------------------------------------------------------------------

#: The causes ``ops.job_error`` may suggest, in its options' order without
#: the escape: one vocabulary for code and Jev
#: (``tests/unit/test_jev_questions.py::test_the_cause_options_are_jev_chips_causes``).
CAUSES: tuple[str, ...] = (
    "network",
    "rate_limit",
    "vendor_service",
    "credentials",
    "data_missing",
    "data_invalid",
    "configuration",
    "database",
    "resource_limit",
    "code_defect",
)

#: The causes code alone gives, for what it knows exactly and never asks
#: about: a switch that was off, a window or a lease that ran out, a hold the
#: design puts in place, an outcome a person must read, and an error of a
#: kind that is never sent that no shape places.
CODE_ONLY_CAUSES: tuple[str, ...] = (
    "switched_off",
    "expired",
    "held_by_design",
    "needs_review",
    "unclassified",
)

#: The worker's kinds that reach a venue or replay a decision against a
#: hypothetical book: code chips alone, never sent (docs/09, D9).
#: ``tests/unit/test_jev_chips.py::TestTheKinds`` holds them to the worker's
#: ``HANDLERS`` and apart from the triaged kinds.
VENUE_KINDS: tuple[str, ...] = (
    "live_decision",
    "submit_orders",
    "cancel_open_orders",
    "eod_marks",
    "reconcile",
    "shadow_decision",
)

#: The programme's own kinds, ``main.JEV_HANDLERS``' — copied, since this
#: module loads no runner, and held equal by ``TestTheKinds``. Their errors
#: are code-built, and triaging them with Jev would be a loop.
PROGRAMME_KINDS: tuple[str, ...] = (
    "jev_probe",
    "jev_regime",
    "jev_reask",
    "jev_web_ingest",
    "jev_ask",
)

_TRIAGED = jev_redact.TRIAGED_KINDS
_ASKS = ("jev_ask", "jev_reask")
_REGIME = ("jev_regime",)
_INGEST = ("jev_web_ingest",)
_VERDICTS = ("jev_probe", "jev_regime", "jev_reask", "jev_ask")
_NOT_ASKED = r"\A(?:nothing was asked|the probe was not asked): "
_FAILED = r"\Athe (?:call|probe) failed: "
_FETCH = r"\Athe fetch of \S+ failed \("
_ASK_FAILED = (
    r"\A(?:asking \S+ about the row .* failed|re-asking request \S+ failed) \("
)


@dataclass(frozen=True, slots=True)
class JobErrorShape:
    """
    One shape of error this system's code writes: its name, the job kinds it
    is read for (``()`` for every kind), the pattern searched for in the
    error as recorded, and the cause it places the error under.
    """

    name: str
    kinds: tuple[str, ...]
    pattern: str
    cause: str


#: The shapes, in the order they are read; the first that applies decides.
#: Each pattern is written against the message its raise site renders, a
#: formatted value standing wherever one can, and the tests hold the table to
#: the raise sites: every literal raise of the triaged kinds' modules and of
#: ``src/data``, every venue raise the venue shapes name, and every error a
#: programme handler fails its job with, each placed by the shape pinned for
#: it (``tests/unit/test_jev_chips.py::TestCodeFirst``). A whole message the
#: queue itself writes comes first; a SQLSTATE, which ``job_errors.described``
#: names and a quoted error can carry, is read last, so it never outranks the
#: shape of the message quoting it.
JOB_ERROR_SHAPES: tuple[JobErrorShape, ...] = (
    # What the queue writes for any kind: ``src/worker/main.py``,
    # ``src/programme/main.py``, ``src/api/drain.py`` and ``jobs.requeue_expired``.
    JobErrorShape(
        "kill_switch_engaged", (), r"\Akill switch engaged\Z", "switched_off"
    ),
    JobErrorShape(
        "lease_expired",
        (),
        r"\Alease expired; worker presumed dead\Z",
        "expired",
    ),
    JobErrorShape("no_handler", (), r"\Ano handler for \S+\Z", "code_defect"),
    JobErrorShape("not_drainable", (), r"\A\S+ is not drainable\Z", "code_defect"),
    # The triaged kinds' own raise sites.
    JobErrorShape(
        "unknown_backtest_run",
        ("backtest",),
        r"\Aunknown backtest run ",
        "code_defect",
    ),
    JobErrorShape(
        "unknown_walkforward_run",
        ("walkforward",),
        r"\Aunknown walkforward run ",
        "code_defect",
    ),
    JobErrorShape(
        "unknown_data_source",
        ("backtest", "walkforward"),
        r"\Aunknown data source ",
        "configuration",
    ),
    JobErrorShape(
        "no_bars",
        ("backtest", "walkforward"),
        r"\Ano bars for .+ between .+ and ",
        "data_missing",
    ),
    JobErrorShape(
        "span_refetch_failed",
        ("ingest_bars",),
        r": refetching the stored span from \S+ failed \(",
        "vendor_service",
    ),
    JobErrorShape(
        "no_close_stored",
        ("ingest_reference_bars",),
        r": no close is stored for ",
        "data_missing",
    ),
    JobErrorShape(
        "bars_not_yet_settled",
        ("ingest_reference_bars",),
        r"'s bars settle at .+ UTC, its close plus ",
        "expired",
    ),
    JobErrorShape(
        "reference_job_superseded",
        ("ingest_reference_bars",),
        r"\Athe reference job for \S+ is superseded: ",
        "expired",
    ),
    JobErrorShape(
        "not_an_nyse_session",
        ("ingest_reference_bars",),
        r" is not an NYSE session the calendar can answer for",
        "code_defect",
    ),
    JobErrorShape(
        "reference_source",
        ("ingest_reference_bars",),
        r"\Athe reference bars are kept under ",
        "configuration",
    ),
    # The data sources the triaged kinds fetch through (``src/data``).
    JobErrorShape(
        "yfinance_no_rows",
        _TRIAGED,
        r"\Ayfinance returned no rows for ",
        "data_missing",
    ),
    JobErrorShape(
        "yfinance_no_usable_bars",
        _TRIAGED,
        r"\Ayfinance produced no usable bars for ",
        "data_missing",
    ),
    JobErrorShape(
        "yfinance_download_failed",
        _TRIAGED,
        r"\Ayfinance download failed: ",
        "vendor_service",
    ),
    JobErrorShape(
        "yfinance_not_installed",
        _TRIAGED,
        r"\Ayfinance is not installed",
        "configuration",
    ),
    JobErrorShape(
        "cryptocom_no_bars",
        _TRIAGED,
        r"\Acryptocom returned no (?:bars|candles) for ",
        "data_missing",
    ),
    JobErrorShape(
        "cryptocom_request_failed",
        _TRIAGED,
        r"\Acryptocom candlestick request failed for ",
        "vendor_service",
    ),
    JobErrorShape(
        "cryptocom_no_usable_candles",
        _TRIAGED,
        r"\Ano usable candles for ",
        "data_missing",
    ),
    JobErrorShape(
        "cryptocom_candle_without_timestamp",
        _TRIAGED,
        r"\Acandle has no timestamp: ",
        "data_invalid",
    ),
    JobErrorShape(
        "cryptocom_fixture_without_instruments",
        _TRIAGED,
        r" has no 'instruments' section\Z",
        "data_invalid",
    ),
    JobErrorShape(
        "requests_not_installed",
        _TRIAGED,
        r"\Arequests is not installed\Z",
        "configuration",
    ),
    JobErrorShape(
        "span_reversed",
        _TRIAGED,
        r"\Aend \S+ precedes start ",
        "code_defect",
    ),
    # The venue kinds and the shadow replay: code chips alone.
    JobErrorShape(
        "alpaca_credentials_missing",
        VENUE_KINDS,
        r"Alpaca credentials are (?:not configured|required)",
        "credentials",
    ),
    JobErrorShape(
        "alpaca_unauthorized",
        VENUE_KINDS,
        r"\AAlpaca \S+ \S+ returned 401\b",
        "credentials",
    ),
    JobErrorShape(
        "alpaca_rate_limited",
        VENUE_KINDS,
        r"\AAlpaca \S+ \S+ returned 429\b",
        "rate_limit",
    ),
    JobErrorShape(
        "alpaca_server_error",
        VENUE_KINDS,
        r"\AAlpaca \S+ \S+ returned 5\d\d\b",
        "vendor_service",
    ),
    JobErrorShape(
        "alpaca_other_status",
        VENUE_KINDS,
        r"\AAlpaca \S+ \S+ returned ",
        "needs_review",
    ),
    JobErrorShape(
        "alpaca_rejected", VENUE_KINDS, r"\AAlpaca rejected ", "needs_review"
    ),
    JobErrorShape(
        "alpaca_request_failed",
        VENUE_KINDS,
        r"\AAlpaca request failed: ",
        "network",
    ),
    JobErrorShape(
        "live_trading_gated",
        VENUE_KINDS,
        r"Live mode requires allow_live|LIVE_TRADING_ENABLED is not set",
        "switched_off",
    ),
    JobErrorShape(
        "broker_mode",
        VENUE_KINDS,
        r"\AAlpacaBroker supports PAPER or LIVE",
        "configuration",
    ),
    JobErrorShape(
        "simulated_broker_halted",
        VENUE_KINDS,
        r"\ASimulatedBroker is halted",
        "switched_off",
    ),
    JobErrorShape(
        "fractional_quantity_rejected",
        VENUE_KINDS,
        r": fractional qty \S+ rejected",
        "needs_review",
    ),
    JobErrorShape(
        "orders_still_open",
        VENUE_KINDS,
        r"of this system's order\(s\) still open at the venue|"
        r"an order-placing job is still running in another worker",
        "needs_review",
    ),
    JobErrorShape(
        "unknown_order_deployment_or_candidate",
        VENUE_KINDS,
        r"\Aunknown (?:order|deployment|candidate) ",
        "code_defect",
    ),
    JobErrorShape(
        "no_deployment_to_shadow",
        VENUE_KINDS,
        r" has no deployment to shadow against",
        "held_by_design",
    ),
    # The programme's kinds: an ask's or a probe's verdict
    # (``job_errors.ask_verdict``, ``main.probe_verdict``).
    JobErrorShape(
        "refused_whole",
        _VERDICTS,
        r"\Athe response was refused whole|\Athe probe's answer failed validation",
        "vendor_service",
    ),
    JobErrorShape(
        "call_failed_network",
        _VERDICTS,
        _FAILED + r"(?:connection|timeout)\b",
        "network",
    ),
    JobErrorShape(
        "call_failed_rate_limited",
        _VERDICTS,
        _FAILED + r"rate_limited\b",
        "rate_limit",
    ),
    JobErrorShape(
        "call_failed_vendor",
        _VERDICTS,
        _FAILED + r"(?:server|response_shape)\b",
        "vendor_service",
    ),
    JobErrorShape("call_failed_auth", _VERDICTS, _FAILED + r"auth\b", "credentials"),
    JobErrorShape(
        "call_failed_content_block",
        _VERDICTS,
        _FAILED + r"content_block\b",
        "held_by_design",
    ),
    JobErrorShape(
        "call_failed_invalid_request",
        _VERDICTS,
        _FAILED + r"invalid_request\b",
        "needs_review",
    ),
    JobErrorShape(
        "call_failed_client",
        _VERDICTS,
        _FAILED + r"client\b",
        "code_defect",
    ),
    JobErrorShape("call_failed_other", _VERDICTS, _FAILED, "needs_review"),
    JobErrorShape(
        "probe_not_as_expected",
        _VERDICTS,
        r"\Athe probe was answered, but not as expected|"
        r"\Athe probe's answer was not measured",
        "needs_review",
    ),
    JobErrorShape(
        "not_asked_switched_off",
        _VERDICTS,
        _NOT_ASKED + r"(?:Jev, the programme or this set's area was switched off|"
        r"Jev was switched off while the job ran)",
        "switched_off",
    ),
    JobErrorShape(
        "not_asked_credentials",
        _VERDICTS,
        _NOT_ASKED + r"(?:no TypeSafe key is set|"
        r"an authentication failure was recorded today)",
        "credentials",
    ),
    JobErrorShape(
        "not_asked_model",
        _VERDICTS,
        _NOT_ASKED + r"the model setting is not a usable pin",
        "configuration",
    ),
    JobErrorShape(
        "not_asked_set_refused",
        _VERDICTS,
        _NOT_ASKED + r"the vendor refused this set's request with a 422",
        "needs_review",
    ),
    JobErrorShape(
        "not_asked_held",
        _VERDICTS,
        _NOT_ASKED + r"(?:no call is left today|the request is over the size limits|"
        r"the vendor blocked this state's content|the text is quarantined|"
        r"the text has no clean answer from the injection screen)",
        "held_by_design",
    ),
    JobErrorShape(
        "not_asked_other", _VERDICTS, _NOT_ASKED + r"it came to ", "needs_review"
    ),
    # The forward clock's (``jev_forward``).
    JobErrorShape(
        "regime_job_names_another_set",
        _REGIME,
        r"\Aa regime job asks \S+, and this one names ",
        "code_defect",
    ),
    JobErrorShape(
        "regime_cutoff_passed",
        _REGIME,
        r"\Aexpired: the forward clock missed ",
        "expired",
    ),
    JobErrorShape(
        "regime_area_off",
        _REGIME,
        r"\Athe decisions area is off, so ",
        "switched_off",
    ),
    JobErrorShape(
        "regime_waits_for_the_live_ingest",
        _REGIME,
        r": the live ingest's, since |: no enabled deployment trades it now, but ",
        "held_by_design",
    ),
    JobErrorShape(
        "regime_without_bars_or_state",
        _REGIME,
        r"\Ano reference bar is stored under |\Ano regime state for ",
        "data_missing",
    ),
    JobErrorShape(
        "regime_session_malformed",
        _REGIME,
        r"\Aa regime job names its session as YYYY-MM-DD|"
        r" is not an NYSE session the calendar holds\Z",
        "code_defect",
    ),
    # The web ingest's (``main``, ``web_ingest``).
    JobErrorShape(
        "ingest_off",
        _INGEST,
        r"\Athe programme is switched off; nothing was fetched|"
        r"\AJev, or its \S+ area, is off; nothing was fetched",
        "switched_off",
    ),
    JobErrorShape(
        "ingest_no_key",
        _INGEST,
        r"\Ano TypeSafe key is set \(System > Configuration, or "
        r"TYPESAFE_API_KEY\), so nothing could be asked about the page",
        "credentials",
    ),
    JobErrorShape(
        "ingest_no_pin",
        _INGEST,
        r"\Athe model setting is not a usable pin, so nothing could be asked",
        "configuration",
    ),
    JobErrorShape(
        "ingest_fetch_rate_limited",
        _INGEST,
        _FETCH + r"status, HTTP 429\)",
        "rate_limit",
    ),
    JobErrorShape(
        "ingest_fetch_network",
        _INGEST,
        _FETCH + r"(?:timeout|connection|protocol)\b",
        "network",
    ),
    JobErrorShape(
        "ingest_fetch_vendor",
        _INGEST,
        _FETCH + r"(?:status|too_large|content_type|content_encoding|not_utf8)\b",
        "vendor_service",
    ),
    JobErrorShape(
        "ingest_fetch_refused",
        _INGEST,
        _FETCH + r"(?:redirect|tls|address)\b",
        "needs_review",
    ),
    JobErrorShape(
        "ingest_fetch_client",
        _INGEST,
        _FETCH + r"client\b",
        "code_defect",
    ),
    JobErrorShape(
        "ingest_page_changed_shape",
        _INGEST,
        r"\Athe parser needs review: ",
        "needs_review",
    ),
    JobErrorShape(
        "ingest_store_failed",
        _INGEST,
        r"\Astoring the snapshot of \S+ failed \(",
        "database",
    ),
    JobErrorShape(
        "ingest_malformed",
        _INGEST,
        r" is not as web_sources wrote it; nothing was fetched|"
        r"\Athe job was handed a connection inside a transaction|"
        r"\Aa web ingest job's payload is |"
        r"\Aa web ingest job names a source on the allow-list",
        "code_defect",
    ),
    # The asks' and the re-asks' (``jev_jobs``).
    JobErrorShape(
        "ask_held",
        _ASKS,
        r"'s content is quarantined, and nothing asks about it again|"
        r"\Athe code screen flags |"
        r"'s content was flagged by Jev's injection screen on request |"
        r" was written by \S+, not by the programme's model|"
        r"'s title is \S+ characters, over the ",
        "held_by_design",
    ),
    JobErrorShape(
        "ask_no_plan",
        _ASKS,
        r" has no analysis plan \(jev_prereg\)",
        "configuration",
    ),
    JobErrorShape(
        "ask_row_missing",
        _ASKS,
        r"\Athe row .* this job names is not stored; nothing was asked|"
        r"\Arequest \S+ is not in the ledger",
        "data_missing",
    ),
    JobErrorShape(
        "ask_text_or_state_refused",
        _ASKS,
        r" does not hold the text whose address this job names|"
        r"'s text does not make the state its set is asked about|"
        r"\Arequest \S+'s state does not make ",
        "data_invalid",
    ),
    JobErrorShape(
        "ask_malformed",
        _ASKS,
        r"\Aa web excerpt's row is a stored document, named by its id|"
        r"\Aa (?:hypothesis|finding) title's row is a (?:hypothesis|finding), "
        r"named by its ref|"
        r"\Aa jev_ask job asks one of |"
        r" is asked about a \S+, and this job names a |"
        r"\Aa jev_ask job's payload is |"
        r"\Aa jev_ask job names (?:a set by name|each plan)|"
        r"\Aa re-ask names its request by id|"
        r", not a canonical answer; only a canonical answer is re-asked",
        "code_defect",
    ),
    # Phase D3's ops ask, refusing a job outside its set's population: one the
    # planner never plans — not failed, of a kind never triaged, with no finish
    # time, or named by something other than its id — and one that has left
    # the population since it was planned, because code's table or the
    # redactor moved between the plan and the claim.
    JobErrorShape(
        "ops_ask_outside_the_population",
        _ASKS,
        r"\Ajob \S+ is \S+, not failed; |"
        r"\Ajob \S+ is of the kind \S+, whose errors code alone places; |"
        r"\Ajob \S+ has no finish time; |"
        r"\Aa job error's row is a job, named by its id",
        "code_defect",
    ),
    JobErrorShape(
        "ops_ask_left_to_code",
        _ASKS,
        r"\Ajob \S+'s error is placed by code \(|"
        r"\Ajob \S+'s error reduces to fewer than \S+ words of the vocabulary",
        "held_by_design",
    ),
    JobErrorShape(
        "ask_failed_in_the_database",
        _ASKS,
        _ASK_FAILED + r"[^)]*\bSQLSTATE [0-9A-Z]{5}\b",
        "database",
    ),
    JobErrorShape("ask_failed", _ASKS, _ASK_FAILED, "code_defect"),
    # Read last: a SQLSTATE, as ``job_errors.described`` writes one.
    JobErrorShape("sqlstate", (), r"\bSQLSTATE [0-9A-Z]{5}\b", "database"),
)

#: The shapes' version: a pattern, a cause, a kind or an order changed is a
#: new version, named with its hash by the ops set's plan. Version 2 added
#: the ops ask's own refusals, before any plan named version 1.
SHAPES_VERSION = 2

#: :func:`shapes_sha256` of this version, pinned beside the table and held
#: to an append-only released history kept in
#: ``tests/unit/test_jev_chips.py``, so re-pinning this after an edit still
#: fails there.
GOLDEN_SHAPES_SHA256 = (
    "0ce6cdc62fbbbfe20ba80fa5f268157f6a21f838687fc8657bf8f4a84aa474d8"
)

_COMPILED_SHAPES: tuple[tuple[JobErrorShape, re.Pattern[str]], ...] = tuple(
    (shape, re.compile(shape.pattern)) for shape in JOB_ERROR_SHAPES
)


def shapes_sha256() -> str:
    """
    sha256 of the shapes as compact JSON: the version, both lists of causes,
    the triaged kinds, the input bound, and every shape's name, kinds,
    pattern and cause, in order. What the ops set's plan names and
    :data:`GOLDEN_SHAPES_SHA256` pins.
    """
    definition = {
        "version": SHAPES_VERSION,
        "causes": list(CAUSES),
        "code_only_causes": list(CODE_ONLY_CAUSES),
        "triaged_kinds": list(jev_redact.TRIAGED_KINDS),
        "max_input_chars": jev_redact.MAX_INPUT_CHARS,
        "shapes": [
            [shape.name, list(shape.kinds), shape.pattern, shape.cause]
            for shape in JOB_ERROR_SHAPES
        ],
    }
    text = json.dumps(definition, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def job_error_shape(kind: object, error: object) -> JobErrorShape | None:
    """
    The first shape of :data:`JOB_ERROR_SHAPES` read for ``kind`` that
    ``error`` matches, its first ``jev_redact.MAX_INPUT_CHARS`` characters
    read, as the redactor reads them; ``None`` for no match, or for an
    error that is not text.
    """
    if not isinstance(error, str):
        return None
    text = error[: jev_redact.MAX_INPUT_CHARS]
    for shape, pattern in _COMPILED_SHAPES:
        if shape.kinds and kind not in shape.kinds:
            continue
        if pattern.search(text):
            return shape
    return None


def code_cause(kind: object, error: object) -> str | None:
    """
    What code makes of a failed job's error: the cause its shape places it
    under (:func:`job_error_shape`), one of :data:`CAUSES` or
    :data:`CODE_ONLY_CAUSES`; ``unclassified`` for an error of any other
    kind that no shape places, and for one that is not text; and ``None``
    only for a triaged kind's (``jev_redact.TRIAGED_KINDS``) text that no
    shape matches — the residue, the one thing Jev may be asked about.
    Pure, and never raises.
    ``tests/unit/test_jev_chips.py::TestCodeFirst::test_code_cause_is_none_only_for_triaged_residue``.
    """
    if not isinstance(error, str):
        return "unclassified"
    shape = job_error_shape(kind, error)
    if shape is not None:
        return shape.cause
    return None if kind in jev_redact.TRIAGED_KINDS else "unclassified"


def residue_skeleton(kind: object, error: object) -> tuple[str, ...] | None:
    """
    The skeleton ``ops.job_error`` may be asked about for a failed job of
    ``kind`` whose error is ``error``, or ``None``: the redactor's skeleton
    (``jev_redact.skeleton``) of an error code leaves to Jev
    (:func:`code_cause` is ``None``, so ``kind`` is a triaged kind's and
    ``error`` is text), and only when it holds enough words of the
    vocabulary to be asked about (``jev_redact.admissible``). The one rule a
    job's error is read by wherever it may become state — the planner, the
    harness and the reads beneath them, and the ``jev_ask`` handler's
    admission, part by part — so that what is planned is what is asked, and
    what is labelled is what was planned for. Pure, and never raises.
    ``tests/unit/test_jev_chips.py::TestTheResidue``.
    """
    if code_cause(kind, error) is not None:
        return None
    tokens = jev_redact.skeleton(error)
    return tokens if jev_redact.admissible(tokens) else None


@dataclass(frozen=True, slots=True)
class CodeChip:
    """
    A chip code made from a structured row: what it says, as a label, and
    any flags beside it. Labels alone: never a symbol, an amount or any
    other value of the row it was read from.
    """

    kind: Literal["reconciliation", "data_health", "ingest"]
    label: str
    flags: tuple[str, ...] = ()


#: The labels a reconciliation discrepancy is given.
RECONCILIATION_LABELS: tuple[str, ...] = (
    "venue_only_position",
    "ledger_only_position",
    "quantity_mismatch",
    "cash_drift",
)

#: The labels data health is given: ``reports._data_health``'s alerts.
DATA_HEALTH_LABELS: tuple[str, ...] = (
    "no_data_ingested",
    "deployment_unbuildable",
    "traded_symbol_without_bars",
    "traded_data_stale",
)

#: The labels an ingest's partial result is given.
INGEST_LABELS: tuple[str, ...] = ("session_bar_missing", "rows_not_refreshed")

#: Days behind past which the traded universe's data is stale:
#: ``reports._required_actions``' own threshold, held to it by
#: ``tests/unit/test_jev_chips.py::test_the_stale_rule_is_the_reports``.
STALE_AFTER_DAYS = 3


def _zero(value: object) -> bool:
    """
    Whether a quantity written as text, as reconciliation writes one, is
    zero; text that is not a number is not zero.
    """
    if not isinstance(value, str):
        return False
    try:
        return float(value) == 0.0
    except ValueError:
        return False


def reconciliation_chip(
    mismatch: Mapping[str, object], *, traded: Iterable[str]
) -> CodeChip | None:
    """
    One entry of ``maintenance_jobs.run_reconcile``'s mismatches, as a chip:
    ``cash_drift`` for cash; for a position, ``venue_only_position`` where the
    ledger holds none — flagged ``untraded`` when no enabled deployment's
    universe (``traded``) holds the symbol — ``ledger_only_position`` where
    the venue holds none, and ``quantity_mismatch`` otherwise. ``None`` for
    an entry of a kind reconciliation does not write. It corrects nothing.
    """
    kind = mismatch.get("kind")
    if kind == "cash":
        return CodeChip("reconciliation", "cash_drift")
    if kind != "position":
        return None
    ours, venue = mismatch.get("ours"), mismatch.get("venue")
    if _zero(ours) and not _zero(venue):
        held = mismatch.get("symbol") in set(traded)
        return CodeChip(
            "reconciliation", "venue_only_position", () if held else ("untraded",)
        )
    if _zero(venue) and not _zero(ours):
        return CodeChip("reconciliation", "ledger_only_position")
    return CodeChip("reconciliation", "quantity_mismatch")


def data_health_chips(data_health: Mapping[str, object]) -> list[CodeChip]:
    """
    ``reports._data_health``'s dict as chips: ``no_data_ingested`` with no
    row stored, ``deployment_unbuildable`` for a deployment whose parameters
    cannot be built, ``traded_symbol_without_bars`` for a traded symbol with
    no bar, and ``traded_data_stale`` more than :data:`STALE_AFTER_DAYS`
    behind. An unknown is no chip, never a value.
    """
    chips: list[CodeChip] = []
    if data_health.get("rows") == 0:
        chips.append(CodeChip("data_health", "no_data_ingested"))
    if data_health.get("unreadable_deployments"):
        chips.append(CodeChip("data_health", "deployment_unbuildable"))
    if data_health.get("missing_symbols"):
        chips.append(CodeChip("data_health", "traded_symbol_without_bars"))
    behind = data_health.get("sessions_behind")
    if isinstance(behind, int) and not isinstance(behind, bool):
        if behind > STALE_AFTER_DAYS:
            chips.append(CodeChip("data_health", "traded_data_stale"))
    return chips


def ingest_chips(result: Mapping[str, object]) -> list[CodeChip]:
    """
    An ingest's result as chips: ``session_bar_missing`` where it names a
    symbol whose session bar the fetch left out, and ``rows_not_refreshed``
    where stored rows kept an older adjustment basis.
    """
    chips: list[CodeChip] = []
    if result.get("session_missing"):
        chips.append(CodeChip("ingest", "session_bar_missing"))
    left = result.get("rows_not_refreshed")
    if isinstance(left, int) and not isinstance(left, bool) and left > 0:
        chips.append(CodeChip("ingest", "rows_not_refreshed"))
    return chips


__all__ = [
    "BLOCKING_SEVERITIES",
    "CAUSES",
    "CODE_ONLY_CAUSES",
    "DATA_HEALTH_LABELS",
    "GOLDEN_SHAPES_SHA256",
    "INGEST_LABELS",
    "JOB_ERROR_SHAPES",
    "PROGRAMME_KINDS",
    "RECONCILIATION_LABELS",
    "ROLE_KEYS",
    "SEVERITIES",
    "SHAPES_VERSION",
    "STALE_AFTER_DAYS",
    "VENUE_KINDS",
    "VETO_ROLES",
    "Chip",
    "ChipKind",
    "ChipSource",
    "CodeChip",
    "FindingView",
    "JobErrorShape",
    "Suggestion",
    "blocks",
    "code_cause",
    "data_health_chips",
    "duplicate_chips",
    "ingest_chips",
    "job_error_shape",
    "normalised_title",
    "reconciliation_chip",
    "residue_skeleton",
    "route_chip",
    "severity_chip",
    "shapes_sha256",
]

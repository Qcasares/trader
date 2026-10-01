"""
What phase E may show beside a finding, held now (docs/09, sections 4.6, 6.3
and 6.4; ``src/programme/jev_chips.py``), and, from phase D3, code's triage of
a failed job and code's own chips from structured rows (sections 4.5 and 4.6).

Each chip can only add friction before a finding is closed, never release
it, and each property is checked over seeded random registers as well as by
case: the severity chip only escalates (design M5); the route chip never
sets a reviewer without a veto beside a veto that blocks (M24, D-SAFE-3);
closing every finding a duplicate chip marks unblocks nothing (M4); and a
chip is labels and numbers. Whether a finding blocks is judged here by
``gates.FindingFact.blocks`` itself, never by the module's copy, so a copy
that drifted from the gate is a failure rather than a second opinion.

Code first, for a failed job: every message this system's own raise sites
write is placed by the shape pinned for it, under every kind its job can be;
every raise that writes no message of its own is in a reviewed list; every
verdict a programme job fails with is placed by a shape of its own; and only
a triaged kind's residue is left to Jev. The chips from a reconciliation, the
daily report's data health and an ingest's result cover every case, and the
stale rule is the report's own.

Every title, symbol, amount and id here is invented.
"""

from __future__ import annotations

import ast
import dataclasses
import random
import re
import time
import typing
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.programme import (
    gates,
    jev_chips,
    jev_client,
    jev_lane,
    jev_questions,
    jev_redact,
    job_errors,
    reports,
    roles,
    web_fetch,
)
from src.programme import main as programme_main
from src.programme.jev_chips import Chip, FindingView, Suggestion
from src.worker import main as worker_main
from tests.unit.test_jev_redact import FUZZ, SENTINEL, raise_sites

ROOT = Path(__file__).resolve().parents[2]

#: Statuses a finding is recorded in (migration 0008's CHECK).
STATUSES = ("open", "remediated", "accepted", "withdrawn")

#: Raisers a register may hold: every role, a Jev raiser and an older
#: programme spelling no role has.
RAISERS = (*jev_chips.ROLE_KEYS, "jev:guardrail.card", "programme:legacy")

#: What a findings set may answer: its options, the escape among them.
OWNER_OPTIONS = tuple(
    dict(jev_questions.FINDINGS_OWNER.questions)["owning_role"]["criteria"]
)
SEVERITY_OPTIONS = tuple(
    dict(jev_questions.FINDINGS_SEVERITY.questions)["severity"]["criteria"]
)

#: Invented titles, few enough that random registers repeat them.
TITLES = (
    "Invented Fills Assumed at Prices No Venue Gave",
    "invented fills assumed  at prices no venue gave",
    "Invented Borrow Never Located",
    "Invented Stale Marks on an Invented Book",
)

RAISED = datetime(2026, 9, 28, 9, tzinfo=UTC)


def _gate_blocks(finding: FindingView) -> bool:
    """Whether the gate itself would block on ``finding``."""
    return gates.FindingFact(
        ref=finding.ref,
        raised_by=finding.raised_by,
        severity=finding.severity,
        title=finding.title,
        status=finding.status,
    ).blocks


def _finding(
    ref: str = "F-0001",
    *,
    raised_by: str = "independent_risk",
    severity: str = "high",
    status: str = "open",
    candidate_id: str | None = "c-1",
    title: str = TITLES[0],
    opened_at: datetime = RAISED,
) -> FindingView:
    return FindingView(
        ref=ref,
        raised_by=raised_by,
        severity=severity,
        status=status,
        candidate_id=candidate_id,
        title=title,
        opened_at=opened_at,
    )


def _answer(value: str | None, *, valid: bool = True) -> Suggestion:
    return Suggestion(
        value=value,
        valid=valid,
        probability=0.71 if valid else None,
        margin=0.42 if valid else None,
        question_set_version=1,
        model_answered="jev-1.13.0",
        request_id=88,
    )


def _random_finding(rng: random.Random, n: int) -> FindingView:
    return _finding(
        f"F-{n:04d}",
        raised_by=rng.choice(RAISERS),
        severity=rng.choice(roles.SEVERITIES),
        status=rng.choice(STATUSES),
        candidate_id=rng.choice(("c-1", "c-2", "c-3", None)),
        title=rng.choice(TITLES),
        opened_at=RAISED + timedelta(hours=rng.randrange(0, 6)),
    )


def _random_answer(rng: random.Random, options: tuple[str, ...]) -> Suggestion:
    return _answer(rng.choice((*options, None)), valid=rng.random() < 0.8)


def _register(rng: random.Random) -> list[FindingView]:
    return [_random_finding(rng, n) for n in range(rng.randrange(1, 12))]


def _contested_register(rng: random.Random) -> list[FindingView]:
    """
    A register weighted towards what the duplicate rule must get right: open
    findings from roles holding a veto, at blocking severities, a few titles
    on two candidates.
    """
    register = []
    for n in range(rng.randrange(2, 10)):
        register.append(
            _finding(
                f"F-{n:04d}",
                raised_by=rng.choice(
                    (*sorted(jev_chips.VETO_ROLES), "execution", "quant_research")
                ),
                severity=rng.choice(("medium", "high", "high", "critical")),
                status=rng.choice(("open", "open", "open", "accepted")),
                candidate_id=rng.choice(("c-1", "c-2")),
                title=rng.choice(TITLES[:3]),
                opened_at=RAISED + timedelta(hours=rng.randrange(0, 4)),
            )
        )
    return register


# ---------------------------------------------------------------------------
# The copies
# ---------------------------------------------------------------------------


class TestTheCopies:
    """
    The module loads nothing but the standard library, so it holds copies of
    what decides blocking and of the vocabulary it suggests from, each held
    equal to its original here.
    """

    def test_the_veto_roles_and_the_blocking_severities_are_the_gates(self) -> None:
        assert jev_chips.VETO_ROLES == gates.VETO_ROLES
        assert jev_chips.BLOCKING_SEVERITIES == gates.BLOCKING_SEVERITIES

    def test_the_severities_are_the_panels_in_order(self) -> None:
        assert jev_chips.SEVERITIES == roles.SEVERITIES
        assert set(jev_chips.BLOCKING_SEVERITIES) <= set(jev_chips.SEVERITIES)

    def test_the_roles_are_the_panels_and_the_owner_sets_options(self) -> None:
        assert jev_chips.ROLE_KEYS == tuple(roles.ROLES_BY_KEY)
        escape = jev_questions.FINDINGS_OWNER.escape_options["owning_role"]
        assert jev_chips.ROLE_KEYS == tuple(o for o in OWNER_OPTIONS if o != escape)
        escape = jev_questions.FINDINGS_SEVERITY.escape_options["severity"]
        assert jev_chips.SEVERITIES == tuple(o for o in SEVERITY_OPTIONS if o != escape)

    @pytest.mark.parametrize("raised_by", RAISERS)
    @pytest.mark.parametrize("severity", (*roles.SEVERITIES, "unheard_of"))
    @pytest.mark.parametrize("status", STATUSES)
    def test_blocks_is_the_gates_rule(
        self, raised_by: str, severity: str, status: str
    ) -> None:
        finding = _finding(raised_by=raised_by, severity=severity, status=status)
        assert jev_chips.blocks(finding) is _gate_blocks(finding)


# ---------------------------------------------------------------------------
# The severity chip only escalates
# ---------------------------------------------------------------------------


def test_the_severity_chip_only_escalates() -> None:
    """
    Design M5: a chip only where the suggestion is more serious than the
    severity recorded, never at or below it, never for the escape or an
    answer that was not valid — every combination, then a seeded property
    over random findings and answers.
    """
    for recorded in roles.SEVERITIES:
        for suggested in SEVERITY_OPTIONS:
            for valid in (True, False):
                chip = jev_chips.severity_chip(
                    _finding(severity=recorded), _answer(suggested, valid=valid)
                )
                escalates = (
                    valid
                    and suggested in roles.SEVERITIES
                    and roles.SEVERITIES.index(suggested)
                    > roles.SEVERITIES.index(recorded)
                )
                assert (chip is not None) is escalates, (recorded, suggested, valid)
                if chip is not None:
                    assert (chip.kind, chip.source, chip.value) == (
                        "severity",
                        "jev",
                        suggested,
                    )
    rng = random.Random(20261001)
    for _ in range(5_000):
        finding = _random_finding(rng, 1)
        answer = _random_answer(rng, SEVERITY_OPTIONS)
        chip = jev_chips.severity_chip(finding, answer)
        if chip is not None:
            assert answer.valid and answer.value == chip.value
            assert roles.SEVERITIES.index(chip.value) > roles.SEVERITIES.index(
                finding.severity
            )
    assert (
        jev_chips.severity_chip(_finding(severity="unheard_of"), _answer("critical"))
        is None
    )


# ---------------------------------------------------------------------------
# The route chip never argues against a veto
# ---------------------------------------------------------------------------


def test_the_route_chip_never_argues_against_a_veto() -> None:
    """
    Design M24 (D-SAFE-3), mirroring the severity chip's property, over
    random registers: on every finding the gate says blocks, the route chip
    is ``None`` or names a role in ``gates.VETO_ROLES``; on one that blocks
    nothing, every valid answer naming a role shows, and nothing else does.
    """
    rng = random.Random(1_000_003)
    seen = {"blocking-veto": 0, "blocking-refused": 0, "not-blocking": 0}
    for _ in range(400):
        for finding in _register(rng):
            for _ in range(4):
                answer = _random_answer(rng, OWNER_OPTIONS)
                chip = jev_chips.route_chip(finding, answer)
                names_a_role = answer.valid and answer.value in roles.ROLES_BY_KEY
                if _gate_blocks(finding):
                    if chip is not None:
                        assert chip.value in gates.VETO_ROLES, (finding, answer)
                        seen["blocking-veto"] += 1
                    elif names_a_role:
                        assert answer.value not in gates.VETO_ROLES
                        seen["blocking-refused"] += 1
                else:
                    assert (chip is not None) is names_a_role, (finding, answer)
                    seen["not-blocking"] += 1
                if chip is not None:
                    assert (chip.kind, chip.source, chip.value) == (
                        "route",
                        "jev",
                        answer.value,
                    )
    assert all(seen.values()), seen


@pytest.mark.parametrize("role", jev_chips.ROLE_KEYS)
def test_on_a_blocking_finding_only_a_veto_is_suggested(role: str) -> None:
    blocking = _finding(raised_by="independent_risk", severity="critical")
    assert _gate_blocks(blocking)
    chip = jev_chips.route_chip(blocking, _answer(role))
    assert (chip is not None) is (role in gates.VETO_ROLES)
    open_note = _finding(raised_by="execution", severity="critical")
    assert not _gate_blocks(open_note)
    assert jev_chips.route_chip(open_note, _answer(role)) is not None


def test_the_escape_and_an_invalid_answer_make_no_route_chip() -> None:
    finding = _finding(severity="low")
    assert jev_chips.route_chip(finding, _answer("unclear")) is None
    assert jev_chips.route_chip(finding, _answer("compliance", valid=False)) is None
    assert jev_chips.route_chip(finding, _answer(None)) is None


# ---------------------------------------------------------------------------
# Closing what duplicate chips mark unblocks nothing
# ---------------------------------------------------------------------------


def _blocked(register: list[FindingView]) -> dict[str, str]:
    """Each candidate the gate holds, with the most serious severity holding it."""
    held: dict[str, str] = {}
    for finding in register:
        if finding.candidate_id is None or not _gate_blocks(finding):
            continue
        current = held.get(finding.candidate_id)
        if current is None or roles.SEVERITIES.index(
            finding.severity
        ) > roles.SEVERITIES.index(current):
            held[finding.candidate_id] = finding.severity
    return held


def _open_titles(register: list[FindingView]) -> set[tuple[str | None, str]]:
    """Each candidate's titles, normalised, that an open finding still holds."""
    return {
        (finding.candidate_id, jev_chips.normalised_title(finding.title))
        for finding in register
        if finding.status == "open"
    }


def test_closing_what_duplicate_chips_mark_unblocks_nothing() -> None:
    """
    Design M4, a property over random registers: close every finding a
    duplicate chip points from, as an operator would on the chip's word, and
    every candidate the gate held stays held, as seriously, and every title
    an open finding held is still held by one; and every chip points from a
    newer finding to an older one on the same candidate whose title is the
    same once normalised.
    """
    rng = random.Random(4_000_037)
    pointed = blocking = 0
    for n in range(4_000):
        register = _register(rng) if n % 2 else _contested_register(rng)
        by_ref = {finding.ref: finding for finding in register}
        chips = jev_chips.duplicate_chips(register)
        for chip in chips:
            newer, older = by_ref[chip.finding_ref], by_ref[chip.value]
            assert (chip.kind, chip.source) == ("duplicate", "code")
            assert (older.opened_at, older.ref) < (newer.opened_at, newer.ref)
            assert older.candidate_id == newer.candidate_id is not None
            assert jev_chips.normalised_title(
                older.title
            ) == jev_chips.normalised_title(newer.title)
            assert _gate_blocks(older) or not _gate_blocks(newer)
        marked = {chip.finding_ref for chip in chips}
        assert len(marked) == len(chips), "one chip a finding"
        closed = [
            dataclasses.replace(finding, status="accepted")
            if finding.ref in marked
            else finding
            for finding in register
        ]
        assert _blocked(closed) == _blocked(register), (register, chips)
        assert _open_titles(closed) == _open_titles(register), (register, chips)
        pointed += len(chips)
        blocking += sum(1 for ref in marked if _gate_blocks(by_ref[ref]))
    assert pointed > 1_000 and blocking > 500, (pointed, blocking)


def test_a_duplicate_points_to_the_earliest_older_finding_that_holds_as_much() -> None:
    first = _finding("F-0001", severity="critical", opened_at=RAISED)
    weaker = _finding("F-0002", severity="medium", opened_at=RAISED + timedelta(1))
    newest = _finding("F-0003", severity="high", opened_at=RAISED + timedelta(2))
    (chip,) = [
        c
        for c in jev_chips.duplicate_chips([newest, weaker, first])
        if c.finding_ref == "F-0003"
    ]
    assert chip.value == "F-0001", "the weaker older finding holds less"


@pytest.mark.parametrize(
    ("older", "holds_as_much_as_a_note"),
    [
        (_finding("F-0001", severity="medium"), False),
        (_finding("F-0001", raised_by="execution"), True),
        (_finding("F-0001", status="withdrawn"), False),
        (_finding("F-0001", status="accepted", raised_by="execution"), False),
        (_finding("F-0001", candidate_id="c-2"), False),
        (_finding("F-0001", title="Invented Fills Assumed at Other Prices"), False),
        (_finding("F-0001", opened_at=RAISED + timedelta(days=3)), False),
    ],
    ids=[
        "less-serious",
        "raised-without-a-veto",
        "closed-already",
        "closed-and-never-blocking",
        "another-candidate",
        "another-title",
        "newer-than-it",
    ],
)
def test_no_chip_points_to_a_finding_that_holds_less(
    older: FindingView, holds_as_much_as_a_note: bool
) -> None:
    """
    Against a newer finding that blocks, none of these older findings holds as
    much, so none is pointed to. Against a newer open note that blocks
    nothing, only an older open finding at least as serious is: a closed one
    would leave the title held by no open finding once the note was closed.
    """
    blocking = _finding("F-0002", opened_at=RAISED + timedelta(days=1))
    note = _finding("F-0002", opened_at=RAISED + timedelta(days=1), severity="high")
    note = dataclasses.replace(note, raised_by="execution")
    assert _gate_blocks(blocking) and not _gate_blocks(note)

    def pointed(newer: FindingView) -> list[str]:
        chips = jev_chips.duplicate_chips([older, newer])
        return [chip.value for chip in chips if chip.finding_ref == "F-0002"]

    assert pointed(blocking) == []
    assert pointed(note) == (["F-0001"] if holds_as_much_as_a_note else [])


def test_no_chip_on_a_finding_with_no_candidate() -> None:
    older = _finding("F-0001", candidate_id=None)
    newer = _finding("F-0002", candidate_id=None, opened_at=RAISED + timedelta(1))
    assert jev_chips.duplicate_chips([older, newer]) == []


def test_titles_are_the_same_once_normalised_and_only_then() -> None:
    normalised = jev_chips.normalised_title
    assert normalised(TITLES[0]) == normalised(TITLES[1])
    assert normalised("Ｉnvented\tFills ") == normalised("invented fills")
    assert normalised("Invented Fills.") != normalised("Invented Fills")


# ---------------------------------------------------------------------------
# A chip is labels and numbers
# ---------------------------------------------------------------------------

#: A label, an id or a model's name: no space, no sentence.
LABEL = re.compile(r"[A-Za-z0-9_.:-]+")


def test_a_chip_is_labels_and_numbers() -> None:
    """
    Every chip any function makes, over random registers and answers: each
    text field a label — a role key, a severity, a ref, a model — and each
    other a number or nothing; never a title, which only the duplicate rule
    compares.
    """
    hints = typing.get_type_hints(Chip)
    assert set(hints) == {
        "kind",
        "source",
        "finding_ref",
        "value",
        "probability",
        "margin",
        "question_set_version",
        "model_answered",
        "request_id",
    }
    rng = random.Random(77)
    made = 0
    for _ in range(500):
        register = _register(rng)
        chips = list(jev_chips.duplicate_chips(register))
        for finding in register:
            chips.append(
                jev_chips.route_chip(finding, _random_answer(rng, OWNER_OPTIONS))
            )
            chips.append(
                jev_chips.severity_chip(finding, _random_answer(rng, SEVERITY_OPTIONS))
            )
        titles = {finding.title for finding in register}
        for chip in chips:
            if chip is None:
                continue
            made += 1
            for name, value in dataclasses.asdict(chip).items():
                if isinstance(value, str):
                    assert LABEL.fullmatch(value), (name, value)
                    assert value not in titles
                else:
                    assert value is None or isinstance(value, int | float), name
    assert made > 500


def test_the_module_reads_nothing_and_holds_no_text_of_a_finding() -> None:
    """Pure by its imports; the load test is ``test_import_boundaries``'."""
    import inspect

    source = inspect.getsource(jev_chips)
    imported = set(re.findall(r"^(?:from|import) ([\w.]+)", source, re.MULTILINE))
    assert imported == {
        "__future__",
        "hashlib",
        "json",
        "re",
        "unicodedata",
        "collections.abc",
        "dataclasses",
        "datetime",
        "typing",
        # Phase D3: the triaged kinds and the input bound (docs/09, 4.6).
        "src.programme",
    }
    assert re.findall(r"^from src\.programme import (.+)$", source, re.MULTILINE) == [
        "jev_redact"
    ]
    assert "title" not in {field.name for field in dataclasses.fields(Chip)}


# ---------------------------------------------------------------------------
# Phase D3: code first, for a failed job (docs/09, sections 4.5 and 4.6)
# ---------------------------------------------------------------------------

#: Every released version of the shapes table, by version: append-only, and
#: kept here rather than beside the table, so re-pinning the golden after an
#: edit still fails. A change is a new version, which the ops set's plan
#: names by its hash.
RELEASED_SHAPES_SHA256: dict[int, str] = {
    1: "f4760e9218a63855942d567b8ad23c550cc3862119cd46f3c1c3445300adc53a",
}

TRIAGED = jev_redact.TRIAGED_KINDS

#: The causes each status that made no call comes to, as the design maps
#: them (docs/09, section 4.5): a switch is ``switched_off``; a missing or
#: refused key ``credentials``; a hold or a block ``held_by_design``; a set
#: the vendor refused ``needs_review``; a model setting nobody can use
#: ``configuration``; and a response refused whole ``vendor_service``.
VERDICT_CAUSES: dict[str, str] = {
    "disabled": "switched_off",
    "refused_model": "configuration",
    "quarantined": "held_by_design",
    "unscreened": "held_by_design",
    "content_blocked": "held_by_design",
    "no_key": "credentials",
    "auth_held": "credentials",
    "set_refused": "needs_review",
    "refused_budget": "held_by_design",
    "refused_limits": "held_by_design",
    "invalid": "vendor_service",
}

#: What each failed call comes to, by the client's error kind: the retried
#: kinds are ``network``, ``rate_limit`` or ``vendor_service``.
ERROR_KIND_CAUSES: dict[str, str] = {
    "auth": "credentials",
    "content_block": "held_by_design",
    "invalid_request": "needs_review",
    "rate_limited": "rate_limit",
    "server": "vendor_service",
    "timeout": "network",
    "connection": "network",
    "response_shape": "vendor_service",
    "client": "code_defect",
}

#: The shapes that read a verdict no listed status or error kind wrote: each
#: listed one must be placed by a shape of its own, never by these.
CATCH_ALLS = frozenset({"call_failed_other", "not_asked_other"})

#: The kinds that reach each function of ``maintenance_jobs`` that raises. A
#: raise added to any other function fails :class:`TestCodeFirst` until it is
#: placed here.
_INGEST_FUNCTIONS: dict[str, tuple[str, ...]] = {
    "run_ingest_bars": ("ingest_bars",),
    "run_ingest_reference_bars": ("ingest_reference_bars",),
    "_reference_session": ("ingest_reference_bars",),
    "_refuse_outside_the_window": ("ingest_reference_bars",),
    "_require_every_close": ("ingest_reference_bars",),
}


def _site_kinds(path: str, function: str) -> tuple[str, ...]:
    """The triaged kinds whose job can fail with a raise at this site."""
    if path == "src/worker/backtest_job.py":
        return ("backtest",)
    if path == "src/worker/walkforward_job.py":
        return ("walkforward",)
    if path == "src/worker/maintenance_jobs.py":
        return _INGEST_FUNCTIONS[function]
    assert path.startswith("src/data/"), path
    return TRIAGED


#: The shape each literal raise of the triaged kinds' modules and of
#: ``src/data`` is placed by, under every kind that reaches it, keyed by its
#: path and the first 48 characters of its message rendered with the
#: sentinel. A raise added, reworded or removed fails here until it is placed.
OWN_SHAPES: dict[tuple[str, str], str] = {
    (
        "src/data/cryptocom_source.py",
        "candle has no timestamp: sentinel",
    ): "cryptocom_candle_without_timestamp",
    (
        "src/data/cryptocom_source.py",
        "cryptocom candlestick request failed for sentine",
    ): "cryptocom_request_failed",
    (
        "src/data/cryptocom_source.py",
        "cryptocom returned no bars for sentinel between ",
    ): "cryptocom_no_bars",
    (
        "src/data/cryptocom_source.py",
        "cryptocom returned no candles for sentinel",
    ): "cryptocom_no_bars",
    (
        "src/data/cryptocom_source.py",
        "end sentinel precedes start sentinel",
    ): "span_reversed",
    (
        "src/data/cryptocom_source.py",
        "no usable candles for sentinel",
    ): "cryptocom_no_usable_candles",
    (
        "src/data/cryptocom_source.py",
        "requests is not installed",
    ): "requests_not_installed",
    (
        "src/data/cryptocom_source.py",
        "sentinel has no 'instruments' section",
    ): "cryptocom_fixture_without_instruments",
    (
        "src/data/yfinance_source.py",
        "yfinance download failed: sentinel",
    ): "yfinance_download_failed",
    (
        "src/data/yfinance_source.py",
        "yfinance is not installed; it is a research-only",
    ): "yfinance_not_installed",
    (
        "src/data/yfinance_source.py",
        "yfinance produced no usable bars for sentinel",
    ): "yfinance_no_usable_bars",
    (
        "src/data/yfinance_source.py",
        "yfinance returned no rows for sentinel between s",
    ): "yfinance_no_rows",
    (
        "src/worker/backtest_job.py",
        "no bars for sentinel between sentinel and sentin",
    ): "no_bars",
    (
        "src/worker/backtest_job.py",
        "unknown backtest run sentinel",
    ): "unknown_backtest_run",
    (
        "src/worker/backtest_job.py",
        "unknown data source sentinel",
    ): "unknown_data_source",
    (
        "src/worker/maintenance_jobs.py",
        "sentinel is not an NYSE session the calendar can",
    ): "not_an_nyse_session",
    (
        "src/worker/maintenance_jobs.py",
        "sentinel's bars settle at sentinel UTC, its clos",
    ): "bars_not_yet_settled",
    (
        "src/worker/maintenance_jobs.py",
        "sentinel: no close is stored for sentinel. The j",
    ): "no_close_stored",
    (
        "src/worker/maintenance_jobs.py",
        "sentinel: refetching the stored span from sentin",
    ): "span_refetch_failed",
    (
        "src/worker/maintenance_jobs.py",
        "the reference bars are kept under sentinel, the ",
    ): "reference_source",
    (
        "src/worker/maintenance_jobs.py",
        "the reference job for sentinel is superseded: th",
    ): "reference_job_superseded",
    (
        "src/worker/walkforward_job.py",
        "no bars for sentinel between sentinel and sentin",
    ): "no_bars",
    (
        "src/worker/walkforward_job.py",
        "unknown data source sentinel",
    ): "unknown_data_source",
    (
        "src/worker/walkforward_job.py",
        "unknown walkforward run sentinel",
    ): "unknown_walkforward_run",
}

#: Every raise of those modules that writes no message of its own, reviewed:
#: what each carries is a message a raise site above wrote, and placed there,
#: or the residue — an exception from the engine, a strategy, the driver or a
#: library — which is the one thing ``ops.job_error`` may be asked about,
#: and only as its skeleton. Keyed by path, function and the expression
#: passed, ``None`` for a bare re-raise.
PASS_THROUGHS: dict[tuple[str, str, str | None], str] = {
    ("src/worker/backtest_job.py", "run_backtest_job", "str(exc)"): (
        "a DataSourceError's message, unchanged: src/data's or _execute's, "
        "each placed in OWN_SHAPES"
    ),
    ("src/worker/backtest_job.py", "run_backtest_job", None): (
        "whatever the run raised, recorded on the run's row and re-raised: "
        "one of OWN_SHAPES, or the residue"
    ),
    ("src/worker/walkforward_job.py", "run_walkforward_job", None): (
        "whatever the study raised, recorded on the study's row and "
        "re-raised: one of OWN_SHAPES, or the residue"
    ),
    ("src/worker/maintenance_jobs.py", "run_ingest_bars", None): (
        "the ten-day window's own failure, after the span's: a data source's "
        "message, placed in OWN_SHAPES, or the residue"
    ),
    ("src/worker/maintenance_jobs.py", "run_ingest_reference_bars", None): (
        "the fetch's failure: a data source's message, placed in OWN_SHAPES, "
        "or the residue"
    ),
}


def _render(node: ast.expr, values: dict[str, str] | None = None) -> str | None:
    """
    A message expression as text: a literal as written, an f-string's
    formatted values each the value given for its source text in ``values``
    or the sentinel, a ``str.join`` the sentinel, and a sum of them in order;
    ``None`` for anything else.
    """
    values = values or {}
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for value in node.values:
            if isinstance(value, ast.Constant):
                parts.append(str(value.value))
            else:
                assert isinstance(value, ast.FormattedValue)
                parts.append(values.get(ast.unparse(value.value), SENTINEL))
        return "".join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _render(node.left, values), _render(node.right, values)
        return None if left is None or right is None else left + right
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "join"
        and isinstance(node.func.value, ast.Constant)
    ):
        return SENTINEL
    return None


def _functions(path: str) -> Iterator[ast.FunctionDef | ast.AsyncFunctionDef]:
    tree = ast.parse((ROOT / path).read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def _messages_raised(
    path: str, values: dict[str, str] | None = None
) -> Iterator[tuple[str, str]]:
    """Each raise's function and message in ``path``, where a literal spells it."""
    for function in _functions(path):
        for node in ast.walk(function):
            if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
                if node.exc.args:
                    message = _render(node.exc.args[0], values)
                    if message is not None:
                        yield function.name, message


def _messages_returned(
    path: str, function_name: str, values: dict[str, str] | None = None
) -> list[str]:
    """Every string a function of ``path`` returns, rendered."""
    found = []
    for function in _functions(path):
        if function.name != function_name:
            continue
        for node in ast.walk(function):
            if isinstance(node, ast.Return) and node.value is not None:
                message = _render(node.value, values)
                if message:
                    found.append(message)
    assert found, (path, function_name)
    return found


def _assigned(path: str, function_name: str, name: str) -> str:
    """The string a function of ``path`` assigns to ``name``, rendered."""
    for function in _functions(path):
        if function.name != function_name:
            continue
        for node in ast.walk(function):
            if (
                isinstance(node, ast.Assign)
                and [ast.unparse(target) for target in node.targets] == [name]
                and (text := _render(node.value)) is not None
            ):
                return text
    raise AssertionError((path, function_name, name))


#: The modules a venue kind's error comes from: the broker adapters and the
#: worker's venue jobs (``VENUE_KINDS``), whose errors are code chips alone.
VENUE_MODULES = (
    "src/execution/alpaca.py",
    "src/execution/base.py",
    "src/execution/simulated.py",
    "src/worker/live_job.py",
    "src/worker/shadow_job.py",
    "src/worker/kill_job.py",
)

#: The statuses the adapter's ``returned {response.status}`` is rendered with,
#: one for each shape that reads it.
VENUE_STATUSES = ("401", "404", "429", "503")


def _venue_messages() -> list[str]:
    """Every message a venue module writes, each status rendered in turn."""
    messages: list[str] = []
    for status in VENUE_STATUSES:
        for path in VENUE_MODULES:
            values = {"response.status": status}
            messages.extend(message for _, message in _messages_raised(path, values))
    messages.extend(_messages_returned("src/worker/kill_job.py", "_problem"))
    return sorted(set(messages))


@dataclasses.dataclass(frozen=True)
class _Asked:
    """What ``job_errors.ask_verdict`` reads of an ask's result."""

    status: str
    request_row_id: int | None
    error_kind: str | None


def _verdicts() -> Iterator[tuple[str, str, str]]:
    """
    Every verdict an ask, a re-ask, a regime job or a probe can fail with:
    its kind, what it stands for, and the error, each status, each error kind
    and each request id written in turn.
    """
    statuses = typing.get_args(jev_lane.AskStatus)
    for status in statuses:
        for row in (None, 7):
            kinds = jev_client.ERROR_KINDS if status == "error" else (None,)
            for error_kind in kinds:
                asked = _Asked(status, row, error_kind)
                error, _ = job_errors.ask_verdict(asked)
                if error is not None:
                    for kind in ("jev_ask", "jev_reask", "jev_regime"):
                        yield kind, error_kind or status, error
                probed, _ = programme_main.probe_verdict(
                    {"status": status, "request_id": row, "error_kind": error_kind}
                )
                if probed is not None and status != "ok":
                    yield "jev_probe", error_kind or status, probed


class TestCodeFirst:
    """
    Code places what it wrote before Jev is asked about anything, and only
    the residue of a triaged kind is left to Jev (docs/09, section 4.5).
    """

    def test_every_literal_raise_is_placed_for_every_kind_that_reaches_it(
        self,
    ) -> None:
        sites = [site for site in raise_sites() if site["message"] is not None]
        found: dict[tuple[str, str], str] = {}
        for site in sites:
            for kind in _site_kinds(site["path"], site["function"]):
                shape = jev_chips.job_error_shape(kind, site["message"])
                assert shape is not None, (kind, site["message"])
                key = (site["path"], site["message"][:48])
                assert found.setdefault(key, shape.name) == shape.name, key
        assert len(found) == len({(s["path"], s["message"]) for s in sites})
        assert found == OWN_SHAPES

    def test_the_sentinel_stands_for_any_value(self) -> None:
        """
        A shape reads the words around a value, never the value: each
        message rendered with another value in every place is placed by the
        same shape.
        """
        for site in raise_sites():
            if site["message"] is None:
                continue
            for value in ("SPY", "2026-09-30", "'yfinance'", "17", "a1b2c3"):
                message = site["message"].replace(SENTINEL, value)
                for kind in _site_kinds(site["path"], site["function"]):
                    shape = jev_chips.job_error_shape(kind, message)
                    assert shape is not None, message
                    assert (
                        shape.name == OWN_SHAPES[(site["path"], site["message"][:48])]
                    ), message

    def test_every_pass_through_is_reviewed(self) -> None:
        found = {
            (site["path"], site["function"], site["passed"])
            for site in raise_sites()
            if site["message"] is None
        }
        assert found == set(PASS_THROUGHS)

    def test_the_residue_is_what_no_shape_places(self) -> None:
        """
        An error the engine, a strategy or a library raised, under a triaged
        kind: no shape, so ``None``, the one thing Jev may be asked about.
        """
        for message in (
            "list index out of range",
            "'NoneType' object has no attribute 'close'",
            "connection refused",
            "division by zero",
        ):
            for kind in TRIAGED:
                assert jev_chips.job_error_shape(kind, message) is None
                assert jev_chips.code_cause(kind, message) is None

    def test_code_cause_is_none_only_for_triaged_residue(self) -> None:
        """
        Over the redactor's fuzz and every message this system writes, under
        every kind, an unknown one and values that are not kinds: ``None``
        exactly when the kind is triaged, the error text, and no shape places
        it; otherwise a known cause. It never raises.
        """
        corpus: list[object] = list(FUZZ[:2_000])
        corpus += [site["message"] for site in raise_sites() if site["message"]]
        corpus += _venue_messages()
        corpus += [error for _, _, error in _verdicts()]
        corpus += ["", None, b"bytes", 7, {"error": "x"}]
        known = {*jev_chips.CAUSES, *jev_chips.CODE_ONLY_CAUSES}
        kinds: tuple[object, ...] = (
            *TRIAGED,
            *jev_chips.VENUE_KINDS,
            *jev_chips.PROGRAMME_KINDS,
            "no_such_kind",
            None,
            7,
        )
        residue = 0
        for error in corpus:
            for kind in kinds:
                cause = jev_chips.code_cause(kind, error)
                placed = jev_chips.job_error_shape(kind, error)
                if cause is None:
                    residue += 1
                    assert kind in TRIAGED, (kind, error)
                    assert isinstance(error, str)
                    assert placed is None
                else:
                    assert cause in known, cause
                    if kind in TRIAGED and isinstance(error, str):
                        assert placed is not None and placed.cause == cause
                    if placed is None:
                        assert cause == "unclassified"
        assert residue > 0

    def test_an_error_that_is_not_text_is_never_residue(self) -> None:
        for error in (None, b"connection refused", 7, ["connection refused"]):
            for kind in TRIAGED:
                assert jev_chips.code_cause(kind, error) == "unclassified"

    def test_another_kinds_unplaced_error_is_unclassified(self) -> None:
        for kind in (*jev_chips.VENUE_KINDS, *jev_chips.PROGRAMME_KINDS, "x"):
            assert jev_chips.code_cause(kind, "list index out of range") == (
                "unclassified"
            )

    def test_only_the_first_characters_are_read(self) -> None:
        """As much as the redactor reads, and no more."""
        head = "x" * (jev_redact.MAX_INPUT_CHARS - 20)
        assert jev_chips.code_cause("backtest", head + " SQLSTATE 23505") == (
            "database"
        )
        head = "x" * jev_redact.MAX_INPUT_CHARS
        assert jev_chips.code_cause("backtest", head + " SQLSTATE 23505") is None

    def test_a_shape_reads_only_its_own_kinds(self) -> None:
        """A triaged kind's shape places nothing for another kind."""
        message = "unknown backtest run 7"
        assert jev_chips.code_cause("backtest", message) == "code_defect"
        assert jev_chips.code_cause("walkforward", message) is None
        assert jev_chips.code_cause("live_decision", message) == "unclassified"

    def test_a_quoted_sqlstate_never_outranks_the_message_quoting_it(self) -> None:
        quoted = (
            "expired: the forward clock missed 2026-09-30; its cutoff was "
            "2026-09-30 20:50 UTC. Before the cutoff: storing failed "
            "(UniqueViolationError, SQLSTATE 23505)"
        )
        assert jev_chips.code_cause("jev_regime", quoted) == "expired"
        assert jev_chips.code_cause("jev_probe", "SQLSTATE 40001") == "database"

    @pytest.mark.parametrize(
        "text",
        [
            "'s bars settle at " * 250,
            ": no close is stored for " * 160,
            "no bars for " + "x between " * 390,
            "asking x about the row " + "(" * 3_900,
            "the row " + " this job names" * 260,
            "SQLSTATE " * 440,
            "\x00" * jev_redact.MAX_INPUT_CHARS,
        ],
        ids=lambda text: repr(text[:8]),
    )
    def test_no_pathological_error_holds_it(self, text: str) -> None:
        kinds = (*TRIAGED, *jev_chips.VENUE_KINDS, *jev_chips.PROGRAMME_KINDS)
        started = time.perf_counter()
        for kind in kinds:
            jev_chips.code_cause(kind, text)
        assert time.perf_counter() - started < 0.05 * len(kinds)


class TestTheResidue:
    """
    ``residue_skeleton``: the one rule a job's error is read by wherever it
    may become state — the planner, the harness and the ``jev_ask`` handler's
    admission (docs/09, sections 4.2 and 5.1) — code's triage first, then the
    redactor, then enough words of the vocabulary to be asked about.
    """

    def test_it_is_the_skeleton_of_admissible_residue_and_nothing_else(
        self,
    ) -> None:
        """
        Over the redactor's fuzz and every message this system writes, under
        every kind and values that are not kinds: the skeleton exactly when
        code leaves the error to Jev and the skeleton is admissible, else
        ``None``; it never raises.
        """
        corpus: list[object] = list(FUZZ[:2_000])
        corpus += [site["message"] for site in raise_sites() if site["message"]]
        corpus += [
            "[Errno 111] Connection refused while reading an invented page",
            "type object 'Frame' has no attribute 'close'",
            "division by zero",
            "",
            None,
            b"connection refused",
        ]
        kinds: tuple[object, ...] = (
            *TRIAGED,
            *jev_chips.VENUE_KINDS,
            *jev_chips.PROGRAMME_KINDS,
            "no_such_kind",
            None,
        )
        asked = 0
        for error in corpus:
            for kind in kinds:
                tokens = jev_chips.residue_skeleton(kind, error)
                left = jev_chips.code_cause(kind, error) is None
                skeleton = jev_redact.skeleton(error)
                if left and jev_redact.admissible(skeleton):
                    assert tokens == skeleton, (kind, error)
                    asked += 1
                else:
                    assert tokens is None, (kind, error)
        assert asked > 0

    @pytest.mark.parametrize(
        ("kind", "error"),
        [
            ("backtest", "unknown data source 'invented'"),
            ("ingest_bars", "division by zero"),
            ("ingest_bars", "'Adj Close'"),
            ("live_decision", "[Errno 111] Connection refused while reading x"),
            ("jev_ask", "[Errno 111] Connection refused while reading x"),
            ("ingest_bars", None),
            ("ingest_bars", ""),
        ],
        ids=[
            "placed-by-code",
            "too-few-words",
            "a-quoted-key-alone",
            "a-venue-kind",
            "a-programme-kind",
            "no-error",
            "empty",
        ],
    )
    def test_each_rule_refuses_alone(self, kind: str, error: object) -> None:
        assert jev_chips.residue_skeleton(kind, error) is None

    def test_admissible_residue_is_its_skeleton(self) -> None:
        error = "[Errno 111] Connection refused while reading an invented page"
        for kind in TRIAGED:
            assert jev_chips.residue_skeleton(kind, error) == (
                jev_redact.skeleton(error)
            )


class TestTheVenueShapes:
    """A venue kind's error is a code chip, and each venue shape is live."""

    def test_every_venue_message_is_placed_or_unclassified(self) -> None:
        for message in _venue_messages():
            for kind in jev_chips.VENUE_KINDS:
                assert jev_chips.code_cause(kind, message) is not None

    def test_every_venue_shape_places_a_message_a_venue_module_writes(self) -> None:
        venue = {
            shape.name
            for shape in jev_chips.JOB_ERROR_SHAPES
            if shape.kinds == jev_chips.VENUE_KINDS
        }
        placed = set()
        for message in _venue_messages():
            shape = jev_chips.job_error_shape("submit_orders", message)
            if shape is not None and shape.kinds == jev_chips.VENUE_KINDS:
                placed.add(shape.name)
        assert venue
        assert placed == venue, sorted(venue - placed)

    def test_the_adapters_statuses_are_placed_by_their_own_shapes(self) -> None:
        expected = {
            "401": ("alpaca_unauthorized", "credentials"),
            "404": ("alpaca_other_status", "needs_review"),
            "429": ("alpaca_rate_limited", "rate_limit"),
            "503": ("alpaca_server_error", "vendor_service"),
        }
        assert set(expected) == set(VENUE_STATUSES)
        for status, (name, cause) in expected.items():
            messages = [
                m
                for m in _venue_messages()
                if m.startswith("Alpaca ") and f" returned {status}:" in m
            ]
            assert messages, status
            for message in messages:
                shape = jev_chips.job_error_shape("reconcile", message)
                assert shape is not None and (shape.name, shape.cause) == (
                    name,
                    cause,
                ), message


class TestTheProgrammeShapes:
    """Every error a programme handler fails its job with is placed by code."""

    def test_every_verdict_is_placed_by_its_own_shape(self) -> None:
        assert set(VERDICT_CAUSES) | {"ok", "error"} == set(
            typing.get_args(jev_lane.AskStatus)
        )
        assert set(ERROR_KIND_CAUSES) == set(jev_client.ERROR_KINDS)
        expected = {**VERDICT_CAUSES, **ERROR_KIND_CAUSES}
        seen = set()
        for kind, outcome, error in _verdicts():
            shape = jev_chips.job_error_shape(kind, error)
            assert shape is not None, (kind, error)
            assert shape.name not in CATCH_ALLS, (kind, error)
            assert shape.cause == expected[outcome], (kind, outcome, error)
            seen.add(outcome)
        assert seen == set(expected)

    def test_a_probe_answered_otherwise_needs_review(self) -> None:
        for as_expected in (False, None):
            error, _ = programme_main.probe_verdict(
                {"status": "ok", "request_id": 3, "as_expected": as_expected}
            )
            assert error is not None
            assert jev_chips.code_cause("jev_probe", error) == "needs_review"

    def test_an_unknown_outcome_falls_to_a_catch_all(self) -> None:
        for kind in ("jev_ask", "jev_probe"):
            error, _ = job_errors.ask_verdict(_Asked("unheard_of", None, None))
            assert jev_chips.job_error_shape(kind, error).name == "not_asked_other"
            error, _ = job_errors.ask_verdict(_Asked("error", None, "unheard_of"))
            assert jev_chips.job_error_shape(kind, error).name == "call_failed_other"

    #: The handlers' modules, and the kinds whose job each fails.
    HANDLER_MODULES: typing.ClassVar[dict[str, tuple[str, ...]]] = {
        "src/programme/jev_forward.py": ("jev_regime",),
        "src/programme/jev_jobs.py": ("jev_ask", "jev_reask"),
        "src/programme/web_ingest.py": ("jev_web_ingest",),
        "src/programme/main.py": ("jev_probe", "jev_web_ingest"),
    }

    #: Every ``JobFailedError`` whose error no literal spells, reviewed: each
    #: is placed by another test here.
    COMPUTED: typing.ClassVar[dict[tuple[str, str, str], str]] = {
        ("src/programme/jev_forward.py", "collect", "error"): "ask_verdict's",
        (
            "src/programme/jev_forward.py",
            "collect",
            "await _expired(conn, question_set, session, cutoff, now)",
        ): "_expired's, rendered",
        ("src/programme/jev_forward.py", "collect", "waiting"): (
            "_live_ingest_problem's, rendered"
        ),
        ("src/programme/main.py", "_jev_probe", "error"): "probe_verdict's",
        ("src/programme/main.py", "_jev_web_ingest", "WEB_INGEST_NO_KEY"): (
            "the constant"
        ),
        (
            "src/programme/jev_jobs.py",
            "run_ask",
            "error + _quarantine_note(followed)",
        ): ("ask_verdict's, a note after it"),
        (
            "src/programme/jev_jobs.py",
            "run_reask",
            "error + _quarantine_note(followed)",
        ): "ask_verdict's, a note after it",
    }

    def _constructions(self) -> Iterator[tuple[str, str, ast.expr]]:
        for path in self.HANDLER_MODULES:
            for function in _functions(path):
                for node in ast.walk(function):
                    if (
                        isinstance(node, ast.Call)
                        and getattr(node.func, "id", None) == "JobFailedError"
                    ):
                        yield path, function.name, node.args[0]

    def test_every_error_a_handler_spells_is_placed(self) -> None:
        """
        Each rendered with the sentinel, but for the fetch's failure kind and
        status, which decide its shape: every kind of them is placed by
        ``test_every_fetch_failure_is_placed_by_a_fetch_shape``.
        """
        computed = set()
        spelled = 0
        values = {"fetched.kind": "connection", "status": ""}
        for path, function, argument in self._constructions():
            message = _render(argument, values)
            if message is None:
                computed.add((path, function, ast.unparse(argument)))
                continue
            spelled += 1
            for kind in self.HANDLER_MODULES[path]:
                shape = jev_chips.job_error_shape(kind, message)
                assert shape is not None, (kind, message)
                assert shape.name not in CATCH_ALLS
                assert shape.kinds and kind in shape.kinds
        assert spelled > 30
        assert computed == set(self.COMPUTED)

    def test_the_web_ingests_no_key_is_placed(self) -> None:
        error = programme_main.WEB_INGEST_NO_KEY
        assert jev_chips.code_cause("jev_web_ingest", error) == "credentials"

    def test_every_fetch_failure_is_placed_by_a_fetch_shape(self) -> None:
        argument = next(
            arg
            for path, function, arg in self._constructions()
            if path == "src/programme/web_ingest.py"
            and "the fetch of" in (_render(arg) or "")
        )
        for failure in web_fetch.FAILURE_KINDS:
            for status in ("", ", HTTP 503", ", HTTP 429"):
                message = _render(argument, {"fetched.kind": failure, "status": status})
                assert message is not None
                shape = jev_chips.job_error_shape("jev_web_ingest", message)
                assert shape is not None, message
                assert shape.name.startswith("ingest_fetch_"), message
                if (failure, status) == ("status", ", HTTP 429"):
                    assert shape.cause == "rate_limit"

    def test_the_forward_clocks_reasons_are_placed(self) -> None:
        """
        A wait for the live ingest, and the cutoff passed: what
        ``_live_ingest_problem`` and ``_expired`` return, the latter with the
        sentence it opens with, which it assigns before returning.
        """
        path = "src/programme/jev_forward.py"
        waits = _messages_returned(path, "_live_ingest_problem")
        said = _assigned(path, "_expired", "said")
        expired = _messages_returned(path, "_expired", {"said": said})
        assert len(waits) == 2 and len(expired) == 2
        for messages, name in (
            (waits, "regime_waits_for_the_live_ingest"),
            (expired, "regime_cutoff_passed"),
        ):
            for message in messages:
                shape = jev_chips.job_error_shape("jev_regime", message)
                assert shape is not None and shape.name == name, message


class TestTheShapesTable:
    def test_names_are_unique_and_patterns_compile(self) -> None:
        names = [shape.name for shape in jev_chips.JOB_ERROR_SHAPES]
        assert len(names) == len(set(names))
        for shape in jev_chips.JOB_ERROR_SHAPES:
            re.compile(shape.pattern)
            assert re.fullmatch(r"[a-z][a-z0-9_]*", shape.name), shape.name

    def test_every_cause_is_known_and_none_is_unclassified(self) -> None:
        known = {*jev_chips.CAUSES, *jev_chips.CODE_ONLY_CAUSES} - {"unclassified"}
        for shape in jev_chips.JOB_ERROR_SHAPES:
            assert shape.cause in known, shape.name

    def test_every_kind_a_shape_reads_is_a_known_kind(self) -> None:
        kinds = {*TRIAGED, *jev_chips.VENUE_KINDS, *jev_chips.PROGRAMME_KINDS}
        for shape in jev_chips.JOB_ERROR_SHAPES:
            assert set(shape.kinds) <= kinds, shape.name

    def test_the_causes_are_disjoint(self) -> None:
        assert not set(jev_chips.CAUSES) & set(jev_chips.CODE_ONLY_CAUSES)
        assert len(set(jev_chips.CAUSES)) == len(jev_chips.CAUSES)

    def test_golden_and_released(self) -> None:
        assert jev_chips.shapes_sha256() == jev_chips.GOLDEN_SHAPES_SHA256
        assert RELEASED_SHAPES_SHA256[jev_chips.SHAPES_VERSION] == (
            jev_chips.GOLDEN_SHAPES_SHA256
        )
        assert sorted(RELEASED_SHAPES_SHA256) == list(
            range(1, jev_chips.SHAPES_VERSION + 1)
        )
        assert len(set(RELEASED_SHAPES_SHA256.values())) == len(RELEASED_SHAPES_SHA256)

    @pytest.mark.parametrize(
        ("target", "attribute", "moved"),
        [
            (jev_chips, "SHAPES_VERSION", 2),
            (jev_chips, "CAUSES", ("network",)),
            (jev_chips, "CODE_ONLY_CAUSES", ("expired",)),
            (jev_chips, "JOB_ERROR_SHAPES", "reversed"),
            (jev_chips, "JOB_ERROR_SHAPES", "pattern"),
            (jev_chips, "JOB_ERROR_SHAPES", "cause"),
            (jev_chips, "JOB_ERROR_SHAPES", "kinds"),
            (jev_chips, "JOB_ERROR_SHAPES", "name"),
            (jev_redact, "TRIAGED_KINDS", ("backtest",)),
            (jev_redact, "MAX_INPUT_CHARS", 3_999),
        ],
    )
    def test_everything_hashed_moves_the_hash(
        self,
        monkeypatch: pytest.MonkeyPatch,
        target: object,
        attribute: str,
        moved: object,
    ) -> None:
        shapes = jev_chips.JOB_ERROR_SHAPES
        first = shapes[0]
        if moved == "reversed":
            moved = tuple(reversed(shapes))
        elif moved in ("pattern", "cause", "kinds", "name"):
            changed = {
                "pattern": {"pattern": first.pattern + "x"},
                "cause": {"cause": "database"},
                "kinds": {"kinds": ("backtest",)},
                "name": {"name": first.name + "_x"},
            }[moved]
            moved = (dataclasses.replace(first, **changed), *shapes[1:])
        monkeypatch.setattr(target, attribute, moved)
        assert jev_chips.shapes_sha256() != jev_chips.GOLDEN_SHAPES_SHA256


class TestTheKinds:
    """The kinds each list names are the processes' own (docs/09, D9)."""

    def test_the_programme_kinds_are_its_handlers(self) -> None:
        assert jev_chips.PROGRAMME_KINDS == tuple(programme_main.JEV_HANDLERS)

    def test_every_worker_kind_is_triaged_or_a_venue_kind(self) -> None:
        triaged, venue = set(TRIAGED), set(jev_chips.VENUE_KINDS)
        assert not triaged & venue
        assert triaged | venue == set(worker_main.HANDLERS)

    def test_no_programme_kind_is_triaged(self) -> None:
        assert not set(TRIAGED) & set(jev_chips.PROGRAMME_KINDS)
        assert not set(jev_chips.VENUE_KINDS) & set(jev_chips.PROGRAMME_KINDS)


# ---------------------------------------------------------------------------
# Code's chips from structured rows
# ---------------------------------------------------------------------------


def _mismatch(kind: str, **fields: str) -> dict[str, str]:
    return {
        "deployment_id": "0b0e5e9c-0000-4000-8000-000000000001",
        "kind": kind,
        **fields,
    }


def test_reconciliation_and_data_health_chips_cover_every_shape() -> None:
    """
    Every case each structured row can hold has its chip, and every label
    is reached: a reconciliation discrepancy of each kind, each data-health
    alert, each part of an ingest's result, and nothing for a clean row.
    """
    traded = {"SPY"}
    cases = [
        (
            _mismatch("position", symbol="SPY", ours="0", venue="12.5"),
            ("venue_only_position", ()),
        ),
        (
            _mismatch("position", symbol="QQQ", ours="0", venue="3"),
            ("venue_only_position", ("untraded",)),
        ),
        (
            _mismatch("position", symbol="SPY", ours="4", venue="0"),
            ("ledger_only_position", ()),
        ),
        (
            _mismatch("position", symbol="SPY", ours="4", venue="0E-9"),
            ("ledger_only_position", ()),
        ),
        (
            _mismatch("position", symbol="SPY", ours="4", venue="5"),
            ("quantity_mismatch", ()),
        ),
        (
            _mismatch("cash", ours="1000.00", venue="990.00", drift="10.00"),
            ("cash_drift", ()),
        ),
    ]
    labels = set()
    for mismatch, (label, flags) in cases:
        chip = jev_chips.reconciliation_chip(mismatch, traded=traded)
        assert chip == jev_chips.CodeChip("reconciliation", label, flags), mismatch
        labels.add(label)
    assert labels == set(jev_chips.RECONCILIATION_LABELS)
    assert jev_chips.reconciliation_chip({"kind": "other"}, traded=traded) is None

    healthy = {
        "rows": 120,
        "unreadable_deployments": [],
        "missing_symbols": [],
        "sessions_behind": 1,
    }
    assert jev_chips.data_health_chips(healthy) == []
    alerts = {
        "no_data_ingested": {**healthy, "rows": 0, "sessions_behind": None},
        "deployment_unbuildable": {
            **healthy,
            "unreadable_deployments": ["0b0e5e9c"],
            "sessions_behind": None,
        },
        "traded_symbol_without_bars": {
            **healthy,
            "missing_symbols": ["SPY"],
            "sessions_behind": None,
        },
        "traded_data_stale": {**healthy, "sessions_behind": 9},
    }
    assert set(alerts) == set(jev_chips.DATA_HEALTH_LABELS)
    for label, data_health in alerts.items():
        assert [chip.label for chip in jev_chips.data_health_chips(data_health)] == [
            label
        ]

    assert (
        jev_chips.ingest_chips({"session_missing": [], "rows_not_refreshed": 0}) == []
    )
    ingests = {
        "session_bar_missing": {"session_missing": ["SPY"], "rows_not_refreshed": 0},
        "rows_not_refreshed": {"session_missing": [], "rows_not_refreshed": 3},
    }
    assert set(ingests) == set(jev_chips.INGEST_LABELS)
    for label, result in ingests.items():
        assert [chip.label for chip in jev_chips.ingest_chips(result)] == [label]


def test_an_unknown_is_no_chip(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Data health that cannot be read gives no chip, never a value: a
    boolean is not a count of days, which only a threshold below 1 could
    show, so the threshold is lowered to show it.
    """
    assert jev_chips.data_health_chips({}) == []
    for behind in (None, "9", 9.0, True):
        assert jev_chips.data_health_chips({"sessions_behind": behind}) == []
    monkeypatch.setattr(jev_chips, "STALE_AFTER_DAYS", 0)
    assert jev_chips.data_health_chips({"sessions_behind": True}) == []
    assert jev_chips.data_health_chips({"sessions_behind": 1}) != []
    assert jev_chips.ingest_chips({"rows_not_refreshed": True}) == []
    assert jev_chips.ingest_chips({"rows_not_refreshed": "3"}) == []


def test_a_code_chip_is_labels() -> None:
    """No symbol, quantity, amount or id of the row it was read from."""
    row = _mismatch("position", symbol="SPY", ours="0", venue="12.5")
    chip = jev_chips.reconciliation_chip(row, traded=())
    assert chip is not None
    values = {str(v) for v in row.values()}
    for field in dataclasses.fields(chip):
        value = getattr(chip, field.name)
        for item in value if isinstance(value, tuple) else (value,):
            assert item not in values
            assert LABEL.fullmatch(item)


def test_the_stale_rule_is_the_reports() -> None:
    """
    ``traded_data_stale`` is shown exactly where the daily report asks the
    operator to act on stale data: one threshold, read from one place.
    """
    for behind in (None, -1, 0, 1, 2, 3, 4, 5, 30):
        data_health = {
            "rows": 120,
            "unreadable_deployments": [],
            "missing_symbols": [],
            "sessions_behind": behind,
        }
        actions = reports._required_actions(
            {},
            {},
            {"severe_findings": 0},
            {"workers": [], "shadow_failures": 0, "jobs": {}},
            data_health,
        )
        reported = any("behind" in action for action in actions)
        chipped = [c.label for c in jev_chips.data_health_chips(data_health)]
        assert reported == ("traded_data_stale" in chipped), behind

"""
What phase E may show beside a finding, held now (docs/09, sections 4.6, 6.3
and 6.4; ``src/programme/jev_chips.py``).

Each chip can only add friction before a finding is closed, never release
it, and each property is checked over seeded random registers as well as by
case: the severity chip only escalates (design M5); the route chip never
sets a reviewer without a veto beside a veto that blocks (M24, D-SAFE-3);
closing every finding a duplicate chip marks unblocks nothing (M4); and a
chip is labels and numbers. Whether a finding blocks is judged here by
``gates.FindingFact.blocks`` itself, never by the module's copy, so a copy
that drifted from the gate is a failure rather than a second opinion.

Every title here is invented.
"""

from __future__ import annotations

import dataclasses
import random
import re
import typing
from datetime import UTC, datetime, timedelta

import pytest

from src.programme import gates, jev_chips, jev_questions, roles
from src.programme.jev_chips import Chip, FindingView, Suggestion

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
        assert jev_chips.SEVERITIES == tuple(
            o for o in SEVERITY_OPTIONS if o != escape
        )

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
    assert jev_chips.severity_chip(
        _finding(severity="unheard_of"), _answer("critical")
    ) is None


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
        c for c in jev_chips.duplicate_chips([newest, weaker, first])
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
        "re",
        "unicodedata",
        "collections.abc",
        "dataclasses",
        "datetime",
        "typing",
    }
    assert "title" not in {field.name for field in dataclasses.fields(Chip)}

"""
jev_chips.py
------------
What phase E may show beside a finding, computed when the page is read and
stored nowhere: a suggested reviewer, a suggested severity, and a pointer to
an older finding the newer one repeats (docs/09, sections 6.1 and 6.4).

Pure: the standard library, and nothing else, so the API may import it and a
test may run every function on random registers with no database. Nothing
here reads the ledger, a finding or an answer: phase E reads them and hands
over what a chip is computed from. Phase D shows no chip anywhere — the
harness's ``suggestions`` prints statuses, never a chip (docs/09, section
9.3) — so these are the functions phase E's contract binds, tested now.

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
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

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


__all__ = [
    "BLOCKING_SEVERITIES",
    "ROLE_KEYS",
    "SEVERITIES",
    "VETO_ROLES",
    "Chip",
    "ChipKind",
    "ChipSource",
    "FindingView",
    "Suggestion",
    "blocks",
    "duplicate_chips",
    "normalised_title",
    "route_chip",
    "severity_chip",
]

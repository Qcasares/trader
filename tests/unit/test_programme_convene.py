"""
test_programme_convene.py
-------------------------
The specialist panel actually sits.

``tick._convene`` once bound the stage's roles to a local called ``panel`` and
then called ``panel.assess`` — on the tuple, because the module of that name had
never been imported. Every call raised ``AttributeError``, the broad ``except``
that exists so one role's bad reply cannot silence the rest caught it, and the
pass recorded ``assessment_failed`` for every role while the gate went on
promoting. Wherever a key and a model configuration existed, the panel could
not sit and its veto could not fire, and nothing failed.

Nothing *could* have failed: ruff sees a bound local and an attribute access,
no type checker runs in CI, and no test drove ``_convene`` with a key. These
do, with the one function that talks to a model replaced by a fake, so the
assertion is on what the runner does with a reply rather than on whether a
vendor is reachable.

The database is faked at the reads ``_convene`` makes before asking anyone, and
its two writes are captured. The real-Postgres version, which also proves the
finding blocks the promotion in the same pass, is
``tests/integration/test_programme.py::TestThePanelSitsBeforeThePromotion``.

Where a test needs the panel to *remember* — a second pass, a role heard on an
earlier one, a write that must roll back — the fake is ``_LedgerConn``, which
keeps the rows across passes and undoes a transaction that raised. The rollback
itself, which only Postgres can prove, is
``tests/integration/test_programme_panel_atomicity.py``.
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import date
from typing import Any

import asyncpg
import pytest

from src.programme import models, panel, repo, tick
from src.programme.gates import (
    MIN_BARS_PER_SYMBOL,
    REQUIRED_CARD_FIELDS,
    CandidateFacts,
    Criterion,
    FindingFact,
    GateResult,
    evaluate,
)
from src.programme.roles import (
    Assessment,
    ProposedFinding,
    Role,
    roles_for_stage,
)

API_KEY = "sk-test-not-a-real-key"

SETTINGS = models.build_settings(
    models.ANTHROPIC,
    models.DEFAULT_MODEL,
    models.DEFAULT_EFFORT,
    models.DEFAULT_MAX_TOKENS,
)

STAGE = 0

GATE = GateResult(
    from_stage=STAGE,
    to_stage=STAGE + 1,
    criteria=(
        Criterion(
            id="card_complete",
            description="The hypothesis card carries every required field",
            met=True,
        ),
    ),
    requires_human=False,
)


class _FreshCandidateConn:
    """
    Answers the reads ``_convene`` makes as a fresh candidate would.

    No role has sat at this stage yet, and there are no experiments to show
    them. Anything else ``_convene`` tries to do with the connection is a
    change this fake should be told about, so it is not silently absorbed.
    """

    async def fetch(self, query: str, *args: Any) -> list[Any]:
        assert "role_assessments" in query or "experiments" in query, query
        return []

    def transaction(self) -> contextlib.AbstractAsyncContextManager[None]:
        """
        Nothing is written through this fake — the ``written`` fixture
        captures the writes — so there is nothing here for a rollback to undo.
        """
        return contextlib.nullcontext()


class _Transaction:
    """
    ``conn.transaction()`` as Postgres keeps it: what the block wrote stays if
    the block exits cleanly and is gone if it raised.
    """

    def __init__(self, conn: _LedgerConn) -> None:
        self._conn = conn
        self._marks = (0, 0)

    async def __aenter__(self) -> None:
        self._marks = (len(self._conn.assessments), len(self._conn.findings))

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        if exc_type is not None:
            del self._conn.assessments[self._marks[0] :]
            del self._conn.findings[self._marks[1] :]
        return False


class _LedgerConn:
    """
    One stage-0 candidate's panel rows, kept across passes as the database
    keeps them.

    The two repo writes land here (see the ``ledger`` fixture), ``fetch``
    answers from what has been kept, and ``transaction()`` rolls a block back
    when it raises. The last part is the point. The defect these tests pin was
    a view committed without its findings, and a fake that could not roll back
    could not tell the fix from the bug.

    ``facts`` is what ``repo.load_facts`` would assemble: a candidate whose
    gate passes on everything but the findings, so the real ``evaluate`` —
    veto included — decides, rather than a stub that would pass regardless.
    """

    def __init__(self, heard: tuple[str, ...] = ()) -> None:
        self.assessments: list[dict[str, Any]] = [
            {"role": key, "stage": STAGE, "verdict": "support"} for key in heard
        ]
        self.findings: list[dict[str, Any]] = []
        #: Makes the next finding write fail as a clash on ``findings.ref``
        #: does when two runners overlap.
        self.refuse_findings = False

    async def fetch(self, query: str, *args: Any) -> list[Any]:
        if "role_assessments" in query:
            return [{"role": key} for key in self.heard()]
        assert "experiments" in query, query
        return []

    def transaction(self) -> _Transaction:
        return _Transaction(self)

    def heard(self) -> set[str]:
        return {row["role"] for row in self.assessments}

    def facts(self) -> CandidateFacts:
        return CandidateFacts(
            stage=STAGE,
            status="active",
            params={"symbols": ["SPY"]},
            universe=("SPY",),
            start_session=date(2010, 1, 4),
            end_session=date(2020, 12, 31),
            data_source="yfinance",
            evidence_is_synthetic=False,
            hypothesis_ref="H-0001",
            hypothesis_owner="programme",
            hypothesis_card={name: "stated" for name in REQUIRED_CARD_FIELDS},
            universe_coverage={"SPY": MIN_BARS_PER_SYMBOL},
            findings=tuple(
                FindingFact(
                    ref=row["ref"],
                    raised_by=row["raised_by"],
                    severity=row["severity"],
                    title=row["title"],
                )
                for row in self.findings
            ),
        )


def _candidate() -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "stage": STAGE,
        "hypothesis_ref": "H-0001",
        "hypothesis_title": "Slow institutional rebalancing",
        "strategy_name": "buy_and_hold",
        "params": {"symbols": ["SPY"]},
        "universe": ["SPY"],
        "start_session": "2010-01-04",
        "end_session": "2020-12-31",
        "data_source": "yfinance",
        "evidence_is_synthetic": False,
    }


def _support() -> Assessment:
    return Assessment(
        verdict="support",
        summary="The card names a mechanism and the window has the data.",
    )


def _veto() -> Assessment:
    return Assessment(
        verdict="object",
        summary="The universe is selected after the fact; the result is survivors.",
        findings=[
            ProposedFinding(
                severity="critical",
                title="the universe excludes delisted instruments",
                detail="Every symbol still trades today, so this measures "
                "survivors and not the stated mechanism.",
                remediation="Rebuild the universe from point-in-time membership.",
            )
        ],
    )


@pytest.fixture
def written(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[dict[str, Any]]]:
    """Capture the two writes ``_convene`` makes, instead of making them."""
    rows: dict[str, list[dict[str, Any]]] = {"assessments": [], "findings": []}

    async def record_assessment(conn: Any, **kwargs: Any) -> None:
        rows["assessments"].append(kwargs)

    async def raise_finding(conn: Any, **kwargs: Any) -> dict[str, Any]:
        rows["findings"].append(kwargs)
        return {"id": str(uuid.uuid4()), "ref": f"F-{len(rows['findings']):04d}"}

    monkeypatch.setattr(repo, "record_assessment", record_assessment)
    monkeypatch.setattr(repo, "raise_finding", raise_finding)
    return rows


@pytest.fixture
def ledger(monkeypatch: pytest.MonkeyPatch) -> None:
    """Route the two writes into the ``_LedgerConn`` they are made on."""

    async def record_assessment(conn: _LedgerConn, **kwargs: Any) -> None:
        conn.assessments.append(kwargs)

    async def raise_finding(conn: _LedgerConn, **kwargs: Any) -> dict[str, Any]:
        if conn.refuse_findings:
            raise asyncpg.exceptions.UniqueViolationError(
                'duplicate key value violates unique constraint "findings_ref_key"'
            )
        ref = f"F-{len(conn.findings) + 1:04d}"
        conn.findings.append({"ref": ref, **kwargs})
        return {"id": str(uuid.uuid4()), "ref": ref}

    monkeypatch.setattr(repo, "record_assessment", record_assessment)
    monkeypatch.setattr(repo, "raise_finding", raise_finding)


def _asked(
    monkeypatch: pytest.MonkeyPatch, reply: dict[str, Assessment] | None = None
) -> list[str]:
    """
    Replace the model with a fake that answers per role, and log who it asked.

    Patched on :mod:`src.programme.panel` — the module that owns the one model
    call — rather than on ``tick``, so the test holds whatever name ``tick``
    imports it under and fails if ``tick`` stops reaching it at all.
    """
    asked: list[str] = []

    async def assess(
        role: Role, api_key: str | None, settings: Any, facts_brief: str
    ) -> Assessment:
        assert api_key == API_KEY
        assert settings is SETTINGS
        assert facts_brief, "a role must be shown the evidence it is judging"
        asked.append(role.key)
        return (reply or {}).get(role.key) or _support()

    monkeypatch.setattr(panel, "assess", assess)
    return asked


def _actions(report: tick.TickReport, action: str) -> list[dict[str, Any]]:
    return [a for a in report.actions if a["action"] == action]


class TestThePanelSits:
    async def test_every_role_the_stage_summons_is_asked(
        self, monkeypatch: pytest.MonkeyPatch, written: dict[str, list]
    ) -> None:
        asked = _asked(monkeypatch)
        report = tick.TickReport()

        await tick._convene(
            _FreshCandidateConn(), _candidate(), GATE, report, API_KEY, SETTINGS
        )

        assert asked == [role.key for role in roles_for_stage(STAGE)]

    async def test_every_view_is_recorded_and_none_fails(
        self, monkeypatch: pytest.MonkeyPatch, written: dict[str, list]
    ) -> None:
        """
        The regression itself. Before the fix this recorded nothing and noted
        ``assessment_failed`` once per role, with ``'tuple' object has no
        attribute 'assess'`` as the reason.
        """
        _asked(monkeypatch)
        report = tick.TickReport()
        candidate = _candidate()

        await tick._convene(
            _FreshCandidateConn(), candidate, GATE, report, API_KEY, SETTINGS
        )

        assert _actions(report, "assessment_failed") == []
        expected = [role.key for role in roles_for_stage(STAGE)]
        assert [row["role"] for row in written["assessments"]] == expected
        for row in written["assessments"]:
            assert row["candidate_id"] == candidate["id"]
            assert row["stage"] == STAGE
            assert row["verdict"] == "support"
            assert row["model"] == SETTINGS.model
        assert [a["role"] for a in _actions(report, "assessment_recorded")] == (
            expected
        )

    async def test_a_veto_role_finding_is_opened_as_blocking(
        self, monkeypatch: pytest.MonkeyPatch, written: dict[str, list]
    ) -> None:
        """
        A finding is the only thing a role says that has force, so it is the
        part most worth proving reaches the register. ``data_engineering``
        holds a veto and sits at stage 0.
        """
        _asked(monkeypatch, {"data_engineering": _veto()})
        report = tick.TickReport()

        await tick._convene(
            _FreshCandidateConn(), _candidate(), GATE, report, API_KEY, SETTINGS
        )

        assert [(f["raised_by"], f["severity"]) for f in written["findings"]] == [
            ("data_engineering", "critical")
        ]
        (raised,) = _actions(report, "finding_raised")
        assert raised["blocks"] is True

    async def test_one_role_failing_does_not_silence_the_rest(
        self, monkeypatch: pytest.MonkeyPatch, written: dict[str, list]
    ) -> None:
        """
        What the broad ``except`` is for: a malformed reply from one role is
        noted against that role, and the others are still heard. It is also
        what hid the defect, which is why the test above asserts on the
        absence of the note rather than trusting a pass that completed.
        """
        asked: list[str] = []

        async def assess(role: Role, *args: Any) -> Assessment:
            asked.append(role.key)
            if role.key == "quant_research":
                raise ValueError("verdict must be one of the vocabulary")
            return _support()

        monkeypatch.setattr(panel, "assess", assess)
        report = tick.TickReport()

        await tick._convene(
            _FreshCandidateConn(), _candidate(), GATE, report, API_KEY, SETTINGS
        )

        assert [a["role"] for a in _actions(report, "assessment_failed")] == [
            "quant_research"
        ]
        assert {row["role"] for row in written["assessments"]} == {
            role.key for role in roles_for_stage(STAGE)
        } - {"quant_research"}


class _Advanced:
    """
    What ``_advance`` wrote, with the database faked at its repo calls.

    The gate is a stub that always passes unless ``real_gate`` is set, in which
    case the real ``evaluate`` judges ``_LedgerConn.facts()`` — so a finding
    the panel opened blocks exactly as it would in production.
    """

    def __init__(
        self, monkeypatch: pytest.MonkeyPatch, *, real_gate: bool = False
    ) -> None:
        self.gates: list[bool] = []
        self.promoted_to: list[int] = []

        async def load_facts(conn: Any, candidate_id: str) -> object:
            return conn.facts() if real_gate else object()

        async def record_gate(
            conn: Any, candidate_id: str, result: GateResult, promoted: bool = False
        ) -> int:
            self.gates.append(promoted)
            return len(self.gates)

        async def promote(conn: Any, candidate_id: str, to_stage: int) -> None:
            self.promoted_to.append(to_stage)

        async def record_decision(conn: Any, **kwargs: Any) -> None:
            return None

        monkeypatch.setattr(repo, "load_facts", load_facts)
        monkeypatch.setattr(repo, "record_gate", record_gate)
        monkeypatch.setattr(repo, "promote", promote)
        monkeypatch.setattr(repo, "record_decision", record_decision)
        if not real_gate:
            monkeypatch.setattr(tick, "evaluate", lambda facts: GATE)


class TestAPanelThatDidNotFinishHoldsThePromotion:
    """
    The panel sitting is necessary; the panel having *finished* is what makes
    it a control.

    The fix above made the roles reachable, and the broad ``except`` still
    means one role's failure is noted and the pass moves on — which is right
    for hearing the others, and was wrong for the promotion that followed. A
    candidate whose data engineer failed to report was promoted exactly as if
    that role had been heard and had raised nothing. It is the original defect
    reduced to one role at a time, so the promotion now waits for every role the
    stage summoned.
    """

    async def test_a_role_that_failed_holds_the_promotion(
        self, monkeypatch: pytest.MonkeyPatch, written: dict[str, list]
    ) -> None:
        async def assess(role: Role, *args: Any) -> Assessment:
            if role.key == "data_engineering":
                raise TimeoutError("the model did not answer")
            return _support()

        monkeypatch.setattr(panel, "assess", assess)
        advanced = _Advanced(monkeypatch)
        report = tick.TickReport()

        await tick._advance(
            _FreshCandidateConn(), _candidate(), report, 1, API_KEY, SETTINGS
        )

        assert GATE.passed, "the control: the gate itself would have promoted"
        assert advanced.promoted_to == []
        assert advanced.gates == [False]
        (held,) = _actions(report, "promotion_withheld")
        assert "data_engineering" in held["reason"]
        assert "asked again next pass" in held["reason"]

    async def test_a_full_panel_lets_the_gate_decide(
        self, monkeypatch: pytest.MonkeyPatch, written: dict[str, list]
    ) -> None:
        """The other direction: a hold that fired always would also pass above."""
        _asked(monkeypatch)
        advanced = _Advanced(monkeypatch)
        report = tick.TickReport()

        await tick._advance(
            _FreshCandidateConn(), _candidate(), report, 1, API_KEY, SETTINGS
        )

        assert advanced.promoted_to == [STAGE + 1]
        assert advanced.gates == [True]
        assert _actions(report, "promotion_withheld") == []

    async def test_a_panel_never_convened_holds_nothing(
        self, monkeypatch: pytest.MonkeyPatch, written: dict[str, list]
    ) -> None:
        """
        No key is not a failed panel. The module docstring's degradation —
        reconcile, evaluate and promote, but call nothing — is deliberate, and a
        hold keyed on "no views recorded" would have quietly repealed it.
        """

        async def assess(role: Role, *args: Any) -> Assessment:
            raise AssertionError("no key, so no role may be asked")

        monkeypatch.setattr(panel, "assess", assess)
        advanced = _Advanced(monkeypatch)
        report = tick.TickReport()

        await tick._advance(_FreshCandidateConn(), _candidate(), report, 1, None, None)

        assert advanced.promoted_to == [STAGE + 1]
        assert _actions(report, "promotion_withheld") == []

    @pytest.mark.parametrize(
        ("api_key", "settings"),
        [(None, SETTINGS), (API_KEY, None), (None, None)],
        ids=["no_key", "no_settings", "neither"],
    )
    async def test_a_panel_that_sat_in_part_holds_after_the_key_is_gone(
        self,
        monkeypatch: pytest.MonkeyPatch,
        ledger: None,
        api_key: str | None,
        settings: models.ModelSettings | None,
    ) -> None:
        """
        Convened, unfinished, and now unable to finish is still unfinished.

        The data engineer fails on a pass that had a key, and the next pass
        has none. ``_convene`` used to return before reading a row whenever the
        key or the settings were missing, so that second pass looked exactly
        like a panel never convened and promoted past the one veto role at
        this stage that had not reported: withheld on one pass and released on
        the next by nothing more than the key going away.
        """
        conn = _LedgerConn()
        candidate = _candidate()

        async def assess(role: Role, *args: Any) -> Assessment:
            if role.key == "data_engineering":
                raise TimeoutError("the model did not answer")
            return _support()

        monkeypatch.setattr(panel, "assess", assess)
        advanced = _Advanced(monkeypatch)

        await tick._advance(conn, candidate, tick.TickReport(), 1, API_KEY, SETTINGS)
        assert advanced.promoted_to == []
        assert conn.heard() == {role.key for role in roles_for_stage(STAGE)} - {
            "data_engineering"
        }

        async def unreachable(role: Role, *args: Any) -> Assessment:
            raise AssertionError("without a key and settings no role may be asked")

        monkeypatch.setattr(panel, "assess", unreachable)
        report = tick.TickReport()

        await tick._advance(conn, candidate, report, 1, api_key, settings)

        assert advanced.promoted_to == []
        assert advanced.gates == [False, False]
        (held,) = _actions(report, "promotion_withheld")
        assert "data_engineering" in held["reason"]
        # The retry the key case promises cannot happen here, and the note
        # says so rather than repeating a promise on every pass.
        assert "cannot be asked" in held["reason"]
        assert "asked again next pass" not in held["reason"]

    async def test_a_panel_that_sat_in_full_holds_nothing_without_a_key(
        self, monkeypatch: pytest.MonkeyPatch, ledger: None
    ) -> None:
        """
        The other direction for the case above: views on record are not
        themselves a hold. A hold that fired whenever there was no key and any
        row existed would also have passed it.
        """
        conn = _LedgerConn(heard=tuple(role.key for role in roles_for_stage(STAGE)))

        async def assess(role: Role, *args: Any) -> Assessment:
            raise AssertionError("no key, so no role may be asked")

        monkeypatch.setattr(panel, "assess", assess)
        advanced = _Advanced(monkeypatch)
        report = tick.TickReport()

        await tick._advance(conn, _candidate(), report, 1, None, None)

        assert advanced.promoted_to == [STAGE + 1]
        assert _actions(report, "promotion_withheld") == []


class TestAViewAndItsFindingsAreOneWrite:
    """
    A role counts as heard once its view is on record, and a heard role is
    never asked again — so its view must never be on record without its
    findings.

    They were separate statements. A failure between them — a clash on
    ``findings.ref``, whose next value is ``COUNT(*) + 1`` and collides when
    two runners overlap — left the data engineer heard and its critical finding
    nowhere. The next pass did not ask it, the gate found nothing blocking, and
    the candidate was promoted past a veto that had been raised and lost.
    """

    async def test_a_finding_that_fails_to_write_takes_its_view_with_it(
        self, monkeypatch: pytest.MonkeyPatch, ledger: None
    ) -> None:
        conn = _LedgerConn()
        candidate = _candidate()
        assert evaluate(conn.facts()).passed, "the control: no finding, a pass"

        asked = _asked(monkeypatch, {"data_engineering": _veto()})
        advanced = _Advanced(monkeypatch, real_gate=True)

        # Pass one: the veto role objects, and its finding cannot be written.
        conn.refuse_findings = True
        first = tick.TickReport()
        await tick._advance(conn, candidate, first, 1, API_KEY, SETTINGS)

        assert conn.findings == []
        assert "data_engineering" not in conn.heard(), "rolled back with it"
        assert conn.heard() == {role.key for role in roles_for_stage(STAGE)} - {
            "data_engineering"
        }, "and the roles after it are still heard"
        assert advanced.promoted_to == []
        (held,) = _actions(first, "promotion_withheld")
        assert "data_engineering" in held["reason"]
        (unrecorded,) = _actions(first, "assessment_unrecorded")
        assert unrecorded["role"] == "data_engineering"
        assert "findings_ref_key" in unrecorded["error"]
        # The action list reports only what the ledger kept.
        recorded = [a["role"] for a in _actions(first, "assessment_recorded")]
        assert "data_engineering" not in recorded
        assert _actions(first, "finding_raised") == []

        # Pass two: the write goes through. Only the role that was lost is
        # asked, and its finding blocks the promotion the gate would have made.
        conn.refuse_findings = False
        asked.clear()
        second = tick.TickReport()
        await tick._advance(conn, candidate, second, 1, API_KEY, SETTINGS)

        assert asked == ["data_engineering"]
        assert [(f["raised_by"], f["severity"]) for f in conn.findings] == [
            ("data_engineering", "critical")
        ]
        (raised,) = _actions(second, "finding_raised")
        assert raised["blocks"] is True
        assert advanced.promoted_to == []
        assert advanced.gates == [False, False]

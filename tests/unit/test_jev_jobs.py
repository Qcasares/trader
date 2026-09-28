"""
What a Jev job's one ask comes to, and the re-ask that measures the noise.

``src/programme/jev_jobs.py`` turns an ask into a job's verdict
(:func:`ask_verdict`) and runs the ``jev_reask`` job (:func:`run_reask`). What
carries the weight, each failing silently if it goes:

* **A job whose ask came to nothing fails, with the reason as its error.** The
  jobs page shows status and error and nothing reads the result column, so an
  ask recorded as ``succeeded`` with a refusal in its result is a failure
  nobody sees. Every status the road can return has a reason of its own.
* **Only what another attempt could change is retried.** A standing refusal
  retried twenty times is twenty refusals, and a response refused whole
  retried is a second answer bought to replace the first.
* **A re-ask asks the canonical request's own state, once, as a probe**, and
  retires rather than asks when the words or the judge have changed since: an
  answer to other words, or from another model, measures nothing about this
  one.

No database: the connection refuses every use, and every ledger read, the pin
and the ask are fakes of the module attributes the handler calls.
"""

from __future__ import annotations

import typing
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pytest

from src.programme import flags, jev_client, jev_jobs, jev_lane, jev_repo, main
from src.programme.jev_lane import AskResult
from src.programme.jev_questions import DECISION_REGIME, RegimeState, SleeveState
from src.programme.jev_validate import ValidatedAnswer
from src.programme.job_errors import RETRIED_ERROR_KINDS, JobFailedError

PIN = "jev-1.13.0"
KEY = "ts-test-key-not-a-secret"
STATUSES = typing.get_args(jev_lane.AskStatus)
ASKED = frozenset({"ok", "invalid", "error"})


# ---------------------------------------------------------------------------
# ask_verdict
# ---------------------------------------------------------------------------


class TestAskVerdict:
    def test_an_answer_recorded_succeeds(self) -> None:
        assert jev_jobs.ask_verdict(AskResult("ok", request_row_id=3)) == (None, False)

    def test_a_response_refused_whole_fails_for_good(self) -> None:
        """What the model sent is recorded; asking again buys a second answer."""
        error, retry = jev_jobs.ask_verdict(AskResult("invalid", request_row_id=3))
        assert error == "the response was refused whole (request 3)"
        assert retry is False

    @pytest.mark.parametrize("kind", jev_client.ERROR_KINDS)
    def test_a_failed_call_is_retried_only_where_another_could_differ(
        self, kind: str
    ) -> None:
        error, retry = jev_jobs.ask_verdict(
            AskResult("error", request_row_id=3, error_kind=kind)
        )
        assert error == f"the call failed: {kind} (request 3)"
        assert retry is (kind in {"connection", "timeout", "rate_limited", "server"})

    def test_the_retried_kinds_are_the_clients_own(self) -> None:
        assert RETRIED_ERROR_KINDS <= set(jev_client.ERROR_KINDS)

    @pytest.mark.parametrize("status", sorted(set(STATUSES) - ASKED))
    def test_every_status_that_asked_nothing_says_why(self, status: str) -> None:
        """
        Each has its own reason, never the fallback, and only ``disabled`` — a
        switch turned off while the job ran — waits for another attempt.
        """
        error, retry = jev_jobs.ask_verdict(AskResult(status))
        assert error == f"nothing was asked: {jev_jobs.NOT_ASKED[status]}"
        assert "it came to" not in error
        assert retry is (status == "disabled")

    def test_the_reasons_are_exactly_the_statuses_that_asked_nothing(self) -> None:
        assert set(jev_jobs.NOT_ASKED) == set(STATUSES) - ASKED
        assert jev_lane.UNRECORDED_STATUSES <= set(jev_jobs.NOT_ASKED)

    def test_a_refusal_that_wrote_a_row_names_it(self) -> None:
        error, _ = jev_jobs.ask_verdict(AskResult("refused_budget", request_row_id=9))
        assert error.endswith("(request 9)")

    @pytest.mark.parametrize("status", sorted(set(STATUSES) - {"ok"}))
    def test_it_retries_exactly_where_the_probe_does(self, status: str) -> None:
        """
        The probe's rule, ``main.probe_verdict``, for every other ask: the two
        agree on which outcomes are worth another attempt.
        """
        for kind in jev_client.ERROR_KINDS if status == "error" else (None,):
            _, retry = jev_jobs.ask_verdict(AskResult(status, error_kind=kind))
            _, probe_retry = main.probe_verdict({"status": status, "error_kind": kind})
            assert retry is probe_retry, (status, kind)


# ---------------------------------------------------------------------------
# run_reask
# ---------------------------------------------------------------------------

_STATE = RegimeState(
    equities=SleeveState(
        trend="above", volatility_quintile=2, drawdown="none", momentum="up"
    ),
    bonds=SleeveState(
        trend="below", volatility_quintile=4, drawdown="deep", momentum="down"
    ),
    commodities=SleeveState(
        trend="near", volatility_quintile=3, drawdown="shallow", momentum="flat"
    ),
)
AS_OF = datetime(2026, 9, 25, 20, 0, tzinfo=UTC)


def _canonical(**overrides: Any) -> dict[str, Any]:
    row = {
        "id": 41,
        "status": "ok",
        "lane": "decision",
        "question_set": DECISION_REGIME.name,
        "question_set_version": DECISION_REGIME.version,
        "pack_hash": DECISION_REGIME.pack_hash,
        "model_requested": PIN,
        "model_answered": PIN,
        "state": DECISION_REGIME.dump_state(_STATE),
        "subject_type": "session",
        "subject_id": "2026-09-25",
        "as_of": AS_OF,
    }
    row.update(overrides)
    return row


def _validated(argmax: str | None, *, valid: bool = True) -> ValidatedAnswer:
    return ValidatedAnswer(
        question_key="regime",
        question_type="choice",
        noul=None,
        choice=argmax,
        score=None,
        probabilities=None,
        confidence=None,
        argmax=argmax if valid else None,
        margin=0.4 if valid else None,
        valid=valid,
        invalid_reason=None if valid else "probabilities_do_not_sum",
    )


class _NoSQL:
    """The handler's connection: every ledger read is a fake, so none may run."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"the handler used the connection itself: {name}")


@dataclass
class Rig:
    canonical: dict[str, Any] | None = field(default_factory=_canonical)
    recorded: list[dict[str, Any]] = field(
        default_factory=lambda: [
            {"question_key": "regime", "valid": True, "argmax": "risk_on"}
        ]
    )
    pin: str | None = PIN
    result: AskResult = field(
        default_factory=lambda: AskResult(
            "ok", request_row_id=88, answers={"regime": _validated("risk_on")}
        )
    )
    asks: list[dict[str, Any]] = field(default_factory=list)

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def get_request(conn: Any, request_id: int) -> dict[str, Any] | None:
            assert request_id == 41 or self.canonical is None
            return self.canonical

        async def answers_for(conn: Any, request_id: int) -> list[dict[str, Any]]:
            assert request_id == 41
            return self.recorded

        async def jev_model(conn: Any) -> str | None:
            return self.pin

        async def ask(conn: Any, **kwargs: Any) -> AskResult:
            self.asks.append(kwargs)
            return self.result

        monkeypatch.setattr(jev_repo, "get_request", get_request)
        monkeypatch.setattr(jev_repo, "answers_for", answers_for)
        monkeypatch.setattr(flags, "jev_model", jev_model)
        monkeypatch.setattr(jev_lane, "ask", ask)

    async def run(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return await jev_jobs.run_reask(
            _NoSQL(), {"request_id": 41} if payload is None else payload, KEY
        )


@pytest.fixture
def rig(monkeypatch: pytest.MonkeyPatch) -> Rig:
    r = Rig()
    r.install(monkeypatch)
    return r


class TestTheReaskAsksTheCanonicalRequestAgain:
    async def test_it_asks_once_as_a_probe_about_the_rows_own_subject(
        self, rig: Rig
    ) -> None:
        result = await rig.run()
        assert len(rig.asks) == 1
        (asked,) = rig.asks
        assert set(asked) == {
            "question_set",
            "state",
            "subject_type",
            "subject_id",
            "as_of",
            "api_key",
            "probe",
        }, "every keyword spelled, and no transport"
        assert asked["probe"] is True
        assert asked["question_set"] is DECISION_REGIME
        assert asked["subject_type"] == "session"
        assert asked["subject_id"] == "2026-09-25"
        assert asked["as_of"] == AS_OF
        assert asked["api_key"] == KEY
        assert result == {
            "request_id": 41,
            "probe_request_id": 88,
            "status": "ok",
            "flipped": {"regime": False},
        }

    async def test_the_state_is_rebuilt_through_the_sets_own_model(
        self, rig: Rig
    ) -> None:
        """
        Exactly the registered model, equal to the state first asked: the road
        hashes the state it is given, and the request hash of the re-ask is
        the canonical one's.
        """
        await rig.run()
        state = rig.asks[0]["state"]
        assert type(state) is RegimeState
        assert state == _STATE
        assert DECISION_REGIME.dump_state(state) == rig.canonical["state"]

    @pytest.mark.parametrize(
        ("first", "again", "flipped"),
        [
            (("risk_on", True), ("risk_on", True), False),
            (("risk_on", True), ("risk_off", True), True),
            (("risk_on", True), ("insufficient_evidence", True), True),
            ((None, False), ("risk_on", True), None),
            (("risk_on", True), (None, False), None),
        ],
    )
    async def test_a_flip_is_a_moved_argmax_between_two_measurements(
        self,
        rig: Rig,
        first: tuple[str | None, bool],
        again: tuple[str | None, bool],
        flipped: bool | None,
    ) -> None:
        """Where either answer was not measured, it is neither flip nor agreement."""
        rig.recorded = [
            {"question_key": "regime", "valid": first[1], "argmax": first[0]}
        ]
        rig.result = AskResult(
            "ok",
            request_row_id=88,
            answers={"regime": _validated(again[0], valid=again[1])},
        )
        assert (await rig.run())["flipped"] == {"regime": flipped}

    async def test_a_question_the_canonical_row_never_answered_is_not_a_flip(
        self, rig: Rig
    ) -> None:
        rig.recorded = []
        assert (await rig.run())["flipped"] == {"regime": None}


class TestWhatIsNotReasked:
    @pytest.mark.parametrize(
        "payload", [{}, {"request_id": "41"}, {"request_id": True}]
    )
    async def test_a_payload_that_names_no_request_fails_for_good(
        self, rig: Rig, payload: dict[str, Any]
    ) -> None:
        with pytest.raises(JobFailedError) as failed:
            await rig.run(payload)
        assert failed.value.retry is False
        assert rig.asks == []

    async def test_a_request_not_in_the_ledger_fails_for_good(self, rig: Rig) -> None:
        rig.canonical = None
        with pytest.raises(JobFailedError) as failed:
            await rig.run()
        assert failed.value.retry is False
        assert rig.asks == []

    @pytest.mark.parametrize(
        "overrides",
        [
            {"status": "invalid"},
            {"status": "error"},
            {"status": "refused_budget"},
            {"lane": "probe"},
        ],
    )
    async def test_only_a_canonical_answer_is_reasked(
        self, rig: Rig, overrides: dict[str, Any]
    ) -> None:
        rig.canonical = _canonical(**overrides)
        with pytest.raises(JobFailedError) as failed:
            await rig.run()
        assert failed.value.retry is False
        assert "not a canonical answer" in failed.value.error
        assert rig.asks == []

    @pytest.mark.parametrize(
        ("overrides", "why"),
        [
            ({"question_set": "decision.gone"}, "no longer registered"),
            ({"pack_hash": "0" * 64, "question_set_version": 0}, "not the v0"),
            ({"model_requested": "jev-1.12.0"}, "the pin is jev-1.13.0"),
        ],
    )
    async def test_other_words_or_another_judge_retire_the_reask(
        self, rig: Rig, overrides: dict[str, Any], why: str
    ) -> None:
        rig.canonical = _canonical(**overrides)
        result = await rig.run()
        assert result["status"] == "superseded"
        assert why in result["why"]
        assert rig.asks == []

    @pytest.mark.parametrize("pin", [None, "jev-latest"])
    async def test_no_usable_pin_is_not_another_pin(
        self, rig: Rig, pin: str | None
    ) -> None:
        """
        The road refuses the ask itself and the job fails saying so; retiring
        it as superseded would lose the re-ask to a setting nobody chose.
        """
        rig.pin = pin
        rig.result = AskResult("refused_model")
        with pytest.raises(JobFailedError) as failed:
            await rig.run()
        assert failed.value.retry is False
        assert jev_jobs.NOT_ASKED["refused_model"] in failed.value.error
        assert len(rig.asks) == 1

    async def test_a_failed_call_is_retried_when_another_could_differ(
        self, rig: Rig
    ) -> None:
        rig.result = AskResult("error", request_row_id=90, error_kind="timeout")
        with pytest.raises(JobFailedError) as failed:
            await rig.run()
        assert failed.value.retry is True
        assert failed.value.error == "the call failed: timeout (request 90)"

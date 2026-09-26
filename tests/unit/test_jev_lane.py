"""
test_jev_lane.py
----------------
The one road to Jev: each early return writes exactly what it should and sends
nothing it should not, a recorded answer is replayed rather than asked for
again, a probe always asks, and a call is always recorded.

Unit tests, with no database and no SDK. The switches are read through the
shipped readers in ``flags.py``, from a fake connection answering the one query
they make, as ``test_jev_flags.py`` does, so a lane that asked the wrong switch
— the lane's name ``decision`` where the area ``decisions`` belongs — reads
off here exactly as it would in production. The ledger is a fake of
``jev_repo``'s functions that binds every write against ``record_request``'s
real signature, applies the migration's checks on a request row, and holds the
canonical index; and ``jev_client.ask`` is a fake that counts its calls. The
real-Postgres counterpart is ``tests/integration/test_jev_lane.py``.

The key the lane is handed, resolved by ``src/programme/main.py``, is tested at
the end. Who claims the job that asks the probe is
``tests/unit/test_job_ownership.py``.
"""

from __future__ import annotations

import ast
import asyncio
import dataclasses
import hashlib
import inspect
import json
import pathlib
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

import asyncpg
import pytest

from src.programme import (
    flags,
    jev_catalogue,
    jev_client,
    jev_lane,
    jev_questions,
    jev_repo,
    jev_validate,
)
from src.programme.jev_lane import AskResult
from src.programme.jev_questions import (
    DECISION_REGIME,
    PROBE_CONNECTIVITY,
    ProbeState,
    RegimeState,
    SleeveState,
)
from src.programme.jev_validate import ValidatedAnswer

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "src"

MODEL = jev_catalogue.DEFAULT_MODEL
KEY = "ts-test-key-not-a-secret"
AS_OF = datetime(2026, 9, 25, 20, 0, tzinfo=UTC)

#: The one query the switches' readers make. The fake connection refuses any
#: other: the lane reads the switches through ``flags`` and the ledger through
#: ``jev_repo``, and SQL of its own would be a third road nobody tests.
FLAG_QUERY = "SELECT value FROM system_flags WHERE key = $1"

#: A clean answer's probabilities, in the order the options are asked.
REGIME_PROBABILITIES = (0.62, 0.21, 0.12, 0.05)


# ---------------------------------------------------------------------------
# The switches
# ---------------------------------------------------------------------------


def _switches() -> dict[str, str]:
    """
    Every switch the decision set needs on, every other area off, and the
    settings at their seeds: stored JSON text, as asyncpg hands ``jsonb`` over.
    """
    rows = {f"{flags.JEV_AREA_PREFIX}{area}": "false" for area in jev_catalogue.AREAS}
    rows.update(
        {
            flags.JEV_ENABLED: "true",
            f"{flags.JEV_AREA_PREFIX}decisions": "true",
            flags.JEV_MODEL: json.dumps(MODEL),
            flags.JEV_DAILY_REQUEST_BUDGET: "500",
            flags.JEV_MAX_STATE_TOKENS: "8000",
            flags.JEV_SEND_INTERNAL_DETAIL: "false",
        }
    )
    return rows


class _Conn:
    """
    A connection that answers the switches' query from ``rows`` and nothing
    else. A key absent from ``rows`` is a missing row. ``asked`` records every
    key read, in order.
    """

    def __init__(self, rows: Mapping[str, str]) -> None:
        self.rows = dict(rows)
        self.asked: list[str] = []

    async def fetchrow(self, query: str, *args: object) -> dict[str, str] | None:
        assert query == FLAG_QUERY, f"the lane ran SQL of its own: {query!r}"
        (key,) = args
        name = str(key)
        self.asked.append(name)
        if name not in self.rows:
            return None
        return {"value": self.rows[name]}


# ---------------------------------------------------------------------------
# The ledger
# ---------------------------------------------------------------------------

_RECORD_REQUEST = inspect.signature(jev_repo.record_request)
_REFUSED = ("refused_budget", "refused_limits", "refused_model")


def _row_problems(fields: Mapping[str, Any]) -> list[str]:
    """What migration 0012 would refuse about a request row."""
    problems = []
    status, http = fields.get("status"), fields.get("http_status")
    if status not in (*jev_repo.CALL_STATUSES, *_REFUSED):
        problems.append(f"status {status!r}")
    if fields["lane"] not in jev_catalogue.LANES:
        problems.append(f"lane {fields['lane']!r}")
    if fields["provenance"] not in jev_catalogue.PROVENANCES:
        problems.append(f"provenance {fields['provenance']!r}")
    if status in ("ok", "invalid") and not (
        http is not None and 200 <= http <= 299 and fields.get("raw_body") is not None
    ):
        problems.append("jev_requests_validated_has_its_body")
    if status == "ok" and fields.get("model_answered") != fields["model_requested"]:
        problems.append("jev_requests_ok_is_the_model_asked")
    if status in _REFUSED and http is not None:
        problems.append("jev_requests_refused_got_no_response")
    if http is None and any(
        fields.get(name) is not None
        for name in ("vendor_request_id", "raw_body", "model_answered")
    ):
        problems.append("jev_requests_evidence_needs_a_response")
    for name in ("raw_body", "vendor_request_id"):
        if isinstance(fields.get(name), str) and "\x00" in fields[name]:
            problems.append(f"{name} holds a NUL, which a text column cannot")
    for name in ("input_tokens", "output_tokens", "latency_ms", "http_status"):
        value = fields.get(name)
        if value is not None and not 0 <= value <= jev_lane.MAX_INT_COLUMN:
            problems.append(f"{name} {value} does not fit an INT column")
    return problems


def _jsonb_order(mapping: Mapping[str, Any]) -> dict[str, Any]:
    """Keys as ``jsonb`` keeps them: shorter first, then bytewise."""
    ordered = sorted(mapping, key=lambda key: (len(key.encode()), key.encode()))
    return {key: mapping[key] for key in ordered}


def _unique_violation(constraint: str) -> asyncpg.UniqueViolationError:
    error = asyncpg.UniqueViolationError(
        f'duplicate key value violates unique constraint "{constraint}"'
    )
    error.constraint_name = constraint
    return error


class _Ledger:
    """
    ``jev_repo``'s functions over lists, with the canonical index.

    ``log`` records each function called, in order. ``calls_today`` is the
    calls already made today by others; rows recorded here are counted on top.
    ``before_record`` runs at the start of each write, which is where another
    writer's commit lands in a race.
    """

    def __init__(self, calls_today: int = 0) -> None:
        self.requests: list[dict[str, Any]] = []
        self.answers: dict[int, list[ValidatedAnswer]] = {}
        self.calls_today = calls_today
        self.log: list[str] = []
        self.before_record: Callable[[], None] | None = None

    # The writes -------------------------------------------------------------

    def insert(self, fields: Mapping[str, Any], answers=()) -> int:
        """A row as the database would take it, or the error it would raise."""
        _RECORD_REQUEST.bind(object(), **fields)
        problems = _row_problems(fields)
        assert not problems, f"the schema would refuse this row: {problems}"
        if fields["status"] == "ok" and fields["lane"] != "probe":
            if self._canonical(fields["request_hash"]) is not None:
                raise _unique_violation(jev_repo.CANONICAL_INDEX)
        row_id = len(self.requests) + 1
        self.requests.append({"id": row_id, **fields})
        self.answers[row_id] = list(answers)
        return row_id

    async def record_exchange(self, conn, request_fields, answers) -> int:
        self.log.append("record_exchange")
        if request_fields.get("status") == "ok" and not answers:
            raise ValueError("an ok request must be recorded with its answers")
        if self.before_record is not None:
            hook, self.before_record = self.before_record, None
            hook()
        return self.insert(request_fields, answers)

    # The reads --------------------------------------------------------------

    def _canonical(self, request_hash: str) -> dict[str, Any] | None:
        for row in self.requests:
            if (
                row["request_hash"] == request_hash
                and row["status"] == "ok"
                and row["lane"] != "probe"
            ):
                return row
        return None

    async def find_canonical(self, conn, request_hash):
        self.log.append("find_canonical")
        row = self._canonical(request_hash)
        return dict(row) if row is not None else None

    async def requests_today(self, conn) -> int:
        self.log.append("requests_today")
        recorded = [r for r in self.requests if r["status"] in jev_repo.CALL_STATUSES]
        return self.calls_today + len(recorded)

    async def answers_for(self, conn, request_id):
        self.log.append("answers_for")
        rows = []
        for number, answer in enumerate(self.answers[request_id], start=1):
            row = {"id": number, "request_id": request_id}
            row.update({f: getattr(answer, f) for f in jev_repo.ANSWER_FIELDS})
            if isinstance(row["probabilities"], dict):
                row["probabilities"] = _jsonb_order(row["probabilities"])
            rows.append(row)
        return rows

    # For the assertions -------------------------------------------------------

    @property
    def only_request(self) -> dict[str, Any]:
        assert len(self.requests) == 1, self.requests
        return self.requests[0]


# ---------------------------------------------------------------------------
# The client
# ---------------------------------------------------------------------------


def _call(
    status: int | None = 200,
    body: str | None = None,
    *,
    request_id: str | None = "req_0001",
    latency_ms: int = 140,
    error_class: str | None = None,
    error_kind: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> Any:
    return jev_client.JevCall(
        http_status=status,
        raw_body=body,
        request_id=request_id,
        latency_ms=latency_ms,
        error_class=error_class,
        error_kind=error_kind,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def _clean_answers(questions: Mapping[str, dict]) -> dict[str, Any]:
    """A sound answer to each question asked."""
    answers: dict[str, Any] = {}
    for key, question in questions.items():
        if question["type"] == "noul":
            answers[key] = {"type": "noul", "noul": 0.97}
        elif question["type"] == "choice":
            options = list(question["criteria"])
            probabilities = dict(zip(options, REGIME_PROBABILITIES, strict=True))
            answers[key] = {
                "type": "choice",
                "choice": options[0],
                "confidence": 0.49,
                "probabilities": probabilities,
            }
        else:  # pragma: no cover - no Score is registered yet
            raise AssertionError(f"no clean answer for {question['type']}")
    return answers


def _body(answers: Mapping[str, Any], model: str = MODEL) -> str:
    return json.dumps(
        {
            "model": model,
            "answers": answers,
            "usage": {"input_tokens": 212, "output_tokens": 0},
        }
    )


def _answering(**overrides: Any) -> Callable[..., Any]:
    """A responder answering whatever it is asked cleanly, as a 200."""

    def respond(**kwargs: Any) -> Any:
        return _call(200, _body(_clean_answers(kwargs["questions"])), **overrides)

    return respond


class _Client:
    """
    ``jev_client.ask``. ``respond`` builds each answer from the call's
    arguments; ``calls`` records the arguments of every call made.
    """

    def __init__(self, respond: Callable[..., Any]) -> None:
        self.respond = respond
        self.calls: list[dict[str, Any]] = []

    async def ask(self, **kwargs: Any) -> Any:
        assert set(kwargs) == {
            "api_key",
            "model",
            "state",
            "questions",
            "transport",
        }, sorted(kwargs)
        self.calls.append(kwargs)
        return self.respond(**kwargs)


# ---------------------------------------------------------------------------
# The rig
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class Rig:
    conn: _Conn
    ledger: _Ledger
    client: _Client


@pytest.fixture
def rig(monkeypatch: pytest.MonkeyPatch) -> Rig:
    ledger = _Ledger()
    client = _Client(_answering())
    for name in ("find_canonical", "requests_today", "record_exchange", "answers_for"):
        monkeypatch.setattr(jev_repo, name, getattr(ledger, name))
    monkeypatch.setattr(jev_client, "ask", client.ask)
    return Rig(_Conn(_switches()), ledger, client)


def _sleeve(**overrides: Any) -> SleeveState:
    values = {
        "trend": "above",
        "volatility_quintile": 2,
        "drawdown": "none",
        "momentum": "up",
    }
    values.update(overrides)
    return SleeveState(**values)


def _regime_state(**sleeves: SleeveState) -> RegimeState:
    values = {"equities": _sleeve(), "bonds": _sleeve(), "commodities": _sleeve()}
    values.update(sleeves)
    return RegimeState(**values)


async def _ask(
    rig: Rig,
    question_set: jev_questions.QuestionSet = DECISION_REGIME,
    state: Any = None,
    *,
    api_key: str | None = KEY,
    **kwargs: Any,
) -> AskResult:
    if state is None:
        state = ProbeState() if question_set.lane == "probe" else _regime_state()
    return await jev_lane.ask(
        rig.conn,
        question_set=question_set,
        state=state,
        subject_type=kwargs.pop("subject_type", "session"),
        subject_id=kwargs.pop("subject_id", "2026-09-25"),
        as_of=kwargs.pop("as_of", AS_OF),
        api_key=api_key,
        **kwargs,
    )


def _nothing_happened(rig: Rig) -> None:
    assert rig.client.calls == [], "a call was made"
    assert rig.ledger.requests == [], "a row was written"


# ---------------------------------------------------------------------------
# The arguments are checked first
# ---------------------------------------------------------------------------


class TestTheArgumentsAreCheckedFirst:
    """
    Before any switch is read, so a lane's mistake is found while Jev is off,
    which is when every lane will first be written and tested.
    """

    @pytest.fixture(autouse=True)
    def _everything_off(self, rig: Rig) -> None:
        rig.conn.rows[flags.JEV_ENABLED] = "false"

    async def test_a_state_of_another_model_is_a_type_error(self, rig: Rig) -> None:
        with pytest.raises(TypeError, match="RegimeState"):
            await _ask(rig, DECISION_REGIME, ProbeState())
        assert rig.conn.asked == [], "a switch was read before the state was checked"
        _nothing_happened(rig)

    async def test_a_subclass_of_the_state_model_is_refused(self, rig: Rig) -> None:
        class Dated(RegimeState):
            pass

        state = Dated(equities=_sleeve(), bonds=_sleeve(), commodities=_sleeve())
        with pytest.raises(TypeError):
            await _ask(rig, DECISION_REGIME, state)
        _nothing_happened(rig)

    async def test_a_set_that_is_not_the_registered_one_is_refused(
        self, rig: Rig
    ) -> None:
        reworded = dataclasses.replace(
            DECISION_REGIME,
            questions=(
                (
                    "regime",
                    {
                        **DECISION_REGIME.as_request_questions()["regime"],
                        "instructions": "Which regime is it?",
                    },
                ),
            ),
        )
        assert reworded.name == DECISION_REGIME.name
        with pytest.raises(ValueError, match="registered"):
            await _ask(rig, reworded)
        assert rig.conn.asked == []
        _nothing_happened(rig)

    async def test_a_copy_of_the_registered_set_is_the_registered_set(
        self, rig: Rig
    ) -> None:
        rig.conn.rows[flags.JEV_ENABLED] = "true"
        copied = dataclasses.replace(DECISION_REGIME)
        result = await _ask(rig, copied)
        assert result.status == "ok"

    async def test_something_that_is_not_a_question_set_is_refused(
        self, rig: Rig
    ) -> None:
        with pytest.raises(TypeError, match="QuestionSet"):
            await _ask(rig, DECISION_REGIME.as_request_questions(), _regime_state())
        _nothing_happened(rig)

    async def test_a_naive_as_of_is_refused(self, rig: Rig) -> None:
        with pytest.raises(ValueError, match="timezone"):
            await _ask(rig, as_of=datetime(2026, 9, 25, 20, 0))
        _nothing_happened(rig)

    async def test_as_of_must_be_a_datetime(self, rig: Rig) -> None:
        with pytest.raises(TypeError, match="as_of"):
            await _ask(rig, as_of="2026-09-25")
        _nothing_happened(rig)

    @pytest.mark.parametrize("field", ["subject_type", "subject_id"])
    @pytest.mark.parametrize("value", ["", "   ", None])
    async def test_a_blank_subject_is_refused(
        self, rig: Rig, field: str, value: object
    ) -> None:
        with pytest.raises(ValueError, match=field):
            await _ask(rig, **{field: value})
        _nothing_happened(rig)


# ---------------------------------------------------------------------------
# 1. Switched off: nothing written, nothing sent
# ---------------------------------------------------------------------------


class TestSwitchedOffWritesNothing:
    @pytest.mark.parametrize("stored", ["false", '"true"', "1", "null", None])
    async def test_the_master_switch_off_asks_nothing(
        self, rig: Rig, stored: str | None
    ) -> None:
        if stored is None:
            del rig.conn.rows[flags.JEV_ENABLED]
        else:
            rig.conn.rows[flags.JEV_ENABLED] = stored
        result = await _ask(rig)
        assert result == AskResult(status="disabled")
        assert flags.JEV_MODEL not in rig.conn.asked, "the model was read anyway"
        assert rig.ledger.log == [], "the ledger was consulted"
        _nothing_happened(rig)

    async def test_the_sets_area_switch_off_asks_nothing(self, rig: Rig) -> None:
        rig.conn.rows[f"{flags.JEV_AREA_PREFIX}decisions"] = "false"
        result = await _ask(rig)
        assert result.status == "disabled"
        assert rig.ledger.log == []
        _nothing_happened(rig)

    async def test_the_decision_lane_answers_to_the_decisions_area(
        self, rig: Rig
    ) -> None:
        """
        The lane is ``decision`` and its area ``decisions``. A lane that passed
        its own name would read a switch nobody seeded — off forever, silently.
        """
        await _ask(rig)
        assert f"{flags.JEV_AREA_PREFIX}decisions" in rig.conn.asked
        assert f"{flags.JEV_AREA_PREFIX}decision" not in rig.conn.asked
        assert len(rig.client.calls) == 1

    async def test_another_area_on_does_not_open_this_one(self, rig: Rig) -> None:
        for area in jev_catalogue.AREAS:
            rig.conn.rows[f"{flags.JEV_AREA_PREFIX}{area}"] = "true"
        rig.conn.rows[f"{flags.JEV_AREA_PREFIX}decisions"] = "false"
        assert (await _ask(rig)).status == "disabled"
        _nothing_happened(rig)

    async def test_the_probe_answers_to_the_master_switch_alone(self, rig: Rig) -> None:
        for area in jev_catalogue.AREAS:
            rig.conn.rows[f"{flags.JEV_AREA_PREFIX}{area}"] = "false"
        result = await _ask(rig, PROBE_CONNECTIVITY)
        assert result.status == "ok"
        assert len(rig.client.calls) == 1
        assert not any(k.startswith(flags.JEV_AREA_PREFIX) for k in rig.conn.asked)

    async def test_the_probe_is_off_with_the_master_switch(self, rig: Rig) -> None:
        rig.conn.rows[flags.JEV_ENABLED] = "false"
        assert (await _ask(rig, PROBE_CONNECTIVITY)).status == "disabled"
        _nothing_happened(rig)

    async def test_probing_an_areas_question_needs_that_area_on(self, rig: Rig) -> None:
        """
        A probe re-asks a set's questions; it does not escape the set's switch.
        An operator who switched decisions off has not asked for decision
        questions to be sent, to measure them or for any other reason.
        """
        rig.conn.rows[f"{flags.JEV_AREA_PREFIX}decisions"] = "false"
        result = await _ask(rig, DECISION_REGIME, probe=True)
        assert result.status == "disabled"
        _nothing_happened(rig)


# ---------------------------------------------------------------------------
# 2. No usable model: nothing written, nothing sent
# ---------------------------------------------------------------------------


class TestNoUsableModelWritesNothing:
    @pytest.mark.parametrize(
        "stored",
        [
            json.dumps("jev-latest"),
            json.dumps("jev-preview"),
            json.dumps("jev-9.9.9"),
            "null",
            "3",
            None,
        ],
    )
    async def test_it_asks_nothing(self, rig: Rig, stored: str | None) -> None:
        """
        Nothing is written because nothing honest could be: every row names the
        model it requested, and there is none to name.
        """
        if stored is None:
            del rig.conn.rows[flags.JEV_MODEL]
        else:
            rig.conn.rows[flags.JEV_MODEL] = stored
        result = await _ask(rig)
        assert result == AskResult(status="refused_model")
        assert rig.ledger.log == []
        _nothing_happened(rig)


# ---------------------------------------------------------------------------
# 3. Replayed: nothing written, nothing sent
# ---------------------------------------------------------------------------


class TestARecordedAnswerIsReplayed:
    async def test_the_second_ask_is_answered_from_the_ledger(self, rig: Rig) -> None:
        first = await _ask(rig)
        assert first.status == "ok" and not first.replayed
        assert len(rig.client.calls) == 1

        second = await _ask(rig)

        assert len(rig.client.calls) == 1, "the recorded answer was asked for again"
        assert len(rig.ledger.requests) == 1, "the replay wrote a row"
        assert second.replayed is True
        assert second.status == "ok"
        assert second.request_row_id == first.request_row_id
        assert second.answers == first.answers
        assert second.error_kind is None

    async def test_a_replay_needs_no_key_and_no_budget(self, rig: Rig) -> None:
        first = await _ask(rig)
        rig.conn.rows[flags.JEV_DAILY_REQUEST_BUDGET] = "0"
        rig.ledger.log.clear()

        second = await _ask(rig, api_key=None)

        assert second.replayed and second.answers == first.answers
        assert rig.ledger.log == ["find_canonical", "answers_for"]
        assert len(rig.client.calls) == 1

    async def test_a_replay_reads_in_the_order_asked(self, rig: Rig) -> None:
        """
        The probabilities come back from ``jsonb``, which reorders keys. The
        fake ledger does the same, so this fails if the order is not restored.
        """
        await _ask(rig)
        replayed = (await _ask(rig)).answers["regime"]
        asked = list(DECISION_REGIME.as_request_questions()["regime"]["criteria"])
        stored = rig.ledger.answers[1][0].probabilities
        assert list(_jsonb_order(stored)) != asked, "the control does not bite"
        assert list(replayed.probabilities) == asked

    async def test_a_replay_answers_every_question_asked(self, rig: Rig) -> None:
        await _ask(rig)
        replayed = await _ask(rig)
        assert list(replayed.answers) == [k for k, _ in DECISION_REGIME.questions]
        assert all(isinstance(a, ValidatedAnswer) for a in replayed.answers.values())

    async def test_another_state_is_another_request(self, rig: Rig) -> None:
        await _ask(rig)
        other = await _ask(rig, state=_regime_state(bonds=_sleeve(trend="below")))
        assert not other.replayed
        assert len(rig.client.calls) == 2

    async def test_an_invalid_response_is_not_replayed(self, rig: Rig) -> None:
        """Only an ok row is canonical: a refused response is asked again."""
        rig.client.respond = lambda **kw: _call(200, "not json")
        first = await _ask(rig)
        assert first.status == "invalid"
        rig.client.respond = _answering()
        second = await _ask(rig)
        assert second.status == "ok" and not second.replayed
        assert len(rig.client.calls) == 2

    async def test_a_failed_call_is_not_replayed(self, rig: Rig) -> None:
        rig.client.respond = lambda **kw: _call(
            None, None, request_id=None, error_kind="timeout", error_class="T"
        )
        assert (await _ask(rig)).status == "error"
        rig.client.respond = _answering()
        assert (await _ask(rig)).status == "ok"
        assert len(rig.client.calls) == 2


# ---------------------------------------------------------------------------
# 4. No key: nothing written, nothing sent
# ---------------------------------------------------------------------------


class TestNoKeyWritesNothing:
    @pytest.mark.parametrize("api_key", [None, "", "   "])
    async def test_it_asks_nothing(self, rig: Rig, api_key: str | None) -> None:
        result = await _ask(rig, api_key=api_key)
        assert result == AskResult(status="no_key")
        assert "record_exchange" not in rig.ledger.log
        _nothing_happened(rig)

    async def test_the_ledger_is_asked_before_the_key(self, rig: Rig) -> None:
        await _ask(rig, api_key=None)
        assert rig.ledger.log == ["find_canonical"]


# ---------------------------------------------------------------------------
# 5. Over budget: a refused_budget row, nothing sent
# ---------------------------------------------------------------------------


def _assert_refused_row(row: Mapping[str, Any], status: str) -> None:
    assert row["status"] == status
    for name in (
        "http_status",
        "raw_body",
        "vendor_request_id",
        "model_answered",
        "error_class",
        "error_kind",
        "input_tokens",
        "output_tokens",
        "latency_ms",
    ):
        assert row.get(name) is None, name
    # Dated by the database: a request never sent has no send time to give.
    assert row.get("requested_at") is None
    assert row["model_requested"] == MODEL


class TestTheBudget:
    async def test_a_spent_budget_writes_a_refusal_and_sends_nothing(
        self, rig: Rig
    ) -> None:
        rig.conn.rows[flags.JEV_DAILY_REQUEST_BUDGET] = "3"
        rig.ledger.calls_today = 3

        result = await _ask(rig)

        assert rig.client.calls == []
        row = rig.ledger.only_request
        _assert_refused_row(row, "refused_budget")
        assert result == AskResult(status="refused_budget", request_row_id=row["id"])
        assert rig.ledger.answers[row["id"]] == []

    async def test_one_call_left_is_one_call(self, rig: Rig) -> None:
        rig.conn.rows[flags.JEV_DAILY_REQUEST_BUDGET] = "3"
        rig.ledger.calls_today = 2

        first = await _ask(rig)
        second = await _ask(rig, state=_regime_state(bonds=_sleeve(trend="near")))

        assert first.status == "ok"
        assert second.status == "refused_budget"
        assert len(rig.client.calls) == 1

    @pytest.mark.parametrize("stored", ["0", None, '"500"', "true", "-1", "1.5"])
    async def test_a_budget_that_cannot_be_read_permits_nothing(
        self, rig: Rig, stored: str | None
    ) -> None:
        if stored is None:
            del rig.conn.rows[flags.JEV_DAILY_REQUEST_BUDGET]
        else:
            rig.conn.rows[flags.JEV_DAILY_REQUEST_BUDGET] = stored
        result = await _ask(rig)
        assert result.status == "refused_budget"
        assert rig.client.calls == []

    async def test_probes_spend_the_budget_too(self, rig: Rig) -> None:
        rig.conn.rows[flags.JEV_DAILY_REQUEST_BUDGET] = "1"
        assert (await _ask(rig, PROBE_CONNECTIVITY)).status == "ok"
        assert (await _ask(rig, PROBE_CONNECTIVITY)).status == "refused_budget"
        assert len(rig.client.calls) == 1


# ---------------------------------------------------------------------------
# 6. Too large: a refused_limits row, nothing sent
# ---------------------------------------------------------------------------


def _state_tokens(state: RegimeState) -> int:
    dumped = DECISION_REGIME.dump_state(state)
    return jev_catalogue.estimate_tokens(json.dumps(dumped, ensure_ascii=False))


class TestTheSizeLimit:
    async def test_a_state_over_the_limit_writes_a_refusal_and_sends_nothing(
        self, rig: Rig
    ) -> None:
        tokens = _state_tokens(_regime_state())
        rig.conn.rows[flags.JEV_MAX_STATE_TOKENS] = str(tokens - 1)

        result = await _ask(rig)

        assert rig.client.calls == []
        row = rig.ledger.only_request
        _assert_refused_row(row, "refused_limits")
        assert result == AskResult(status="refused_limits", request_row_id=row["id"])

    async def test_a_state_at_the_limit_is_sent(self, rig: Rig) -> None:
        tokens = _state_tokens(_regime_state())
        rig.conn.rows[flags.JEV_MAX_STATE_TOKENS] = str(tokens)
        assert (await _ask(rig)).status == "ok"
        assert len(rig.client.calls) == 1

    @pytest.mark.parametrize("stored", ["0", None, "true", '"8000"', "999999"])
    async def test_a_limit_that_cannot_be_read_admits_nothing(
        self, rig: Rig, stored: str | None
    ) -> None:
        if stored is None:
            del rig.conn.rows[flags.JEV_MAX_STATE_TOKENS]
        else:
            rig.conn.rows[flags.JEV_MAX_STATE_TOKENS] = stored
        assert (await _ask(rig)).status == "refused_limits"
        assert rig.client.calls == []

    async def test_the_budget_is_asked_first(self, rig: Rig) -> None:
        rig.conn.rows[flags.JEV_DAILY_REQUEST_BUDGET] = "0"
        rig.conn.rows[flags.JEV_MAX_STATE_TOKENS] = "0"
        assert (await _ask(rig)).status == "refused_budget"


# ---------------------------------------------------------------------------
# 7. The call, recorded once
# ---------------------------------------------------------------------------


class TestACallIsRecordedOnce:
    async def test_an_answer_is_one_row_and_its_answers(self, rig: Rig) -> None:
        state = _regime_state()
        rig.client.respond = _answering(input_tokens=212, output_tokens=0)

        result = await _ask(rig, state=state)

        assert len(rig.client.calls) == 1
        row = rig.ledger.only_request
        questions = DECISION_REGIME.as_request_questions()
        dumped = DECISION_REGIME.dump_state(state)
        assert row["status"] == "ok"
        assert row["request_hash"] == jev_lane.request_hash(MODEL, dumped, questions)
        assert row["state_hash"] == jev_lane.state_hash(dumped)
        assert row["question_set"] == "decision.regime"
        assert row["question_set_version"] == 1
        assert row["pack_hash"] == DECISION_REGIME.pack_hash
        assert row["lane"] == "decision"
        assert row["provenance"] == "internal"
        assert (row["subject_type"], row["subject_id"]) == ("session", "2026-09-25")
        assert row["as_of"] == AS_OF
        assert row["state"] == dumped
        assert row["questions"] == questions
        assert list(row["questions"]["regime"]["criteria"]) == list(
            questions["regime"]["criteria"]
        )
        assert row["model_requested"] == row["model_answered"] == MODEL
        assert row["http_status"] == 200
        assert row["raw_body"] == _body(_clean_answers(questions))
        assert row["vendor_request_id"] == "req_0001"
        assert row["error_class"] is None and row["error_kind"] is None
        assert (row["input_tokens"], row["output_tokens"]) == (212, 0)
        assert row["latency_ms"] == 140
        assert row["requested_at"].tzinfo is not None

        answers = rig.ledger.answers[row["id"]]
        assert [a.question_key for a in answers] == ["regime"]
        (answer,) = answers
        assert answer.valid and answer.choice == answer.argmax == "risk_on"
        assert result == AskResult(
            status="ok",
            request_row_id=row["id"],
            answers={"regime": answer},
            replayed=False,
            error_kind=None,
        )

    async def test_the_answers_are_the_validators(self, rig: Rig) -> None:
        questions = DECISION_REGIME.as_request_questions()
        body = _body(_clean_answers(questions))
        rig.client.respond = lambda **kw: _call(200, body)
        result = await _ask(rig)
        expected = jev_validate.validate_body(body, questions, MODEL)
        assert tuple(result.answers.values()) == expected.answers

    async def test_the_client_is_handed_the_request_that_was_hashed(
        self, rig: Rig
    ) -> None:
        state = _regime_state(commodities=_sleeve(momentum="flat"))
        await _ask(rig, state=state)
        (call,) = rig.client.calls
        row = rig.ledger.only_request
        assert call["api_key"] == KEY
        assert call["model"] == MODEL
        assert call["state"] == DECISION_REGIME.dump_state(state) == row["state"]
        assert call["questions"] == DECISION_REGIME.as_request_questions()
        assert list(call["questions"]) == [k for k, _ in DECISION_REGIME.questions]
        assert list(call["questions"]["regime"]["criteria"]) == list(
            DECISION_REGIME.questions[0][1]["criteria"]
        )
        assert call["transport"] is None
        assert (
            jev_lane.request_hash(call["model"], call["state"], call["questions"])
            == (row["request_hash"])
        )

    async def test_what_the_client_does_to_its_arguments_changes_no_record(
        self, rig: Rig
    ) -> None:
        def vandal(**kwargs: Any) -> Any:
            body = _body(_clean_answers(kwargs["questions"]))
            kwargs["state"]["equities"]["trend"] = "below"
            kwargs["questions"]["regime"]["criteria"].clear()
            return _call(200, body)

        rig.client.respond = vandal
        state = _regime_state()
        await _ask(rig, state=state)
        row = rig.ledger.only_request
        assert row["state"] == DECISION_REGIME.dump_state(state)
        assert row["questions"] == DECISION_REGIME.as_request_questions()
        assert DECISION_REGIME.as_request_questions()["regime"]["criteria"]

    async def test_a_wrong_answer_in_a_sound_response_is_recorded_as_such(
        self, rig: Rig
    ) -> None:
        """
        Issue #15: a choice that is not the most probable option. The response
        is sound, so it is ``ok`` and canonical; the answer is not measured.
        """
        answers = _clean_answers(DECISION_REGIME.as_request_questions())
        answers["regime"]["choice"] = "neutral"
        rig.client.respond = lambda **kw: _call(200, _body(answers))

        result = await _ask(rig)

        assert result.status == "ok"
        answer = result.answers["regime"]
        assert not answer.valid and answer.invalid_reason == "choice_not_argmax"
        assert rig.ledger.answers[result.request_row_id] == [answer]
        again = await _ask(rig)
        assert again.replayed and again.answers["regime"] == answer

    async def test_the_counts_the_ledger_cannot_hold_are_not_written(
        self, rig: Rig
    ) -> None:
        rig.client.respond = lambda **kw: _call(
            503,
            "{}",
            latency_ms=2**31,
            input_tokens=-1,
            output_tokens=True,
            error_kind="server",
            error_class="TypeSafeInternalServerError",
        )
        await _ask(rig)
        row = rig.ledger.only_request
        assert row["latency_ms"] is None
        assert row["input_tokens"] is None and row["output_tokens"] is None

    async def test_the_validated_counts_are_the_ones_written(self, rig: Rig) -> None:
        """
        A validated row's counts are read from the body, strictly, and not from
        what the client says it parsed.
        """
        rig.client.respond = _answering(input_tokens=999, output_tokens=999)
        await _ask(rig)
        row = rig.ledger.only_request
        assert (row["input_tokens"], row["output_tokens"]) == (212, 0)


# ---------------------------------------------------------------------------
# A response refused whole
# ---------------------------------------------------------------------------


class TestAResponseRefusedWhole:
    async def test_another_model_is_invalid_and_asked_again(self, rig: Rig) -> None:
        questions = DECISION_REGIME.as_request_questions()
        body = _body(_clean_answers(questions), model="jev-1.13.1")
        rig.client.respond = lambda **kw: _call(200, body)

        result = await _ask(rig)

        assert result.status == "invalid"
        row = rig.ledger.only_request
        assert row["status"] == "invalid"
        assert row["model_answered"] == "jev-1.13.1"
        assert row["raw_body"] == body
        (answer,) = rig.ledger.answers[row["id"]]
        assert not answer.valid and answer.invalid_reason == "model_mismatch"
        assert result.answers == {"regime": answer}

        await _ask(rig)
        assert len(rig.client.calls) == 2, "a refused response was replayed"

    @pytest.mark.parametrize(
        "body, reason",
        [
            ("not json", "unparseable"),
            ("[]", "not_an_object"),
            ('{"model": "jev-1.13.0"}', "answers_not_an_object"),
            ('{"model": "jev-1.13.0", "answers": {}}', "no_answers"),
        ],
    )
    async def test_a_body_that_is_not_an_answer(
        self, rig: Rig, body: str, reason: str
    ) -> None:
        rig.client.respond = lambda **kw: _call(200, body)
        result = await _ask(rig)
        assert result.status == "invalid"
        assert rig.ledger.only_request["raw_body"] == body
        assert [a.invalid_reason for a in result.answers.values()] == [reason]


# ---------------------------------------------------------------------------
# A failed call is an error, recorded
# ---------------------------------------------------------------------------


class TestAFailedCallIsRecorded:
    @pytest.mark.parametrize(
        "status, kind, error_class",
        [
            (401, "auth", "TypeSafeAuthenticationError"),
            (403, "auth", "TypeSafePermissionDeniedError"),
            (422, "invalid_request", "TypeSafeUnprocessableEntityError"),
            (429, "rate_limited", "TypeSafeRateLimitError"),
            (529, "server", "TypeSafeInternalServerError"),
        ],
    )
    async def test_an_http_error(
        self, rig: Rig, status: int, kind: str, error_class: str
    ) -> None:
        body = '{"error": "Must supply an API key!"}'
        rig.client.respond = lambda **kw: _call(
            status, body, request_id="req_err", error_kind=kind, error_class=error_class
        )

        result = await _ask(rig)

        assert result == AskResult(
            status="error",
            request_row_id=1,
            answers={},
            replayed=False,
            error_kind=kind,
        )
        row = rig.ledger.only_request
        assert row["status"] == "error"
        assert row["http_status"] == status
        assert row["raw_body"] == body
        assert row["vendor_request_id"] == "req_err"
        assert (row["error_kind"], row["error_class"]) == (kind, error_class)
        assert row["model_answered"] is None
        assert rig.ledger.answers[row["id"]] == []

    @pytest.mark.parametrize(
        "kind, error_class",
        [
            ("connection", "TypeSafeAPIConnectionError"),
            ("timeout", "TypeSafeAPITimeoutError"),
        ],
    )
    async def test_no_response_records_no_response(
        self, rig: Rig, kind: str, error_class: str
    ) -> None:
        rig.client.respond = lambda **kw: _call(
            None, None, request_id=None, error_kind=kind, error_class=error_class
        )
        result = await _ask(rig)
        assert result.status == "error" and result.error_kind == kind
        row = rig.ledger.only_request
        assert row["http_status"] is None
        assert row["raw_body"] is None and row["vendor_request_id"] is None

    async def test_a_2xx_without_a_body_is_an_error(self, rig: Rig) -> None:
        rig.client.respond = lambda **kw: _call(200, None)
        assert (await _ask(rig)).status == "error"
        assert rig.ledger.only_request["http_status"] == 200

    @pytest.mark.parametrize("status", [199, 300, 404])
    async def test_a_body_outside_2xx_is_not_validated(
        self, rig: Rig, status: int
    ) -> None:
        body = _body(_clean_answers(DECISION_REGIME.as_request_questions()))
        rig.client.respond = lambda **kw: _call(status, body, error_kind="client")
        result = await _ask(rig)
        assert result.status == "error" and result.answers == {}

    async def test_a_body_the_ledger_cannot_store_is_kept_as_near_as_it_can(
        self, rig: Rig
    ) -> None:
        """
        A 403 page holding a NUL would fail the insert recording a call that
        was made. It is stored with U+FFFD where the NUL was; the fake ledger
        refuses a NUL exactly as the text column does.
        """
        body = "<html>blocked\x00\ud800</html>"
        rig.client.respond = lambda **kw: _call(
            403,
            body,
            request_id="req\x00x",
            error_kind="content_block",
            error_class="TypeSafePermissionDeniedError",
        )
        result = await _ask(rig)
        assert result.status == "error"
        row = rig.ledger.only_request
        assert row["raw_body"] == "<html>blocked\ufffd\ufffd</html>"
        assert row["vendor_request_id"] == "req\ufffdx"

    async def test_a_storable_body_is_stored_verbatim(self, rig: Rig) -> None:
        body = "<html>Forbidden — é ✓</html>"
        rig.client.respond = lambda **kw: _call(
            403, body, error_kind="content_block", error_class="X"
        )
        await _ask(rig)
        assert rig.ledger.only_request["raw_body"] == body


# ---------------------------------------------------------------------------
# A 2xx the SDK could not read
# ---------------------------------------------------------------------------


class TestA2xxTheSDKCouldNotReadIsJudgedByTheValidator:
    """
    The SDK raises for a 2xx whose shape it does not accept — a ``usage`` block
    missing, say, which the validator deliberately never lets decide — and the
    client still hands over the body exactly as it arrived. The validator's
    verdict is the status; the SDK's objection is kept beside it.
    """

    def _shape_error(self, body: str) -> Callable[..., Any]:
        return lambda **kw: _call(
            200,
            body,
            error_kind="response_shape",
            error_class="TypeSafeAPIResponseValidationError",
        )

    async def test_a_body_the_validator_accepts_is_ok_and_canonical(
        self, rig: Rig
    ) -> None:
        questions = DECISION_REGIME.as_request_questions()
        body = json.dumps({"model": MODEL, "answers": _clean_answers(questions)})
        validation = jev_validate.validate_body(body, questions, MODEL)
        rig.client.respond = self._shape_error(body)

        result = await _ask(rig)

        assert result.status == "ok"
        assert result.error_kind == "response_shape"
        assert tuple(result.answers.values()) == validation.answers
        assert all(answer.valid for answer in validation.answers)
        row = rig.ledger.only_request
        assert row["status"] == "ok"
        assert row["raw_body"] == body
        assert row["error_kind"] == "response_shape"
        assert row["error_class"] == "TypeSafeAPIResponseValidationError"
        again = await _ask(rig)
        assert again.replayed and len(rig.client.calls) == 1

    async def test_the_sdks_objection_is_said_out_loud(
        self, rig: Rig, caplog: pytest.LogCaptureFixture
    ) -> None:
        questions = DECISION_REGIME.as_request_questions()
        body = json.dumps({"model": MODEL, "answers": _clean_answers(questions)})
        rig.client.respond = self._shape_error(body)
        with caplog.at_level("WARNING", logger=jev_lane.__name__):
            await _ask(rig)
        said = [r.getMessage() for r in caplog.records]
        assert any("response_shape" in line and "ok" in line for line in said), said

    async def test_a_body_the_validator_refuses_is_invalid(self, rig: Rig) -> None:
        rig.client.respond = self._shape_error('{"answers": 3}')
        result = await _ask(rig)
        assert result.status == "invalid"
        assert result.error_kind == "response_shape"
        assert [a.invalid_reason for a in result.answers.values()] == [
            "answers_not_an_object"
        ]
        assert rig.ledger.only_request["error_kind"] == "response_shape"


# ---------------------------------------------------------------------------
# A probe always asks, and is never canonical
# ---------------------------------------------------------------------------


class TestAProbeAlwaysAsks:
    async def test_a_probe_asks_again_what_the_ledger_already_holds(
        self, rig: Rig
    ) -> None:
        canonical = await _ask(rig)
        rig.ledger.log.clear()

        probed = await _ask(rig, probe=True)

        assert len(rig.client.calls) == 2, "the probe replayed instead of asking"
        assert probed.status == "ok" and not probed.replayed
        assert probed.request_row_id != canonical.request_row_id
        assert "find_canonical" not in rig.ledger.log
        row = rig.ledger.requests[-1]
        assert row["lane"] == "probe"
        assert row["request_hash"] == rig.ledger.requests[0]["request_hash"]
        # The set and its words are the set's own: only the lane says probe.
        assert row["question_set"] == "decision.regime"
        assert row["pack_hash"] == DECISION_REGIME.pack_hash
        assert row["provenance"] == "internal"

    async def test_probes_are_never_replayed(self, rig: Rig) -> None:
        results = [await _ask(rig, PROBE_CONNECTIVITY) for _ in range(3)]
        assert len(rig.client.calls) == 3
        assert all(r.status == "ok" and not r.replayed for r in results)
        assert {r["lane"] for r in rig.ledger.requests} == {"probe"}
        assert len({r["request_hash"] for r in rig.ledger.requests}) == 1

    async def test_a_probe_lane_set_is_always_a_probe(self, rig: Rig) -> None:
        await _ask(rig, PROBE_CONNECTIVITY, probe=False)
        await _ask(rig, PROBE_CONNECTIVITY, probe=False)
        assert len(rig.client.calls) == 2
        assert "find_canonical" not in rig.ledger.log


# ---------------------------------------------------------------------------
# Two writers, one answer
# ---------------------------------------------------------------------------


class TestTheRaceForTheCanonicalAnswer:
    async def test_the_loser_replays_the_winner(self, rig: Rig) -> None:
        """
        Both find nothing and both call; the other writer commits first, and
        this one's write meets the canonical index.
        """
        state = _regime_state()
        dumped = DECISION_REGIME.dump_state(state)
        questions = DECISION_REGIME.as_request_questions()
        winners_answers = jev_validate.validate_body(
            _body(_clean_answers(questions)), questions, MODEL
        ).answers
        winner = {
            "request_hash": jev_lane.request_hash(MODEL, dumped, questions),
            "state_hash": jev_lane.state_hash(dumped),
            "question_set": DECISION_REGIME.name,
            "question_set_version": DECISION_REGIME.version,
            "pack_hash": DECISION_REGIME.pack_hash,
            "lane": "decision",
            "provenance": "internal",
            "subject_type": "session",
            "subject_id": "2026-09-25",
            "as_of": AS_OF,
            "state": dumped,
            "questions": questions,
            "model_requested": MODEL,
            "status": "ok",
            "model_answered": MODEL,
            "http_status": 200,
            "raw_body": "{}",
        }
        rig.ledger.before_record = lambda: rig.ledger.insert(winner, winners_answers)
        answers = _clean_answers(questions)
        answers["regime"]["probabilities"]["risk_on"] = 0.61
        answers["regime"]["probabilities"]["neutral"] = 0.22
        rig.client.respond = lambda **kw: _call(200, _body(answers))

        result = await _ask(rig, state=state)

        assert len(rig.client.calls) == 1
        assert len(rig.ledger.requests) == 1, "the losing answer was written"
        assert result.replayed is True
        assert result.status == "ok"
        assert result.request_row_id == rig.ledger.requests[0]["id"]
        assert tuple(result.answers.values()) == winners_answers

    async def test_any_other_unique_violation_is_raised(
        self, rig: Rig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Only the canonical index means "replay the winner". Here a winner is
        on record too, so a lane that replayed on any clash would pass for
        working; two answers to one question is a bug to surface, not a race.
        """

        async def clash(conn, request_fields, answers):
            rig.ledger.insert(
                {**request_fields, "status": "ok"},
                jev_validate.validate_body(
                    request_fields["raw_body"], request_fields["questions"], MODEL
                ).answers,
            )
            raise _unique_violation("jev_answers_one_per_question")

        monkeypatch.setattr(jev_repo, "record_exchange", clash)
        with pytest.raises(asyncpg.UniqueViolationError):
            await _ask(rig)
        assert len(rig.ledger.requests) == 1, "the control does not bite"

    async def test_a_conflict_with_no_winner_to_read_is_raised(
        self, rig: Rig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def clash(conn, request_fields, answers):
            raise _unique_violation(jev_repo.CANONICAL_INDEX)

        monkeypatch.setattr(jev_repo, "record_exchange", clash)
        with pytest.raises(asyncpg.UniqueViolationError):
            await _ask(rig)


# ---------------------------------------------------------------------------
# The request's identity
# ---------------------------------------------------------------------------


def _independent_hash(model: str, state: Any, questions: Any) -> str:
    """The definition, written again without the lane's code."""
    body = {
        "model": model,
        "state": json.loads(json.dumps(state, sort_keys=True)),
        "questions": questions,
    }
    text = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _reversed_options(questions: Mapping[str, dict]) -> dict[str, dict]:
    out = json.loads(json.dumps(questions))
    criteria = out["regime"]["criteria"]
    out["regime"]["criteria"] = dict(reversed(list(criteria.items())))
    return out


class TestTheRequestHash:
    STATE = {"b": {"y": 1, "x": [3, 1, 2]}, "a": "é"}
    QUESTIONS = {
        "regime": DECISION_REGIME.as_request_questions()["regime"],
        "about_the_sun": PROBE_CONNECTIVITY.as_request_questions()["about_the_sun"],
    }

    def test_it_is_the_documented_definition(self) -> None:
        assert jev_lane.request_hash(MODEL, self.STATE, self.QUESTIONS) == (
            _independent_hash(MODEL, self.STATE, self.QUESTIONS)
        )

    def test_the_states_key_order_does_not_matter(self) -> None:
        reordered = {"a": "é", "b": {"x": [3, 1, 2], "y": 1}}
        assert list(reordered) != list(self.STATE)
        assert jev_lane.request_hash(MODEL, reordered, self.QUESTIONS) == (
            jev_lane.request_hash(MODEL, self.STATE, self.QUESTIONS)
        )
        assert jev_lane.state_hash(reordered) == jev_lane.state_hash(self.STATE)

    def test_the_order_of_a_list_in_the_state_does(self) -> None:
        shuffled = {"b": {"y": 1, "x": [1, 2, 3]}, "a": "é"}
        assert jev_lane.request_hash(MODEL, shuffled, self.QUESTIONS) != (
            jev_lane.request_hash(MODEL, self.STATE, self.QUESTIONS)
        )
        assert jev_lane.state_hash(shuffled) != jev_lane.state_hash(self.STATE)

    def test_the_options_order_does(self) -> None:
        reordered = _reversed_options(self.QUESTIONS)
        assert reordered == self.QUESTIONS, "dict equality ignores order"
        assert jev_lane.request_hash(MODEL, self.STATE, reordered) != (
            jev_lane.request_hash(MODEL, self.STATE, self.QUESTIONS)
        )

    def test_the_questions_order_does(self) -> None:
        reordered = dict(reversed(list(self.QUESTIONS.items())))
        assert jev_lane.request_hash(MODEL, self.STATE, reordered) != (
            jev_lane.request_hash(MODEL, self.STATE, self.QUESTIONS)
        )

    def test_the_model_does(self) -> None:
        assert jev_lane.request_hash("jev-1.13.1", self.STATE, self.QUESTIONS) != (
            jev_lane.request_hash(MODEL, self.STATE, self.QUESTIONS)
        )

    def test_a_value_in_the_state_does(self) -> None:
        changed = {"b": {"y": 2, "x": [3, 1, 2]}, "a": "é"}
        assert jev_lane.request_hash(MODEL, changed, self.QUESTIONS) != (
            jev_lane.request_hash(MODEL, self.STATE, self.QUESTIONS)
        )

    def test_the_state_hash_is_the_sorted_compact_state(self) -> None:
        text = json.dumps(self.STATE, sort_keys=True, separators=(",", ":"))
        text = json.dumps(json.loads(text), separators=(",", ":"), ensure_ascii=False)
        assert jev_lane.state_hash(self.STATE) == (
            hashlib.sha256(text.encode("utf-8")).hexdigest()
        )

    @pytest.mark.parametrize("bad", [float("nan"), float("inf")])
    def test_a_number_json_cannot_spell_is_refused(self, bad: float) -> None:
        with pytest.raises(ValueError):
            jev_lane.request_hash(MODEL, {"x": bad}, self.QUESTIONS)

    async def test_the_lane_records_the_hash_of_what_it_sent(self, rig: Rig) -> None:
        await _ask(rig)
        row = rig.ledger.only_request
        assert row["request_hash"] == _independent_hash(
            row["model_requested"], row["state"], row["questions"]
        )


# ---------------------------------------------------------------------------
# The probe job
# ---------------------------------------------------------------------------


def _probe_answering(noul: object) -> Callable[..., Any]:
    def respond(**kwargs: Any) -> Any:
        answers = {"about_the_sun": {"type": "noul", "noul": noul}}
        return _call(200, _body(answers))

    return respond


class TestRunProbe:
    async def test_it_asks_the_connectivity_set_as_a_probe(self, rig: Rig) -> None:
        report = await jev_lane.run_probe(rig.conn, KEY)

        (call,) = rig.client.calls
        assert call["state"] == {"text": jev_questions.PROBE_TEXT}
        assert call["questions"] == PROBE_CONNECTIVITY.as_request_questions()
        row = rig.ledger.only_request
        assert row["lane"] == "probe" and row["question_set"] == "probe.connectivity"
        assert (row["subject_type"], row["subject_id"]) == ("probe", "connectivity")
        assert row["as_of"].tzinfo is not None
        assert report["status"] == "ok"
        assert report["request_id"] == row["id"]

    async def test_it_reports_what_it_should_have_heard(self, rig: Rig) -> None:
        rig.client.respond = _probe_answering(0.97)
        report = await jev_lane.run_probe(rig.conn, KEY)
        assert report == {
            "question_set": "probe.connectivity",
            "question_set_version": 1,
            "status": "ok",
            "request_id": 1,
            "error_kind": None,
            "answers": {
                "about_the_sun": {
                    "type": "noul",
                    "valid": True,
                    "invalid_reason": None,
                    "argmax": "true",
                    "margin": pytest.approx(0.94),
                    "noul": 0.97,
                }
            },
            "as_expected": True,
        }
        json.dumps(report)

    async def test_the_wrong_answer_is_reported_as_wrong(self, rig: Rig) -> None:
        rig.client.respond = _probe_answering(0.03)
        report = await jev_lane.run_probe(rig.conn, KEY)
        assert report["status"] == "ok" and report["as_expected"] is False

    @pytest.mark.parametrize("noul", [0.5, 1.5, "0.97", True])
    async def test_an_unmeasured_answer_is_neither_right_nor_wrong(
        self, rig: Rig, noul: object
    ) -> None:
        rig.client.respond = _probe_answering(noul)
        report = await jev_lane.run_probe(rig.conn, KEY)
        assert report["answers"]["about_the_sun"]["valid"] is False
        assert report["as_expected"] is None

    async def test_a_failed_probe_reports_the_failure(self, rig: Rig) -> None:
        rig.client.respond = lambda **kw: _call(
            401, '{"error": "bad key"}', error_kind="auth", error_class="A"
        )
        report = await jev_lane.run_probe(rig.conn, KEY)
        assert report["status"] == "error" and report["error_kind"] == "auth"
        assert report["answers"] == {} and report["as_expected"] is None

    async def test_a_probe_while_off_reports_that_and_asks_nothing(
        self, rig: Rig
    ) -> None:
        rig.conn.rows[flags.JEV_ENABLED] = "false"
        report = await jev_lane.run_probe(rig.conn, KEY)
        assert report["status"] == "disabled" and report["request_id"] is None
        _nothing_happened(rig)

    async def test_the_transport_is_handed_through(self, rig: Rig) -> None:
        seam = object()
        await jev_lane.run_probe(rig.conn, KEY, transport=seam)
        assert rig.client.calls[0]["transport"] is seam

    def test_every_probe_knows_what_it_should_hear(self) -> None:
        """
        A registered probe-lane set whose words changed without its expected
        answers being decided again fails here.
        """
        probes = {
            (qs.name, qs.version): qs
            for qs in jev_questions.REGISTRY.values()
            if qs.lane == "probe"
        }
        assert probes, "no probe is registered"
        assert set(jev_lane.PROBE_EXPECTED) == set(probes)
        for identity, expected in jev_lane.PROBE_EXPECTED.items():
            questions = probes[identity].as_request_questions()
            assert set(expected) == set(questions), identity
            for key, argmax in expected.items():
                assert questions[key]["type"] == "noul"
                assert argmax in ("true", "false")


# ---------------------------------------------------------------------------
# The transport is a test seam
# ---------------------------------------------------------------------------

#: The callables a transport could be handed to on its way to the SDK.
_SEAM_CALLEES = frozenset({"ask", "run_probe"})
_LANE = "src/programme/jev_lane.py"


def _transport_handoffs(relative: str, source: str) -> list[str]:
    """
    Every call to an ``ask`` or ``run_probe`` in ``source`` that passes a
    transport, other than the lane handing its own parameter through.
    """
    found = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name not in _SEAM_CALLEES:
            continue
        for keyword in node.keywords:
            forwarded = (
                relative == _LANE
                and isinstance(keyword.value, ast.Name)
                and keyword.value.id == "transport"
            )
            if keyword.arg is None or (keyword.arg == "transport" and not forwarded):
                found.append(f"{relative}:{node.lineno}: {ast.unparse(node)}")
    return found


class TestTheTransportIsATestSeam:
    @pytest.mark.parametrize(
        "relative, source, offends",
        [
            ("src/programme/tick.py", "jev_lane.ask(conn, transport=t)", True),
            ("src/programme/main.py", "run_probe(conn, key, transport=x)", True),
            ("src/programme/x.py", "jev_client.ask(api_key=k, transport=None)", True),
            ("src/programme/x.py", "jev_lane.ask(conn, **options)", True),
            (_LANE, "jev_client.ask(api_key=k, transport=transport)", False),
            (_LANE, "jev_client.ask(api_key=k, transport=other)", True),
            ("src/programme/tick.py", "jev_lane.ask(conn, transport=transport)", True),
            ("src/programme/main.py", "jev_lane.run_probe(conn, api_key)", False),
            ("src/programme/x.py", "client.system_one(s, q, transport=t)", False),
        ],
    )
    def test_the_scan(self, relative: str, source: str, offends: bool) -> None:
        assert bool(_transport_handoffs(relative, source)) is offends

    def test_nothing_in_src_hands_one_over(self) -> None:
        offenders = []
        for path in sorted(SRC.rglob("*.py")):
            relative = path.relative_to(ROOT).as_posix()
            offenders += _transport_handoffs(relative, path.read_text("utf-8"))
        assert not offenders, (
            "production code hands a transport towards the SDK; it is a test "
            "seam, and one supplied here would replace the route to the "
            "vendor:\n" + "\n".join(offenders)
        )

    def test_the_lane_hands_its_own_through(self) -> None:
        tree = ast.parse((ROOT / _LANE).read_text("utf-8"))
        handoffs = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "ask"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "jev_client"
        ]
        assert len(handoffs) == 1, "the lane calls the client in one place"
        (call,) = handoffs
        transport = [k for k in call.keywords if k.arg == "transport"]
        assert len(transport) == 1 and isinstance(transport[0].value, ast.Name)
        assert transport[0].value.id == "transport"


# ---------------------------------------------------------------------------
# The key the lane is handed
# ---------------------------------------------------------------------------


class TestTheKeyTheLaneIsHanded:
    """
    ``Programme._resolve_typesafe_key``: the vault first, the environment
    second, like the Anthropic key, and read for every job.
    """

    @pytest.fixture
    def vault(self, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
        from src.db.repos import secrets as secret_repo

        stored: dict[str, Any] = {"values": {}, "asked": []}

        async def get(conn, name, key):
            stored["asked"].append((name, key))
            return stored["values"].get(name)

        monkeypatch.setattr(secret_repo, "get", get)
        return stored

    def _programme(self, typesafe_key: str | None) -> Any:
        from src.programme.main import Programme

        return Programme(
            "postgresql://unused",
            api_key="anthropic-env",
            secrets_key="the-secrets-key",
            typesafe_key=typesafe_key,
        )

    async def test_the_vault_comes_first(self, vault: dict[str, Any]) -> None:
        from src.db.repos import secrets as secret_repo

        vault["values"][secret_repo.TYPESAFE_API_KEY] = "from-the-vault"
        programme = self._programme("from-the-environment")
        assert await programme._resolve_typesafe_key(object()) == "from-the-vault"
        assert vault["asked"] == [(secret_repo.TYPESAFE_API_KEY, "the-secrets-key")]

    async def test_the_environment_is_the_fallback(self, vault: dict[str, Any]) -> None:
        programme = self._programme("from-the-environment")
        assert await programme._resolve_typesafe_key(object()) == (
            "from-the-environment"
        )

    async def test_both_absent_is_no_key(self, vault: dict[str, Any]) -> None:
        assert await self._programme(None)._resolve_typesafe_key(object()) is None

    async def test_it_is_not_the_anthropic_key(self, vault: dict[str, Any]) -> None:
        from src.db.repos import secrets as secret_repo

        vault["values"][secret_repo.ANTHROPIC_API_KEY] = "anthropic-vault"
        assert await self._programme(None)._resolve_typesafe_key(object()) is None

    def test_the_environment_variable_is_read_by_its_name(self) -> None:
        """
        ``.env.example`` documents ``TYPESAFE_API_KEY`` and its inventory test
        counts it as read only if a literal read of it exists.
        """
        source = (SRC / "programme" / "main.py").read_text("utf-8")
        assert 'os.environ.get("TYPESAFE_API_KEY", "")' in source

    @pytest.mark.parametrize(
        "environment, handed",
        [
            ("  ts-env-key\n", "ts-env-key"),
            ("", None),
            ("   ", None),
            (None, None),
        ],
    )
    async def test_the_process_hands_the_environments_key_to_the_programme(
        self,
        monkeypatch: pytest.MonkeyPatch,
        environment: str | None,
        handed: str | None,
    ) -> None:
        """
        What ``python -m src.programme.main`` does with ``TYPESAFE_API_KEY``:
        stripped, and absent when blank, as the Anthropic key is.
        """
        from types import SimpleNamespace

        from src.programme import main as programme_main

        built: list[dict[str, Any]] = []
        signature = inspect.signature(programme_main.Programme)

        class Recorder:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                bound = signature.bind(*args, **kwargs)
                bound.apply_defaults()
                built.append(dict(bound.arguments))

            def stop(self) -> None:
                pass

            async def start(self) -> None:
                pass

        monkeypatch.setattr(programme_main, "Programme", Recorder)
        monkeypatch.setattr(
            programme_main,
            "get_settings",
            lambda: SimpleNamespace(
                database_url="postgresql://unused", secrets_key="the-secrets-key"
            ),
        )
        monkeypatch.setattr(programme_main, "require_database_url", lambda s: None)
        if environment is None:
            monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
        else:
            monkeypatch.setenv("TYPESAFE_API_KEY", environment)

        await programme_main._amain()

        (arguments,) = built
        assert arguments["typesafe_key"] == handed
        assert arguments["secrets_key"] == "the-secrets-key"


class TestNothingSentReachesALog:
    """
    What is sent to a vendor does not also go to wherever the logs go: not the
    key, not the state, not the body that came back. The probe's state is one
    fixed sentence, which makes it easy to look for.
    """

    @pytest.mark.parametrize(
        "respond",
        [
            pytest.param(_probe_answering(0.97), id="ok"),
            pytest.param(lambda **kw: _call(200, "not json at all"), id="invalid"),
            pytest.param(
                lambda **kw: _call(
                    403,
                    "<html>blocked by the gateway</html>",
                    error_kind="content_block",
                    error_class="TypeSafePermissionDeniedError",
                ),
                id="error",
            ),
        ],
    )
    async def test_the_key_the_state_and_the_body_stay_out(
        self, rig: Rig, caplog: pytest.LogCaptureFixture, respond: Any
    ) -> None:
        rig.client.respond = respond
        with caplog.at_level("DEBUG"):
            await jev_lane.run_probe(rig.conn, KEY)
            await jev_lane.run_probe(rig.conn, None)
        said = "\n".join(r.getMessage() for r in caplog.records)
        assert caplog.records, "nothing was logged, so this proves nothing"
        assert KEY not in said
        assert jev_questions.PROBE_TEXT not in said
        body = rig.ledger.requests[0]["raw_body"]
        assert body not in said


def _programme_imports(module: str) -> set[str]:
    """The ``src.programme`` modules ``module`` imports, however spelled."""
    tree = ast.parse((SRC / "programme" / f"{module}.py").read_text("utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            package = "src.programme" if node.level == 1 else node.module or ""
            if node.level == 1 and node.module:
                found.add(node.module.split(".")[0])
            elif package == "src.programme":
                found |= {alias.name for alias in node.names}
            elif package.startswith("src.programme."):
                found.add(package.split(".")[2])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("src.programme."):
                    found.add(alias.name.split(".")[2])
    return {m for m in found if (SRC / "programme" / f"{m}.py").exists()}


def test_the_lane_never_reaches_the_programmes_other_model() -> None:
    """
    docs/08: the lanes never import ``client.py``, so on the signal path the
    cascade ends at Jev. Nothing the lane loads may hold the Anthropic client,
    or the code that prompts it.
    """
    seen: set[str] = set()
    todo = ["jev_lane"]
    while todo:
        module = todo.pop()
        if module not in seen:
            seen.add(module)
            todo += sorted(_programme_imports(module))
    assert "jev_client" in seen, "the walk is reading nothing"
    reached = seen & {"client", "author", "panel", "tick"}
    assert not reached, f"jev_lane reaches {sorted(reached)}"


def test_the_fakes_take_what_the_real_functions_take() -> None:
    """
    Guards the rig. The lane calls the ledger positionally, so a fake whose
    parameters drifted from ``jev_repo``'s would pass calls the real one
    refuses; and a fake that is not a coroutine function would pass nothing.
    """
    ledger = _Ledger()
    for name in ("find_canonical", "requests_today", "record_exchange", "answers_for"):
        fake, real = getattr(ledger, name), getattr(jev_repo, name)
        assert asyncio.iscoroutinefunction(fake), name
        assert list(inspect.signature(fake).parameters) == list(
            inspect.signature(real).parameters
        ), name
    assert asyncio.iscoroutinefunction(_Client(_answering()).ask)

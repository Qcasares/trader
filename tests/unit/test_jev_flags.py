"""
test_jev_flags.py
-----------------
The Jev switches fail closed.

Every Jev setting is a row in ``system_flags`` read through
``src/programme/flags.py``, and every reader there makes the promise
``programme_enabled`` makes: a missing row, an unreadable value, a value of the
wrong type and a database error all read as off. A fail-closed control that has
never been seen failing closed is a claim rather than a control, so each reader
is driven through each failure here. Each "off" is paired with an "on" from the
same fake, because a reader that always said no would pass every failure case
below while switching Jev off for good — the guard ``test_api.py`` puts on the
kill switch.

Unit tests: the database is faked at the one query the readers make. The fake
answers as asyncpg does with no codec registered, handing ``jsonb`` back as its
JSON text for ``flag_repo.get_flag`` to parse, so each test states exactly what
is stored: ``'"true"'`` is the JSON string and ``'true'`` the JSON boolean. The
real-Postgres counterpart, which reads migration 0012's own seeds through these
readers, is ``tests/integration/test_jev_schema.py``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import pathlib
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field

import asyncpg
import pytest

from src.programme import flags, jev_catalogue

ROOT = pathlib.Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "migrations" / "0012_jev.sql"

#: The one query ``flag_repo.get_flag`` makes. The fake refuses any other, so a
#: reader that starts reading some other way gets looked at rather than
#: absorbed.
QUERY = "SELECT value FROM system_flags WHERE key = $1"


class _SystemFlags:
    """
    ``system_flags`` as the readers see it through asyncpg.

    ``rows`` maps a key to the JSON text in its ``value`` column. ``failing``
    maps a key to a factory for the exception reading it raises. ``asked``
    records every key read, in order.
    """

    def __init__(
        self,
        rows: Mapping[str, str] | None = None,
        failing: Mapping[str, Callable[[], BaseException]] | None = None,
    ) -> None:
        self.rows = dict(rows or {})
        self.failing = dict(failing or {})
        self.asked: list[str] = []

    async def fetchrow(self, query: str, *args: object) -> dict[str, str] | None:
        assert query == QUERY, query
        (key,) = args
        assert isinstance(key, str), key
        self.asked.append(key)
        if key in self.failing:
            raise self.failing[key]()
        if key not in self.rows:
            return None
        return {"value": self.rows[key]}


def _everything_on() -> dict[str, str]:
    """Every Jev switch on and every Jev setting at its seeded, usable value."""
    rows = {key: "true" for key in flags.JEV_KEYS}
    rows[flags.JEV_MODEL] = json.dumps(jev_catalogue.DEFAULT_MODEL)
    rows[flags.JEV_DAILY_REQUEST_BUDGET] = json.dumps(
        jev_catalogue.DEFAULT_DAILY_REQUEST_BUDGET
    )
    rows[flags.JEV_MAX_STATE_TOKENS] = json.dumps(
        jev_catalogue.DEFAULT_MAX_STATE_TOKENS
    )
    return rows


#: What reading a row can raise. The readers' ``except`` is broad on purpose,
#: and these are the failures it is broad for: not only Postgres's own errors
#: but the socket and the pool beneath them.
DATABASE_ERRORS: dict[str, Callable[[], BaseException]] = {
    "connection closed": lambda: asyncpg.exceptions.ConnectionDoesNotExistError(
        "connection was closed in the middle of operation"
    ),
    "statement timeout": lambda: asyncpg.exceptions.QueryCanceledError(
        "canceling statement due to statement timeout"
    ),
    "table missing": lambda: asyncpg.exceptions.UndefinedTableError(
        'relation "system_flags" does not exist'
    ),
    "pool closing": lambda: asyncpg.InterfaceError("pool is closing"),
    "socket reset": lambda: ConnectionResetError(104, "Connection reset by peer"),
    "timeout": lambda: TimeoutError(),
}

#: JSON that is not ``true``: plausible things for a hand-written UPDATE to
#: store while meaning "on", and a JSON null, which is not a missing row but
#: must read the same way.
NOT_TRUE: dict[str, str] = {
    "the string true": '"true"',
    "the string True": '"True"',
    "the string on": '"on"',
    "one": "1",
    "one point oh": "1.0",
    "null": "null",
    "a list holding true": "[true]",
    "an object holding true": '{"enabled": true}',
}

#: Text that is not JSON at all. Postgres will not store any of it in a
#: ``jsonb`` column, so a reader only meets it when something between the
#: column and the reader has changed — which is exactly when to read off.
NOT_JSON: dict[str, str] = {
    "Python's True": "True",
    "truncated": "tru",
    "half an object": "{",
    "empty": "",
    "single-quoted": "'true'",
}


def _ids(table: Mapping[str, object]) -> list[str]:
    return list(table)


# ---------------------------------------------------------------------------
# Every reader, for what they have in common
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Reader:
    """One reader, the row it is being tested on, and what "closed" means."""

    label: str
    read: Callable[[_SystemFlags], Awaitable[object]]
    key: str
    closed: object
    #: Rows that must be on for ``key`` to be the one that decides.
    beside: Mapping[str, str] = field(default_factory=dict)

    def is_closed(self, value: object) -> bool:
        """
        ``value`` is this reader's closed answer, type included: ``0 == False``
        in Python, and a switch that answered ``0`` or a count that answered
        ``False`` would compare equal to the right answer while being the wrong
        kind of thing for its caller.
        """
        return type(value) is type(self.closed) and value == self.closed


READERS = (
    Reader("jev_enabled", flags.jev_enabled, flags.JEV_ENABLED, False),
    Reader(
        "jev_area_enabled by its own switch",
        lambda conn: flags.jev_area_enabled(conn, "ops"),
        "jev_area_ops",
        False,
        {flags.JEV_ENABLED: "true"},
    ),
    Reader(
        "jev_area_enabled by the master switch",
        lambda conn: flags.jev_area_enabled(conn, "ops"),
        flags.JEV_ENABLED,
        False,
        {"jev_area_ops": "true"},
    ),
    Reader("jev_model", flags.jev_model, flags.JEV_MODEL, None),
    Reader(
        "jev_daily_request_budget",
        flags.jev_daily_request_budget,
        flags.JEV_DAILY_REQUEST_BUDGET,
        0,
    ),
    Reader(
        "jev_max_state_tokens",
        flags.jev_max_state_tokens,
        flags.JEV_MAX_STATE_TOKENS,
        0,
    ),
    Reader(
        "jev_send_internal_detail",
        flags.jev_send_internal_detail,
        flags.JEV_SEND_INTERNAL_DETAIL,
        False,
    ),
)


@pytest.mark.parametrize("reader", READERS, ids=lambda r: r.label)
class TestEveryReaderFailsClosed:
    async def test_it_opens_when_everything_is_on(self, reader: Reader) -> None:
        """
        The pair to every refusal below, from the same fake. A reader that
        always answered "closed" would pass the rest of this class.
        """
        assert await reader.read(_SystemFlags(_everything_on())) != reader.closed

    @pytest.mark.parametrize(
        "error", DATABASE_ERRORS.values(), ids=_ids(DATABASE_ERRORS)
    )
    async def test_a_database_error_reads_closed(
        self, reader: Reader, error: Callable[[], BaseException]
    ) -> None:
        conn = _SystemFlags(_everything_on(), failing={reader.key: error})
        assert reader.is_closed(await reader.read(conn))
        assert reader.key in conn.asked

    async def test_it_says_which_setting_it_could_not_read(
        self, reader: Reader, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        A switch that is off because the database is unreachable looks exactly
        like one an operator turned off, except in the log. So the log names
        the setting.
        """
        conn = _SystemFlags(
            _everything_on(), failing={reader.key: DATABASE_ERRORS["socket reset"]}
        )
        with caplog.at_level(logging.ERROR, logger=flags.__name__):
            await reader.read(conn)
        assert any(reader.key in record.getMessage() for record in caplog.records)

    async def test_a_cancellation_is_not_read_as_closed(self, reader: Reader) -> None:
        """
        Cancellation is how the programme shuts down, not a database error. An
        ``except`` broad enough to swallow it would turn a stop into "off" and
        let the loop carry on.
        """
        conn = _SystemFlags(
            _everything_on(), failing={reader.key: asyncio.CancelledError}
        )
        with pytest.raises(asyncio.CancelledError):
            await reader.read(conn)


# ---------------------------------------------------------------------------
# The switches
# ---------------------------------------------------------------------------


SWITCHES = tuple(reader for reader in READERS if isinstance(reader.closed, bool))


@pytest.mark.parametrize("switch", SWITCHES, ids=lambda s: s.label)
class TestEverySwitchIsOnOnlyForJsonTrue:
    """
    ``programme_enabled``'s rule, for each Jev switch and for the master
    switch as an area sees it.
    """

    @staticmethod
    def _conn(switch: Reader, stored: str | None) -> _SystemFlags:
        rows = dict(switch.beside)
        if stored is not None:
            rows[switch.key] = stored
        return _SystemFlags(rows)

    async def test_json_true_is_on(self, switch: Reader) -> None:
        assert await switch.read(self._conn(switch, "true")) is True

    async def test_json_false_is_off(self, switch: Reader) -> None:
        assert await switch.read(self._conn(switch, "false")) is False

    async def test_a_missing_row_is_off(self, switch: Reader) -> None:
        assert await switch.read(self._conn(switch, None)) is False

    @pytest.mark.parametrize("stored", NOT_TRUE.values(), ids=_ids(NOT_TRUE))
    async def test_json_that_is_not_true_is_off(
        self, switch: Reader, stored: str
    ) -> None:
        assert await switch.read(self._conn(switch, stored)) is False

    @pytest.mark.parametrize("stored", NOT_JSON.values(), ids=_ids(NOT_JSON))
    async def test_a_value_that_is_not_json_is_off(
        self, switch: Reader, stored: str
    ) -> None:
        assert await switch.read(self._conn(switch, stored)) is False

    async def test_a_string_true_is_called_out(
        self, switch: Reader, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        Whoever stored ``"true"`` believes the switch is on, and the log is
        where they find out that it is not, and why.
        """
        with caplog.at_level(logging.ERROR, logger=flags.__name__):
            await switch.read(self._conn(switch, '"true"'))
        messages = [record.getMessage() for record in caplog.records]
        assert any(
            switch.key in message and "not a boolean" in message for message in messages
        ), messages


class TestTheAreaSwitches:
    @pytest.mark.parametrize("area", jev_catalogue.AREAS)
    async def test_each_area_answers_to_its_own_switch(self, area: str) -> None:
        rows = {f"jev_area_{other}": "false" for other in jev_catalogue.AREAS}
        rows[flags.JEV_ENABLED] = "true"
        rows[f"jev_area_{area}"] = "true"
        conn = _SystemFlags(rows)
        answers = {
            other: await flags.jev_area_enabled(conn, other)
            for other in jev_catalogue.AREAS
        }
        assert answers == {other: other == area for other in jev_catalogue.AREAS}

    async def test_every_area_is_off_while_the_master_switch_is_off(self) -> None:
        """
        The master switch has to stop everything without an operator having to
        remember which areas were on, so an area's own ``true`` counts for
        nothing beneath it.
        """
        rows = _everything_on()
        rows[flags.JEV_ENABLED] = "false"
        conn = _SystemFlags(rows)
        for area in jev_catalogue.AREAS:
            assert await flags.jev_area_enabled(conn, area) is False, area

    @pytest.mark.parametrize(
        "name",
        [
            "guardrail",
            "decision",
            "probe",
            "",
            "RESEARCH",
            " research",
            "research ",
            "jev_area_research",
            "enabled",
            None,
            1,
            ("research",),
        ],
        ids=repr,
    )
    async def test_a_name_that_is_not_an_area_is_off_and_reads_nothing(
        self, name: object
    ) -> None:
        """
        ``"guardrail"`` is a lane and ``"guardrails"`` its area, and the lane's
        name is the mistake most likely to reach here. Rows for the wrong names
        are stored and on, as a hand-written INSERT "fixing" a lane would leave
        them, and still nothing is read.
        """
        rows = _everything_on()
        for stray in ("guardrail", "decision", "probe", "", "RESEARCH", "enabled"):
            rows[f"jev_area_{stray}"] = "true"
        conn = _SystemFlags(rows)
        assert await flags.jev_area_enabled(conn, name) is False  # type: ignore[arg-type]
        assert conn.asked == []

    @pytest.mark.parametrize(
        ("lane", "area"),
        [(lane, area) for lane, area in jev_catalogue.LANE_AREA.items() if area],
    )
    async def test_every_lane_s_area_is_a_switch_that_can_be_turned_on(
        self, lane: str, area: str
    ) -> None:
        """
        The lane looks its area up in ``LANE_AREA`` and asks this reader. A
        mapping that named something this reader does not accept would leave
        that lane off forever, with every switch on the page reading on.
        """
        assert await flags.jev_area_enabled(_SystemFlags(_everything_on()), area)

    async def test_the_probe_has_no_area_switch(self) -> None:
        """
        The probe answers to ``jev_enabled`` alone: it is the check that a key
        and a pinned model work before any area is switched on. Its entry in
        ``LANE_AREA`` is not an area, so no area switch can stand in for the
        master switch on its behalf.
        """
        probe_area = jev_catalogue.LANE_AREA["probe"]
        assert probe_area is None
        conn = _SystemFlags(_everything_on())
        assert await flags.jev_area_enabled(conn, probe_area) is False  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The model
# ---------------------------------------------------------------------------


def _model(stored: str | None) -> _SystemFlags:
    return _SystemFlags({} if stored is None else {flags.JEV_MODEL: stored})


class TestTheModelIsPinned:
    async def test_the_seeded_model_is_returned(self) -> None:
        assert (
            await flags.jev_model(_model(json.dumps(jev_catalogue.DEFAULT_MODEL)))
            == "jev-1.13.0"
        )

    @pytest.mark.parametrize(
        "alias",
        [
            *sorted(jev_catalogue.REFUSED_ALIASES),
            "JEV-LATEST",
            " jev-latest",
            "jev-preview\n",
        ],
        ids=repr,
    )
    async def test_an_alias_is_refused(self, alias: str) -> None:
        assert await flags.jev_model(_model(json.dumps(alias))) is None

    async def test_an_alias_is_refused_as_an_alias(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        The catalogue's sentence reaches the log, so an operator learns that
        ``jev-latest`` was refused for being an alias rather than guessing.
        """
        with caplog.at_level(logging.ERROR, logger=flags.__name__):
            await flags.jev_model(_model('"jev-latest"'))
        messages = [record.getMessage() for record in caplog.records]
        assert any(
            flags.JEV_MODEL in message and "alias" in message for message in messages
        ), messages

    @pytest.mark.parametrize(
        "model",
        [
            "jev-1.13.1",
            "jev-2.0.0",
            "jev-1.12",
            "jev-1.13.0\n",
            "jev-1.13.0 ",
            " jev-1.13.0",
            "JEV-1.13.0",
            "jev-1.13.0-rc1",
            "jev-\u0661.13.0",  # an Arabic-Indic one, which \d matches without re.ASCII
            "typesafe/jev-1.13",
            "typesafe-jev-1.13.0",
            "claude-sonnet-5",
        ],
        ids=repr,
    )
    async def test_an_id_outside_the_catalogue_is_refused(self, model: str) -> None:
        """
        Near misses of the pinned id, the gateways' spellings of it, and
        another vendor's model. Only the catalogue's exact string is sent.
        """
        assert await flags.jev_model(_model(json.dumps(model))) is None

    @pytest.mark.parametrize(
        "stored",
        ["1", "1.13", "true", "null", '["jev-1.13.0"]', '{"model": "jev-1.13.0"}'],
    )
    async def test_json_that_is_not_a_model_id_is_refused(self, stored: str) -> None:
        assert await flags.jev_model(_model(stored)) is None

    @pytest.mark.parametrize("stored", NOT_JSON.values(), ids=_ids(NOT_JSON))
    async def test_a_value_that_is_not_json_is_refused(self, stored: str) -> None:
        assert await flags.jev_model(_model(stored)) is None

    async def test_an_unquoted_model_id_is_not_json_and_is_refused(self) -> None:
        # The likeliest hand-written mistake: the id without its JSON quotes.
        assert await flags.jev_model(_model("jev-1.13.0")) is None

    async def test_a_missing_row_is_refused_rather_than_defaulted(self) -> None:
        """
        Not the catalogue's default. A request made under a model nobody chose
        would be recorded as though somebody had.
        """
        assert await flags.jev_model(_model(None)) is None

    async def test_acceptance_is_the_catalogue_s(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        A release is added to the catalogue once it has been evaluated, and
        that alone must be enough: no second list here to forget.
        """
        monkeypatch.setattr(
            jev_catalogue, "KNOWN_MODELS", (*jev_catalogue.KNOWN_MODELS, "jev-1.14.0")
        )
        assert await flags.jev_model(_model('"jev-1.14.0"')) == "jev-1.14.0"

    async def test_refusal_is_the_catalogue_s(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """One rule, shared with the configuration form: whatever it refuses."""
        monkeypatch.setattr(
            jev_catalogue, "model_problem", lambda model: "withdrawn for this test"
        )
        with caplog.at_level(logging.ERROR, logger=flags.__name__):
            assert await flags.jev_model(_model('"jev-1.13.0"')) is None
        assert "withdrawn for this test" in caplog.text


# ---------------------------------------------------------------------------
# The counts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Count:
    label: str
    read: Callable[[_SystemFlags], Awaitable[int]]
    key: str
    seeded: int
    #: The catalogue constant that caps this setting.
    ceiling: str
    #: What the configuration form will be told about a value, beside the
    #: other two settings at their seeded values.
    form_problem: Callable[[object], str | None]


COUNTS = (
    Count(
        "daily request budget",
        flags.jev_daily_request_budget,
        flags.JEV_DAILY_REQUEST_BUDGET,
        500,
        "MAX_DAILY_REQUEST_BUDGET",
        lambda value: jev_catalogue.settings_problem(
            jev_catalogue.DEFAULT_MODEL, value, jev_catalogue.DEFAULT_MAX_STATE_TOKENS
        ),
    ),
    Count(
        "state limit",
        flags.jev_max_state_tokens,
        flags.JEV_MAX_STATE_TOKENS,
        8_000,
        "MAX_STATE_PLUS_LONGEST_QUESTION",
        lambda value: jev_catalogue.settings_problem(
            jev_catalogue.DEFAULT_MODEL,
            jev_catalogue.DEFAULT_DAILY_REQUEST_BUDGET,
            value,
        ),
    ),
)

#: Values a count row could hold: legal ones either side of each ceiling, and
#: every way to be something other than a whole number in range.
SWEEP: tuple[object, ...] = (
    0,
    1,
    499,
    500,
    8_000,
    9_999,
    10_000,
    10_001,
    27_999,
    28_000,
    28_001,
    10**30,
    -1,
    True,
    False,
    None,
    "500",
    500.0,
    2.5,
    [500],
    {"n": 500},
)


def _count(count: Count, stored: str | None) -> _SystemFlags:
    return _SystemFlags({} if stored is None else {count.key: stored})


def _whole(value: object, expected: int) -> bool:
    """``value`` is ``expected`` and an int, not a bool that compares equal."""
    return type(value) is int and value == expected


@pytest.mark.parametrize("count", COUNTS, ids=lambda c: c.label)
class TestTheCountsFailClosedToZero:
    async def test_the_seeded_value_reads_back(self, count: Count) -> None:
        value = await count.read(_count(count, json.dumps(count.seeded)))
        assert _whole(value, count.seeded)

    async def test_zero_is_a_setting_not_a_failure(self, count: Count) -> None:
        assert _whole(await count.read(_count(count, "0")), 0)

    async def test_the_ceiling_itself_is_allowed(self, count: Count) -> None:
        ceiling = getattr(jev_catalogue, count.ceiling)
        assert _whole(await count.read(_count(count, json.dumps(ceiling))), ceiling)

    async def test_above_the_ceiling_is_zero_not_the_ceiling(
        self, count: Count
    ) -> None:
        """
        Clamping would spend the most the catalogue allows on the strength of a
        value it refuses. Zero stops the calls, and the log says why.
        """
        ceiling = getattr(jev_catalogue, count.ceiling)
        assert _whole(await count.read(_count(count, json.dumps(ceiling + 1))), 0)
        assert _whole(await count.read(_count(count, json.dumps(10**30))), 0)

    async def test_a_negative_count_is_zero(self, count: Count) -> None:
        assert _whole(await count.read(_count(count, "-1")), 0)

    @pytest.mark.parametrize(
        "stored", ["true", "false", '"500"', "500.0", "1e3", "2.5", "null", "[500]"]
    )
    async def test_json_that_is_not_a_whole_number_is_zero(
        self, count: Count, stored: str
    ) -> None:
        """
        ``true`` is the case that matters: it is an int in Python, and a budget
        of one request a day because somebody stored a boolean is exactly the
        quiet wrongness ``max_auto_stage`` refuses.
        """
        assert _whole(await count.read(_count(count, stored)), 0)

    async def test_a_missing_row_is_zero(self, count: Count) -> None:
        assert _whole(await count.read(_count(count, None)), 0)

    @pytest.mark.parametrize("stored", NOT_JSON.values(), ids=_ids(NOT_JSON))
    async def test_a_value_that_is_not_json_is_zero(
        self, count: Count, stored: str
    ) -> None:
        assert _whole(await count.read(_count(count, stored)), 0)

    @pytest.mark.parametrize("value", SWEEP, ids=repr)
    async def test_the_runner_and_the_form_apply_one_rule(
        self, count: Count, value: object
    ) -> None:
        """
        Whatever the form refuses, the runner reads as zero; whatever it
        accepts, the runner reads as itself. A row can be written by something
        other than the form, so the form refusing a value is not enough.
        """
        read = await count.read(_count(count, json.dumps(value)))
        expected = value if count.form_problem(value) is None else 0
        assert _whole(read, expected)  # type: ignore[arg-type]

    async def test_the_refusal_is_logged_with_the_catalogue_s_reason(
        self, count: Count, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The sentence the form would show, so the log and the page agree."""
        with caplog.at_level(logging.ERROR, logger=flags.__name__):
            await count.read(_count(count, "-1"))
        reason = count.form_problem(-1)
        assert reason is not None
        assert count.key in caplog.text and reason in caplog.text

    async def test_the_catalogue_decides_refusal(
        self, count: Count, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            jev_catalogue, "settings_problem", lambda *settings: "refused for a test"
        )
        assert _whole(await count.read(_count(count, json.dumps(count.seeded))), 0)

    async def test_the_catalogue_decides_acceptance(
        self, count: Count, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        No second copy of the rule here. Whatever the catalogue accepts, this
        reader returns, so the catalogue's own tests are what hold the rule and
        there is no copy here for them to disagree with.
        """
        monkeypatch.setattr(jev_catalogue, "settings_problem", lambda *settings: None)
        assert _whole(await count.read(_count(count, "12345")), 12345)


async def test_a_state_limit_nobody_can_read_admits_no_request() -> None:
    """
    What the zero is for: the lane hands it to the catalogue's size check,
    which then refuses even the smallest request there is.
    """
    conn = _SystemFlags(
        failing={flags.JEV_MAX_STATE_TOKENS: DATABASE_ERRORS["connection closed"]}
    )
    limit = await flags.jev_max_state_tokens(conn)
    assert jev_catalogue.request_size_problem("{}", {"q": "{}"}, limit) is not None


# ---------------------------------------------------------------------------
# The keys
# ---------------------------------------------------------------------------


def _seeded_jev_keys() -> set[str]:
    """The ``jev_`` keys migration 0012 inserts into ``system_flags``."""
    sql = re.sub(r"--[^\n]*", "", MIGRATION.read_text(encoding="utf-8"))
    keys: set[str] = set()
    for statement in re.findall(
        r"INSERT\s+INTO\s+system_flags\b(.*?);", sql, re.S | re.I
    ):
        keys.update(re.findall(r"\(\s*'(jev_[a-z0-9_]*)'\s*,", statement))
    return keys


class TestTheReadersReadTheSeededKeys:
    """
    A reader pointed at a key nobody seeded reads as off forever and says
    nothing, which for the boolean switches is indistinguishable from working:
    the seed is off too. So the keys are held to the migration by name.
    """

    def test_every_key_read_is_one_migration_0012_seeds(self) -> None:
        seeded = _seeded_jev_keys()
        assert flags.JEV_ENABLED in seeded, (
            f"found {sorted(seeded)} in {MIGRATION.name}; has the statement that "
            "seeds system_flags changed shape?"
        )
        assert set(flags.JEV_KEYS) == seeded

    def test_there_is_an_area_switch_for_every_area_and_no_other(self) -> None:
        areas = {
            key.removeprefix(flags.JEV_AREA_PREFIX)
            for key in flags.JEV_KEYS
            if key.startswith(flags.JEV_AREA_PREFIX)
        }
        assert areas == set(jev_catalogue.AREAS)

    async def test_the_readers_ask_for_those_keys_and_no_others(self) -> None:
        conn = _SystemFlags(_everything_on())
        await flags.jev_enabled(conn)
        for area in jev_catalogue.AREAS:
            await flags.jev_area_enabled(conn, area)
        await flags.jev_model(conn)
        await flags.jev_daily_request_budget(conn)
        await flags.jev_max_state_tokens(conn)
        await flags.jev_send_internal_detail(conn)
        assert set(conn.asked) == set(flags.JEV_KEYS)

    async def test_everything_on_reads_as_on(self) -> None:
        """The fixture every refusal above is paired with, read in full."""
        conn = _SystemFlags(_everything_on())
        assert await flags.jev_enabled(conn) is True
        for area in jev_catalogue.AREAS:
            assert await flags.jev_area_enabled(conn, area) is True, area
        assert await flags.jev_model(conn) == jev_catalogue.DEFAULT_MODEL
        assert await flags.jev_daily_request_budget(conn) == 500
        assert await flags.jev_max_state_tokens(conn) == 8_000
        assert await flags.jev_send_internal_detail(conn) is True

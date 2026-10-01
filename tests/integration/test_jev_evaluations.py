"""
test_jev_evaluations.py
-----------------------
Phase C9 on PostgreSQL: migration 0014, which says what an evaluation of Jev
measured and what no row of one may say.

Every rule in it is a CHECK, so none of it can be proved without the database
that enforces it. Each case starts from a row that passes every rule, breaks
one, and names the constraint that refuses it: PostgreSQL tests a table's
CHECK constraints in alphabetical order by name, so a case that broke two
would name the wrong one, and each case is written to break one alone. Then
the other side: what was not measured is NULL and stays NULL, a genuine zero
stays a zero, and a threshold forced onto an upper bound is refused whoever
writes it.

Rows are written with plain SQL rather than through ``jev_repo``, so what is
tested is the schema, which holds whatever writes to it.

Runs on databases of its own, derived from ``TEST_DATABASE_URL`` as
``test_jev_schema.py``'s are: the ledger refuses DELETE and TRUNCATE, so rows
written here could never be cleared from a shared database. Skipped unless
``TEST_DATABASE_URL`` is set.

    TEST_DATABASE_URL=postgresql://localhost/trader_test \\
        pytest tests/integration/test_jev_evaluations.py
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from typing import Any

import pytest

pytest.importorskip("asyncpg")

import asyncpg  # noqa: E402

from src.db import migrate as migrations  # noqa: E402
from tests.integration.test_jev_schema import (  # noqa: E402
    _fresh_database,
    _migrations_up_to,
)

TEST_DSN = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_DSN, reason="TEST_DATABASE_URL not set; skipping evaluation tests"
)

MODEL = "jev-1.13.0"

#: The columns sent as JSON text.
JSONB = frozenset({"n_per_class", "calibration_bins", "per_class"})

#: Every column 0014 adds, and what each holds on a row that measured nothing:
#: NULL, but for the split, whose default is the whole dataset.
ADDED: dict[str, Any] = {
    "split": "all",
    **dict.fromkeys(
        (
            "analysis_plan_hash",
            "keyword_baseline_ref",
            "answers_sha256",
            "ci_level",
            "n_valid",
            "n_escape",
            "n_invalid",
            "n_not_asked",
            "n_contested",
            "n_distinct_states",
            "n_other_plans",
            "n_plan_unknown",
            "accuracy_all_items",
            "accuracy_all_items_wilson_low",
            "accuracy_all_items_wilson_high",
            "per_class",
            "brier_reference",
            "threshold_outcome",
            "threshold_statistic",
            "threshold_target",
            "threshold_dataset_sha256",
            "n_at_threshold",
            "accuracy_at_threshold",
            "accuracy_at_threshold_wilson_low",
            "accuracy_at_threshold_wilson_high",
            "vs_majority_diff",
            "vs_majority_diff_low",
            "vs_majority_diff_high",
            "vs_keyword_diff",
            "vs_keyword_diff_low",
            "vs_keyword_diff_high",
            "flip_rate_n",
            "flip_rate_low_margin",
            "flip_rate_low_margin_n",
            "flip_rate_near_threshold",
            "flip_rate_near_threshold_n",
            "flip_median_lag_hours",
            "labeller_agreement",
            "labeller_kappa",
            "labeller_agreement_n",
        )
    ),
}


# ---------------------------------------------------------------------------
# Databases and rows
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def dsn() -> str:
    async def setup() -> str:
        fresh = await _fresh_database("jev_evaluations")
        await migrations.migrate(fresh)
        return fresh

    return asyncio.run(setup())


@pytest.fixture
async def conn(dsn: str) -> AsyncIterator[asyncpg.Connection]:
    connection = await asyncpg.connect(dsn)
    try:
        yield connection
    finally:
        await connection.close()


async def _insert(conn: asyncpg.Connection, row: dict[str, Any]) -> asyncpg.Record:
    columns = list(row)
    values = [
        json.dumps(row[c]) if c in JSONB and row[c] is not None else row[c]
        for c in columns
    ]
    placeholders = [
        f"${i}::jsonb" if c in JSONB else f"${i}" for i, c in enumerate(columns, 1)
    ]
    return await conn.fetchrow(
        f"INSERT INTO jev_evaluations ({', '.join(columns)}) "
        f"VALUES ({', '.join(placeholders)}) RETURNING *",
        *values,
    )


def _bare(**overrides: Any) -> dict[str, Any]:
    """0012's required columns and nothing measured: the least a row can be."""
    row: dict[str, Any] = {
        "question_set": "research.catalogue",
        "question_set_version": 1,
        "question_key": "asset_class",
        "model": MODEL,
        "dataset_ref": "operator:quentin",
        "dataset_sha256": "a" * 64,
        "possibly_in_training": True,
        "n": 61,
        "n_per_class": {"equities": 40, "bonds": 21},
        "code_commit": "f" * 40,
    }
    row.update(overrides)
    return row


def _measured(**overrides: Any) -> dict[str, Any]:
    """
    A row that measured everything, and passes every rule: 200 test items
    after the model was first observed, a threshold chosen, both baselines
    beaten, flips on enough pairs, a second labeller. Each case below breaks
    one thing about it.
    """
    row = _bare(
        possibly_in_training=False,
        n=200,
        n_per_class={"equities": 120, "bonds": 80},
        split="test",
        analysis_plan_hash="b" * 64,
        keyword_baseline_ref="jev_prereg.keyword_label keywords/v1, reading excerpt",
        answers_sha256="c" * 64,
        ci_level=0.95,
        n_valid=180,
        n_escape=10,
        n_invalid=15,
        n_not_asked=5,
        n_contested=0,
        n_distinct_states=195,
        n_other_plans=0,
        n_plan_unknown=0,
        accuracy=0.80,
        accuracy_wilson_low=0.73,
        accuracy_wilson_high=0.85,
        accuracy_all_items=0.72,
        accuracy_all_items_wilson_low=0.65,
        accuracy_all_items_wilson_high=0.78,
        balanced_accuracy=0.70,
        per_class={"equities": {"n": 120, "correct": 90}},
        brier=0.30,
        brier_ci_low=0.25,
        brier_ci_high=0.36,
        brier_reference=0.48,
        calibration_bins=[{"low": 0.9, "high": 1.0, "n": 12}],
        majority_baseline_accuracy=0.60,
        keyword_baseline_accuracy=0.50,
        vs_majority_diff=0.12,
        vs_majority_diff_low=0.02,
        vs_majority_diff_high=0.22,
        vs_keyword_diff=0.22,
        vs_keyword_diff_low=0.10,
        vs_keyword_diff_high=0.33,
        threshold_outcome="chosen",
        threshold_statistic="covered_accuracy",
        threshold_target=0.80,
        threshold_dataset_sha256="d" * 64,
        threshold=0.40,
        coverage_at_threshold=0.60,
        n_at_threshold=120,
        accuracy_at_threshold=0.90,
        accuracy_at_threshold_wilson_low=0.83,
        accuracy_at_threshold_wilson_high=0.94,
        flip_rate=0.03,
        flip_rate_n=40,
        flip_rate_low_margin=0.08,
        flip_rate_low_margin_n=50,
        flip_rate_near_threshold=0.07,
        flip_rate_near_threshold_n=35,
        flip_median_lag_hours=26.5,
        labeller_agreement=0.90,
        labeller_kappa=0.80,
        labeller_agreement_n=60,
    )
    row.update(overrides)
    return row


def _triple(name: str, low: float, value: float, high: float) -> dict[str, float]:
    """An estimate and its interval, all three, so one rule alone is broken."""
    bounds = {
        "accuracy": ("accuracy_wilson_low", "accuracy_wilson_high"),
        "accuracy_all_items": (
            "accuracy_all_items_wilson_low",
            "accuracy_all_items_wilson_high",
        ),
        "accuracy_at_threshold": (
            "accuracy_at_threshold_wilson_low",
            "accuracy_at_threshold_wilson_high",
        ),
        "brier": ("brier_ci_low", "brier_ci_high"),
        "vs_majority_diff": ("vs_majority_diff_low", "vs_majority_diff_high"),
        "vs_keyword_diff": ("vs_keyword_diff_low", "vs_keyword_diff_high"),
    }[name]
    return {bounds[0]: low, name: value, bounds[1]: high}


#: The six estimates that carry an interval.
TRIPLES = (
    "accuracy",
    "accuracy_all_items",
    "accuracy_at_threshold",
    "brier",
    "vs_majority_diff",
    "vs_keyword_diff",
)

#: The single proportions, each outside [0, 1] on either side.
SINGLE_PROPORTIONS = (
    "balanced_accuracy",
    "threshold",
    "coverage_at_threshold",
    "majority_baseline_accuracy",
    "keyword_baseline_accuracy",
    "flip_rate",
    "threshold_target",
    "flip_rate_low_margin",
    "flip_rate_near_threshold",
    "labeller_agreement",
)

#: Every way a row can break one rule, and the rule that refuses it.
BROKEN: list[tuple[str, dict[str, Any], str]] = [
    *[
        (f"{column} {value}", {column: value}, "jev_evaluations_proportions")
        for column in SINGLE_PROPORTIONS
        for value in (1.01, -0.01)
    ],
    *[
        (f"{name} above 1", _triple(name, 1.1, 1.2, 1.3), "jev_evaluations_proportions")
        for name in ("accuracy", "accuracy_all_items", "accuracy_at_threshold")
    ],
    *[
        (
            f"{name} below 0",
            _triple(name, -0.3, -0.2, -0.1),
            "jev_evaluations_proportions",
        )
        for name in ("accuracy", "accuracy_all_items", "accuracy_at_threshold")
    ],
    *[
        (f"ci_level {value}", {"ci_level": value}, "jev_evaluations_ci_level")
        for value in (0.0, 1.0, 1.5, -0.5)
    ],
    ("brier above 2", _triple("brier", 2.1, 2.2, 2.3), "jev_evaluations_brier_range"),
    (
        "brier below 0",
        _triple("brier", -0.3, -0.2, -0.1),
        "jev_evaluations_brier_range",
    ),
    ("climatology above 2", {"brier_reference": 2.5}, "jev_evaluations_brier_range"),
    ("climatology below 0", {"brier_reference": -0.1}, "jev_evaluations_brier_range"),
    ("kappa above 1", {"labeller_kappa": 1.5}, "jev_evaluations_kappa_range"),
    ("kappa below -1", {"labeller_kappa": -1.5}, "jev_evaluations_kappa_range"),
    *[
        (
            f"{name} {side}",
            _triple(name, *values),
            "jev_evaluations_differences_range",
        )
        for name in ("vs_majority_diff", "vs_keyword_diff")
        for side, values in (
            ("above 1", (1.1, 1.2, 1.3)),
            ("below -1", (-1.3, -1.2, -1.1)),
        )
    ],
    *[
        (
            f"{name} outside its interval",
            _triple(name, *values),
            "jev_evaluations_intervals_hold_their_estimates",
        )
        for name, values in (
            ("accuracy", (0.73, 0.90, 0.85)),
            ("accuracy_all_items", (0.65, 0.60, 0.78)),
            ("accuracy_at_threshold", (0.83, 0.95, 0.94)),
            ("brier", (0.25, 0.20, 0.36)),
            ("vs_majority_diff", (0.02, 0.30, 0.22)),
            ("vs_keyword_diff", (0.10, 0.05, 0.33)),
        )
    ],
    *[
        (
            f"{name} without its {side} bound",
            {column: None},
            "jev_evaluations_estimates_carry_their_intervals",
        )
        for name in TRIPLES
        for side, column in zip(
            ("lower", "upper"), list(_triple(name, 0, 0, 0))[::2], strict=True
        )
    ],
    *[
        (
            f"{name}'s interval without it",
            {name: None},
            "jev_evaluations_estimates_carry_their_intervals",
        )
        for name in TRIPLES
    ],
    # Counts inside n: the three that partition n are moved together, so they
    # still add up and only the bound is broken.
    (
        "a negative count of answers",
        {"n_valid": 190, "n_invalid": -5, "n_not_asked": 15},
        "jev_evaluations_counts_within_n",
    ),
    (
        "more valid answers than items",
        {"n_valid": 205, "n_invalid": 0, "n_not_asked": -5},
        "jev_evaluations_counts_within_n",
    ),
    (
        "a negative count of escapes",
        {"n_escape": -1},
        "jev_evaluations_counts_within_n",
    ),
    *[
        (f"{column} above n", {column: 201}, "jev_evaluations_counts_within_n")
        for column in (
            "n_distinct_states",
            "n_at_threshold",
            "flip_rate_n",
            "flip_rate_low_margin_n",
            "flip_rate_near_threshold_n",
            "labeller_agreement_n",
        )
    ],
    *[
        (f"{column} negative", {column: -1}, "jev_evaluations_counts_within_n")
        for column in ("n_distinct_states", "n_at_threshold", "labeller_agreement_n")
    ],
    *[
        (f"{column} negative", {column: -1}, "jev_evaluations_counts_outside_n")
        for column in ("n_contested", "n_other_plans", "n_plan_unknown")
    ],
    (
        "answers that do not add up to n",
        {"n_valid": 170},
        "jev_evaluations_answers_add_up",
    ),
    (
        "more escapes than valid answers",
        {"n_escape": 181},
        "jev_evaluations_answers_add_up",
    ),
    *[
        (f"{rate} with {n} pairs", {n: pairs}, "jev_evaluations_flip_rates_need_pairs")
        for rate, n in (
            ("flip_rate", "flip_rate_n"),
            ("flip_rate_low_margin", "flip_rate_low_margin_n"),
            ("flip_rate_near_threshold", "flip_rate_near_threshold_n"),
        )
        for pairs in (0, None)
    ],
    *[
        (
            f"{n} pairs and no {rate}",
            {rate: None},
            "jev_evaluations_flip_rates_need_pairs",
        )
        for rate, n in (
            ("flip_rate", "flip_rate_n"),
            ("flip_rate_low_margin", "flip_rate_low_margin_n"),
            ("flip_rate_near_threshold", "flip_rate_near_threshold_n"),
        )
    ],
    (
        "a lag with no uniform pairs",
        {"flip_rate": None, "flip_rate_n": 0},
        "jev_evaluations_flip_rates_need_pairs",
    ),
    (
        "a negative lag",
        {"flip_median_lag_hours": -1.0},
        "jev_evaluations_flip_rates_need_pairs",
    ),
    *[
        (
            f"a chosen threshold without its {column}",
            {column: None},
            "jev_evaluations_threshold_whole",
        )
        for column in (
            "threshold",
            "threshold_statistic",
            "threshold_target",
            "threshold_dataset_sha256",
            "n_at_threshold",
        )
    ],
    *[
        (
            f"a threshold's group under the outcome {outcome}",
            {
                "threshold_outcome": outcome,
                **_triple("accuracy_at_threshold", None, None, None),
                "coverage_at_threshold": None,
            },
            "jev_evaluations_threshold_whole",
        )
        for outcome in ("none_found", "not_attempted", None)
    ],
    *[
        (
            f"a measurement at no threshold, outcome {outcome}",
            {
                "threshold_outcome": outcome,
                "threshold": None,
                "threshold_statistic": None,
                "threshold_target": None,
                "threshold_dataset_sha256": None,
                "n_at_threshold": None,
                column: value,
            },
            "jev_evaluations_at_threshold_needs_one",
        )
        for outcome in ("none_found", "not_attempted", None)
        for column, value in (("coverage_at_threshold", 0.6),)
    ],
    (
        "a threshold on an upper bound",
        {"possibly_in_training": True},
        "jev_evaluations_no_threshold_on_an_upper_bound",
    ),
    *[
        (f"the model {model!r}", {"model": model}, "jev_evaluations_model_is_pinned")
        for model in (
            "jev-latest",
            "jev-preview",
            "jev",
            "jev-1.13",
            "JEV-1.13.0",
            " jev-1.13.0",
            "jev-1.13.0 ",
            "jev-1.13.0\n",
            "jev-١.13.0",
            "jev-1.13.0-rc1",
        )
    ],
    *[
        (f"the split {split!r}", {"split": split}, "jev_evaluations_split_check")
        for split in ("dev", "ALL", "Test", "")
    ],
    (
        "an outcome outside the vocabulary",
        {
            "threshold_outcome": "found",
            "threshold": None,
            "threshold_statistic": None,
            "threshold_target": None,
            "threshold_dataset_sha256": None,
            "n_at_threshold": None,
            "coverage_at_threshold": None,
            **_triple("accuracy_at_threshold", None, None, None),
        },
        "jev_evaluations_threshold_outcome_check",
    ),
]


# ---------------------------------------------------------------------------
# Migration 0014: every rule bites
# ---------------------------------------------------------------------------


class TestEveryRuleBites:
    async def test_the_measured_row_passes_every_rule(
        self, conn: asyncpg.Connection
    ) -> None:
        """The cases below each break one thing about a row that is lawful."""
        stored = await _insert(conn, _measured())
        assert stored["threshold"] == 0.40
        assert json.loads(stored["per_class"]) == {
            "equities": {"n": 120, "correct": 90}
        }

    @pytest.mark.parametrize(
        ("overrides", "constraint"),
        [pytest.param(o, c, id=name) for name, o, c in BROKEN],
    )
    async def test_a_row_that_breaks_a_rule_is_refused(
        self, conn: asyncpg.Connection, overrides: dict[str, Any], constraint: str
    ) -> None:
        before = await conn.fetchval("SELECT COUNT(*) FROM jev_evaluations")
        with pytest.raises(asyncpg.CheckViolationError) as refused:
            await _insert(conn, _measured(**overrides))
        assert refused.value.constraint_name == constraint
        assert await conn.fetchval("SELECT COUNT(*) FROM jev_evaluations") == before

    async def test_every_rule_0014_adds_has_a_case(
        self, conn: asyncpg.Connection
    ) -> None:
        """A CHECK added without a case here would be a rule nobody saw bite."""
        rows = await conn.fetch(
            "SELECT conname FROM pg_constraint "
            "WHERE conrelid = 'jev_evaluations'::regclass AND contype = 'c'"
        )
        checks = {row["conname"] for row in rows} - {"jev_evaluations_n_check"}
        assert checks == {constraint for _, _, constraint in BROKEN}


class TestNothingMeasuredIsNull:
    async def test_what_0014_adds_starts_as_not_measured(
        self, conn: asyncpg.Connection
    ) -> None:
        stored = await _insert(conn, _bare())
        assert {column: stored[column] for column in ADDED} == ADDED

    async def test_a_genuine_zero_is_kept_as_one(
        self, conn: asyncpg.Connection
    ) -> None:
        """
        0 of 40 pairs flipped is a measurement, and so is an accuracy of 0
        with its interval; a count of nothing contested is a count.
        """
        stored = await _insert(
            conn,
            _measured(
                flip_rate=0.0,
                flip_rate_low_margin=0.0,
                n_contested=0,
                n_escape=0,
                **_triple("accuracy", 0.0, 0.0, 0.02),
            ),
        )
        assert (stored["flip_rate"], stored["flip_rate_low_margin"]) == (0.0, 0.0)
        assert (stored["accuracy"], stored["n_contested"], stored["n_escape"]) == (
            0.0,
            0,
            0,
        )

    async def test_no_pairs_is_a_count_and_no_rate(
        self, conn: asyncpg.Connection
    ) -> None:
        stored = await _insert(
            conn,
            _measured(
                flip_rate=None,
                flip_rate_n=0,
                flip_median_lag_hours=None,
                flip_rate_near_threshold=None,
                flip_rate_near_threshold_n=0,
            ),
        )
        assert (stored["flip_rate"], stored["flip_rate_n"]) == (None, 0)

    @pytest.mark.parametrize("outcome", ["none_found", "not_attempted"])
    async def test_an_outcome_without_a_threshold_carries_none(
        self, conn: asyncpg.Connection, outcome: str
    ) -> None:
        stored = await _insert(
            conn,
            _measured(
                threshold_outcome=outcome,
                threshold=None,
                threshold_statistic=None,
                threshold_target=None,
                threshold_dataset_sha256=None,
                n_at_threshold=None,
                coverage_at_threshold=None,
                flip_rate_near_threshold=None,
                flip_rate_near_threshold_n=None,
                **_triple("accuracy_at_threshold", None, None, None),
            ),
        )
        assert stored["threshold_outcome"] == outcome
        assert stored["threshold"] is None

    async def test_a_threshold_measured_over_no_test_item_stays_null(
        self, conn: asyncpg.Connection
    ) -> None:
        """Chosen on the dev split, it may cover none of the test split."""
        stored = await _insert(
            conn,
            _measured(
                n_at_threshold=0,
                coverage_at_threshold=0.0,
                **_triple("accuracy_at_threshold", None, None, None),
            ),
        )
        assert (stored["n_at_threshold"], stored["accuracy_at_threshold"]) == (0, None)


class TestAThresholdNeverRestsOnAnUpperBound:
    async def test_a_forced_threshold_on_an_upper_bound_is_refused(
        self, conn: asyncpg.Connection
    ) -> None:
        """
        Whatever writes it — the harness never does — a row that may hold the
        model's training data carries no threshold, though every other part
        of the row is lawful.
        """
        with pytest.raises(asyncpg.CheckViolationError) as refused:
            await _insert(conn, _measured(possibly_in_training=True))
        assert refused.value.constraint_name == (
            "jev_evaluations_no_threshold_on_an_upper_bound"
        )

    async def test_an_upper_bound_with_no_threshold_is_recorded(
        self, conn: asyncpg.Connection
    ) -> None:
        stored = await _insert(
            conn,
            _measured(
                possibly_in_training=True,
                threshold_outcome="not_attempted",
                threshold=None,
                threshold_statistic=None,
                threshold_target=None,
                threshold_dataset_sha256=None,
                n_at_threshold=None,
                coverage_at_threshold=None,
                flip_rate_near_threshold=None,
                flip_rate_near_threshold_n=None,
                **_triple("accuracy_at_threshold", None, None, None),
            ),
        )
        assert stored["possibly_in_training"] is True

    async def test_the_rows_are_still_append_only(
        self, conn: asyncpg.Connection
    ) -> None:
        """0012's trigger refuses an edit of what 0014 added, as of the rest."""
        stored = await _insert(conn, _bare())
        with pytest.raises(asyncpg.RaiseError):
            await conn.execute(
                "UPDATE jev_evaluations SET split = 'test' WHERE id = $1",
                stored["id"],
            )
        assert (
            await conn.fetchval(
                "SELECT split FROM jev_evaluations WHERE id = $1", stored["id"]
            )
            == "all"
        )


# ---------------------------------------------------------------------------
# Migration 0014 over a database already at 0013
# ---------------------------------------------------------------------------


#: Two rows of 0012's shape that 0014's rules find lawful: one that measured
#: nothing, and one that measured accuracy, the Brier score and both
#: baselines, each figure with its interval.
LEGACY_ROWS = (
    _bare(),
    _bare(
        accuracy=0.7,
        accuracy_wilson_low=0.58,
        accuracy_wilson_high=0.80,
        balanced_accuracy=0.65,
        brier=0.4,
        brier_ci_low=0.33,
        brier_ci_high=0.47,
        majority_baseline_accuracy=0.66,
        keyword_baseline_accuracy=0.5,
        calibration_bins=[{"low": 0.9, "high": 1.0, "n": 12}],
    ),
)


class TestTheMigration:
    async def test_it_applies_on_top_of_a_database_already_at_0013(
        self, tmp_path: Any
    ) -> None:
        """
        0014 adds columns and CHECKs, and the CHECKs validate every row they
        find. Taken to 0013 first and given rows, the database goes to 0014
        through the shipped runner, every row as it was, what 0014 adds not
        measured.
        """
        directories = _migrations_up_to(tmp_path, 13, 14)
        dsn = await _fresh_database("jev_upgrade_0014")
        first = await migrations.migrate(dsn, directory=directories[13])
        assert [m.version for m in first] == list(range(1, 14))
        on_disk = {m.version: m for m in migrations.discover()}

        conn = await asyncpg.connect(dsn)
        try:
            before = [await _insert(conn, dict(row)) for row in LEGACY_ROWS]
            applied = await migrations.migrate(dsn, directory=directories[14])

            assert [str(m) for m in applied] == ["0014_jev_evaluations_measured"]
            assert (
                await conn.fetchval(
                    "SELECT checksum FROM schema_migrations WHERE version = 14"
                )
                == on_disk[14].checksum
            )
            assert await migrations.migrate(dsn, directory=directories[14]) == []
            for row in before:
                after = await conn.fetchrow(
                    "SELECT * FROM jev_evaluations WHERE id = $1", row["id"]
                )
                assert {key: after[key] for key in row.keys()} == dict(row)
                assert {column: after[column] for column in ADDED} == ADDED
            await _insert(conn, _measured())
        finally:
            await conn.close()

    @pytest.mark.parametrize(
        ("overrides", "constraint"),
        [
            pytest.param(
                {"flip_rate": 0.0},
                "jev_evaluations_flip_rates_need_pairs",
                id="a flip rate with no pairs counted",
            ),
            pytest.param(
                {"threshold": 0.4, "possibly_in_training": False},
                "jev_evaluations_threshold_whole",
                id="a threshold with no outcome",
            ),
            pytest.param(
                {"coverage_at_threshold": 0.5},
                "jev_evaluations_at_threshold_needs_one",
                id="a coverage at no threshold",
            ),
            pytest.param(
                {"model": "jev-latest"},
                "jev_evaluations_model_is_pinned",
                id="an alias",
            ),
            pytest.param(
                {"accuracy": 0.7},
                "jev_evaluations_estimates_carry_their_intervals",
                id="an accuracy with no interval",
            ),
        ],
    )
    async def test_it_refuses_a_row_its_rules_refuse(
        self, tmp_path: Any, overrides: dict[str, Any], constraint: str
    ) -> None:
        """
        No database holds an evaluation yet, so none holds one 0014 refuses;
        were one to, 0014 fails whole, in its transaction, and the database
        stays at 0013 for somebody to look at rather than keep a row its
        rules would never have admitted.
        """
        directories = _migrations_up_to(tmp_path, 13, 14)
        dsn = await _fresh_database("jev_upgrade_0014_refused")
        await migrations.migrate(dsn, directory=directories[13])
        conn = await asyncpg.connect(dsn)
        try:
            await _insert(conn, _bare(**overrides))
            with pytest.raises(asyncpg.CheckViolationError) as refused:
                await migrations.migrate(dsn, directory=directories[14])
            assert refused.value.constraint_name == constraint
            assert (
                await conn.fetchval("SELECT MAX(version) FROM schema_migrations") == 13
            )
            columns = await conn.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'jev_evaluations' AND column_name = 'split'"
            )
            assert columns == []
        finally:
            await conn.close()

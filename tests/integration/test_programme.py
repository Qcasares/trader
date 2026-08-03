"""
test_programme.py
-----------------
The AI programme's guarantees, against a real PostgreSQL database.

Skipped unless ``TEST_DATABASE_URL`` is set. These are the checks that cannot
be made in a unit test because the guarantee lives in the schema rather than in
Python:

* A DELETE on ``hypotheses`` leaves the row in place. "Never delete a failed
  hypothesis" is worth nothing as a policy and everything as a rule.
* ``experiments.preregistered_criteria`` cannot be updated after insert. An
  acceptance test that can be revised once the answer is known is not a
  preregistered one, and it is the control everything else rests on.
* The promote endpoint refuses a gate that has not passed. That is what makes a
  human approval a *confirmation of a pass* rather than an override of a
  failure, which is the whole of the decision-rights model in one refusal.

    createdb trader_test
    TEST_DATABASE_URL=postgresql://localhost/trader_test \
        pytest tests/integration/test_programme.py
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("asyncpg")

import asyncpg  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from src.api.security import hash_password  # noqa: E402

TEST_DSN = os.environ.get("TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not TEST_DSN,
    reason="TEST_DATABASE_URL not set; skipping programme integration tests",
)

PASSWORD = "test-password-123"

CARD = {
    "economic_mechanism": "slow institutional rebalancing",
    "why_it_persists": "mandated bands force the other side",
    "instruments": "asset-class ETFs",
    "trading_horizon": "monthly",
    "entry_exit_concept": "hold above the long average, cash below",
    "expected_return_source": "a premium for bearing rebalancing pressure",
    "expected_risks": "whipsaw in range-bound regimes",
    "expected_turnover": "roughly twelve rebalances a year",
    "expected_capacity": "constrained by ETF depth",
    "data_requirements": "daily adjusted closes",
    "alternative_explanations": "disguised equity beta",
    "simplest_baseline": "equal-weight buy and hold",
    "falsification_test": "permute the signal and the edge should vanish",
    "acceptance_criteria": "sharpe >= 0.3",
    "rejection_criteria": "sharpe < 0",
    "limitations": "universe listed from 2006",
}


@pytest.fixture(scope="module")
def client():
    from src.config import get_settings
    from src.db.migrate import migrate

    os.environ["DATABASE_URL"] = TEST_DSN
    os.environ["SESSION_SECRET"] = "a" * 48
    os.environ["ADMIN_PASSWORD_HASH"] = hash_password(PASSWORD)
    get_settings.cache_clear()

    asyncio.run(migrate(TEST_DSN))

    from src.api.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def authed(client):
    assert (
        client.post("/api/v1/auth/login", json={"password": PASSWORD}).status_code
        == 200
    )
    return client


def _run(coro):
    return asyncio.run(coro)


async def _with_conn(fn):
    conn = await asyncpg.connect(TEST_DSN)
    try:
        return await fn(conn)
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class TestConfiguration:
    def test_the_vocabulary_is_the_operating_prompt(self, authed) -> None:
        body = authed.get("/api/v1/programme/config").json()
        assert len(body["items"]) == 33
        keys = {item["key"] for item in body["items"]}
        assert {"base_currency", "maximum_drawdown", "approval_requirements"} <= keys

    def test_the_migration_never_invents_a_value(self, authed) -> None:
        """
        A value nobody supplied is TBD, not a plausible default.

        Asserted as "no row the migration wrote carries a value" rather than
        "every row is NULL", so it survives a database an operator has already
        configured — setting a value replaces `updated_by`. The version that
        checked for NULL everywhere passed on a fresh database and failed on a
        reused one, which is a test that describes the fixture rather than the
        property.
        """

        async def invented(conn):
            return await conn.fetchval(
                "SELECT COUNT(*) FROM programme_config "
                "WHERE updated_by = 'migration' AND value IS NOT NULL"
            )

        assert _run(_with_conn(invented)) == 0

    def test_a_critical_key_is_flagged_as_such(self, authed) -> None:
        body = authed.get("/api/v1/programme/config").json()
        drawdown = next(i for i in body["items"] if i["key"] == "maximum_drawdown")
        assert drawdown["is_critical"] is True

    def test_setting_a_value_clears_it_from_the_unknowns(self, authed) -> None:
        response = authed.post(
            "/api/v1/programme/config", json={"values": {"base_currency": "USD"}}
        )
        assert response.status_code == 200
        assert "base_currency" not in response.json()["critical_unknowns"]

    def test_an_unknown_key_is_refused(self, authed) -> None:
        response = authed.post(
            "/api/v1/programme/config", json={"values": {"lucky_number": "7"}}
        )
        assert response.status_code == 422
        assert "lucky_number" in response.json()["detail"]

    def test_clearing_a_value_returns_it_to_tbd(self, authed) -> None:
        authed.post(
            "/api/v1/programme/config", json={"values": {"timezone": "Europe/London"}}
        )
        body = authed.post(
            "/api/v1/programme/config", json={"values": {"timezone": ""}}
        ).json()
        item = next(i for i in body["items"] if i["key"] == "timezone")
        assert item["value"] is None


# ---------------------------------------------------------------------------
# The ledger is append-only
# ---------------------------------------------------------------------------


class TestTheLedgerCannotBeTidied:
    def test_a_delete_leaves_the_row_in_place(self, authed) -> None:
        """
        The rule turns DELETE into a no-op rather than an error.

        A raising trigger would be equally safe and less useful: the property
        wanted is "the row is still there afterwards", and a caller that tries
        is a bug to find here rather than an outage to cause in production.
        """
        created = authed.post(
            "/api/v1/programme/hypotheses",
            json={"title": "Deletable in theory", "owner": "test", "card": CARD},
        ).json()

        async def attempt(conn):
            await conn.execute("DELETE FROM hypotheses WHERE ref = $1", created["ref"])
            return await conn.fetchval(
                "SELECT COUNT(*) FROM hypotheses WHERE ref = $1", created["ref"]
            )

        assert _run(_with_conn(attempt)) == 1

    def test_a_blanket_delete_removes_nothing(self, authed) -> None:
        authed.post(
            "/api/v1/programme/hypotheses",
            json={"title": "Survives a truncating hand", "owner": "test", "card": CARD},
        )

        async def attempt(conn):
            before = await conn.fetchval("SELECT COUNT(*) FROM hypotheses")
            await conn.execute("DELETE FROM hypotheses")
            return before, await conn.fetchval("SELECT COUNT(*) FROM hypotheses")

        before, after = _run(_with_conn(attempt))
        assert before == after and before > 0

    def test_rejected_hypotheses_are_listed_by_default(self, authed) -> None:
        created = authed.post(
            "/api/v1/programme/hypotheses",
            json={
                "title": "A failed idea worth keeping",
                "owner": "test",
                "card": CARD,
            },
        ).json()

        async def reject(conn):
            await conn.execute(
                "UPDATE hypotheses SET status='rejected' WHERE ref=$1", created["ref"]
            )

        _run(_with_conn(reject))
        refs = [h["ref"] for h in authed.get("/api/v1/programme/hypotheses").json()]
        assert created["ref"] in refs


# ---------------------------------------------------------------------------
# Preregistration is immutable
# ---------------------------------------------------------------------------


class TestPreregistrationIsImmutable:
    def _candidate(self, authed) -> tuple[str, str]:
        hypothesis = authed.post(
            "/api/v1/programme/hypotheses",
            json={"title": "Something to experiment on", "owner": "test", "card": CARD},
        ).json()
        candidate = authed.post(
            "/api/v1/programme/candidates",
            json={
                "hypothesis_ref": hypothesis["ref"],
                "strategy": "asset_class_trend_following",
                "params": {"sma_period": 210},
                "start_session": "2010-01-04",
                "end_session": "2020-12-31",
            },
        ).json()
        return hypothesis["id"], candidate["candidate_id"]

    def test_an_experiment_needs_criteria_to_exist(self, authed) -> None:
        from src.programme.repo import PreregistrationRequiredError, record_experiment

        hypothesis_id, candidate_id = self._candidate(authed)

        async def attempt(conn):
            with pytest.raises(PreregistrationRequiredError):
                await record_experiment(
                    conn,
                    candidate_id=candidate_id,
                    hypothesis_id=hypothesis_id,
                    kind="backtest",
                    preregistered_criteria=[],
                )

        _run(_with_conn(attempt))

    def test_the_criteria_cannot_be_edited_afterwards(self, authed) -> None:
        """
        The one control everything else rests on.

        A column that can be revised once the result is known does not prevent
        retrospective selection; it merely records it in a field nobody
        re-reads.
        """
        from src.programme.repo import record_experiment

        hypothesis_id, candidate_id = self._candidate(authed)

        async def attempt(conn):
            experiment = await record_experiment(
                conn,
                candidate_id=candidate_id,
                hypothesis_id=hypothesis_id,
                kind="backtest",
                preregistered_criteria=[
                    {"metric": "sharpe", "op": ">=", "value": 0.8}
                ],
            )
            with pytest.raises(asyncpg.PostgresError):
                await conn.execute(
                    "UPDATE experiments SET preregistered_criteria = $2::jsonb "
                    "WHERE ref = $1",
                    experiment["ref"],
                    json.dumps([{"metric": "sharpe", "op": ">=", "value": 0.1}]),
                )
            stored = await conn.fetchval(
                "SELECT preregistered_criteria FROM experiments WHERE ref = $1",
                experiment["ref"],
            )
            return json.loads(stored) if isinstance(stored, str) else stored

        criteria = _run(_with_conn(attempt))
        assert criteria[0]["value"] == 0.8

    def test_other_columns_still_update(self, authed) -> None:
        """The trigger must guard one column, not freeze the row."""
        from src.programme.repo import complete_experiment, record_experiment

        hypothesis_id, candidate_id = self._candidate(authed)

        async def attempt(conn):
            experiment = await record_experiment(
                conn,
                candidate_id=candidate_id,
                hypothesis_id=hypothesis_id,
                kind="backtest",
                preregistered_criteria=[
                    {"metric": "sharpe", "op": ">=", "value": 0.3}
                ],
            )
            return await complete_experiment(conn, experiment["ref"], {"sharpe": 0.6})

        assert _run(_with_conn(attempt)) == "pass"

    def test_the_conclusion_is_computed_not_asserted(self, authed) -> None:
        from src.programme.repo import complete_experiment, record_experiment

        hypothesis_id, candidate_id = self._candidate(authed)

        async def attempt(conn):
            experiment = await record_experiment(
                conn,
                candidate_id=candidate_id,
                hypothesis_id=hypothesis_id,
                kind="backtest",
                preregistered_criteria=[
                    {"metric": "sharpe", "op": ">=", "value": 0.9}
                ],
            )
            failed = await complete_experiment(
                conn, experiment["ref"], {"sharpe": 0.2}
            )
            second = await record_experiment(
                conn,
                candidate_id=candidate_id,
                hypothesis_id=hypothesis_id,
                kind="cost_stress",
                preregistered_criteria=[
                    {"metric": "deflated_sharpe", "op": ">=", "value": 0.3}
                ],
            )
            unanswerable = await complete_experiment(
                conn, second["ref"], {"sharpe": 5.0}
            )
            return failed, unanswerable

        failed, unanswerable = _run(_with_conn(attempt))
        assert failed == "fail"
        # A metric the outcome does not carry is not a passed test and is not a
        # failed one. Conflating them turns a missing measurement into a tick.
        assert unanswerable == "inconclusive"


# ---------------------------------------------------------------------------
# Promotion confirms; it cannot override
# ---------------------------------------------------------------------------


class TestPromotionCannotOverrideAGate:
    def _fresh_candidate(self, authed) -> str:
        hypothesis = authed.post(
            "/api/v1/programme/hypotheses",
            json={
                "title": "A candidate with no evidence",
                "owner": "test",
                "card": CARD,
            },
        ).json()
        return authed.post(
            "/api/v1/programme/candidates",
            json={
                "hypothesis_ref": hypothesis["ref"],
                "strategy": "asset_class_trend_following",
                "params": {"sma_period": 210},
                "start_session": "2010-01-04",
                "end_session": "2020-12-31",
            },
        ).json()["candidate_id"]

    def test_an_unpassed_gate_refuses_the_promotion(self, authed) -> None:
        candidate_id = self._fresh_candidate(authed)
        response = authed.post(
            f"/api/v1/programme/candidates/{candidate_id}/promote",
            json={"confirm": "PROMOTE", "rationale": "I would like it to advance"},
        )
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["unmet"], "the refusal must name what is missing"

    def test_the_candidate_does_not_move(self, authed) -> None:
        candidate_id = self._fresh_candidate(authed)
        authed.post(
            f"/api/v1/programme/candidates/{candidate_id}/promote",
            json={"confirm": "PROMOTE"},
        )
        stage = authed.get(f"/api/v1/programme/candidates/{candidate_id}").json()[
            "stage"
        ]
        assert stage == 0

    def test_the_confirmation_string_is_required(self, authed) -> None:
        candidate_id = self._fresh_candidate(authed)
        response = authed.post(
            f"/api/v1/programme/candidates/{candidate_id}/promote",
            json={"confirm": "yes"},
        )
        assert response.status_code == 422

    def test_the_gate_names_the_missing_evidence(self, authed) -> None:
        """
        A refusal that does not say what is missing teaches an operator only
        that they were told no.
        """
        candidate_id = self._fresh_candidate(authed)
        gate = authed.get(
            f"/api/v1/programme/candidates/{candidate_id}/gate"
        ).json()
        unmet = {c["id"] for c in gate["criteria"] if not c["met"]}
        # No bars have been ingested for this window in a fresh test database,
        # so the universe criterion is the one that should bite.
        assert "universe_available" in unmet
        assert gate["passed"] is False

    def test_rejecting_needs_no_gate(self, authed) -> None:
        """Stopping is frictionless; advancing is not. The same asymmetry as
        the kill switch, for the same reason."""
        candidate_id = self._fresh_candidate(authed)
        response = authed.post(
            f"/api/v1/programme/candidates/{candidate_id}/reject",
            json={"rationale": "the mechanism does not survive scrutiny"},
        )
        assert response.status_code == 200
        assert (
            authed.get(f"/api/v1/programme/candidates/{candidate_id}").json()["status"]
            == "rejected"
        )


# ---------------------------------------------------------------------------
# The switch and the runner
# ---------------------------------------------------------------------------


class TestTheProgrammeSwitch:
    def test_it_starts_disabled(self, authed) -> None:
        assert authed.get("/api/v1/programme/status").json()["enabled"] is False

    def test_enabling_needs_the_typed_confirmation(self, authed) -> None:
        response = authed.post(
            "/api/v1/programme/enabled", json={"enabled": True, "confirm": "yes"}
        )
        assert response.status_code == 422
        assert authed.get("/api/v1/programme/status").json()["enabled"] is False

    def test_it_can_be_enabled_and_disabled(self, authed) -> None:
        enabled = authed.post(
            "/api/v1/programme/enabled",
            json={"enabled": True, "confirm": "ENABLE PROGRAMME", "reason": "test"},
        ).json()
        assert enabled["enabled"] is True
        # Disabling needs no confirmation at all.
        disabled = authed.post(
            "/api/v1/programme/enabled", json={"enabled": False, "reason": "test"}
        ).json()
        assert disabled["enabled"] is False

    def test_an_unreadable_switch_reads_as_disabled(self, authed) -> None:
        """
        Fail closed. A value that is not exactly ``true`` is not permission.
        """
        from src.programme.flags import PROGRAMME_ENABLED

        async def corrupt(conn):
            await conn.execute(
                "UPDATE system_flags SET value = '\"maybe\"'::jsonb WHERE key = $1",
                PROGRAMME_ENABLED,
            )

        _run(_with_conn(corrupt))
        assert authed.get("/api/v1/programme/status").json()["enabled"] is False

    def test_a_tick_is_requested_never_run_inline(self, authed) -> None:
        """
        202 and a row. The API holds no model client and must not block a
        request handler on a model call, for the same reason it never runs a
        backtest inline.
        """
        response = authed.post("/api/v1/programme/tick")
        assert response.status_code == 202
        run_id = response.json()["run_id"]
        uuid.UUID(run_id)
        runs = authed.get("/api/v1/programme/runs").json()
        pending = next(r for r in runs if r["id"] == run_id)
        assert pending["status"] == "requested"
        assert pending["trigger"] == "manual"
        assert pending["finished_at"] is None


# ---------------------------------------------------------------------------
# The veto
# ---------------------------------------------------------------------------


class TestAModelCannotCloseItsOwnFinding:
    """
    The rule the findings table exists for.

    A role that can both raise and retract a blocking finding has not vetoed
    anything: the pass that raised it on Monday would be free to withdraw it on
    Tuesday when it got in the way. So closure is an operator act, enforced by
    a CHECK constraint rather than by the runner's good manners.
    """

    def _finding(self, authed, **overrides) -> dict:
        body = {
            "raised_by": "independent_risk",
            "severity": "critical",
            "title": "the universe excludes delisted instruments",
            "detail": "every symbol still trades, so this measures survivors",
            "remediation": "rebuild from point-in-time membership",
        }
        body.update(overrides)
        response = authed.post("/api/v1/programme/findings", json=body)
        assert response.status_code == 201, response.text
        return response.json()

    def test_the_database_refuses_a_close_by_anything_else(self, authed) -> None:
        created = self._finding(authed)

        async def attempt(conn):
            with pytest.raises(asyncpg.PostgresError):
                await conn.execute(
                    "UPDATE findings SET status='withdrawn', "
                    "closed_by='programme:independent_risk', closed_at=NOW() "
                    "WHERE ref = $1",
                    created["ref"],
                )
            return await conn.fetchval(
                "SELECT status FROM findings WHERE ref = $1", created["ref"]
            )

        assert _run(_with_conn(attempt)) == "open"

    def test_a_close_with_no_closer_at_all_is_refused(self, authed) -> None:
        created = self._finding(authed)

        async def attempt(conn):
            with pytest.raises(asyncpg.PostgresError):
                await conn.execute(
                    "UPDATE findings SET status='remediated' WHERE ref = $1",
                    created["ref"],
                )
            return await conn.fetchval(
                "SELECT status FROM findings WHERE ref = $1", created["ref"]
            )

        assert _run(_with_conn(attempt)) == "open"

    def test_the_repository_refuses_a_non_operator(self, authed) -> None:
        from src.programme.repo import FindingClosureError, close_finding

        created = self._finding(authed)

        async def attempt(conn):
            with pytest.raises(FindingClosureError):
                await close_finding(
                    conn, created["ref"], "withdrawn", "programme:independent_risk"
                )

        _run(_with_conn(attempt))

    def test_an_operator_can_close_it(self, authed) -> None:
        created = self._finding(authed)
        response = authed.post(
            f"/api/v1/programme/findings/{created['ref']}/close",
            json={"status": "remediated", "note": "universe rebuilt"},
        )
        assert response.status_code == 200
        assert response.json()["closed_by"].startswith("operator:")

    def test_accepted_is_not_the_same_as_fixed(self, authed) -> None:
        """
        A register that cannot distinguish "we fixed it" from "we decided to
        live with it" describes a programme with no outstanding problems.
        """
        created = self._finding(authed)
        authed.post(
            f"/api/v1/programme/findings/{created['ref']}/close",
            json={"status": "accepted", "note": "known, and within appetite"},
        )
        findings = authed.get("/api/v1/programme/findings").json()["findings"]
        stored = next(f for f in findings if f["ref"] == created["ref"])
        assert stored["status"] == "accepted"

    def test_a_finding_cannot_be_reopened_through_the_api(self, authed) -> None:
        created = self._finding(authed)
        response = authed.post(
            f"/api/v1/programme/findings/{created['ref']}/close",
            json={"status": "open", "note": "actually still a problem"},
        )
        assert response.status_code == 422


class TestABlockingFindingStopsAPromotion:
    def _candidate(self, authed) -> str:
        hypothesis = authed.post(
            "/api/v1/programme/hypotheses",
            json={
                "title": "Blocked by a finding",
                "owner": "test",
                "card": CARD,
            },
        ).json()
        return authed.post(
            "/api/v1/programme/candidates",
            json={
                "hypothesis_ref": hypothesis["ref"],
                "strategy": "asset_class_trend_following",
                "start_session": "2010-01-04",
                "end_session": "2020-12-31",
            },
        ).json()["candidate_id"]

    def test_the_gate_names_it(self, authed) -> None:
        candidate_id = self._candidate(authed)
        authed.post(
            "/api/v1/programme/findings",
            json={
                "candidate_id": candidate_id,
                "raised_by": "independent_risk",
                "severity": "critical",
                "title": "the drawdown limit would not have caught this",
                "detail": "the worst month exceeds the configured limit",
                "remediation": "lower max_drawdown_pct or reject",
            },
        )
        gate = authed.get(
            f"/api/v1/programme/candidates/{candidate_id}/gate"
        ).json()
        criterion = next(
            c for c in gate["criteria"] if c["id"] == "no_blocking_findings"
        )
        assert criterion["met"] is False
        assert "independent_risk" in criterion["detail"]

    def test_a_role_without_a_veto_does_not_block(self, authed) -> None:
        candidate_id = self._candidate(authed)
        authed.post(
            "/api/v1/programme/findings",
            json={
                "candidate_id": candidate_id,
                "raised_by": "quant_research",
                "severity": "critical",
                "title": "the mechanism is weaker than it first appeared",
                "detail": "the stated participants would not persist",
                "remediation": "revise the card",
            },
        )
        gate = authed.get(
            f"/api/v1/programme/candidates/{candidate_id}/gate"
        ).json()
        criterion = next(
            c for c in gate["criteria"] if c["id"] == "no_blocking_findings"
        )
        assert criterion["met"] is True

    def test_closing_it_unblocks_the_criterion(self, authed) -> None:
        candidate_id = self._candidate(authed)
        created = authed.post(
            "/api/v1/programme/findings",
            json={
                "candidate_id": candidate_id,
                "raised_by": "compliance",
                "severity": "high",
                "title": "the data licence does not permit this use",
                "detail": "redistribution is prohibited by the vendor terms",
                "remediation": "obtain a licence or change source",
            },
        ).json()
        authed.post(
            f"/api/v1/programme/findings/{created['ref']}/close",
            json={"status": "remediated", "note": "licence obtained"},
        )
        gate = authed.get(
            f"/api/v1/programme/candidates/{candidate_id}/gate"
        ).json()
        criterion = next(
            c for c in gate["criteria"] if c["id"] == "no_blocking_findings"
        )
        assert criterion["met"] is True

    def test_an_unknown_role_cannot_raise_one(self, authed) -> None:
        """A finding from a role that does not exist could never be actioned."""
        response = authed.post(
            "/api/v1/programme/findings",
            json={
                "raised_by": "chief_vibes_officer",
                "severity": "critical",
                "title": "something feels wrong about this candidate",
            },
        )
        assert response.status_code == 422

    def test_an_unknown_severity_cannot_be_raised(self, authed) -> None:
        response = authed.post(
            "/api/v1/programme/findings",
            json={
                "raised_by": "independent_risk",
                "severity": "medium-high",
                "title": "a severity the gate cannot compare",
            },
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# The autonomy ceiling
# ---------------------------------------------------------------------------


class TestTheAutonomyCeiling:
    def test_it_starts_at_zero(self, authed) -> None:
        """Promote nothing, until an operator says otherwise."""
        assert authed.get("/api/v1/programme/status").json()["max_auto_stage"] == 0

    def test_raising_it_needs_the_typed_confirmation(self, authed) -> None:
        response = authed.post(
            "/api/v1/programme/autonomy", json={"max_auto_stage": 3}
        )
        assert response.status_code == 422
        assert authed.get("/api/v1/programme/status").json()["max_auto_stage"] == 0

    def test_it_can_be_raised_and_lowered(self, authed) -> None:
        raised = authed.post(
            "/api/v1/programme/autonomy",
            json={
                "max_auto_stage": 2,
                "confirm": "RAISE AUTONOMY",
                "reason": "test",
            },
        ).json()
        assert raised["effective"] == 2
        # Lowering needs nothing at all.
        lowered = authed.post(
            "/api/v1/programme/autonomy", json={"max_auto_stage": 0}
        ).json()
        assert lowered["effective"] == 0

    def test_it_cannot_be_raised_into_the_human_gated_stages(self, authed) -> None:
        """
        The stored value is honoured as asked; the clamp is applied on the way
        out. Setting it to 8 does not let a model promote into production.
        """
        from src.programme.gates import FIRST_HUMAN_GATED_STAGE

        response = authed.post(
            "/api/v1/programme/autonomy",
            json={
                "max_auto_stage": 8,
                "confirm": "RAISE AUTONOMY",
                "reason": "trying it on",
            },
        ).json()
        assert response["requested"] == 8
        assert response["effective"] == FIRST_HUMAN_GATED_STAGE - 1
        assert (
            authed.get("/api/v1/programme/status").json()["max_auto_stage"]
            == FIRST_HUMAN_GATED_STAGE - 1
        )
        authed.post("/api/v1/programme/autonomy", json={"max_auto_stage": 0})

    def test_a_corrupt_ceiling_reads_as_zero(self, authed) -> None:
        """Fail closed, in the direction of promoting nothing."""
        from src.programme.flags import PROGRAMME_MAX_AUTO_STAGE

        async def corrupt(conn):
            await conn.execute(
                "UPDATE system_flags SET value = '\"lots\"'::jsonb WHERE key = $1",
                PROGRAMME_MAX_AUTO_STAGE,
            )

        _run(_with_conn(corrupt))
        assert authed.get("/api/v1/programme/status").json()["max_auto_stage"] == 0

    def test_a_boolean_is_not_a_stage(self, authed) -> None:
        """`True` is an int in Python and would otherwise read as stage 1."""
        from src.programme.flags import PROGRAMME_MAX_AUTO_STAGE

        async def corrupt(conn):
            await conn.execute(
                "UPDATE system_flags SET value = 'true'::jsonb WHERE key = $1",
                PROGRAMME_MAX_AUTO_STAGE,
            )

        _run(_with_conn(corrupt))
        assert authed.get("/api/v1/programme/status").json()["max_auto_stage"] == 0


# ---------------------------------------------------------------------------
# Candidate validation
# ---------------------------------------------------------------------------


class TestCandidateValidation:
    def _hypothesis(self, authed) -> str:
        return authed.post(
            "/api/v1/programme/hypotheses",
            json={"title": "For validation checks", "owner": "test", "card": CARD},
        ).json()["ref"]

    def test_an_unregistered_strategy_is_refused(self, authed) -> None:
        response = authed.post(
            "/api/v1/programme/candidates",
            json={
                "hypothesis_ref": self._hypothesis(authed),
                "strategy": "alpha_machine",
                "start_session": "2010-01-04",
                "end_session": "2020-12-31",
            },
        )
        assert response.status_code == 404

    def test_an_out_of_schema_parameter_is_refused(self, authed) -> None:
        """
        The strategy's own model is the arbiter here, exactly as it is on the
        backtest endpoint and in the runner. One definition of valid.
        """
        response = authed.post(
            "/api/v1/programme/candidates",
            json={
                "hypothesis_ref": self._hypothesis(authed),
                "strategy": "asset_class_trend_following",
                "params": {"lookback_weeks": 40},
                "start_session": "2010-01-04",
                "end_session": "2020-12-31",
            },
        )
        assert response.status_code == 422

    def test_a_backwards_window_is_refused(self, authed) -> None:
        response = authed.post(
            "/api/v1/programme/candidates",
            json={
                "hypothesis_ref": self._hypothesis(authed),
                "strategy": "asset_class_trend_following",
                "start_session": "2020-12-31",
                "end_session": "2010-01-04",
            },
        )
        assert response.status_code == 422

    def test_a_synthetic_candidate_is_marked_on_creation(self, authed) -> None:
        """
        The mark is set at creation and never cleared, so a candidate cannot
        launder synthetic evidence by later running against a real source.
        """
        candidate_id = authed.post(
            "/api/v1/programme/candidates",
            json={
                "hypothesis_ref": self._hypothesis(authed),
                "strategy": "asset_class_trend_following",
                "start_session": "2010-01-04",
                "end_session": "2020-12-31",
                "data_source": "synthetic",
            },
        ).json()["candidate_id"]
        body = authed.get(f"/api/v1/programme/candidates/{candidate_id}").json()
        assert body["evidence_is_synthetic"] is True

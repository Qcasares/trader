"""
test_jev_hash.py
----------------
The hashes a Jev request, its questions and a text subject are known by.

The request hash moved from ``jev_lane`` to ``jev_hash`` in phase C, so the
evaluation harness and the API can compute it without the client that holds the
SDK. A move is exactly the edit that can change a formula without anybody
meaning to, and the ledger finds every answer already paid for by this hash: a
formula that drifted would find nothing and say nothing. So the values here
were computed by phase B's own code, before the move, and are pinned.

What else must hold:

* the lane still exports the same functions, so every existing import works;
* the questions hash is exactly the part of the request a set contributes, so
  equal questions hashes mean byte-identical questions in the request, which is
  what the registry's open item 15 rule refuses;
* a text subject is the sha256 of its UTF-8 text;
* importing the module loads nothing but the standard library.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.programme import jev_hash, jev_lane
from src.programme import jev_questions as jq

ROOT = Path(__file__).resolve().parents[2]
MODEL = "jev-1.13.0"

#: A regime state, as ``DECISION_REGIME.dump_state`` sends it.
REGIME_STATE = {
    "equities": {
        "trend": "above",
        "volatility_quintile": 2,
        "drawdown": "none",
        "momentum": "up",
    },
    "bonds": {
        "trend": "below",
        "volatility_quintile": 5,
        "drawdown": "severe",
        "momentum": "down",
    },
    "commodities": {
        "trend": "above",
        "volatility_quintile": 2,
        "drawdown": "none",
        "momentum": "up",
    },
}

#: Computed on 2026-09-27 by phase B's ``jev_lane.request_hash`` and
#: ``jev_lane.state_hash`` on main at 4346f4c, before either moved.
#: Never re-recorded: a failure here means the formula changed, and every
#: canonical answer already in a ledger would stop being found.
PHASE_B = {
    "regime_request": (
        "b934f18a4a83c8d5a22f1a55c320cbc4eb30ff884ba8f5b55cfa2601f0a8e774"
    ),
    "regime_state": "ed612d647addaace40262c804751dc7fc0621b059e149b099029a51c09208c2c",
    "probe_request": "157f6024427b4e3a3c6b1f9914f49fd9753fd15ce7aaa82b9dbc2be7f10dc49e",
    "probe_state": "9d87175a815eba4f770f5fd78dfd6fa01bac9e26c992d7268d4878d9fc88aae4",
    "text_request": "48813a91a88221e82c8abf5523f6dd68bdca4c6bbf87163450e9720aa802e510",
    "text_state": "79be059ef430984dd1f8c268f16d791d82a9b1f0066c707264894706046d57bc",
}

TEXT_STATE = {"excerpt": "Time-Series Momentum Effect \u2014 caf\u00e9"}
TEXT_QUESTIONS = {"q": {"type": "noul", "instructions": "Is it?"}}


class TestTheRequestHashIsPhaseBs:
    def test_the_request_hash_is_phase_bs(self) -> None:
        """The regime, the probe, and text beyond ASCII, as phase B hashed them."""
        regime = jq.DECISION_REGIME.as_request_questions()
        probe = jq.PROBE_CONNECTIVITY.as_request_questions()
        probe_state = {"text": jq.PROBE_TEXT}
        hashed = {
            "regime_request": jev_hash.request_hash(MODEL, REGIME_STATE, regime),
            "regime_state": jev_hash.state_hash(REGIME_STATE),
            "probe_request": jev_hash.request_hash(MODEL, probe_state, probe),
            "probe_state": jev_hash.state_hash(probe_state),
            "text_request": jev_hash.request_hash(MODEL, TEXT_STATE, TEXT_QUESTIONS),
            "text_state": jev_hash.state_hash(TEXT_STATE),
        }
        assert hashed == PHASE_B

    def test_the_regime_state_pinned_here_is_what_the_lane_sends(self) -> None:
        """The pinned value is only a pin if its state is the one really sent."""
        sleeve = jq.SleeveState(**REGIME_STATE["equities"])
        state = jq.RegimeState(
            equities=sleeve,
            bonds=jq.SleeveState(**REGIME_STATE["bonds"]),
            commodities=sleeve,
        )
        assert jq.DECISION_REGIME.dump_state(state) == REGIME_STATE

    def test_the_lane_re_exports_the_same_functions(self) -> None:
        assert jev_lane.request_hash is jev_hash.request_hash
        assert jev_lane.state_hash is jev_hash.state_hash
        assert {"request_hash", "state_hash"} <= set(jev_lane.__all__)


class TestTheQuestionsHash:
    def test_it_is_the_questions_as_the_request_serialises_them(self) -> None:
        """
        Recomputed from the written definition: compact JSON, ``ensure_ascii``
        off, the order kept. The request hash embeds exactly this text.
        """
        for question_set in jq.REGISTRY.values():
            questions = question_set.as_request_questions()
            text = json.dumps(questions, separators=(",", ":"), ensure_ascii=False)
            expected = hashlib.sha256(text.encode("utf-8")).hexdigest()
            assert jev_hash.questions_hash(questions) == expected
            assert question_set.questions_hash == expected

    def test_equal_questions_hashes_are_equal_request_hashes(self) -> None:
        """
        Why the registry compares questions hashes: two sets whose questions
        hash alike send the same request about the same state, whatever their
        names, versions, lanes or provenances.
        """
        regime = jq.DECISION_REGIME
        renamed = jq.QuestionSet(
            name="research.copy",
            version=7,
            lane="research",
            provenance="model",
            questions=regime.questions,
            state_model=regime.state_model,
            purpose="Another set asking the same words.",
        )
        assert renamed.pack_hash != regime.pack_hash
        assert renamed.questions_hash == regime.questions_hash
        assert jev_hash.request_hash(
            MODEL, REGIME_STATE, renamed.as_request_questions()
        ) == jev_hash.request_hash(MODEL, REGIME_STATE, regime.as_request_questions())

    def test_the_order_of_the_options_is_in_it(self) -> None:
        questions = jq.DECISION_REGIME.as_request_questions()
        criteria = questions["regime"]["criteria"]
        reordered = {
            "regime": {
                **questions["regime"],
                "criteria": dict(reversed(list(criteria.items()))),
            }
        }
        assert reordered == questions, "dict equality ignores order"
        assert jev_hash.questions_hash(reordered) != jev_hash.questions_hash(questions)

    def test_a_number_json_cannot_spell_is_refused(self) -> None:
        with pytest.raises(ValueError):
            jev_hash.questions_hash({"q": {"type": "noul", "weight": float("nan")}})


class TestATextSubjectIsItsContent:
    @pytest.mark.parametrize(
        "text", ["", "Momentum", "caf\u00e9 \u2713", "\U0001f600", " spaced "]
    )
    def test_it_is_the_sha256_of_the_utf_8(self, text: str) -> None:
        assert jev_hash.text_sha256(text) == (
            hashlib.sha256(text.encode("utf-8")).hexdigest()
        )

    def test_every_character_counts(self) -> None:
        """No normalising here: two spellings are two subjects, and the
        normaliser runs where the text is stored, once."""
        assert jev_hash.text_sha256("Momentum") != jev_hash.text_sha256("momentum")
        assert jev_hash.text_sha256("a b") != jev_hash.text_sha256("a  b")

    @pytest.mark.parametrize("value", [b"bytes", None, 3, ["a"]])
    def test_only_text_is_a_text_subject(self, value: object) -> None:
        with pytest.raises(TypeError):
            jev_hash.text_sha256(value)  # type: ignore[arg-type]


def test_jev_hash_loads_nothing() -> None:
    """
    Importing it, in a fresh interpreter, loads nothing from ``src`` but
    itself and nothing that can reach a network, a database or a model: it is
    what the harness and the API compute a hash with.
    """
    code = (
        "import sys\n"
        "before = set(sys.modules)\n"
        "import src.programme.jev_hash\n"
        "loaded = sorted(set(sys.modules) - before)\n"
        "print('\\n'.join(loaded))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    loaded = set(result.stdout.split())
    ours = {name for name in loaded if name == "src" or name.startswith("src.")}
    assert ours == {"src", "src.programme", "src.programme.jev_hash"}, ours
    forbidden = (
        "aiohttp",
        "anthropic",
        "asyncpg",
        "httpx",
        "httpx2",
        "pydantic",
        "requests",
        "typesafe_sdk",
        "urllib3",
    )
    reached = sorted(
        name
        for name in loaded
        if any(name == f or name.startswith(f + ".") for f in forbidden)
    )
    assert reached == [], reached

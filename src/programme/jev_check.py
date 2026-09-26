"""
jev_check.py
------------
Whether a TypeSafe key works, asked of TypeSafe's own API, on demand.

    TYPESAFE_API_KEY=... python -m src.programme.jev_check

``.github/workflows/jev-check.yml`` runs this, by dispatch only, with the
repository secret. It is the Jev counterpart of ``tests/e2e/broker_check.py``:
the one place the key and the vendor meet on purpose, before anything the
programme does depends on either. Three steps, and the first that fails ends the
check:

1. **Which models may this key use?** A listing, which spends no tokens. It
   settles that TypeSafe's own host (``jev_catalogue.JEV_BASE_URL``) accepts
   the key — a key sold by one of the lookalike resellers is refused there —
   and that the pinned model is one it may use. A pin the account is not
   offered would make every question fail.
2. **One question, through the shipped client.** The connectivity probe, asked
   exactly as the ``jev_probe`` job asks it: the pinned host, the pinned model,
   the frozen question, the capped retry.
3. **The answer, judged as the lane judges it.** ``jev_validate`` reads the raw
   body, and the validated answer is compared with the one the probe knows.

It records nothing. A check that wrote the ledger would need the database
credential beside the model key, and the job that runs this holds the key and
nothing else — which is also why it is safe to run at any time, and why
``jev_enabled`` has no say over it: the switches govern what the programme
does, and this is an operator asking a question by hand.

It never prints the key, the state or a response body: statuses, the vendor's
request ids, the model names and the validated answer are what an operator
needs, and none of them is a secret.
"""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass, field
from typing import Any

from src.programme import jev_catalogue, jev_client, jev_questions, jev_validate
from src.programme.jev_lane import PROBE_EXPECTED

#: Where the key is read from. The same variable the programme reads as its
#: fallback, and the repository secret's name — never the variable name a
#: lookalike reseller uses, which is a key for someone else's service.
KEY_VARIABLE = "TYPESAFE_API_KEY"

#: Exit codes, so a workflow's failure says which of the three it was.
OK = 0
FAILED = 1
NO_KEY = 2


@dataclass
class CheckReport:
    """What the check found, line by line, and whether it passed."""

    passed: bool = False
    lines: list[str] = field(default_factory=list)

    def say(self, line: str) -> None:
        self.lines.append(line)


async def check(api_key: str, *, transport: Any = None) -> CheckReport:
    """
    Run the three steps with ``api_key``. ``transport`` is a test seam only.
    """
    report = CheckReport()
    pin = jev_catalogue.DEFAULT_MODEL

    listing = await jev_client.list_models(api_key=api_key, transport=transport)
    report.say(f"models: HTTP {listing.http_status}, request id {listing.request_id}")
    if listing.names is None:
        report.say(
            f"the key was not accepted by {jev_catalogue.JEV_BASE_URL}: "
            f"{listing.error_kind} ({listing.error_class}). A key from anywhere "
            "but console.typesafe.ai is refused here."
        )
        return report
    report.say(f"models offered to this key: {', '.join(listing.names) or 'none'}")
    if pin not in listing.names:
        report.say(
            f"the pinned model {pin} is not offered to this key, so every question "
            "the programme asks would fail. Nothing was asked."
        )
        return report

    question_set = jev_questions.PROBE_CONNECTIVITY
    questions = question_set.as_request_questions()
    call = await jev_client.ask(
        api_key=api_key,
        model=pin,
        state=question_set.dump_state(question_set.state_model()),
        questions=questions,
        transport=transport,
    )
    report.say(
        f"probe: HTTP {call.http_status}, request id {call.request_id}, "
        f"{call.latency_ms} ms, tokens in {call.input_tokens} out {call.output_tokens}"
    )
    if call.error_kind is not None:
        report.say(f"the probe failed: {call.error_kind} ({call.error_class})")
        return report

    validation = jev_validate.validate_body(call.raw_body, questions, pin)
    report.say(
        f"validation: {validation.status}, model answered {validation.model_answered}"
        + (f", {validation.problem}" if validation.problem else "")
    )
    expected = PROBE_EXPECTED.get((question_set.name, question_set.version), {})
    agreed = validation.status == "ok"
    for answer in validation.answers:
        if answer.valid:
            want = expected.get(answer.question_key)
            verdict = (
                ""
                if want is None
                else (" as expected" if answer.argmax == want else f", expected {want}")
            )
            report.say(
                f"answer {answer.question_key}: {answer.argmax} "
                f"(p={answer.noul}, margin {answer.margin}){verdict}"
            )
            agreed = agreed and (want is None or answer.argmax == want)
        else:
            report.say(
                f"answer {answer.question_key}: not measured ({answer.invalid_reason})"
            )
            agreed = False
    report.passed = agreed
    report.say("PASS" if agreed else "FAIL")
    return report


def main() -> int:
    api_key = os.environ.get(KEY_VARIABLE, "").strip()
    if not api_key:
        print(
            f"{KEY_VARIABLE} is not set, so there is nothing to check. Set it as the "
            "repository secret of that name, or in this process's environment."
        )
        return NO_KEY
    report = asyncio.run(check(api_key))
    for line in report.lines:
        print(line)
    return OK if report.passed else FAILED


if __name__ == "__main__":
    sys.exit(main())

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

1. **Does TypeSafe's host take the key?** A listing, which spends no tokens. It
   settles that TypeSafe's own host (``jev_catalogue.JEV_BASE_URL``) accepts
   the key — a key sold by one of the lookalike resellers is refused there. It
   does not settle the pin, and the check does not ask it to: the listing names
   the moving aliases only, and a versioned id such as the pin is accepted
   whether or not it is listed (docs/08, "Models and versions").
2. **One question, through the shipped client.** The connectivity probe, asked
   exactly as the ``jev_probe`` job asks it: the pinned host, the pinned model,
   the frozen question, the capped retry. This is where the pin is proven: the
   validator refuses an answer that names any other model.
3. **The answer, judged as the lane judges it.** Any 2xx with a body goes to
   ``jev_validate``, whatever the SDK made of it, exactly as ``jev_lane``
   records it; the SDK's objection, if it had one, is printed beside the
   verdict. The validated answer is compared with the one the probe knows.

Three verdicts, each its own exit code, because they send an operator in three
directions: the key works; the key, the account or the answer is wrong; or the
check never reached TypeSafe's judgement at all — a network failure, a timeout,
a rate limit or a vendor fault, which says nothing about the key and is worth
running again rather than acting on.

It records nothing. A check that wrote the ledger would need the database
credential beside the model key, and the job that runs this holds the key and
nothing else — which is also why it is safe to run at any time, and why
``jev_enabled`` has no say over it: the switches govern what the programme
does, and this is an operator asking a question by hand. It is the one road to
Jev besides ``jev_lane``, and ``tests/unit/test_jev_lane.py`` holds it to being
the only other one.

It never prints the key, the state or a response body: statuses, the vendor's
request ids, the model names and the validated answer are what an operator
needs, and none of them is a secret. The vendor chooses some of those strings,
so every line is also stripped of any run of the key's characters before it is
printed: a vendor that echoed the key into a field printed truncated would
otherwise print a prefix of it, which no log masks.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Literal

from src.programme import jev_catalogue, jev_client, jev_questions, jev_validate
from src.programme.jev_lane import PROBE_EXPECTED

#: Where the key is read from. The same variable the programme reads as its
#: fallback, and the repository secret's name — never the variable name a
#: lookalike reseller uses, which is a key for someone else's service.
KEY_VARIABLE = "TYPESAFE_API_KEY"

#: Exit codes, so a workflow's failure says which verdict it was.
OK = 0
FAILED = 1
NO_KEY = 2
NO_VERDICT = 3

#: The failures that say nothing about the key: no response, a rate limit, a
#: vendor fault, or a block that a listing, which carries no content, cannot
#: have earned. Anything else is TypeSafe's answer, and a refusal.
UNDECIDED_KINDS = frozenset(
    {"connection", "timeout", "rate_limited", "server", "content_block"}
)

#: The shortest run of the key's characters withheld wherever it appears.
MIN_WITHHELD = 12

#: What a model name looks like when it is printed. The vendor chooses the
#: names, so one that does not look like a model is counted, not shown.
_MODEL_NAME = re.compile(r"[a-z0-9][a-z0-9.\-]{0,39}", re.ASCII)

Verdict = Literal["pass", "fail", "no_verdict"]


@dataclass
class CheckReport:
    """What the check found, line by line, and the verdict it came to."""

    secret: str = field(default="", repr=False)
    verdict: Verdict = "fail"
    lines: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.verdict == "pass"

    @property
    def exit_code(self) -> int:
        return {"pass": OK, "fail": FAILED, "no_verdict": NO_VERDICT}[self.verdict]

    def say(self, line: str) -> None:
        self.lines.append(withheld(line, self.secret))

    def end(self, verdict: Verdict, line: str) -> CheckReport:
        self.verdict = verdict
        self.say(line)
        self.say({"pass": "PASS", "fail": "FAIL", "no_verdict": "NO VERDICT"}[verdict])
        return self


async def check(api_key: str) -> CheckReport:
    """
    Run the three steps with ``api_key``.

    No transport is accepted, even as a test seam: production code never hands
    the client one (``tests/unit/test_jev_lane.py::TestTheTransportIsATestSeam``),
    so the tests reach the fake vendor by patching the client instead.
    """
    report = CheckReport(secret=api_key)
    pin = jev_catalogue.DEFAULT_MODEL

    listing = await jev_client.list_models(api_key=api_key)
    report.say(f"models: HTTP {listing.http_status}, request id {listing.request_id}")
    if not _is_2xx(listing.http_status):
        return _listing_refused(report, listing)
    if listing.names is None:
        report.say(
            "the key was accepted, but the listing could not be read "
            f"({listing.error_kind}, {listing.error_class}); asking the probe anyway"
        )
    else:
        report.say(f"models listed for this key: {_names(listing.names)}")
        report.say(
            f"the pin {pin} is proven by the probe below, not by the listing, "
            "which names the moving aliases and need not name a versioned id"
        )

    question_set = jev_questions.PROBE_CONNECTIVITY
    questions = question_set.as_request_questions()
    call = await jev_client.ask(
        api_key=api_key,
        model=pin,
        state=question_set.dump_state(question_set.state_model()),
        questions=questions,
    )
    report.say(
        f"probe: HTTP {call.http_status}, request id {call.request_id}, "
        f"{call.latency_ms} ms, tokens in {call.input_tokens} out {call.output_tokens}"
    )
    # Judged exactly as the lane judges a call: a 2xx with a body is read by the
    # validator whatever the SDK raised over it, and anything else answered
    # nothing.
    if not (_is_2xx(call.http_status) and call.wire_body is not None):
        failed = f"the probe failed: {call.error_kind} ({call.error_class})"
        if call.error_kind in UNDECIDED_KINDS:
            return report.end(
                "no_verdict",
                f"{failed}, which says nothing about the key; run it again",
            )
        return report.end("fail", failed)
    if call.error_kind is not None:
        objection = f"{call.error_kind}, {call.error_class}"
        report.say(
            f"the SDK objected to the response ({objection}); the lane records "
            "the validator's verdict regardless, and so does this"
        )

    validation = jev_validate.validate_body(call.wire_body, questions, pin)
    answered = validation.model_answered
    if answered is not None and not _MODEL_NAME.fullmatch(answered):
        answered = "(not a model name)"
    report.say(
        f"validation: {validation.status}, model answered {answered}"
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
    if agreed:
        return report.end("pass", f"the key works with the pinned model {pin}")
    return report.end("fail", "TypeSafe answered, but not as the probe requires")


def withheld(line: str, secret: str) -> str:
    """``line`` with every run of at least :data:`MIN_WITHHELD` of ``secret``'s
    characters replaced, longest first."""
    if not secret:
        return line
    if len(secret) < MIN_WITHHELD:
        return line.replace(secret, "***")
    for length in range(len(secret), MIN_WITHHELD - 1, -1):
        for start in range(len(secret) - length + 1):
            piece = secret[start : start + length]
            if piece in line:
                line = line.replace(piece, "***")
    return line


def _listing_refused(report: CheckReport, listing: jev_client.JevModels) -> CheckReport:
    kind, error = listing.error_kind, listing.error_class
    if kind == "auth":
        return report.end(
            "fail",
            f"{jev_catalogue.JEV_BASE_URL} refused the key ({error}). A key from "
            "anywhere but console.typesafe.ai is refused here.",
        )
    if kind == "client" and listing.http_status is None:
        return report.end(
            "fail",
            f"the SDK refused the key before sending it ({error}); nothing was sent",
        )
    if kind in UNDECIDED_KINDS:
        return report.end(
            "no_verdict",
            f"the listing failed: {kind} ({error}), which says nothing about the key; "
            "run the check again",
        )
    return report.end("fail", f"the listing failed: {kind} ({error})")


def _names(names: tuple[str, ...]) -> str:
    shown = [name for name in names if _MODEL_NAME.fullmatch(name)]
    hidden = len(names) - len(shown)
    text = ", ".join(shown) or "none"
    return text + (
        f" (and {hidden} not shown, not being model names)" if hidden else ""
    )


def _is_2xx(status: int | None) -> bool:
    return (
        isinstance(status, int) and not isinstance(status, bool) and 200 <= status < 300
    )


def main() -> int:
    api_key = os.environ.get(KEY_VARIABLE, "").strip()
    if not api_key:
        print(
            f"{KEY_VARIABLE} is not set, so there is nothing to check. Set it as the "
            "repository secret of that name, or in this process's environment."
        )
        return NO_KEY
    try:
        report = asyncio.run(check(api_key))
    except Exception as error:  # noqa: BLE001 - the class is the evidence
        # By class alone: an exception's text is not evidence, and has carried
        # the key in SDK releases before 0.7.1.
        print(f"the check failed on this side: {type(error).__name__}")
        print("FAIL")
        return FAILED
    for line in report.lines:
        print(withheld(line, api_key))
    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())

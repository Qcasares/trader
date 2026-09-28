"""
web_ingest.py
-------------
The ``jev_web_ingest`` job: one allow-listed page fetched, the titles in it
read, screened and stored, and nothing asked. Runner-only (``RUNNER_ONLY`` in
``tests/unit/test_import_boundaries.py``), and the one module that imports the
web fetcher (``::test_only_the_ingest_job_imports_the_web_fetcher``).

It calls nothing
~~~~~~~~~~~~~~~~
No model is asked about anything here. The job makes no call to Jev and needs
no key: :func:`run_job` takes none, and ``main`` drops the key the loop
resolves for every Jev job before it hands this one on
(``test_job_ownership.py::TestTheProgrammeRunsWhatItClaims::test_the_ingest_job_is_handed_no_key``).
Its import closure reaches neither the lane nor either client, nor any module
that prompts a generative model, nor the vault
(``test_import_boundaries.py::test_the_ingest_job_reaches_no_model_and_no_key``),
and ``test_job_ownership.py::TestEveryJevHandlerMakesAtMostOneCall`` counts
its calls to the road at none. What it stores is what the injection screen
will be asked about first (phase C7), before any other set may ask.

What each attempt does
~~~~~~~~~~~~~~~~~~~~~~
In order; the first that applies decides.

==  =======================================================  =================
#   Condition                                                Outcome
==  =======================================================  =================
0   The payload is anything but ``{"source": <a name on the   fail, no retry
    allow-list>}``, or the entry is not as ``web_sources``
    wrote it
1   The programme, Jev or its research area is off           fail, no retry
2   The model setting is not a usable pin                    fail, no retry
3   The connection is inside a transaction                   fail, no retry
4   The fetch failed                                         fail, no retry:
                                                             its kind and
                                                             status
5   The source's parser refused the page                     fail, no retry:
                                                             the parser needs
                                                             review
6   Storing failed                                           fail, retried
7   Otherwise                                                complete, with
                                                             counts
==  =======================================================  =================

Steps 0 to 5 are not retried: each would come to the same thing again the same
day, and the planner queues the next day's job (``jev_plan``, once a UTC day
per source), which fetches the page again. Nothing is written before step 6,
and step 6 writes in one transaction, so a job that fails leaves the table as
it found it.

Step 1 reads the programme's switch and the research area, each through its
own fail-closed reader — the area's reads Jev's master switch as well — as the
road to Jev reads all three on every ask: the claim read the programme and Jev
a moment ago, and a switch turned off since is honoured before anything leaves
for the web. Step 2 reads the pin, fail-closed, and ``main``'s wrapper, before
the job runs at all, whether a key is set: the planner plans the ingest only
under both, since a page fetched for a lane that cannot ask about it is a
fetch for nothing (design R28), and a job it queued can be claimed after
either went (docs/08 open item 53)
(``tests/unit/test_web_ingest.py::TestThePin``,
``tests/integration/test_jev_dark.py::TestAJobQueuedBeforeTheKeyOrThePinWentFetchesNothing``).
Step 3 keeps the fetch, up to 20 seconds on the network, out of any
transaction, so no transaction is held open across it; the programme's loop
hands a handler a pooled connection with none open, and
``tests/integration/test_web_ingest.py::TestTheFetchIsOutsideAnyTransaction``
watches the database while the page is in flight.

What is stored
~~~~~~~~~~~~~~
Each row the parser kept is decided by ``web_sources.screen_cell``, and this
job stores what it decides: ``keep``, the excerpt, in use; ``quarantine``,
the excerpt, quarantined for ``web_sources.quarantine_reason(rule)``;
``drop``, nothing, counted under the rule, or under ``empty`` for a row
whose excerpt normalised to nothing. A document is ``web_documents`` as
migration 0012 made it, one per source and content: ``excerpt`` the text, and
the only column holding any; ``title`` and ``published_at`` NULL; ``url`` the
allow-listed URL as ``web_sources`` wrote it; ``fetched_at`` the database's
clock as the storing transaction begins, once the page has arrived; and
``content_sha256`` ``web_sources.content_sha256`` of the excerpt, which is
``jev_hash.text_sha256``, the address ``jev_lane.ask`` recomputes for a
``web_excerpt`` subject and the one its quarantine lookup reads. The same
excerpt twice in one snapshot, under two headings, is one document.

Quarantine is by content, one-way and across sources. An excerpt the screen
passes that a document of any source already holds quarantined is stored
quarantined too, for ``content quarantined earlier (document N)``, N the
earliest such document. A document already stored and not quarantined whose
content the screen now quarantines — a rule added since it was stored — or
that another document holds quarantined is quarantined now, through
``jev_repo.quarantine_content``, the one update the table allows. Nothing
releases one. The documents are written, and the quarantines made, in content
order rather than the page's, so two writers at once — two ingests, or an
ingest beside another writer's quarantine — never each hold what the other
waits for (``tests/integration/test_web_ingest.py::TestTwoWritersAtOnce``).

No web text leaves by any other road
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The result, every error and every log line carry counts, hashes, rule names,
failure kinds and the source's name — never a title, an excerpt or a line of
the page. A failure while storing is reported by its class, its SQLSTATE
and the constraint it names, and nothing else, since a driver's message can
quote the value it could not take.
``tests/integration/test_web_ingest.py::TestTheCanary`` runs a page carrying
a token through the programme's loop and finds it in ``web_documents.excerpt``
and in no other column of any table, no log line and no job's payload, result
or error; and, in a row the parser or the screen refuses, nowhere at all.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Mapping
from typing import Any

import asyncpg

from src.programme import flags, jev_repo, web_fetch, web_sources
from src.programme.job_errors import JobFailedError

logger = logging.getLogger(__name__)

#: The Jev area whose switch the job reads before it fetches.
AREA = "research"

#: What a dropped row with no rule — an excerpt that normalised to nothing — is
#: counted under.
EMPTY_EXCERPT = "empty"

#: The keys of what :func:`run_job` returns: counts, hashes and names, and
#: nothing else. ``tests/unit/test_web_ingest.py`` pins them.
RESULT_KEYS: tuple[str, ...] = (
    "source",
    "bytes",
    "sha256",
    "rows",
    "unparsed",
    "distinct",
    "new",
    "dropped",
    "quarantined_by_code",
    "quarantined_earlier",
    "quarantined_now",
)


def earlier_reason(document_id: int) -> str:
    """
    Why a document is quarantined because its content was quarantined before
    it, under any source: the earliest document holding it quarantined.
    """
    return f"content quarantined earlier (document {int(document_id)})"


async def run_job(conn: asyncpg.Connection, payload: dict[str, Any]) -> dict[str, Any]:
    """
    The ``jev_web_ingest`` job: fetch the source ``payload`` names, read it,
    screen it and store it, and ask nothing. See the module docstring for every
    outcome.

    ``payload`` is ``{"source": <a name on the allow-list>}`` and nothing else;
    the page fetched is the allow-list's, never a URL a payload could carry.
    No key: the job needs none. Returns :data:`RESULT_KEYS`:

    * ``source``, ``bytes``, ``sha256``: the source's name, and the size and
      sha256 of the body fetched;
    * ``rows``: rows the parser kept; ``unparsed``: rows of the table it could
      not read, and dropped;
    * ``distinct``: the distinct excerpts among the rows ``screen_cell`` did
      not drop; ``new``: documents this job stored;
    * ``dropped``: rows ``screen_cell`` dropped, by rule;
    * ``quarantined_by_code``: distinct excerpts the code screen quarantines;
      ``quarantined_earlier``: distinct excerpts it passes that were already
      quarantined, under any source; ``quarantined_now``: documents already
      stored that this job quarantined.
    """
    name = _source_name(payload)
    source = web_sources.ALLOWED_SOURCES[name]
    written = web_sources.as_written(source)
    if written is None:
        raise JobFailedError(
            f"the allow-list entry {name} is not as web_sources wrote it; "
            "nothing was fetched",
            retry=False,
        )
    if not await flags.programme_enabled(conn):
        raise JobFailedError(
            "the programme is switched off; nothing was fetched", retry=False
        )
    if not await flags.jev_area_enabled(conn, AREA):
        raise JobFailedError(
            f"Jev, or its {AREA} area, is off; nothing was fetched", retry=False
        )
    if await flags.jev_model(conn) is None:
        raise JobFailedError(
            "the model setting is not a usable pin, so nothing could be asked "
            "about the page; nothing was fetched",
            retry=False,
        )
    if conn.is_in_transaction():
        raise JobFailedError(
            "the job was handed a connection inside a transaction, and the page "
            "is fetched outside any, so that none is held open across the "
            "network; nothing was fetched",
            retry=False,
        )

    fetched = await web_fetch.fetch(source)
    if isinstance(fetched, web_fetch.FetchFailure):
        status = "" if fetched.http_status is None else f", HTTP {fetched.http_status}"
        raise JobFailedError(
            f"the fetch of {name} failed ({fetched.kind}{status}); nothing was "
            "stored, and the next day's job fetches it again",
            retry=False,
        )

    try:
        snapshot = web_sources.PARSERS[written.parser](fetched.text)
    except web_sources.SnapshotRefused as refused:
        raise JobFailedError(
            f"the parser needs review: {written.parser} refused the page from "
            f"{name} ({refused}); nothing was stored",
            retry=False,
        ) from None

    decided = [web_sources.screen_cell(entry.cell) for entry in snapshot.entries]
    dropped = Counter(
        screened.rule or EMPTY_EXCERPT
        for screened in decided
        if screened.fate == "drop"
    )
    kept: dict[str, web_sources.Screened] = {}
    for screened in decided:
        if screened.fate != "drop":
            kept.setdefault(web_sources.content_sha256(screened.excerpt), screened)
    flagged = {
        content: _rule(screened)
        for content, screened in kept.items()
        if screened.fate == "quarantine"
    }

    try:
        stored, earlier, quarantined_now = await _store(
            conn, name, written.url, kept, flagged
        )
    except Exception as error:  # noqa: BLE001 - reported by class, never by message
        raise JobFailedError(
            f"storing the snapshot of {name} failed ({_described(error)}); "
            "nothing from it was stored",
            retry=True,
        ) from None

    result: dict[str, Any] = {
        "source": name,
        "bytes": fetched.bytes,
        "sha256": fetched.sha256,
        "rows": snapshot.rows,
        "unparsed": snapshot.dropped,
        "distinct": len(kept),
        "new": sum(1 for _, _, inserted in stored if inserted),
        "dropped": dict(sorted(dropped.items())),
        "quarantined_by_code": len(flagged),
        "quarantined_earlier": len(earlier),
        "quarantined_now": quarantined_now,
    }
    logger.info(
        "web ingest of %s: %d rows, %d distinct, %d new, %d dropped, %d quarantined "
        "by the code screen, %d quarantined earlier, %d quarantined now",
        name,
        result["rows"],
        result["distinct"],
        result["new"],
        sum(dropped.values()),
        result["quarantined_by_code"],
        result["quarantined_earlier"],
        result["quarantined_now"],
    )
    return result


async def _store(
    conn: asyncpg.Connection,
    name: str,
    url: str,
    kept: Mapping[str, web_sources.Screened],
    flagged: Mapping[str, str],
) -> tuple[list[tuple[int, str, bool]], dict[str, int], int]:
    """
    Every write of one snapshot, in one transaction: the documents, then the
    quarantine of what was stored before and is quarantined now. Returns what
    ``insert_documents`` returned, the earlier quarantines found, and how many
    stored documents this quarantined.

    Each lock is taken in one order: ``insert_documents`` writes in its
    index's order, and the quarantines, the screen's and the earlier ones
    together, are made in one pass in content order, since a quarantine holds
    every row of its content until the transaction commits. Two writers at
    once — two ingests, or an ingest beside another writer's quarantine —
    then never each hold what the other waits for; in page order, or the
    screen's before the earlier ones, they did, and PostgreSQL ended one with
    a deadlock (``tests/integration/test_web_ingest.py::TestTwoWritersAtOnce``).
    """
    async with conn.transaction(isolation="read_committed"):
        earlier = await jev_repo.earliest_quarantined(
            conn, [content for content in kept if content not in flagged]
        )
        rows = [
            jev_repo.DocumentRow(
                source=name,
                url=url,
                excerpt=screened.excerpt,
                quarantine_reason=_reason(content, flagged, earlier),
            )
            for content, screened in kept.items()
        ]
        stored = await jev_repo.insert_documents(conn, rows)
        reasons = {
            content: web_sources.quarantine_reason(rule)
            for content, rule in flagged.items()
        }
        reasons.update(
            (content, earlier_reason(document_id))
            for content, document_id in earlier.items()
        )
        quarantined_now = 0
        for content in sorted(reasons):
            quarantined_now += await jev_repo.quarantine_content(
                conn, content, reasons[content]
            )
    return stored, earlier, quarantined_now


def _source_name(payload: object) -> str:
    """The allowed source ``payload`` names, and nothing else it could carry."""
    if not isinstance(payload, Mapping) or set(payload) != {"source"}:
        raise JobFailedError(
            'a web ingest job\'s payload is {"source": <a name on the allow-list>} '
            "and nothing else, and this one is not; nothing was fetched",
            retry=False,
        )
    name = payload["source"]
    if not isinstance(name, str) or name not in web_sources.ALLOWED_SOURCES:
        raise JobFailedError(
            "a web ingest job names a source on the allow-list ("
            + ", ".join(sorted(web_sources.ALLOWED_SOURCES))
            + "), and this one does not; nothing was fetched",
            retry=False,
        )
    return name


def _rule(screened: web_sources.Screened) -> str:
    """The rule a quarantine was decided by, which ``screen_cell`` always names."""
    if screened.rule is None:  # pragma: no cover - screen_cell names one
        raise ValueError("a quarantine decided by no rule")
    return screened.rule


def _reason(
    content: str, flagged: Mapping[str, str], earlier: Mapping[str, int]
) -> str | None:
    """Why a document is stored quarantined, or ``None`` for one in use."""
    if content in flagged:
        return web_sources.quarantine_reason(flagged[content])
    if content in earlier:
        return earlier_reason(earlier[content])
    return None


def _described(error: BaseException) -> str:
    """An error by its class, SQLSTATE and constraint: nothing it quoted."""
    parts = [type(error).__name__]
    sqlstate = getattr(error, "sqlstate", None)
    if isinstance(sqlstate, str) and sqlstate:
        parts.append(f"SQLSTATE {sqlstate}")
    constraint = getattr(error, "constraint_name", None)
    if isinstance(constraint, str) and constraint:
        parts.append(f"constraint {constraint}")
    return ", ".join(parts)


__all__ = [
    "AREA",
    "EMPTY_EXCERPT",
    "RESULT_KEYS",
    "earlier_reason",
    "run_job",
]

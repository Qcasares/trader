"""
web_sources.py
--------------
The web pages the programme may fetch, and how what it fetches becomes text a
question could be asked about. Pure: no network, no database, no clock. The
API may import it, to show which sources exist and what their rules are; the
fetcher that reaches the network is ``web_fetch``, which the API may not.

Phase C's research lane asks Jev about excerpts of public web pages, and an
excerpt is text an outsider wrote. Everything here exists so that the one road
from a page to a stored excerpt is narrow, written down and tested:

* **One allow-list, validated when the module loads.** :data:`ALLOWED_SOURCES`
  names each page by its full URL: ``https``, one exact host, no port, no
  query, no fragment. The fetcher fetches a member of it and nothing else, by
  identity and as this module wrote it (:func:`as_written`), with the values
  written rather than the live entry's, and no function anywhere takes a URL.
  No URL is ever built from fetched content: the per-entry links in the page
  are discarded by the parser, never fetched and never stored.
  ``tests/unit/test_web_sources.py::TestTheAllowList::test_the_allow_list_is_pinned``.
* **Titles only.** The one source today is the strategies table of the
  paperswithbacktest README, a repository that publishes no licence. The
  parser keeps each row's title and drops its link and its four figures —
  Sharpe, t-statistic, volatility, years — which are never stored and never
  quoted (docs/08, "What each number may be quoted as"). The headings are kept
  only as the README's own grouping, a label that is not ground truth.
* **A changed page is refused, not guessed at.** The table is read between its
  generator's markers; every line there must be blank, a heading the parser
  knows, a table row, or the generator's note before the first heading; and
  every row must match :data:`ROW_PATTERN` exactly. A snapshot with a line it
  cannot read, too few rows that match, or implausibly many raises
  :class:`SnapshotRefused`, whose message carries counts and line numbers and
  never the page's text.
* **One normal form.** :func:`normalise_excerpt` is idempotent, so the same
  words read twice, or from two sources, are one excerpt and one content
  address (:func:`content_sha256`, ``jev_hash.text_sha256``).
* **A code screen that runs before any model is asked.** :func:`code_screen`,
  version :data:`CODE_SCREEN_VERSION`, flags hidden characters, markup,
  instruction phrases, encoded payloads, mixed-script words and overlong text.
  Its rules and the readings they match are data (:data:`CODE_SCREEN_RULES`,
  :data:`SCREEN_READINGS`), hashed (:func:`code_screen_sha256`), and pinned
  beside the rules by :data:`GOLDEN_CODE_SCREEN_SHA256` and in the test by an
  append-only history of released versions
  (``test_web_sources.py::TestTheCodeScreen``), so "code-screen v1" names one
  rule set forever. It is a keyword baseline and not a defence on its own: an
  excerpt it passes is still screened by Jev's own injection screen before any
  other set may ask about it (C7).

What becomes of a row — kept, quarantined by the screen, or dropped — is
decided here, by :func:`screen_cell`, and nothing here stores anything: the
ingest job (design part C6) stores what it decides.
"""

from __future__ import annotations

import hashlib
import html
import ipaddress
import json
import re
import unicodedata
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, fields
from types import MappingProxyType
from typing import NamedTuple
from urllib.parse import urlsplit, urlunsplit

from src.programme import jev_hash
from src.programme.jev_questions import EXCERPT_MAX_CHARS

# ---------------------------------------------------------------------------
# The allow-list
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AllowedSource:
    """
    One page the fetcher may fetch, and the rules its response is held to.

    ``url`` is the whole address, fixed: nothing is ever appended to it, and no
    function in the programme takes a URL. ``host`` repeats the URL's host so
    the rule that they agree is checked where the list is written.
    ``content_types`` and ``charset`` are what the response must declare, and
    ``max_bytes`` caps the body both as it arrives and once decompressed.
    ``parser`` names the function in :data:`PARSERS` that reads the page.
    """

    name: str
    url: str
    host: str
    content_types: tuple[str, ...]
    charset: str
    max_bytes: int
    parser: str


#: The one parser today, and the name a snapshot records it was read by.
PWB_README_PARSER = "pwb_readme_strategies/v1"

#: Every page the programme may fetch. One today. A frozen mapping of frozen
#: values, validated when the module loads (:func:`allowed_source_problem`),
#: and the fetcher accepts a member by identity, so a source built anywhere
#: else — even one equal to an entry — is refused before a socket opens.
ALLOWED_SOURCES: Mapping[str, AllowedSource] = MappingProxyType(
    {
        "pwb-readme": AllowedSource(
            name="pwb-readme",
            url=(
                "https://raw.githubusercontent.com/paperswithbacktest/"
                "awesome-systematic-trading/main/README.md"
            ),
            host="raw.githubusercontent.com",
            content_types=("text/plain",),
            charset="utf-8",
            # The page was 90,734 bytes on 2026-09-27; this is room for it to
            # grow about fivefold, and no more.
            max_bytes=512 * 1024,
            parser=PWB_README_PARSER,
        ),
    }
)

#: The most any allowed source may declare as its cap. A source is small text;
#: anything larger is a page nobody meant to allow.
MAX_SOURCE_BYTES = 1024 * 1024

_SOURCE_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,62}", re.ASCII)
_HOST_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", re.ASCII)
_MEDIA_TYPE = re.compile(r"[a-z0-9][a-z0-9.+-]*/[a-z0-9][a-z0-9.+-]*", re.ASCII)


def allowed_source_problem(key: str, source: object) -> str | None:
    """
    Why ``source``, filed under ``key``, may not be on the allow-list; ``None``
    if it may.

    Run over :data:`ALLOWED_SOURCES` when the module loads, so a malformed
    entry fails every import rather than the first fetch, and again by the
    fetcher before it opens anything. The URL must be exactly
    ``https://<host>/<path>``: ``https`` and nothing weaker, the host written
    out and equal to ``source.host``, a DNS name rather than an address, no
    port, no user, no query and no fragment, ASCII, and unchanged by being
    split and put back together — so there is one reading of it, and it is the
    reading a reviewer makes.
    """
    if not isinstance(source, AllowedSource):
        return f"{type(source).__name__} is not an AllowedSource"
    if key != source.name or not isinstance(source.name, str):
        return "is not filed under its own name"
    if not _SOURCE_NAME.fullmatch(source.name):
        return "a source's name is lowercase letters, digits and hyphens"
    url = source.url
    if not isinstance(url, str) or not url.isascii() or not url.isprintable():
        return "the URL must be printable ASCII"
    if any(ch.isspace() for ch in url) or "\\" in url:
        return "the URL may hold no whitespace and no backslash"
    parts = urlsplit(url)
    if parts.scheme != "https":
        return "the URL must be https"
    if "?" in url or parts.query:
        return "the URL may carry no query"
    if "#" in url or parts.fragment:
        return "the URL may carry no fragment"
    if "@" in parts.netloc or ":" in parts.netloc:
        return "the URL may carry no user and no port"
    if parts.netloc != source.host or parts.hostname != source.host:
        return "the URL's host must be exactly the source's host"
    if urlunsplit(parts) != url:
        return "the URL must read the same once split and joined again"
    segments = parts.path.split("/")[1:]
    if not parts.path.startswith("/") or not all(segments):
        return "the URL must name a path, with no empty segment"
    if "%" in parts.path or any(s in (".", "..") for s in segments):
        return "the URL's path may hold no escapes and no dot segments"
    problem = _host_problem(source.host)
    if problem is not None:
        return problem
    types = source.content_types
    if (
        not isinstance(types, tuple)
        or not types
        or not all(isinstance(t, str) and _MEDIA_TYPE.fullmatch(t) for t in types)
    ):
        return "content_types is a non-empty tuple of lowercase media types"
    if source.charset != "utf-8":
        return "the charset must be utf-8"
    size = source.max_bytes
    if not isinstance(size, int) or isinstance(size, bool):
        return "max_bytes must be an integer"
    if not 0 < size <= MAX_SOURCE_BYTES:
        return f"max_bytes must be between 1 and {MAX_SOURCE_BYTES}"
    if source.parser not in _PARSER_NAMES:
        return "the parser must be one PARSERS names"
    return None


def _host_problem(host: object) -> str | None:
    """A DNS name in lowercase, with a dot, and not an address."""
    if not isinstance(host, str) or not host or len(host) > 253:
        return "the host must be a DNS name"
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return "the host must be a name, not an address"
    labels = host.split(".")
    if len(labels) < 2 or not all(_HOST_LABEL.fullmatch(label) for label in labels):
        return "the host must be a lowercase DNS name with a dot in it"
    if labels[-1].isdigit():
        return "the host must be a name, not an address"
    return None


class WrittenSource(NamedTuple):
    """
    An allow-list entry's values as this module wrote them: text, a tuple of
    text and a number, held in a tuple, so nothing can edit them in place and
    what the fetcher reads cannot change between its check and its request.
    """

    name: str
    url: str
    host: str
    content_types: tuple[str, ...]
    charset: str
    max_bytes: int
    parser: str


def as_written(source: object) -> WrittenSource | None:
    """
    ``source``'s values as this module wrote them, if ``source`` is one of the
    entries it wrote — the object itself — and still holds exactly those
    values, each of the type it was written as; ``None`` otherwise.

    The entries are frozen, but a frozen dataclass is edited anyway by
    ``object.__setattr__`` or a slot's descriptor, and a name that holds the
    list can be rebound to one holding another page. Checking only that an
    entry is well formed would pass an entry pointed at any other https page,
    so the fetcher asks this at every fetch, and fetches with the values
    returned, never with the live entry's.
    ``tests/unit/test_web_fetch.py::TestOnlyTheAllowListIsFetched``.
    """
    for entry, written in _WRITTEN:
        if source is entry:
            current = tuple(getattr(entry, name) for name in WrittenSource._fields)
            return written if _identical(current, tuple(written)) else None
    return None


def _identical(current: object, written: object) -> bool:
    """Equal, and of exactly the same types, so no subclass's ``==`` can lie."""
    if type(current) is not type(written):
        return False
    if isinstance(written, tuple):
        assert isinstance(current, tuple)
        return len(current) == len(written) and all(
            _identical(a, b) for a, b in zip(current, written, strict=True)
        )
    return current == written


# ---------------------------------------------------------------------------
# The README's strategies table
# ---------------------------------------------------------------------------

#: The line that opens the generated table. The generator writes more after
#: it (" - generated by ..."), so a line that starts with this opens the block.
START_MARKER = "<!-- STRATEGIES:START"

#: The line that closes it, whole.
END_MARKER = "<!-- STRATEGIES:END -->"

#: The README's headings inside the block, and the label each files its rows
#: under: the option key a question about asset class will use. The README's
#: own grouping, which is a label and not ground truth. A heading not listed
#: here refuses the snapshot, since rows under it would be filed under the
#: heading before it — and so does any line the parser cannot read as blank, a
#: heading, a table row or the generator's note, since a renderer may read it
#: as a heading (setext, ``<h2>``, a heading in a quote or a list) or hide the
#: rows after it (a comment, a code fence, ``<details>``).
HEADING_LABELS: Mapping[str, str] = MappingProxyType(
    {
        "Equities": "equities",
        "Bonds": "bonds",
        "Commodities": "commodities",
        "Currencies": "currencies",
        "Cryptocurrencies": "cryptocurrencies",
        "Derivatives": "derivatives",
        "Multi-asset": "multi_asset",
    }
)

#: One row of the table, exactly: a title linked to a strategy page on
#: paperswithbacktest.com, then Sharpe, t-statistic, volatility and years
#: tested, each backticked. Only the title is kept. ``re.ASCII`` so ``\\d`` is
#: 0-9 and nothing else; matched against the whole line (``fullmatch``). The
#: title may hold anything but ``]`` and a line break, so a Markdown link or
#: image can never sit inside one.
ROW_PATTERN = re.compile(
    r"^\| \[(?P<title>[^\]\n]{1,400})\]"
    r"\(https://paperswithbacktest\.com/strategies/[a-z0-9-]{1,200}\)"
    r" \| `-?\d+\.\d{2}` \| `-?\d+\.\d` \| `\d+\.\d%` \| `\d+` \|$",
    re.ASCII,
)

#: More rows than this in a snapshot, or under one heading, is a page that has
#: changed shape: today the generator writes 61 rows, at most 12 under a
#: heading. Either limit refuses the snapshot.
MAX_ROWS = 150
MAX_ROWS_PER_HEADING = 20

#: The longest line read inside the block, checked before any pattern reads
#: one, so no line can hold the parser for long. Today's longest is the
#: generator's note, 465 characters.
MAX_LINE_CHARS = 4_096

#: Why a snapshot can be refused. ``markers``: not exactly one opening and one
#: closing marker, in that order. ``line_too_long``: a line inside the block
#: longer than :data:`MAX_LINE_CHARS`. ``unknown_heading``: a heading inside
#: the block that :data:`HEADING_LABELS` does not name. ``unknown_line``: a
#: line inside the block that is not blank, a heading, a table row, or the
#: generator's note before the first heading. ``no_rows``: no row kept.
#: ``too_many_dropped``: more than half the table's rows did not match
#: :data:`ROW_PATTERN`. ``too_many_under_a_heading`` and ``too_many_rows``: the
#: limits above.
SNAPSHOT_REFUSALS: tuple[str, ...] = (
    "markers",
    "line_too_long",
    "unknown_heading",
    "unknown_line",
    "no_rows",
    "too_many_dropped",
    "too_many_under_a_heading",
    "too_many_rows",
)

#: A Markdown table's delimiter row, which marks the row before it as the
#: header. Neither is a strategy.
_DELIMITER_ROW = re.compile(r"\|(?:[ \t]*:?-{3,}:?[ \t]*\|)+")

#: An ATX heading, as CommonMark reads one: up to three spaces, one to six
#: hashes, then a space or the end of the line. Matched against the line with
#: its trailing spaces and tabs already stripped, so no lazy group is followed
#: by a run of them: that pairing backtracked quadratically, and one line of
#: spaces inside the size cap held the parser for minutes.
_HEADING = re.compile(r" {0,3}(#{1,6})(?:[ \t]+(.*))?")

#: The generator's note: one line in italics, a single emphasis with nothing
#: that could open markup, a link or code, allowed only before the first
#: heading. After a heading an italic line would read as a heading of its own
#: while its rows were filed under the one before.
_NOTE = re.compile(r"\*(?![ \t*])[^*<>\[\]`|\\_]+(?<![ \t])\*")


class SnapshotRefused(Exception):  # noqa: N818 - it names the outcome, not an error
    """
    The page is not one the parser can read with confidence.

    ``reason`` is one of :data:`SNAPSHOT_REFUSALS`. The message holds counts,
    limits and line numbers and never the page's text: it becomes a job's
    error, and phase C keeps web text out of every column but the two that are
    meant to hold it — the stored excerpt and the state a question was asked
    about.
    """

    def __init__(self, reason: str, detail: str) -> None:
        if reason not in SNAPSHOT_REFUSALS:
            raise ValueError(f"{reason!r} is not one of SNAPSHOT_REFUSALS")
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True, slots=True)
class Entry:
    """
    One row kept: the label of the heading it was under, and its title as
    written in the table's cell, before any normalising. Nothing else of the
    row survives the parser.
    """

    label: str
    cell: str


@dataclass(frozen=True, slots=True)
class Snapshot:
    """
    What the parser read from one page: the rows it kept, in page order, and
    how many table rows there were and how many it dropped.

    ``table_rows`` counts every row of a table that is not a header or a
    delimiter; ``dropped`` counts those that did not match :data:`ROW_PATTERN`
    or came before any heading. Counts, never content, are what a job reports.
    """

    parser: str
    entries: tuple[Entry, ...] = field(repr=False)
    table_rows: int
    dropped: int

    @property
    def rows(self) -> int:
        return len(self.entries)


def parse_pwb_readme(text: str) -> Snapshot:
    """
    The titles in the paperswithbacktest README's strategies table.

    Reads only the lines strictly between the one line that starts with
    :data:`START_MARKER` and the one that is :data:`END_MARKER`. Inside it,
    every line must be blank, a level-two heading :data:`HEADING_LABELS` names,
    a table row, or — before the first heading — the generator's note in
    italics; anything else refuses the snapshot, since a renderer may read it
    as a heading the parser would not, or hide the rows under it. Each row is
    kept only if it matches :data:`ROW_PATTERN` in full; a row that does not is
    dropped and counted. A table's header and delimiter rows are not rows.
    Nothing outside the block is read at all, the README's other ``## Crypto``
    heading, under books, among it.

    Raises :class:`SnapshotRefused` for anything that says the page has changed
    shape, and nothing else for any text (``TypeError`` for anything that is
    not text). Lines are split on a line feed alone, with a carriage return
    before one tolerated, so a line or paragraph separator inside a title stays
    in the title, where the code screen sees it. Every line of the block is
    measured against :data:`MAX_LINE_CHARS` before any pattern reads one.
    ``tests/unit/test_web_sources.py::TestARefusedSnapshot``.
    """
    if not isinstance(text, str):
        raise TypeError(f"the README is text, got {type(text).__name__}")
    lines = [line[:-1] if line.endswith("\r") else line for line in text.split("\n")]
    starts = [i for i, line in enumerate(lines) if line.startswith(START_MARKER)]
    ends = [i for i, line in enumerate(lines) if line.strip() == END_MARKER]
    if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
        raise SnapshotRefused(
            "markers",
            f"found {len(starts)} opening and {len(ends)} closing markers; the "
            "table is read only between exactly one of each, in that order",
        )
    first, last = starts[0] + 1, ends[0]
    for index in range(first, last):
        if len(lines[index]) > MAX_LINE_CHARS:
            raise SnapshotRefused(
                "line_too_long",
                f"line {index - first + 1} of the block is longer than "
                f"{MAX_LINE_CHARS} characters",
            )

    entries: list[Entry] = []
    label: str | None = None
    under_heading = 0
    table_rows = 0
    dropped = 0
    for index in range(first, last):
        line = lines[index]
        where = f"line {index - first + 1} of the block"
        if not line.strip(" \t"):
            continue
        heading = _HEADING.fullmatch(line.rstrip(" \t"))
        if heading is not None:
            name = (heading.group(2) or "").strip()
            if len(heading.group(1)) != 2 or name not in HEADING_LABELS:
                raise SnapshotRefused(
                    "unknown_heading",
                    f"{where} is a heading the parser does not know; it knows "
                    f"{len(HEADING_LABELS)} level-two headings",
                )
            label = HEADING_LABELS[name]
            under_heading = 0
            continue
        stripped = line.strip()
        if not stripped.startswith("|"):
            if label is None and _NOTE.fullmatch(line):
                continue  # the generator's note, before the first heading
            raise SnapshotRefused(
                "unknown_line",
                f"{where} is none of a blank line, a known heading, a table "
                "row or, before the first heading, the generator's note",
            )
        if _DELIMITER_ROW.fullmatch(stripped):
            continue
        following = lines[index + 1].strip() if index + 1 < last else ""
        if _DELIMITER_ROW.fullmatch(following):
            continue  # a header row
        table_rows += 1
        match = ROW_PATTERN.fullmatch(line)
        if match is None or label is None:
            dropped += 1
            continue
        under_heading += 1
        if under_heading > MAX_ROWS_PER_HEADING:
            raise SnapshotRefused(
                "too_many_under_a_heading",
                f"more than {MAX_ROWS_PER_HEADING} rows under the heading before "
                f"{where}",
            )
        entries.append(Entry(label=label, cell=match.group("title")))
        if len(entries) > MAX_ROWS:
            raise SnapshotRefused(
                "too_many_rows", f"more than {MAX_ROWS} rows by {where}"
            )
    if not entries:
        raise SnapshotRefused(
            "no_rows", f"no row of {table_rows} matched the pattern under a heading"
        )
    if dropped * 2 > table_rows:
        raise SnapshotRefused(
            "too_many_dropped",
            f"{dropped} of {table_rows} rows did not match; more than half is a "
            "page that has changed shape",
        )
    return Snapshot(
        parser=PWB_README_PARSER,
        entries=tuple(entries),
        table_rows=table_rows,
        dropped=dropped,
    )


#: Each parser by the name an :class:`AllowedSource` gives it.
PARSERS: Mapping[str, Callable[[str], Snapshot]] = MappingProxyType(
    {PWB_README_PARSER: parse_pwb_readme}
)
_PARSER_NAMES = frozenset(PARSERS)


# ---------------------------------------------------------------------------
# One normal form for an excerpt
# ---------------------------------------------------------------------------

#: A Markdown image or link, whose text is kept and whose target is not.
_MARKDOWN_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_MARKDOWN_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")

#: A backslash escape of ASCII punctuation, which CommonMark renders as the
#: character alone. A table cell must escape a literal pipe as ``\\|``.
_MARKDOWN_ESCAPE = re.compile(r"\\([!-/:-@\[-`{-~])")

#: What makes a token — a run of characters between whitespace — an address,
#: or part of one: a scheme's ``://`` (or its backslashed spelling); a
#: ``www.`` host; a protocol-relative ``//host``; an email address; a scheme a
#: browser acts on with no ``//`` (``mailto:``, ``xmpp:``, which GitHub links
#: as it links an email, ``javascript:``, ``vbscript:``, a ``data:`` URI); or a
#: host name followed by a path. Each alternative reads a bounded stretch from
#: where it starts, and each token is read once, so the removal is linear in
#: the text: the ``\S*...\S*`` it replaces backtracked quadratically on a run
#: of text with no space in it.
_ADDRESS = re.compile(
    r":[\\/]{2}"
    r"|www\."
    r"|(?:^|[(\[<{\"'])[\\/]{2,}(?=[^\s\\/])"
    r"|[^\s@]@[^\s@.]+\."
    r"|(?<![a-z0-9+.-])(?:mailto|xmpp|javascript|vbscript):"
    r"|(?<![a-z0-9+.-])data:[a-z]+/"
    r"|[a-z0-9-]\.[a-z]{2,63}/",
    re.IGNORECASE,
)

_TOKEN = re.compile(r"\S+")

_WHITESPACE = re.compile(r"\s+")

#: How many passes :func:`normalise_excerpt` makes before it gives up on text
#: that keeps changing. Each step runs to its own fixed point inside a pass, so
#: a further pass only has work when one step's removal joined characters into
#: something an earlier step reads; real text settles in one or two.
NORMALISE_PASSES = 16

#: The longest text the normaliser works on, as given or once NFKC has
#: expanded it. A row's title is at most 400 characters, and NFKC can make one
#: character eighteen, so this bounds the work a crafted title can ask for.
#: Longer text is no excerpt: it could never be a web state, which holds 300.
NORMALISE_MAX_CHARS = 2_000


def normalise_excerpt(cell: str) -> str:
    """
    The one form an excerpt is stored, hashed and asked about in.

    One pass: HTML character references decoded, and Markdown's backslash
    escapes, each until nothing more decodes; NFKC; whitespace, and the
    blank-glyph fillers a renderer draws as a blank, becoming a space; control
    (Cc), format (Cf), private-use (Co), surrogate (Cs) and unassigned (Cn)
    code points removed, and every other character the code screen's
    ``hidden_characters`` rule names, by the same explicit ranges — each
    default-ignorable code point Unicode lists, the variation selectors and
    plane 14's reserved code points among them, which category alone let
    through; a Markdown image or link replaced by its text, until none is
    left; any token that is or holds an address (:data:`_ADDRESS`) removed
    whole, so no part of one survives; whitespace collapsed to one space, and
    the ends stripped.

    **Idempotent**, by construction rather than by the order of the steps: a
    step can uncover work for another — removing a zero-width space can join
    ``&`` to ``lt;``, or ``http:`` to ``//`` — so passes repeat until the text
    no longer changes, and the result is a text one more pass leaves as it is.
    Text still changing after :data:`NORMALISE_PASSES` passes, or longer than
    :data:`NORMALISE_MAX_CHARS` as given or once expanded, becomes ``""``,
    which is also settled. An empty excerpt is no excerpt: :func:`screen_cell`
    drops the entry, since there is nothing to store or ask about.

    What it does not do is strip HTML. A tag or a comment in a title is a
    finding (the code screen's ``markup_in_cell``), and the excerpt keeps it,
    so a document quarantined for it is quarantined under words that include
    it. Nor does it truncate: an excerpt over the limit is quarantined whole
    (``overlong``), never cut. ``tests/unit/test_web_sources.py::TestTheNormaliser``.
    """
    if not isinstance(cell, str):
        raise TypeError(f"an excerpt is text, got {type(cell).__name__}")
    if len(cell) > NORMALISE_MAX_CHARS:
        return ""
    text = cell
    kept = _Kept()
    for _ in range(NORMALISE_PASSES):
        settled = _normalise_once(text, kept)
        if settled is None:
            return ""
        if settled == text:
            return settled
        text = settled
    return ""


def _normalise_once(text: str, kept: _Kept) -> str | None:
    """One pass, or ``None`` for text NFKC expands past the bound."""
    text = _until_settled(html.unescape, text)
    text = _until_settled(lambda t: _MARKDOWN_ESCAPE.sub(r"\1", t), text)
    text = unicodedata.normalize("NFKC", text)
    if len(text) > NORMALISE_MAX_CHARS:
        return None
    text = text.translate(kept)
    text = _until_settled(lambda t: _MARKDOWN_IMAGE.sub(r"\1", t), text)
    text = _until_settled(lambda t: _MARKDOWN_LINK.sub(r"\1", t), text)
    text = _TOKEN.sub(_unless_an_address, text)
    return _WHITESPACE.sub(" ", text).strip()


def _unless_an_address(token: re.Match[str]) -> str:
    return " " if _ADDRESS.search(token.group()) else token.group()


def _until_settled(step: Callable[[str], str], text: str) -> str:
    """Apply ``step`` until it changes nothing. Each step used here shortens."""
    while True:
        changed = step(text)
        if changed == text:
            return text
        text = changed


#: Categories removed whatever the character: control, format, private use,
#: surrogate and unassigned. Categories come from this Python's Unicode
#: database, so the explicit ranges of ``hidden_characters`` are removed as
#: well: a reserved default-ignorable code point is unassigned, and category
#: alone once let one through.
_REMOVED_CATEGORIES = frozenset({"Cc", "Cf", "Co", "Cs", "Cn"})


#: Hidden characters a renderer draws as a blank the width of a letter — the
#: Hangul fillers and the Braille blank — which read as the space they look
#: like: four words with a Braille blank between each are four words to a
#: reader. Every other hidden character is drawn as nothing, and is removed.
_BLANK_GLYPHS = frozenset("\u115f\u1160\u3164\uffa0\u2800")


def _kept(ch: str) -> str:
    """What one character becomes: itself, a space, or nothing."""
    if ch.isspace() or ch in _BLANK_GLYPHS:
        return " "
    if unicodedata.category(ch) in _REMOVED_CATEGORIES or _HIDDEN.match(ch):
        return ""
    return ch


class _Kept(dict[int, str]):
    """
    :func:`_kept` as a table ``str.translate`` reads, each code point worked
    out once per call to :func:`normalise_excerpt`, whose passes read the same
    characters again: a lookup at the speed of ``translate`` rather than a
    function call per character per pass. Made afresh for each call, so it
    holds no more than one title's characters.
    """

    def __missing__(self, codepoint: int) -> str:
        kept = self[codepoint] = _kept(chr(codepoint))
        return kept


def content_sha256(excerpt: str) -> str:
    """
    The content address of an excerpt: ``jev_hash.text_sha256``, so a stored
    document, a subject the lane asks about and a label all name the same words
    the same way (``web_documents_content_is_its_excerpt``, migration 0013).
    """
    return jev_hash.text_sha256(excerpt)


# ---------------------------------------------------------------------------
# The code screen
# ---------------------------------------------------------------------------

#: The version of the rules below. A quarantine records it
#: (:func:`quarantine_reason`), so it names one rule set forever: changing a
#: pattern, a reading or a table a reading uses means a new version.
CODE_SCREEN_VERSION = 1

#: :func:`code_screen_sha256` of this version, pinned beside the rules. A test
#: compares the two, and holds this one to the append-only history of
#: released versions kept in ``test_web_sources.py``, so re-recording it after
#: a change — the edit a failing hash test invites — still fails there, as
#: ``jev_questions.GOLDEN_PACK_HASHES`` fails against its released history.
#: Re-recorded once before any row could say v1, when review revised v1's rules.
GOLDEN_CODE_SCREEN_SHA256 = (
    "95cc9a98bff72231934da34b8d475668af04ee84a966c86073850958e88e1984"
)


@dataclass(frozen=True, slots=True)
class ScreenRule:
    """
    One rule of the code screen, as data: its name, the reading of the text it
    matches (:data:`SCREEN_READINGS`), and its patterns' sources, each complete
    with its own flags.
    """

    name: str
    reads: str
    patterns: tuple[str, ...]


#: Characters nobody sees: every default-ignorable code point Unicode lists —
#: the soft hyphen, the combining grapheme joiner, the Arabic letter mark, the
#: Hangul and Khmer fillers, the Mongolian variation selectors and vowel
#: separator, the zero-width space, joiners and directional marks, the
#: bidirectional embeddings, overrides and isolates, the word joiner and
#: invisible operators, the variation selectors, the byte-order mark, the
#: reserved specials, the shorthand and musical format controls, and the whole
#: of plane 14's tag block, its reserved code points included — and, beside
#: them, every C0 and C1 control, the line and paragraph separators, the
#: interlinear annotation characters, surrogates, every private-use character,
#: and the blank-glyph characters that are not default-ignorable: the Braille
#: blank, the Khitan filler and the musical null notehead. Explicit ranges
#: rather than Unicode categories, so the rule is the same under every
#: Python's Unicode database; ``test_web_sources.py`` checks it against
#: Unicode's own list. The normaliser removes the same characters.
_HIDDEN_CHARACTERS = (
    r"[\x00-\x1f\x7f-\x9f\xad\u034f\u061c\u115f\u1160"
    r"\u17b4\u17b5\u180b-\u180f\u200b-\u200f"
    r"\u2028-\u202e\u2060-\u206f\u2800\u3164"
    r"\ufe00-\ufe0f\ufeff\uffa0\ufff0-\ufffb"
    r"\ue000-\uf8ff\ud800-\udfff\U00016fe4\U0001bca0-\U0001bca3"
    r"\U0001d159\U0001d173-\U0001d17a\U000e0000-\U000e0fff\U000f0000-\U0010ffff]"
)
_HIDDEN = re.compile(_HIDDEN_CHARACTERS)

#: Letters of the Latin blocks European languages write in. The mixed-script
#: rule reads any other letter beside one of these in a word — Cyrillic,
#: Greek, Armenian, Cherokee, IPA, a small capital — as the shape of a
#: homoglyph.
_LATIN_LETTERS = (
    r"A-Za-z\xaa\xba\xc0-\xd6\xd8-\xf6\xf8-\u024f\u1e00-\u1eff"
    r"\u2c60-\u2c7f\ua720-\ua7ff\uab30-\uab6f"
    r"\uff21-\uff3a\uff41-\uff5a"
)

#: Characters drawn like an ASCII letter, each read as that letter by the
#: ``skeleton`` reading: Latin letters no decomposition reaches (dotless,
#: stroked, hooked, small capitals) and the common lookalikes of the Cyrillic,
#: Greek, Armenian, Coptic, Cherokee and Lisu scripts, after Unicode's
#: confusables (UTS #39). Keyed by case where the two cases look like
#: different letters, since the reading maps before casefolding as well as
#: after: Greek capital eta is an H and its small letter an n. Data, hashed
#: with the rules. ``test_web_sources.py`` reads each entry back through the
#: reading.
_LOOKALIKES: Mapping[str, str] = MappingProxyType(
    {
        "a": "\u0251\u1d00\u0430\u0410\u03b1\u0391\u2c81\u2c80\u13aa\ua4ee",
        "b": (
            "\u0299\u0180\u0243\u0253\u0432\u0412\u044c\u042c\u03b2\u0392\u2c82\u13f4"
            "\ua4d0"
        ),
        "c": "\u1d04\u023c\u023b\u0441\u0421\u03f2\u03f9\u2ca5\u2ca4\u13df\ua4da",
        "d": "\u1d05\u0111\u0110\u0257\u0256\u0501\u0500\u13a0\ua4d3",
        "e": (
            "\u025b\u1d07\u0247\u0246\u0435\u0415\u0454\u0404\u03b5\u0395\u2c89\u2c88"
            "\u13ac\ua4f0"
        ),
        "f": "\ua730\ua4dd",
        "g": "\u0261\u0262\u01e5\u01e4\u0260\u0581\u13c0\ua4d6",
        "h": (
            "\u029c\u0127\u0126\u0266\u04bb\u04ba\u043d\u041d\u0397\u0570\u2c8e\u13bb"
            "\ua4e7"
        ),
        "i": (
            "\u0131\u0269\u026a\u0268\u0197\u0456\u0406\u03b9\u0399\u2c93\u2c92\u13a5"
            "\ua4f2"
        ),
        "j": "\u0237\u1d0a\u0249\u0248\u0458\u0408\u03f3\u037f\u13ab\ua4d9",
        "k": "\u1d0b\u0199\u043a\u041a\u03ba\u039a\u2c95\u2c94\u13e6\ua4d7",
        "l": "\u029f\u0142\u0141\u019a\u026d\u04cf\u04c0\u053c\u13de\ua4e1",
        "m": "\u1d0d\u0271\u043c\u041c\u039c\u2c99\u2c98\u13b7\ua4df",
        "n": "\u0274\u0272\u0273\u043f\u03b7\u039d\u0578\u2c9b\u2c9a\ua4e0",
        "o": (
            "\u0275\u1d0f\xf8\xd8\u043e\u041e\u03bf\u039f\u03c3\u0585\u0555\u2c9f"
            "\u2c9e\ua4f3"
        ),
        "p": "\u1d18\u01a5\u0440\u0420\u03c1\u03a1\u0584\u2ca3\u2ca2\u13e2\ua4d1",
        "q": "\ua7af\u02a0\u051b\u051a\u0566",
        "r": "\u0280\u024d\u024c\u027d\u0433\u13a1\u13d2\ua4e3",
        "s": "\ua731\u0282\u0455\u0405\u13da\ua4e2",
        "t": (
            "\u1d1b\u0167\u0166\u01ad\u0288\u0442\u0422\u03c4\u03a4\u2ca7\u2ca6\u13a2"
            "\ua4d4"
        ),
        "u": "\u028a\u1d1c\u0289\u0244\u03bc\u03c5\u057d\u054d\ua4f4",
        "v": "\u028b\u1d20\u0475\u0474\u03bd\u13d9\ua4e6",
        "w": "\u1d21\u051d\u051c\u03c9\u0561\u2cb1\u13b3\ua4ea",
        "x": "\u0445\u0425\u03c7\u03a7\u2cad\u2cac\ua4eb",
        "y": (
            "\u028f\u024f\u024e\u01b4\u0443\u0423\u04af\u04ae\u03a5\u03b3\u2ca9\u2ca8"
            "\u13a9\ua4ec"
        ),
        "z": "\u1d22\u01b6\u01b5\u0225\u0290\u0396\u2c8d\u2c8c\u13c3\ua4dc",
    }
)

CONFUSABLES: Mapping[str, str] = MappingProxyType(
    {ch: letter for letter, chars in _LOOKALIKES.items() for ch in chars}
)

#: What the ``skeleton`` reading reads as a space: Markdown's emphasis markers,
#: which a renderer hides, among them the underscore, which a pattern's ``\w``
#: would read as a letter — so ``__Ignore__`` or ``_system prompt_`` hid a
#: keyword from every rule.
SKELETON_SPACES = "_*~"

#: How a rule reads a text: the steps applied to it, in order. Data, hashed
#: with the rules, so a reading cannot change under a version either.
#: ``text``: as given. ``nfkc_casefold``: NFKC, then casefolding, so a
#: fullwidth, ligatured or capitalised word reads as the plain one.
#: ``skeleton``: every letter drawn like an ASCII one read as that letter —
#: :data:`CONFUSABLES` mapped before casefolding and after, and the marks NFKD
#: separates dropped, so a capital I with a dot, an o with an umlaut, a dotless
#: i and a Jev spelled in Cyrillic letters all read as the plain words — and
#: :data:`SKELETON_SPACES` read as spaces. Its patterns bound a keyword by the
#: ASCII letters around it, not by ``\b``, so a digit, an underscore or another
#: script's letter beside a keyword does not hide it.
SCREEN_READINGS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "text": (),
        "nfkc_casefold": ("nfkc", "casefold"),
        "skeleton": (
            "confusables",
            "nfkd",
            "drop_marks",
            "confusables",
            "casefold",
            "nfkd",
            "drop_marks",
            "confusables",
            "spaces",
        ),
    }
)

_CONFUSABLES_TABLE = str.maketrans(dict(CONFUSABLES))
_SPACES_TABLE = str.maketrans(dict.fromkeys(SKELETON_SPACES, " "))


def _drop_marks(text: str) -> str:
    return "".join(ch for ch in text if unicodedata.category(ch) not in ("Mn", "Me"))


#: What each step a reading names does.
_READING_STEPS: Mapping[str, Callable[[str], str]] = MappingProxyType(
    {
        "nfkc": lambda text: unicodedata.normalize("NFKC", text),
        "nfkd": lambda text: unicodedata.normalize("NFKD", text),
        "casefold": str.casefold,
        "drop_marks": _drop_marks,
        "confusables": lambda text: text.translate(_CONFUSABLES_TABLE),
        "spaces": lambda text: text.translate(_SPACES_TABLE),
    }
)

#: A keyword starts where no ASCII letter is before it and ends where none
#: follows (the ``skeleton`` has read every lookalike as an ASCII letter);
#: words are apart where anything but a letter or a digit lies between them.
_B = r"(?<![a-z])"
_E = r"(?![a-z])"
_S = r"[^a-z0-9]+"

#: The rules, in the order they are tried; the first that fires is the result.
CODE_SCREEN_RULES: tuple[ScreenRule, ...] = (
    ScreenRule("hidden_characters", "text", (_HIDDEN_CHARACTERS,)),
    ScreenRule(
        "markup_in_cell",
        "text",
        (r"(?i)</?[a-z][^<>]*>|<!--|-->|<![a-z\[]|<\?",),
    ),
    ScreenRule(
        "instruction_phrase",
        "skeleton",
        (
            rf"{_B}(?:ignore|disregard|forget|override|bypass){_E}.{{0,40}}"
            rf"{_B}(?:previous|prior|above|earlier|preceding|all|any){_E}.{{0,20}}"
            rf"{_B}(?:instructions?|prompts?|rules?|directions?|guidelines?){_E}",
            rf"{_B}(?:ignore|disregard|forget|override|bypass){_E}.{{0,20}}"
            rf"{_B}(?:your|the|these|those|my|its|their){_E}.{{0,20}}"
            rf"{_B}(?:instructions?|prompts?){_E}",
            rf"{_B}(?:ignore|disregard|forget){_E}{_S}"
            rf"(?:(?:all|everything|anything|the|of|that){_S}){{0,3}}"
            rf"(?:above|preceding){_E}",
            rf"{_B}(?:do{_S}not|don[^a-z0-9]?t|never|stop){_S}"
            rf"(?:follow|obey|heed)(?:ing)?{_E}.{{0,30}}"
            rf"{_B}(?:instructions?|prompts?|directions?){_E}",
            rf"{_B}(?:system|developer)[^a-z0-9]*prompts?{_E}",
            r"(?:^|[.!?;|>\])])[^a-z0-9]{0,3}"
            rf"(?:system|assistant|user|developer|human){_E}[ \t]*:",
            r"<\|[^|\n]{1,40}\|>",
            r"\[/?inst\]|<</?sys>>",
            r"(?<!#)#{2,}+[^a-z0-9]{0,3}"
            rf"(?:instructions?|response|system|input|human|assistant|user){_E}",
            rf"{_B}(?:answer|classify|label|categori[sz]e|mark|rate|score|tag){_E}"
            rf"{_S}(?:this|it|me|the{_S}(?:title|text|paper|item|entry|row)){_E}"
            rf"(?:{_S}[a-z]+)?{_S}as{_E}",
            rf"{_B}(?:answer|respond|reply){_E}[ \t]+"
            rf"(?:(?:only|just|with|using){_E}[ \t]+){{0,2}}"
            r"[\"'`\u2018\u2019\u201c\u201d]?"
            rf"(?:true|false|yes|no|insufficient[ \t]*evidence){_E}",
            rf"{_B}(?:output|print){_E}[ \t]+(?:only[ \t]+)?"
            rf"(?:true|false|insufficient[ \t]*evidence){_E}",
            rf"{_B}you(?:{_S}are|[^a-z0-9]*re|{_S}r){_E}{_S}(?:now{_S})?"
            rf"(?:an?|the|my|our){_S}(?:[a-z]+{_S}){{0,2}}"
            rf"(?:ai|assistant|model|chatbot|bot|language{_S}model|llm){_E}",
            rf"{_B}(?:jev|typesafe|claude|anthropic|chatgpt|openai|gpt){_E}",
        ),
    ),
    ScreenRule(
        "encoded_payload",
        "text",
        (
            r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{40,}={0,2}",
            r"(?<![A-Za-z0-9_-])(?=[A-Za-z0-9_-]*?[0-9])(?=[A-Za-z0-9_-]*?[_-])"
            r"[A-Za-z0-9_-]{40,}={0,2}",
            r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{16,}={0,2}"
            r"(?:\s+[A-Za-z0-9+/]{16,}={0,2})+",
            r"\b[0-9A-Fa-f]{64,}\b",
        ),
    ),
    ScreenRule(
        "mixed_script_word",
        "nfkc_casefold",
        (
            rf"(?<!\w)(?=\w*?[{_LATIN_LETTERS}])"
            rf"(?=\w*?(?![{_LATIN_LETTERS}])[^\W\d_])\w+",
        ),
    ),
    ScreenRule("overlong", "text", (rf"(?s)\A.{{{EXCERPT_MAX_CHARS + 1}}}",)),
)

CODE_SCREEN_RULE_NAMES: tuple[str, ...] = tuple(r.name for r in CODE_SCREEN_RULES)

_COMPILED_RULES: tuple[tuple[str, str, tuple[re.Pattern[str], ...]], ...] = tuple(
    (rule.name, rule.reads, tuple(re.compile(p) for p in rule.patterns))
    for rule in CODE_SCREEN_RULES
)


def read_as(reading: str, text: str) -> str:
    """``text`` as the reading :data:`SCREEN_READINGS` names reads it."""
    for step in SCREEN_READINGS[reading]:
        text = _READING_STEPS[step](text)
    return text


def code_screen(text: str) -> str | None:
    """
    The name of the first rule of :data:`CODE_SCREEN_RULES` that ``text``
    trips, or ``None``.

    Run on a title as written in its cell and again on its normalised
    excerpt, and :func:`screen_cell` decides what the two findings mean. The
    rules, in order:

    * ``hidden_characters``: every default-ignorable code point, control,
      private-use character and blank-glyph filler, each of which hides
      something from a reader;
    * ``markup_in_cell``: an HTML tag, comment, declaration or processing
      instruction;
    * ``instruction_phrase``: read as a skeleton — "ignore/disregard …
      previous/prior instructions", "ignore your instructions", "ignore the
      above", "do not follow … instructions", "system prompt" however it is
      joined, a role opening the text or a sentence (``system:``,
      ``assistant:``, ``user:``, ``developer:``, ``human:``), chat-template
      tokens, ``[INST]``, ``### instruction``, "answer/classify/label … this/it
      as", "answer/respond true/false/insufficient evidence", "you are … an
      AI/assistant/model", and the names of Jev, TypeSafe and the model
      vendors;
    * ``encoded_payload``: 40 or more base64 or base64url characters in a run,
      two runs of 16 or more split by whitespace, or 64 hex;
    * ``mixed_script_word``: a word holding a Latin letter and a letter of any
      other script or block, the shape of a homoglyph;
    * ``overlong``: more than ``EXCERPT_MAX_CHARS`` characters, which is
      quarantined rather than cut.

    A keyword baseline, not a defence: it catches the obvious, is the baseline
    Jev's own screen is measured against, and has false positives by design
    (a paper whose title names Claude Shannon is quarantined), whose only cost
    is that Jev is not asked about that title. Every pattern reads a bounded
    stretch or runs once per word, so no text holds it for long. Never raises
    for any text. ``tests/unit/test_web_sources.py::TestTheCodeScreen``.
    """
    if not isinstance(text, str):
        raise TypeError(f"the code screen reads text, got {type(text).__name__}")
    readings: dict[str, str] = {}
    for name, reads, patterns in _COMPILED_RULES:
        if reads not in readings:
            readings[reads] = read_as(reads, text)
        if any(pattern.search(readings[reads]) for pattern in patterns):
            return name
    return None


def quarantine_reason(rule: str) -> str:
    """The reason a document quarantined by the code screen records."""
    if rule not in CODE_SCREEN_RULE_NAMES:
        raise ValueError(f"{rule!r} is not a rule of the code screen")
    return f"code-screen v{CODE_SCREEN_VERSION}: {rule}"


def code_screen_sha256() -> str:
    """
    sha256 of the code screen's definition as compact JSON: its version, every
    reading's steps, the tables the readings use, and every rule's name, what
    it reads and its patterns, in order. What a pre-registered analysis plan
    hashes to say which screen it was written against, what
    :data:`GOLDEN_CODE_SCREEN_SHA256` pins, and what the test holds each
    released version to.
    """
    definition = {
        "version": CODE_SCREEN_VERSION,
        "readings": {name: list(steps) for name, steps in SCREEN_READINGS.items()},
        "confusables": sorted(CONFUSABLES.items()),
        "spaces": SKELETON_SPACES,
        "rules": [[r.name, r.reads, list(r.patterns)] for r in CODE_SCREEN_RULES],
    }
    text = json.dumps(definition, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# What becomes of a row the parser kept
# ---------------------------------------------------------------------------

#: What :func:`screen_cell` decides for a kept row. ``keep``: its excerpt is
#: stored, to be asked about. ``quarantine``: its excerpt itself trips the code
#: screen, and is stored quarantined under that rule, so Jev is never asked
#: about it. ``drop``: nothing is stored — the excerpt is empty, or only the
#: cell's decoration tripped the screen.
CELL_FATES: tuple[str, ...] = ("keep", "quarantine", "drop")


@dataclass(frozen=True, slots=True)
class Screened:
    """
    What becomes of one kept row: its fate, one of :data:`CELL_FATES`; the
    excerpt to store, ``""`` for a drop; and the rule that decided, ``None`` for
    a keep and for an empty excerpt. The excerpt is kept out of the ``repr``.
    """

    fate: str
    excerpt: str = field(repr=False)
    rule: str | None

    def __post_init__(self) -> None:
        if self.fate not in CELL_FATES:
            raise ValueError(f"{self.fate!r} is not one of CELL_FATES")


def screen_cell(cell: str) -> Screened:
    """
    Screen a title as written in its cell, normalise it, screen the excerpt,
    and say what becomes of the row: the one decision the ingest job (C6)
    stores, so the rule lives here, pure and tested, rather than in the job.

    Quarantine is by content, one-way and across sources (design part C6): a
    quarantined excerpt is never asked about again, wherever it appears. So
    only an excerpt that itself trips the screen is quarantined. A cell whose
    decoration alone tripped it — a zero-width space, a bidirectional control,
    or an instruction inside a URL, each of which the normaliser removes —
    normalises to words that do not, and quarantining those words would let
    anyone who could decorate one row have a clean title quarantined
    everywhere. That row is dropped instead, and counted, and its rule named;
    the same words from a row without the decoration are kept. An empty
    excerpt, which is nothing to store or ask about, is dropped too.
    ``tests/unit/test_web_sources.py::TestWhatBecomesOfARow``.
    """
    excerpt = normalise_excerpt(cell)
    if not excerpt:
        return Screened("drop", "", None)
    rule = code_screen(excerpt)
    if rule is not None:
        return Screened("quarantine", excerpt, rule)
    rule = code_screen(cell)
    if rule is not None:
        return Screened("drop", "", rule)
    return Screened("keep", excerpt, None)


# ---------------------------------------------------------------------------
# The labeller a source's grouping is recorded as
# ---------------------------------------------------------------------------

_LABEL = re.compile(r"[a-z0-9_]+", re.ASCII)


def dataset_labeller(source: str, pairs: Iterable[tuple[str, str]]) -> str:
    """
    The identity of a source's own grouping as a labeller:
    ``source:<name>@<sha12>``.

    ``pairs`` are ``(label, excerpt)``: each kept row's heading label and its
    normalised excerpt. The hash is the first twelve hex digits of the sha256 of
    the distinct pairs, each written ``label<TAB>excerpt``, sorted, joined by
    line feeds — so the identity changes when a title moves between headings or
    a title is added or removed, and not when a Sharpe moves, since no figure is
    in it. Two rows with the same title under the same heading are one labelled
    item. ``ValueError`` for an unknown source, no pairs, or a label or excerpt
    that could make two different sets write the same text.
    """
    if source not in ALLOWED_SOURCES:
        raise ValueError(f"{source!r} is not an allowed source")
    lines: set[str] = set()
    for label, excerpt in pairs:
        if not isinstance(label, str) or not _LABEL.fullmatch(label):
            raise ValueError("a label is lowercase letters, digits and underscores")
        if not isinstance(excerpt, str) or not excerpt:
            raise ValueError("an excerpt is non-empty text")
        if "\t" in excerpt or "\n" in excerpt:
            raise ValueError("an excerpt holds no tab and no line feed")
        lines.add(f"{label}\t{excerpt}")
    if not lines:
        raise ValueError("a labeller labels something")
    digest = hashlib.sha256("\n".join(sorted(lines)).encode("utf-8")).hexdigest()
    return f"source:{source}@{digest[:12]}"


# ---------------------------------------------------------------------------
# Checked when the module loads
# ---------------------------------------------------------------------------


def _check_the_allow_list() -> None:
    for key, source in ALLOWED_SOURCES.items():
        problem = allowed_source_problem(key, source)
        if problem is not None:
            raise ValueError(f"ALLOWED_SOURCES[{key!r}] {problem}")
    for rule in CODE_SCREEN_RULES:
        if rule.reads not in SCREEN_READINGS:
            raise ValueError(f"code screen rule {rule.name} reads {rule.reads!r}")
    for reading, steps in SCREEN_READINGS.items():
        unknown = [step for step in steps if step not in _READING_STEPS]
        if unknown:
            raise ValueError(f"reading {reading} names unknown steps {unknown}")
    if WrittenSource._fields != tuple(f.name for f in fields(AllowedSource)):
        raise ValueError("WrittenSource must name AllowedSource's fields, in order")


_check_the_allow_list()

#: Each entry as this module wrote it, recorded once the list has been checked:
#: the object, and its values (:func:`as_written`).
_WRITTEN: tuple[tuple[AllowedSource, WrittenSource], ...] = tuple(
    (
        source,
        WrittenSource(*(getattr(source, name) for name in WrittenSource._fields)),
    )
    for source in ALLOWED_SOURCES.values()
)


__all__ = [
    "ALLOWED_SOURCES",
    "CELL_FATES",
    "CODE_SCREEN_RULES",
    "CODE_SCREEN_RULE_NAMES",
    "CODE_SCREEN_VERSION",
    "CONFUSABLES",
    "END_MARKER",
    "GOLDEN_CODE_SCREEN_SHA256",
    "HEADING_LABELS",
    "MAX_LINE_CHARS",
    "MAX_ROWS",
    "MAX_ROWS_PER_HEADING",
    "MAX_SOURCE_BYTES",
    "NORMALISE_MAX_CHARS",
    "NORMALISE_PASSES",
    "PARSERS",
    "PWB_README_PARSER",
    "ROW_PATTERN",
    "SCREEN_READINGS",
    "SKELETON_SPACES",
    "SNAPSHOT_REFUSALS",
    "START_MARKER",
    "AllowedSource",
    "Entry",
    "ScreenRule",
    "Screened",
    "Snapshot",
    "SnapshotRefused",
    "WrittenSource",
    "allowed_source_problem",
    "as_written",
    "code_screen",
    "code_screen_sha256",
    "content_sha256",
    "dataset_labeller",
    "normalise_excerpt",
    "parse_pwb_readme",
    "quarantine_reason",
    "read_as",
    "screen_cell",
]

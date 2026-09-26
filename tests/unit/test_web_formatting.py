"""
test_web_formatting.py
----------------------
Two of CLAUDE.md's honesty rules as the frontend can break them, checked
against the shipped source of ``web/src``.

1. **A percentage is built in one place.** Every ratio the API returns is a
   fraction, and ``fmtPct`` in ``web/src/lib/format.ts`` is where one becomes a
   percentage. The daily report once rendered ``drawdown_pct`` as
   ``<Figure value={...drawdown_pct} suffix="%" />`` — the raw fraction with a
   "%" after it — so a 5.12% drawdown read "-0.051%" there and "-5.12%" on
   /portfolio. Nothing failed: the build, the type checker and every test
   passed, because appending a character to a number is correct TypeScript. So
   a "%" attached to a figure (a ``"%"`` literal, ``{x}%`` / ``${x}%``, a number
   and "%" as JSX text) and an ad hoc ``* 100`` are refused everywhere in
   ``web/src`` except the formatter.

2. **An unmeasured metric is never zero, and an absence says why.** The owner's
   decision of 2026-09-26: "not measured" for a metric never computed, "no
   data" for an observation that never arrived, "missing" plus the reason for a
   required field — never a bare dash, never 0. ``slippage_bps ?? 0`` showed
   every run the programme queued as a frictionless "0 bps", and
   ``periods_per_year ?? 252`` would annualise a missing count on the NYSE year.
   So a nullish or falsy fallback to a number literal, and a dash standing
   alone as a value, are refused; ``<Absent>`` (``web/src/components/Absent.tsx``)
   is what to write instead. A genuine zero stays a zero — nothing here stops
   rendering a count of 0.

A third check keeps a copy honest: the hypothesis page marks which card fields
gate 0 -> 1 requires, so a missing required field can say what it blocks, and
that list is compared with ``REQUIRED_CARD_FIELDS`` in ``src/programme/gates.py``.

The conventions are ``test_import_boundaries.py``'s and
``test_design_tokens.py``'s: a scanner that silently finds nothing passes every
test, so each scanner is applied to synthetic sources that must trip it and
ones that must not, and each real-tree test first asserts it read what it is
meant to read. The allow-lists hold exact counts per file, so they can only
shrink: a new occurrence fails, and so does a removed one until its entry is
deleted.

Standard library and pytest only; nothing here needs Node.
"""

from __future__ import annotations

import os
import re
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "web" / "src"

#: The one file allowed to attach "%" to a number, relative to ``web/src``.
FORMATTER = "lib/format.ts"

SKIPPED_DIRECTORIES = frozenset({"node_modules", ".next"})
SCANNED_SUFFIXES = (".ts", ".tsx")

PERCENT_RULES = ("pct-literal", "pct-after-expression", "pct-times-100", "pct-text")
ABSENCE_RULES = ("numeric-fallback", "bare-dash", "bare-dash-text")

# ---------------------------------------------------------------------------
# Allow-lists. Key: (path relative to web/src, rule, the text matched). Value:
# (exact count in that file, why it is tolerated). Every entry is either a use
# that is not an absent value at all, or debt with an owner — never a pattern
# to copy.
# ---------------------------------------------------------------------------

PERCENT_ALLOWED: dict[tuple[str, str, str], tuple[int, str]] = {}

ABSENCE_ALLOWED: dict[tuple[str, str, str], tuple[int, str]] = {
    ("components/EquityChart.tsx", "numeric-fallback", "|| 1"): (
        1,
        "the equity axis's span when every point is equal: a divisor that keeps "
        "a flat curve drawable, never a rendered value",
    ),
    ("components/EquityChart.tsx", "numeric-fallback", "|| 0.01"): (
        1,
        "the drawdown axis's span when there has been no drawdown: a divisor, "
        "never a rendered value",
    ),
}

# ---------------------------------------------------------------------------
# The scanner
# ---------------------------------------------------------------------------

_STRING = re.compile(
    r'"((?:[^"\\\n]|\\.)*)"|\'((?:[^\'\\\n]|\\.)*)\'|`((?:[^`\\]|\\.)*)`'
)

_DASHES = frozenset({"—", "–"})

_PATTERNS: dict[str, re.Pattern[str]] = {
    # `{value}%` in JSX and `${value}%` in a template literal.
    "pct-after-expression": re.compile(r"\}\s*%"),
    # Scaling by hand: `x * 100`, `100 * x`. Not `* 1000` or `* 100_000`.
    "pct-times-100": re.compile(r"\*\s*100(?![\d_.])|(?<![\w.])100\s*\*"),
    # A number and "%" written as JSX text: `>0%<`, or alone on a line.
    "pct-text": re.compile(
        r">\s*-?\d+(?:\.\d+)?\s*%\s*<|^\s*-?\d+(?:\.\d+)?\s*%\s*$", re.MULTILINE
    ),
    # `x ?? 0`, `x ?? 252`, `x || 0`: an absent value turned into a number.
    "numeric-fallback": re.compile(r"(?:\?\?|\|\|)\s*-?\d[\d_.]*"),
    # A dash alone as JSX text: `>—<`, or alone on a line.
    "bare-dash-text": re.compile(r">\s*[—–-]\s*<|^\s*[—–]\s*$", re.MULTILINE),
}

#: A hyphen is a string literal in plenty of honest code (`split("-")`), so it
#: counts only where it stands in for a value: after `??`, `||`, `?`, `:` or
#: `return`.
_HYPHEN_FALLBACK = re.compile(r"(?:\?\?|\|\||[?:]|\breturn)\s*$")


def blank_comments(text: str) -> str:
    """Replace comments with spaces, keeping offsets and newlines.

    Aware of string literals, so a URL's ``//`` is not a comment. Quotes do not
    cross a newline, so an apostrophe in JSX text costs at most its own line.
    """
    out, i, n, quote = list(text), 0, len(text), None
    while i < n:
        c = text[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote or (c == "\n" and quote != "`"):
                quote = None
            i += 1
            continue
        if c in "\"'`":
            quote = c
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out[i:j] = [ch if ch == "\n" else " " for ch in text[i:j]]
            i = j
            continue
        elif text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            out[i:j] = [" "] * (j - i)
            i = j
            continue
        i += 1
    return "".join(out)


def findings(source: str) -> list[tuple[int, str, str]]:
    """Every (line, rule, matched text) in a TS/TSX source, in order."""
    text = blank_comments(source)
    found: list[tuple[int, int, str, str]] = []

    def line_of(offset: int) -> int:
        return text.count("\n", 0, offset) + 1

    for rule, pattern in _PATTERNS.items():
        for m in pattern.finditer(text):
            # Whitespace collapsed, so a match spanning JSX lines is one key.
            match = " ".join(m.group(0).split())
            found.append((m.start(), line_of(m.start()), rule, match))

    for m in _STRING.finditer(text):
        content = next(g for g in m.groups() if g is not None)
        literal = m.group(0)
        if content == "%":
            found.append((m.start(), line_of(m.start()), "pct-literal", literal))
        elif content.strip() in _DASHES:
            found.append((m.start(), line_of(m.start()), "bare-dash", literal))
        elif content.strip() in {"-", "--"} and _HYPHEN_FALLBACK.search(
            text[: m.start()]
        ):
            found.append((m.start(), line_of(m.start()), "bare-dash", literal))

    return [(line, rule, match) for _, line, rule, match in sorted(found)]


def rules_tripped(source: str) -> list[str]:
    return [rule for _, rule, _ in findings(source)]


def _scanned_files() -> list[Path]:
    files: list[Path] = []
    for directory, subdirectories, names in os.walk(SRC):
        subdirectories[:] = sorted(
            d for d in subdirectories if d not in SKIPPED_DIRECTORIES
        )
        files.extend(
            Path(directory) / n for n in sorted(names) if n.endswith(SCANNED_SUFFIXES)
        )
    return files


def _rel(path: Path) -> str:
    return path.relative_to(SRC).as_posix()


def _census(rules: tuple[str, ...], *, skip: frozenset[str] = frozenset()):
    counts: Counter = Counter()
    where: dict[tuple[str, str, str], list[int]] = {}
    for path in _scanned_files():
        relative = _rel(path)
        if relative in skip:
            continue
        for line, rule, match in findings(path.read_text(encoding="utf-8")):
            if rule in rules:
                key = (relative, rule, match)
                counts[key] += 1
                where.setdefault(key, []).append(line)
    return counts, where


def _against(allowed: dict, observed: Counter, where: dict) -> list[str]:
    problems = []
    for key, n in sorted(observed.items()):
        allowed_n = allowed.get(key, (0, ""))[0]
        if n > allowed_n:
            lines = ", ".join(str(x) for x in where[key])
            problems.append(
                f"{key[0]}:{lines}: {key[1]} {key[2]} x{n} (allowed x{allowed_n})"
            )
    for key, (allowed_n, _) in sorted(allowed.items()):
        if (found := observed.get(key, 0)) < allowed_n:
            problems.append(
                f"{key[0]}: {key[1]} {key[2]} allowed x{allowed_n}, found x{found}"
                " - shrink the allow-list entry"
            )
    return problems


# ---------------------------------------------------------------------------
# The scanner, tested against sources that must trip it
# ---------------------------------------------------------------------------

_TRIPS = [
    # --- percentages -------------------------------------------------------
    (
        # The line this file exists for, verbatim from the report page.
        "the-old-report-drawdown",
        '<Figure value={report.portfolio.drawdown_pct} suffix="%" />',
        ["pct-literal"],
    ),
    ("suffix-in-braces", '<Figure value={x} suffix={"%"} />', ["pct-literal"]),
    ("concatenated", 'const label = value.toFixed(2) + "%";', ["pct-literal"]),
    ("jsx-after-expression", "<dd>{metrics.cagr}%</dd>", ["pct-after-expression"]),
    (
        "jsx-after-expression-spaced",
        "<dd>\n  {metrics.cagr} %\n</dd>",
        ["pct-after-expression"],
    ),
    (
        "hand-rolled-formatter",
        "const pct = (v: number) => `${(v * 100).toFixed(2)}%`;",
        ["pct-times-100", "pct-after-expression"],
    ),
    ("scaled-in-jsx", "<dd>{(dd * 100).toFixed(1)}</dd>", ["pct-times-100"]),
    ("scaled-the-other-way", "const shown = 100 * fraction;", ["pct-times-100"]),
    ("jsx-text-on-its-own-line", "<text>\n  0%\n</text>", ["pct-text"]),
    ("jsx-text-inline", "<text>-5.12%</text>", ["pct-text"]),
    # --- absences ----------------------------------------------------------
    (
        # MetricsPanel's slippage, verbatim.
        "nullish-zero",
        "value={`${run.cost_model.slippage_bps ?? 0} bps`}",
        ["numeric-fallback"],
    ),
    (
        # MetricsPanel's session count, verbatim.
        "nullish-252",
        "value={`${metrics.periods_per_year ?? 252} sessions/year`}",
        ["numeric-fallback"],
    ),
    ("falsy-zero", "const n = count || 0;", ["numeric-fallback"]),
    ("dash-fallback", 'value={portfolio?.as_of ?? "—"}', ["bare-dash"]),
    ("dash-returned", 'if (!iso) return "—";', ["bare-dash"]),
    ("dash-ternary", 'return value == null ? "—" : fmtUsd(value);', ["bare-dash"]),
    ("dash-expression", '<td>{"—"}</td>', ["bare-dash"]),
    ("en-dash", 'const x = y ?? "–";', ["bare-dash"]),
    ("hyphen-fallback", 'const owner = row.owner || "-";', ["bare-dash"]),
    (
        "dash-text-inline",
        '<span className="text-ink-muted">—</span>',
        ["bare-dash-text"],
    ),
    ("dash-text-own-line", '<p className="m-0">\n  —\n</p>', ["bare-dash-text"]),
    ("hyphen-text-inline", "<td>-</td>", ["bare-dash-text"]),
]

_CLEAN = [
    ("the-formatter-called", "<dd>{fmtPct(metrics.cagr)}</dd>"),
    (
        "prose-percentage",
        'hint="annualising it on 252 understates volatility by about 20%."',
    ),
    ("modulo", "if (seconds % 3600 === 0) return (i % 3 === 0);"),
    ("layout-percentage", '<div className="w-[68%]" style={{ width: "50%" }} />'),
    ("larger-multipliers", "const ms = s * 1000; const big = n * 100_000;"),
    (
        "commented-out",
        '// suffix="%" and x * 100 and ?? 0\n/* return "—"; */ const a = 1;',
    ),
    ("jsx-comment", '{/* was: value ?? 252 and "—" */}'),
    ("url-in-a-string", 'const u = "http://localhost:8000"; // x ?? 0'),
    ("range-separator", "cell: (run) => `${run.start_session} → ${run.end_session}`,"),
    ("prose-dash", 'Not yet. The engine has not finished, or the run failed —{" "}'),
    ("dash-before-an-expression", "<span> — {reason}</span>"),
    ("dash-inside-a-sentence", 'setNote("Stored — picked up on the next pass.");'),
    ("genuine-zero", 'return count === 0 ? "none" : String(count);'),
    (
        "non-numeric-fallbacks",
        'const a = x ?? []; const b = y ?? ""; const c = z ?? null;',
    ),
    (
        "absent-component",
        '{run.metrics.effective_start ?? <Absent kind="not-measured" />}',
    ),
    ("hyphen-as-a-separator", 'const parts = session.split("-"); key.join("-");'),
    ("negative-number", "const worst = Math.min(-1, x);"),
]


@pytest.mark.parametrize(
    ("source", "expected"), [c[1:] for c in _TRIPS], ids=[c[0] for c in _TRIPS]
)
def test_the_scanner_trips_on(source: str, expected: list[str]) -> None:
    assert rules_tripped(source) == expected


@pytest.mark.parametrize("source", [c[1] for c in _CLEAN], ids=[c[0] for c in _CLEAN])
def test_the_scanner_passes(source: str) -> None:
    assert findings(source) == []


def test_findings_carry_the_line_they_were_found_on() -> None:
    source = "const a = 1;\nconst b = 2;\nconst c = x ?? 0;\n"
    assert findings(source) == [(3, "numeric-fallback", "?? 0")]


# ---------------------------------------------------------------------------
# The rules, on the real tree
# ---------------------------------------------------------------------------


def test_the_scan_reads_what_it_is_meant_to_read() -> None:
    relatives = {_rel(p) for p in _scanned_files()}
    expected = {
        FORMATTER,
        "lib/api.ts",
        "app/programme/report/page.tsx",
        "app/portfolio/page.tsx",
        "components/MetricsPanel.tsx",
        "components/Absent.tsx",
    }
    assert expected <= relatives, (
        f"the scan did not read: {sorted(expected - relatives)}"
    )
    assert not any(
        part in SKIPPED_DIRECTORIES for p in relatives for part in p.split("/")
    )


def test_the_formatter_is_where_percentages_are_built() -> None:
    """
    Guards the exemption. If ``fmtPct`` moved out of ``lib/format.ts`` the
    exemption would cover nothing, and the file that gained it would be
    reported as a violation below — which is right, but this says why.
    """
    source = (SRC / FORMATTER).read_text(encoding="utf-8")
    assert "export const fmtPct" in source
    assert "pct-times-100" in rules_tripped(source), (
        "fmtPct no longer scales by 100 — every percentage on the site would be "
        "a raw fraction with a % after it"
    )


def test_no_percentage_is_built_outside_the_formatter() -> None:
    observed, where = _census(PERCENT_RULES, skip=frozenset({FORMATTER}))
    problems = _against(PERCENT_ALLOWED, observed, where)
    assert not problems, (
        "A stored fraction becomes a percentage in one place, fmtPct in "
        "web/src/lib/format.ts. Pass it the fraction; do not append '%' or "
        "multiply by 100 by hand:\n" + "\n".join(problems)
    )


def test_no_absent_value_is_rendered_as_a_zero_or_a_dash() -> None:
    observed, where = _census(ABSENCE_RULES)
    problems = _against(ABSENCE_ALLOWED, observed, where)
    assert not problems, (
        "An absent value says why (owner decision, 2026-09-26): render "
        '<Absent kind="not-measured" | "no-data" | "missing" /> from '
        "web/src/components/Absent.tsx, never a number fallback or a bare "
        "dash. A genuine zero stays a zero:\n" + "\n".join(problems)
    )


def test_the_absence_vocabulary_is_the_approved_one() -> None:
    """
    The three words are the owner's decision, not a style choice, so changing
    one is a decision too: it has to change here as well.
    """
    source = (SRC / FORMATTER).read_text(encoding="utf-8")
    block = re.search(
        r"ABSENCE_WORDS: Record<AbsenceKind, string> = \{(.*?)\n\};", source, re.S
    )
    assert block, "ABSENCE_WORDS is no longer declared in lib/format.ts"
    words = dict(
        re.findall(
            r'^\s*"?([\w-]+)"?:\s*"([^"]+)",', blank_comments(block.group(1)), re.M
        )
    )
    assert words == {
        "not-measured": "not measured",
        "no-data": "no data",
        "missing": "missing",
    }


# ---------------------------------------------------------------------------
# The hypothesis card's required fields
# ---------------------------------------------------------------------------

HYPOTHESIS_PAGE = SRC / "app" / "programme" / "hypotheses" / "[ref]" / "page.tsx"


def _card_fields() -> dict[str, bool]:
    source = blank_comments(HYPOTHESIS_PAGE.read_text(encoding="utf-8"))
    return {
        key: flag == "true"
        for key, flag in re.findall(
            r'\[\s*"([a-z_]+)",\s*"[^"]*",\s*(true|false)\s*\]', source
        )
    }


class TestTheCardSaysWhichFieldsAreRequired:
    """
    A missing required field renders "missing" with what it blocks; a missing
    optional one renders the absence word. The page's copy of which is which
    must be the gate's.
    """

    def test_the_parser_found_the_fields(self) -> None:
        # Guards the guard: a parser that finds nothing makes both assertions
        # below compare empty sets and pass.
        assert len(_card_fields()) >= 16, _card_fields()

    def test_the_required_fields_are_the_gates(self) -> None:
        from src.programme.gates import REQUIRED_CARD_FIELDS

        fields = _card_fields()
        required = {key for key, is_required in fields.items() if is_required}
        assert required == set(REQUIRED_CARD_FIELDS), (
            f"marked required but not by the gate: "
            f"{sorted(required - set(REQUIRED_CARD_FIELDS))}; required by the "
            f"gate but not marked: {sorted(set(REQUIRED_CARD_FIELDS) - required)}"
        )

    def test_every_required_field_is_on_the_page(self) -> None:
        from src.programme.gates import REQUIRED_CARD_FIELDS

        assert set(REQUIRED_CARD_FIELDS) <= set(_card_fields())

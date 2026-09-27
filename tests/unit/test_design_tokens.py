"""
test_design_tokens.py
---------------------
The mechanical half of the web design system (web/DESIGN.md §13 (a)).

Three things drift silently in a Tailwind codebase, and none of them fails a
build:

1. A value typed where a token belongs. ``text-[11px]`` renders exactly like
   ``text-xs`` today and stops agreeing with it the day the scale moves. A hex
   in a component renders one theme correctly and the other one wrong.
2. The machine-readable token file drifting from the stylesheet it claims to
   mirror, so that every tool reading ``web/design-tokens.json`` is told a
   palette the browser never paints.
3. A design rule reading as approved when nobody approved it. The contract
   says only the owner approves a rule (web/DESIGN.md §0.1, owner decision
   OD-1), and an agent that marks its own rule APPROVED — or approves it in the
   decision log and forgets the rule itself — has made an INFERRED default look
   like doctrine.

So: no colour literal and no Tailwind arbitrary value appears in ``web/src``
outside the allow-lists below; ``web/design-tokens.json`` is re-derived from
``web/src/app/globals.css`` on every run; and every rule in ``web/DESIGN.md``
has one row in ``web/design/decision-log.md`` with the same status, an APPROVED
one naming who approved it, when, and on what basis.

And one thing the design system itself brought: its documents live in
``web/``, where Tailwind looks for classes, so each is excluded from that scan
by name, or the prose about classes ships as rules nobody uses.

The allow-lists hold exact counts per file, so they can only shrink: a new
occurrence fails, and so does a removed one until its entry is shrunk, which
keeps the list honest about what is left. Everything is read at test time, so
the test judges whatever the tree holds rather than a snapshot of it.

``globals.css`` stays the source of truth (0ec084f:DESIGN.md:6-7, and the
runtime reads only CSS). The JSON is the interchange copy; this file is what
keeps the two equal.

The convention is test_import_boundaries.py's: a scanner that silently finds
nothing passes every test, so each scanner is applied to the real tree *and*,
in this file, to synthetic sources that must trip it, and each real-tree test
first asserts it read the files it is meant to read.

Standard library and pytest only: CI's pytest job installs requirements.txt,
and nothing here needs Node.
"""

from __future__ import annotations

import json
import math
import os
import re
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
SRC = WEB / "src"
GLOBALS = SRC / "app" / "globals.css"
TOKENS = WEB / "design-tokens.json"
MANIFEST = WEB / "examples" / "README.md"
DESIGN = WEB / "DESIGN.md"
#: The decision log, split out of DESIGN.md (its former §12) so the contract an
#: agent reads before every UI change carries rules rather than their history.
#: The two are still held to each other, row for rule.
DECISION_LOG = WEB / "design" / "decision-log.md"

#: ``$extensions`` namespace: reverse-domain notation (DTCG 2025.10 §5.2.3)
#: built from the repository's own remote, github.com/Qcasares/trader.
EXT = "com.github.qcasares.trader"

SKIPPED_DIRECTORIES = frozenset({"node_modules", ".next"})
SCANNED_SUFFIXES = (".ts", ".tsx", ".css")

# ---------------------------------------------------------------------------
# Allow-lists. Key: (path relative to web/src, the class token or literal as
# written). Value: (exact count in that file, why it is tolerated). Every
# entry is debt or a documented library need, never a pattern to copy; the
# rule each one breaks is named in web/DESIGN.md, and the list as a whole is
# D-ALLOW-1 there: recorded debt, awaiting the owner, that only shrinks.
# ---------------------------------------------------------------------------

ARBITRARY_VALUES: dict[tuple[str, str], tuple[int, str]] = {
    # --- product code (DESIGN.md T-1, S-1, L-3) -----------------------------
    ("app/login/page.tsx", "min-h-[70dvh]"): (
        1,
        "login column centring; no viewport-height token",
    ),
    ("app/programme/config/page.tsx", "min-w-[18ch]"): (
        1,
        "key column measure; no ch-width token",
    ),
    ("app/programme/config/page.tsx", "max-w-[40ch]"): (
        1,
        "notes column measure; no ch-width token",
    ),
    ("app/programme/findings/page.tsx", "min-w-[24ch]"): (
        1,
        "close-note input measure; no ch-width token",
    ),
    ("app/programme/page.tsx", "text-[11px]"): (
        1,
        "duplicates text-xs (--t-xs, 11px); delete",
    ),
    ("app/programme/page.tsx", "max-w-[68ch]"): (
        1,
        "prose measure, the .subtitle value (globals.css:448)",
    ),
    ("app/programme/page.tsx", "min-h-[34px]"): (
        1,
        "pipeline stage head, the .pipeline-head value (globals.css:824)",
    ),
    ("app/programme/page.tsx", "tracking-[0.03em]"): (
        1,
        "third caps tracking value; DESIGN.md T-6",
    ),
    ("app/system/page.tsx", "max-w-[36ch]"): (
        1,
        "jobs error cell measure; DESIGN.md E-2",
    ),
    ("components/AppNav.tsx", "tracking-[0.045em]"): (
        1,
        "caps tracking, the .045em legacy value; DESIGN.md T-6",
    ),
    ("components/AppShell.tsx", "md:grid-cols-[13rem_1fr]"): (
        1,
        "the shell's sidebar track (208px)",
    ),
    ("components/SecretField.tsx", "min-w-[16rem]"): (1, "secret input minimum width"),
    # --- vendored shadcn new-york, components/ui (DESIGN.md K-8) ------------
    ("components/ui/alert.tsx", "grid-cols-[0_1fr]"): (1, "vendored; component unused"),
    ("components/ui/alert.tsx", "has-[>svg]:grid-cols-[calc(var(--spacing)*4)_1fr]"): (
        1,
        "vendored; component unused",
    ),
    ("components/ui/badge.tsx", "transition-[color,box-shadow]"): (
        1,
        "vendored transition list",
    ),
    ("components/ui/card.tsx", "grid-rows-[auto_auto]"): (
        1,
        "vendored card header grid",
    ),
    ("components/ui/card.tsx", "has-data-[slot=card-action]:grid-cols-[1fr_auto]"): (
        1,
        "vendored card header grid",
    ),
    ("components/ui/dropdown-menu.tsx", "min-w-[8rem]"): (
        2,
        "vendored; component unused",
    ),
    (
        "components/ui/dropdown-menu.tsx",
        "max-h-(--radix-dropdown-menu-content-available-height)",
    ): (1, "Radix runtime variable"),
    (
        "components/ui/dropdown-menu.tsx",
        "origin-(--radix-dropdown-menu-content-transform-origin)",
    ): (2, "Radix runtime variable"),
    ("components/ui/input.tsx", "transition-[color,box-shadow]"): (
        1,
        "vendored transition list",
    ),
    ("components/ui/select.tsx", "transition-[color,box-shadow]"): (
        1,
        "vendored transition list",
    ),
    ("components/ui/select.tsx", "min-w-[8rem]"): (1, "vendored menu width"),
    ("components/ui/select.tsx", "max-h-(--radix-select-content-available-height)"): (
        1,
        "Radix runtime variable",
    ),
    ("components/ui/select.tsx", "origin-(--radix-select-content-transform-origin)"): (
        1,
        "Radix runtime variable",
    ),
    ("components/ui/select.tsx", "h-[var(--radix-select-trigger-height)]"): (
        1,
        "Radix runtime variable",
    ),
    ("components/ui/select.tsx", "min-w-[var(--radix-select-trigger-width)]"): (
        1,
        "Radix runtime variable",
    ),
    ("components/ui/table.tsx", "[&>[role=checkbox]]:translate-y-[2px]"): (
        2,
        "vendored checkbox nudge",
    ),
    (
        "components/ui/tooltip.tsx",
        "origin-(--radix-tooltip-content-transform-origin)",
    ): (1, "Radix runtime variable; component unused"),
    ("components/ui/tooltip.tsx", "translate-y-[calc(-50%_-_2px)]"): (
        1,
        "vendored arrow; component unused",
    ),
    ("components/ui/tooltip.tsx", "rounded-[2px]"): (
        1,
        "vendored arrow; component unused",
    ),
}

COLOUR_LITERALS: dict[tuple[str, str], tuple[int, str]] = {
    # Empty: the last one, `button.danger`'s white text (globals.css:632 at
    # 0ec084f), went with the legacy button rules it belonged to (K-15).
}

PALETTE_COLOURS: dict[tuple[str, str], tuple[int, str]] = {
    ("components/ui/button.tsx", "text-white"): (
        1,
        "destructive text; DESIGN.md C-9 --blocked-ink",
    ),
    ("components/ui/sheet.tsx", "bg-black/50"): (
        1,
        "sheet overlay; DESIGN.md C-9 --scrim",
    ),
}

#: Tailwind's default shadows compile to hard-coded black alpha. Tolerated in
#: the vendored menus, sheet and controls; refused everywhere else (S-7).
SHADOWS_ALLOWED_UNDER = "components/ui/"

# ---------------------------------------------------------------------------
# The scanner: class tokens from className / headerClassName / cn() / cva()
# ---------------------------------------------------------------------------

_STRING = re.compile(
    r'"((?:[^"\\\n]|\\.)*)"|`((?:[^`\\]|\\.)*)`|\'((?:[^\'\\\n]|\\.)*)\''
)


def _blank_comments(text: str, line_comments: bool = True) -> str:
    """Replace comments with spaces, keeping offsets and newlines.

    ``line_comments`` is off for CSS, which has only ``/* */``.
    """
    out, i, n, quote = list(text), 0, len(text), None
    while i < n:
        c = text[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
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
        elif line_comments and text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            out[i:j] = [" "] * (j - i)
            i = j
            continue
        i += 1
    return "".join(out)


def _balanced(text: str, start: int, open_ch: str, close_ch: str) -> int:
    """Index just past the bracket that closes the one at ``start``."""
    depth, i, quote = 0, start, None
    while i < len(text):
        c = text[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "\"'`":
            quote = c
        elif c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return len(text)


def _literals(segment: str) -> Iterator[str]:
    """String literals in a class expression, minus object keys and comparands."""
    for m in _STRING.finditer(segment):
        s = next(g for g in m.groups() if g is not None)
        if segment[max(0, m.start() - 4) : m.start()].rstrip().endswith(("==", "!=")):
            continue
        prev = segment[: m.start()].rstrip()
        after = segment[m.end() : m.end() + 3].lstrip()
        if (
            after.startswith(":")
            and m.group(1) is not None
            and prev.endswith(("{", ","))
        ):
            continue  # an object key such as "icon-xs": names a variant, not a class
        if m.group(2) is not None:  # template literal: recurse into ${...}
            for inner in re.finditer(r"\$\{([^}]*)\}", s):
                yield from _literals(inner.group(1))
            s = re.sub(r"\$\{[^}]*\}", " ", s)
        if re.search(r"[.!?]\s|\s—\s", s):
            continue  # prose, not a class list
        yield s


def class_tokens(source: str) -> list[str]:
    """Every class token a TS/TSX source passes to the DOM, in order."""
    text = _blank_comments(source)
    text = re.sub(
        r"defaultVariants:\s*\{[^}]*\}", lambda m: " " * len(m.group(0)), text
    )
    spans: list[tuple[int, int]] = []
    for m in re.finditer(r"\b(?:className|headerClassName)\s*=\s*", text):
        j = m.end()
        if j < len(text) and text[j] == '"':
            spans.append((j, text.index('"', j + 1) + 1))
        elif j < len(text) and text[j] == "{":
            spans.append((j, _balanced(text, j, "{", "}")))
    for m in re.finditer(r"\b(?:className|headerClassName)\s*:\s*", text):
        j = m.end()
        if j < len(text) and text[j] in '"`':
            spans.append((j, text.index(text[j], j + 1) + 1))
    for m in re.finditer(r"\b(?:cva|cn)\(", text):
        j = m.end() - 1
        spans.append((j, _balanced(text, j, "(", ")")))
    seen: set[tuple[int, int]] = set()
    tokens: list[str] = []
    for a, b in sorted(spans):
        if (a, b) in seen or any(x <= a and b <= y for x, y in seen):
            continue  # a cn() inside a className={...} span already read
        seen.add((a, b))
        for literal in _literals(text[a:b]):
            tokens.extend(literal.split())
    return tokens


def utility_of(token: str) -> str:
    """The utility after its variants: ``md:hover:bg-panel`` -> ``bg-panel``."""
    depth, last = 0, 0
    for i, c in enumerate(token):
        if c in "[(":
            depth += 1
        elif c in "])":
            depth -= 1
        elif c == ":" and depth == 0:
            last = i + 1
    return token[last:].strip("!")


def is_arbitrary(token: str) -> bool:
    """``min-h-[34px]``, ``[mask-type:x]``, ``max-h-(--v)``; not ``data-[x]:p-2``."""
    utility = utility_of(token)
    return "[" in utility or "(" in utility


_PALETTE = re.compile(
    r"^-?(?:bg|text|border(?:-[xytrblse])?|ring(?:-offset)?|outline|fill|stroke|from|via|to"
    r"|decoration|divide|placeholder|caret|accent|shadow|inset-shadow|drop-shadow)-"
    r"(?:black|white|slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green"
    r"|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)"
    r"(?:-\d{2,3})?(?:/\S+)?$"
)
_SHADOW = re.compile(
    r"^(?:shadow|inset-shadow|drop-shadow)(?:-(?:2xs|xs|sm|md|lg|xl|2xl|none|inner))?$"
)


def is_palette_colour(token: str) -> bool:
    return bool(_PALETTE.match(utility_of(token)))


def is_shadow(token: str) -> bool:
    return bool(_SHADOW.match(utility_of(token)))


_COLOUR_LITERAL = re.compile(
    r"(?<![&\w#])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![\w-])"
    r"|\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\("
)

#: The blocks of globals.css that declare tokens: every top-level ``:root``
#: block, and the light-scheme block. A second top-level ``:root`` is read as
#: a token block too, so moving a declaration into one neither hides it from
#: the mirror nor makes its colour read as a stray literal.
_ROOT_BLOCK = r"^:root \{"
_LIGHT_BLOCK = r"^@media \(prefers-color-scheme: light\) \{"


def _block_spans(css: str, pattern: str) -> list[tuple[int, int]]:
    """(start, end) offsets of every brace block opened on a line matching it."""
    spans = []
    for m in re.finditer(pattern, css, re.M):
        start = m.end() - 1
        spans.append((m.start(), _balanced(css, start, "{", "}")))
    return spans


def _token_block_lines(css: str) -> set[int]:
    """Line numbers (1-based) inside the token blocks."""
    inside: set[int] = set()
    for pattern in (_ROOT_BLOCK, _LIGHT_BLOCK):
        for a, b in _block_spans(css, pattern):
            first = css.count("\n", 0, a) + 1
            last = css.count("\n", 0, b) + 1
            inside.update(range(first, last + 1))
    return inside


def colour_literals(relative: str, source: str) -> list[str]:
    """Colour literals in a source file; in CSS, outside the token blocks."""
    is_css = relative.endswith(".css")
    text = _blank_comments(source, line_comments=not is_css)
    skip = _token_block_lines(text) if is_css else set()
    found = []
    for n, line in enumerate(text.splitlines(), start=1):
        if n in skip:
            continue
        for m in _COLOUR_LITERAL.finditer(line):
            found.append(m.group(0))
    return found


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


def _census(select) -> Counter:
    counts: Counter = Counter()
    for path in _scanned_files():
        if path.suffix == ".css":
            continue
        for token in class_tokens(path.read_text(encoding="utf-8")):
            if select(token):
                counts[(_rel(path), token)] += 1
    return counts


def _against(allowed: dict, observed: Counter, what: str) -> list[str]:
    problems = []
    for key, n in sorted(observed.items()):
        allowed_n = allowed.get(key, (0, ""))[0]
        if n > allowed_n:
            problems.append(
                f"{key[0]}: {key[1]} x{n} (allowed x{allowed_n}) - a new {what}"
            )
    for key, (allowed_n, _) in sorted(allowed.items()):
        if (found := observed.get(key, 0)) < allowed_n:
            problems.append(
                f"{key[0]}: {key[1]} allowed x{allowed_n}, found x{found}"
                " - shrink the allow-list entry"
            )
    return problems


# ---------------------------------------------------------------------------
# The scanner, tested against sources that must trip it
# ---------------------------------------------------------------------------

_TRIPS = [
    ("arbitrary-size", '<p className="text-[11px]" />', ["text-[11px]"]),
    ("arbitrary-colour", '<p className="bg-[#0e1116]" />', ["bg-[#0e1116]"]),
    (
        "arbitrary-with-variant",
        '<div className="md:grid-cols-[13rem_1fr]" />',
        ["md:grid-cols-[13rem_1fr]"],
    ),
    (
        "arbitrary-property",
        '<div className="[mask-type:luminance]" />',
        ["[mask-type:luminance]"],
    ),
    (
        "css-variable-shorthand",
        '<div className="max-h-(--my-height)" />',
        ["max-h-(--my-height)"],
    ),
    ("in-cn", 'cn("px-2", open && "min-h-[34px]")', ["min-h-[34px]"]),
    (
        "in-cva-variant",
        'cva("rounded-md", { variants: { size: { sm: "h-[30px]" } } })',
        ["h-[30px]"],
    ),
    (
        "in-template-branch",
        '<p className={`p-2 ${a ? "w-[3px]" : ""}`} />',
        ["w-[3px]"],
    ),
    ("in-header-classname", '{ headerClassName: "w-[120px]" }', ["w-[120px]"]),
    ("important", '<p className="!mt-[7px]" />', ["!mt-[7px]"]),
]

_CLEAN = [
    ("tokens", '<div className="bg-panel text-ink-muted border-line mt-3 gap-2" />'),
    (
        "arbitrary-variants-only",
        '<div className="data-[state=open]:bg-panel-2 has-[>svg]:px-3'
        ' [&>svg]:size-4 aria-[invalid=true]:border-blocked" />',
    ),
    ("prose-is-not-a-class", '<p>{"Showing [200] rows of w-[3px]."}</p>'),
    ("comparison-operand", 'cn(status === "w-[3px]" && "p-2")'),
    ("commented-out", '// <div className="w-[3px]" />\n<div className="p-2" />'),
]


@pytest.mark.parametrize(
    ("source", "expected"), [c[1:] for c in _TRIPS], ids=[c[0] for c in _TRIPS]
)
def test_the_arbitrary_value_scanner_trips_on(source: str, expected: list[str]) -> None:
    assert [t for t in class_tokens(source) if is_arbitrary(t)] == expected


@pytest.mark.parametrize("source", [c[1] for c in _CLEAN], ids=[c[0] for c in _CLEAN])
def test_the_arbitrary_value_scanner_passes(source: str) -> None:
    assert [t for t in class_tokens(source) if is_arbitrary(t)] == []


@pytest.mark.parametrize(
    ("token", "palette", "shadow"),
    [
        ("text-white", True, False),
        ("bg-black/50", True, False),
        ("hover:border-red-500/40", True, False),
        ("bg-panel", False, False),
        ("text-ink-faint", False, False),
        ("bg-accent", False, False),  # shadcn's accent, which is --panel-2 here
        ("border-transparent", False, False),
        ("shadow-xs", False, True),
        ("focus-visible:shadow-lg", False, True),
        ("shadow-mode", False, False),
    ],
)
def test_the_palette_and_shadow_rules(token: str, palette: bool, shadow: bool) -> None:
    assert (is_palette_colour(token), is_shadow(token)) == (palette, shadow)


@pytest.mark.parametrize(
    ("relative", "source", "expected"),
    [
        ("x.tsx", 'const c = { color: "#0e1116" };', ["#0e1116"]),
        ("x.tsx", 'const c = "rgb(1 2 3)";', ["rgb("]),
        ("x.tsx", 'const c = "oklch(0.5 0.1 200)";', ["oklch("]),
        ("x.tsx", "<p>&#10003; done</p>", []),  # an HTML entity, not a colour
        ("x.tsx", '<a href="#content">Skip</a>', []),
        ("x.css", "a { color: #fff; }", ["#fff"]),
        (
            "x.css",
            ".x { background: color-mix(in oklab, var(--a) 10%, transparent); }",
            [],
        ),
        (
            "x.css",
            ":root {\n  --x: oklch(0.5 0.1 200);\n}\n.y { color: hsl(1 2% 3%); }\n",
            ["hsl("],
        ),
        (
            # A second top-level :root is a token block too; the light block's
            # nested, indented :root is inside the light block.
            "x.css",
            ":root {\n  --x: oklch(0.5 0.1 200);\n}\n"
            "@media (prefers-color-scheme: light) {\n  :root {\n"
            "    --x: oklch(0.9 0.1 200);\n  }\n}\n"
            ":root {\n  --y: #0e1116;\n}\n.z { color: #fff; }\n",
            ["#fff"],
        ),
        ("x.css", "/* was #0e1116 */ .z { color: var(--text); }", []),
    ],
)
def test_the_colour_literal_scanner(
    relative: str, source: str, expected: list[str]
) -> None:
    assert colour_literals(relative, source) == expected


# ---------------------------------------------------------------------------
# The rules, on the real tree
# ---------------------------------------------------------------------------

#: A class list written as a literal, found by a regex far simpler than the
#: scanner. Every file this matches must yield class tokens, so a scanner that
#: stops reading ``className``, ``cn()`` or ``cva()`` fails here instead of
#: passing every allow-list with an empty census.
_LITERAL_CLASS_LIST = re.compile(
    r"""\b(?:className|headerClassName)\s*[=:]\s*["`]|\b(?:cva|cn)\(\s*["`]"""
)


def test_the_scan_reads_what_it_is_meant_to_read() -> None:
    relatives = {_rel(p) for p in _scanned_files()}
    expected = {
        "app/globals.css",
        "app/page.tsx",
        "components/AppShell.tsx",
        "components/ui/button.tsx",
        "lib/api.ts",
    }
    assert expected <= relatives, (
        f"the scan did not read: {sorted(expected - relatives)}"
    )
    assert not any(
        part in SKIPPED_DIRECTORIES for p in relatives for part in p.split("/")
    )
    with_literals = [
        path
        for path in _scanned_files()
        if path.suffix != ".css"
        and _LITERAL_CLASS_LIST.search(
            _blank_comments(path.read_text(encoding="utf-8"))
        )
    ]
    assert len(with_literals) >= 20, (
        f"only {len(with_literals)} files write a class list; the cross-check "
        "itself has stopped finding them"
    )
    silent = [
        _rel(path)
        for path in with_literals
        if not class_tokens(path.read_text(encoding="utf-8"))
    ]
    assert not silent, (
        f"these files write class lists the scanner reads nothing from: {silent}"
    )
    assert any("cva(" in path.read_text(encoding="utf-8") for path in with_literals), (
        "no file uses cva() any more; the cva() half of the scanner is untested"
    )


def test_no_tailwind_arbitrary_value_outside_the_allow_list() -> None:
    problems = _against(ARBITRARY_VALUES, _census(is_arbitrary), "arbitrary value")
    assert not problems, (
        "Tailwind arbitrary values must map to a token (web/DESIGN.md T-1, S-1); "
        "a tolerated one is listed with its count:\n" + "\n".join(problems)
    )


def test_no_palette_colour_outside_the_allow_list() -> None:
    problems = _against(PALETTE_COLOURS, _census(is_palette_colour), "palette colour")
    assert not problems, (
        "Colours come from the tokens (bg-panel, text-ink-muted, bg-brand ...), "
        "not from Tailwind's palette (web/DESIGN.md C-1):\n" + "\n".join(problems)
    )


def test_no_colour_literal_outside_the_token_blocks() -> None:
    observed: Counter = Counter()
    for path in _scanned_files():
        for literal in colour_literals(_rel(path), path.read_text(encoding="utf-8")):
            observed[(_rel(path), literal)] += 1
    problems = _against(COLOUR_LITERALS, observed, "colour literal")
    assert not problems, (
        "A colour is declared once, in a token block of globals.css, and used "
        "through its token (web/DESIGN.md C-1):\n" + "\n".join(problems)
    )


def test_no_shadow_utility_outside_components_ui() -> None:
    offenders = sorted(
        k for k in _census(is_shadow) if not k[0].startswith(SHADOWS_ALLOWED_UNDER)
    )
    assert not offenders, (
        "Tailwind's default shadows are hard-coded black alpha; product code "
        f"uses none (web/DESIGN.md S-7): {offenders}"
    )


# ---------------------------------------------------------------------------
# design-tokens.json: valid DTCG 2025.10, and equal to globals.css
# ---------------------------------------------------------------------------

_TYPES = {"color", "dimension", "fontFamily", "duration", "cubicBezier", "number"}

#: What a pasted entry says until someone writes its job. Refused below, so a
#: token cannot land undescribed.
_UNDESCRIBED = "DESCRIBE:"


def _declarations(body: str) -> dict[str, str]:
    return {k: v.strip() for k, v in re.findall(r"(--[a-z0-9-]+)\s*:\s*([^;]+);", body)}


def _css_blocks() -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    css = _blank_comments(GLOBALS.read_text(encoding="utf-8"), line_comments=False)

    def blocks(pattern: str) -> dict[str, str]:
        spans = _block_spans(css, pattern)
        assert spans, f"globals.css no longer has a block matching {pattern!r}"
        merged: dict[str, str] = {}
        for a, b in spans:
            merged.update(_declarations(css[a:b]))
        return merged

    return blocks(_ROOT_BLOCK), blocks(_LIGHT_BLOCK), blocks(r"^@theme inline \{")


def _walk(
    node: dict, path: tuple[str, ...] = (), inherited: str | None = None
) -> Iterator[tuple[tuple[str, ...], dict, str | None]]:
    kind = node.get("$type", inherited)
    for key, child in node.items():
        if key.startswith("$"):
            continue
        assert not re.search(r"[{}.]", key), (
            f"{'.'.join(path + (key,))}: DTCG forbids {{, }} and . in names"
        )
        assert isinstance(child, dict), (
            f"{'.'.join(path + (key,))} is neither a token nor a group"
        )
        if "$value" in child:
            yield path + (key,), child, child.get("$type", kind)
        else:
            yield from _walk(child, path + (key,), kind)


def _tokens() -> dict[str, tuple[dict, str | None]]:
    data = json.loads(TOKENS.read_text(encoding="utf-8"))
    return {".".join(p): (t, kind) for p, t, kind in _walk(data)}


def _css_kind(value: str) -> str | None:
    """The DTCG type a literal CSS value maps to, or None."""
    if re.fullmatch(r"oklch\([\d.]+\s+[\d.]+\s+[\d.]+\)", value):
        return "color"
    if re.fullmatch(r"[\d.]+(?:px|rem)", value):
        return "dimension"
    if re.fullmatch(r"[\d.]+(?:ms|s)", value):
        return "duration"
    if value.startswith("cubic-bezier("):
        return "cubicBezier"
    if re.fullmatch(r"-?[\d.]+", value):
        return "number"
    if "," in value:
        return "fontFamily"
    return None


def _css_value(kind: str, value: str):
    if kind == "color":
        m = re.fullmatch(r"oklch\(([\d.]+)\s+([\d.]+)\s+([\d.]+)\)", value)
        assert m, f"not an oklch() literal: {value}"
        return [float(x) for x in m.groups()]
    if kind in ("dimension", "duration"):
        m = re.fullmatch(r"([\d.]+)(px|rem|ms|s)", value)
        assert m, f"not a {kind}: {value}"
        return (float(m.group(1)), m.group(2))
    if kind == "fontFamily":
        return [p.strip().strip('"') for p in value.split(",")]
    if kind == "cubicBezier":
        m = re.fullmatch(r"cubic-bezier\(([^)]*)\)", value)
        assert m, f"not a cubic-bezier(): {value}"
        return [float(x) for x in m.group(1).split(",")]
    return float(value)


def _json_value(kind: str, value):
    if kind == "color":
        assert value.get("colorSpace") == "oklch" and value.get("alpha", 1) == 1
        return [float(x) for x in value["components"]]
    if kind in ("dimension", "duration"):
        return (float(value["value"]), value["unit"])
    if kind == "fontFamily":
        return [value] if isinstance(value, str) else list(value)
    if kind == "cubicBezier":
        return [float(x) for x in value]
    return float(value)


def _oklch_hex(lightness: float, chroma: float, hue: float) -> str:
    """OKLCH to clipped sRGB hex, as Chromium paints (CSS Color 4 matrices)."""
    a = chroma * math.cos(math.radians(hue))
    b = chroma * math.sin(math.radians(hue))
    lc, mc, sc = (
        (lightness + 0.3963377774 * a + 0.2158037573 * b) ** 3,
        (lightness - 0.1055613458 * a - 0.0638541728 * b) ** 3,
        (lightness - 0.0894841775 * a - 1.2914855480 * b) ** 3,
    )
    linear = (
        4.0767416621 * lc - 3.3077115913 * mc + 0.2309699292 * sc,
        -1.2684380046 * lc + 2.6097574011 * mc - 0.3413193965 * sc,
        -0.0041960863 * lc - 0.7034186147 * mc + 1.7076147010 * sc,
    )

    def encode(v: float) -> float:
        if v <= 0:
            return 0.0
        return 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055

    return "#" + "".join(f"{round(min(1.0, encode(v)) * 255):02x}" for v in linear)


def _dtcg_value(kind: str, css: str):
    """A literal CSS value as the DTCG ``$value`` this file stores for it."""
    parsed = _css_value(kind, css)
    if kind == "color":
        return {
            "colorSpace": "oklch",
            "components": parsed,
            "alpha": 1,
            "hex": _oklch_hex(*parsed),
        }
    if kind in ("dimension", "duration"):
        return {"value": parsed[0], "unit": parsed[1]}
    return parsed


def _entry_to_paste(prop: str, root: dict[str, str], light: dict[str, str]) -> str:
    """The JSON a custom property newly declared in globals.css needs.

    Values are computed from the stylesheet, hex included, so the only thing
    left to a person is the description — which is why it is a marker the
    validity test refuses rather than a guess.
    """
    declared = root[prop]
    var = re.fullmatch(r"var\((--[a-z0-9-]+)\)", declared)
    kind = None if var else _css_kind(declared)
    if var is None and kind is None:
        return (
            f"  {prop}: {declared} cannot be mirrored: declare it as a literal "
            "(oklch, px/rem, ms/s, cubic-bezier, a number or a font list) or as "
            "var(--another-token), or extend this test"
        )
    entry: dict = {
        "$value": "{<the token that mirrors " + var.group(1) + ">}"
        if var
        else _dtcg_value(kind, declared),
        "$description": f"{_UNDESCRIBED} its job, and the line that states it",
        "$extensions": {EXT: {"css": prop}},
    }
    if kind:
        entry = {"$type": kind, **entry}
    if prop in light and kind and not var:
        entry["$extensions"][EXT]["light"] = _dtcg_value(kind, light[prop])
    body = json.dumps(entry, indent=2).replace("\n", "\n    ")
    group = {
        "color": "color.<surface|ink|accent|signal>",
        "dimension": "rhythm.<space|radius>",
    }.get(kind or "", "<the group for its job>")
    return f"  {prop} -> {group}.{prop[2:]}:\n    {body}"


def test_the_token_file_is_valid_dtcg() -> None:
    tokens = _tokens()
    assert len(tokens) > 40, (
        "the token walk found almost nothing; the scanner is broken"
    )
    for name, (token, kind) in tokens.items():
        assert kind in _TYPES, f"{name}: $type {kind!r} is not one this file uses"
        assert not str(token.get("$description", "")).startswith(_UNDESCRIBED), (
            f"{name} was pasted from a failure message and never described"
        )
        value = token["$value"]
        for key in token.get("$extensions", {}):
            assert "." in key, (
                f"{name}: $extensions key {key!r} is not reverse-domain notation"
            )
        if isinstance(value, str):
            m = re.fullmatch(r"\{([^{}]+)\}", value)
            assert m and m.group(1) in tokens, f"{name}: alias {value} does not resolve"
            assert tokens[m.group(1)][1] == kind, (
                f"{name}: alias to a {tokens[m.group(1)][1]}"
            )
            continue
        if kind == "color":
            assert set(value) <= {"colorSpace", "components", "alpha", "hex"}, name
            assert len(value["components"]) == 3 and 0 <= value.get("alpha", 1) <= 1, (
                name
            )
            assert re.fullmatch(r"#[0-9a-f]{6}", value["hex"]), (
                f"{name}: hex {value['hex']}"
            )
        elif kind == "dimension":
            assert value["unit"] in ("px", "rem"), name
        elif kind == "duration":
            assert value["unit"] in ("ms", "s"), name
        elif kind == "cubicBezier":
            assert len(value) == 4 and 0 <= value[0] <= 1 and 0 <= value[2] <= 1, name
        elif kind == "fontFamily":
            assert isinstance(value, (str, list)) and value, name


def test_every_custom_property_is_mirrored_with_its_value() -> None:
    root, light, _ = _css_blocks()
    tokens = _tokens()
    by_property: dict[str, list[tuple[str, dict, str]]] = {}
    for name, (token, kind) in tokens.items():
        prop = token.get("$extensions", {}).get(EXT, {}).get("css")
        if prop and not name.startswith("utility."):
            by_property.setdefault(prop, []).append((name, token, kind))
    missing = sorted(set(root) - set(by_property))
    gone = sorted(set(by_property) - set(root))
    assert not missing and not gone, (
        "design-tokens.json and globals.css declare different custom properties. "
        + (
            "Declared in globals.css, not mirrored — add these to the JSON:\n"
            + "\n".join(_entry_to_paste(p, root, light) for p in missing)
            + "\n"
            if missing
            else ""
        )
        + (f"Mirrored, but no longer declared: {gone}" if gone else "")
    )
    wrong = []
    for prop, entries in sorted(by_property.items()):
        assert len(entries) == 1, f"{prop} is mirrored by {[e[0] for e in entries]}"
        name, token, kind = entries[0]
        declared = root[prop]
        var = re.fullmatch(r"var\((--[a-z0-9-]+)\)", declared)
        if var:
            target = token["$value"][1:-1] if isinstance(token["$value"], str) else None
            if target is None or tokens.get(target, ({}, None))[0].get(
                "$extensions", {}
            ).get(EXT, {}).get("css") != var.group(1):
                wrong.append(f"{name}: should alias the token for {var.group(1)}")
        elif _json_value(kind, token["$value"]) != _css_value(kind, declared):
            wrong.append(f"{name}: json {token['$value']} != css {prop}: {declared}")
        light_json = token["$extensions"][EXT].get("light")
        if (light_json is None) != (prop not in light):
            where = "missing" if light_json is None else "not in globals.css"
            wrong.append(f"{name}: light theme {where}")
        elif light_json is not None and _json_value(kind, light_json) != _css_value(
            kind, light[prop]
        ):
            wrong.append(
                f"{name}: json light {light_json} != css {prop}: {light[prop]}"
            )
    assert not wrong, (
        "design-tokens.json disagrees with globals.css (edit the JSON):\n"
        + "\n".join(wrong)
    )


def test_every_hex_fallback_is_the_clipped_conversion() -> None:
    wrong = []
    for name, (token, kind) in _tokens().items():
        if kind != "color" or isinstance(token["$value"], str):
            continue
        for label, value in (
            ("dark", token["$value"]),
            ("light", token["$extensions"][EXT].get("light")),
        ):
            if value is None:
                continue
            computed = _oklch_hex(*value["components"])
            if value["hex"] != computed:
                wrong.append(f"{name} ({label}): {value['hex']} != {computed}")
    assert not wrong, "hex fallbacks must be computed, not typed:\n" + "\n".join(wrong)


def test_the_tailwind_theme_mapping_is_mirrored() -> None:
    root, _, theme = _css_blocks()
    tokens = _tokens()
    css_to_token = {
        t["$extensions"][EXT]["css"]: n
        for n, (t, _) in tokens.items()
        if not n.startswith("utility.") and EXT in t.get("$extensions", {})
    }
    mirrored = {
        t["$extensions"][EXT]["theme"]: (n, t)
        for n, (t, _) in tokens.items()
        if n.startswith("utility.")
    }

    def to_paste(prop: str) -> str:
        declared = theme[prop]
        var = re.fullmatch(r"var\((--[a-z0-9-]+)\)", declared)
        group, _, rest = prop[2:].partition("-")
        if var:
            target = css_to_token.get(var.group(1), f"<the token for {var.group(1)}>")
            value = "{" + target + "}"
        else:
            value = "<the resolved value>"
        entry = {
            "$value": value,
            "$extensions": {EXT: {"theme": prop, "css": declared}},
        }
        body = json.dumps(entry, indent=2).replace("\n", "\n    ")
        return f"  {prop} -> utility.{group}.{rest}:\n    {body}"

    missing = sorted(set(theme) - set(mirrored))
    gone = sorted(set(mirrored) - set(theme))
    assert not missing and not gone, (
        "design-tokens.json and the @theme block disagree. "
        + (
            "Declared in @theme, not mirrored — add these to the JSON:\n"
            + "\n".join(to_paste(p) for p in missing)
            + "\n"
            if missing
            else ""
        )
        + (f"Mirrored, but no longer declared: {gone}" if gone else "")
    )
    wrong = []
    for prop, (name, token) in sorted(mirrored.items()):
        declared = theme[prop]
        recorded = token["$extensions"][EXT]["css"]
        if recorded != declared:
            wrong.append(f"{name}: records {recorded!r}, globals.css has {declared!r}")
        var = re.fullmatch(r"var\((--[a-z0-9-]+)\)", declared)
        calc = re.fullmatch(r"calc\(var\((--[a-z0-9-]+)\) \* ([\d.]+)\)", declared)
        if var:
            target = token["$value"][1:-1] if isinstance(token["$value"], str) else None
            if target is None or tokens[target][0]["$extensions"][EXT][
                "css"
            ] != var.group(1):
                wrong.append(f"{name}: should alias the token for {var.group(1)}")
        elif calc:
            base, unit = _css_value("dimension", root[calc.group(1)])
            if _json_value("dimension", token["$value"]) != (
                base * float(calc.group(2)),
                unit,
            ):
                wrong.append(f"{name}: {token['$value']} is not {declared}")
        else:
            wrong.append(f"{name}: unrecognised @theme value {declared!r}")
    assert not wrong, "\n".join(wrong)


# ---------------------------------------------------------------------------
# cn() merges every declared font size as a size
# ---------------------------------------------------------------------------

UTILS = SRC / "lib" / "utils.ts"

#: The font sizes tailwind-merge 3's default config recognises: the literal
#: ``base`` in its font-size group, and its ``tshirtUnitRegex`` for the rest.
#: Any other ``text-*`` it reads as a colour, so ``cn("text-body",
#: "text-ink-muted")`` drops the size.
_TW_MERGE_SIZE = re.compile(r"base|(\d+(\.\d+)?)?(xs|sm|md|lg|xl)")


def test_every_declared_font_size_is_one_cn_merges_as_a_size() -> None:
    _, _, theme = _css_blocks()
    sizes = {p[len("--text-") :] for p in theme if re.fullmatch(r"--text-[a-z0-9]+", p)}
    assert "body" in sizes, "the @theme block no longer declares --text-body"
    utils = _blank_comments(UTILS.read_text(encoding="utf-8"))
    extended = re.search(r"\btext:\s*\[([^\]]*)\]", utils)
    registered = set(re.findall(r'"([^"]+)"', extended.group(1))) if extended else set()
    unknown = sorted(s for s in sizes - registered if not _TW_MERGE_SIZE.fullmatch(s))
    assert not unknown, (
        f"tailwind-merge reads text-{{{','.join(unknown)}}} as a colour; add "
        f"{unknown} to the `text` theme scale in web/src/lib/utils.ts"
    )


# ---------------------------------------------------------------------------
# The design system's own files are not stylesheet source (web/DESIGN.md D-TOK-5)
# ---------------------------------------------------------------------------

_SOURCE_NOT = re.compile(r'^@source\s+not\s+"([^"]+)"\s*;', re.M)


def _excluded_from_tailwind(css: str) -> set[Path]:
    """The files under web/ that ``@source not`` takes out of Tailwind's scan."""
    found: set[Path] = set()
    for pattern in _SOURCE_NOT.findall(_blank_comments(css, line_comments=False)):
        target = Path(os.path.normpath(GLOBALS.parent / pattern))
        if target.is_dir():
            found.update(p for p in target.rglob("*") if p.is_file())
        else:
            found.update(target.parent.glob(target.name))
    return found


def test_the_source_exclusion_reader_reads_globs_and_directories() -> None:
    css = '@source not "../../*.md";\n/* @source not "../../src"; */\n'
    assert DESIGN in _excluded_from_tailwind(css)
    assert GLOBALS not in _excluded_from_tailwind(css), "a comment is not a rule"
    assert MANIFEST in _excluded_from_tailwind('@source not "../../examples";')


def test_tailwind_does_not_read_the_design_system_as_source() -> None:
    """Tailwind 4 finds its classes by reading every file under web/ that git
    does not ignore, and owner decision OD-1 put the design system there: a
    quarter of a megabyte of prose about classes. Read as source, it put 29
    rules no component uses into the stylesheet every visitor downloads —
    ``.bg-red-500``, and ``.text-[Npx]`` from the sentence forbidding it. The
    stylesheet names the documents it must not read; this holds the list to
    whatever documents web/ now holds — web/design/ included, where the
    decision log, the notes and the checks moved out of DESIGN.md."""
    documents = {
        p
        for p in WEB.iterdir()
        if p.is_file() and (p.suffix == ".md" or p.name == TOKENS.name)
    } | {
        p
        for folder in ("examples", "design")
        for p in (WEB / folder).rglob("*")
        if p.is_file()
    }
    # Guards the guard: a walk that found none of them would exclude nothing
    # and pass.
    named = {
        DESIGN,
        TOKENS,
        MANIFEST,
        DECISION_LOG,
        WEB / "REFERENCE.md",
        WEB / "CLAUDE.md",
        WEB / "design" / "notes.md",
        WEB / "design" / "checks.md",
    }
    assert named <= documents, f"not found: {sorted(map(str, named - documents))}"
    excluded = _excluded_from_tailwind(GLOBALS.read_text(encoding="utf-8"))
    read = sorted(p.relative_to(WEB).as_posix() for p in documents - excluded)
    assert not read, (
        "Tailwind reads these design documents as stylesheet source; exclude "
        f'them in globals.css with @source not "../../<path>": {read}'
    )


# ---------------------------------------------------------------------------
# The examples manifest (web/DESIGN.md §13 (d))
# ---------------------------------------------------------------------------

STATUSES = ("approved", "shipped — awaiting owner approval", "historical", "rejected")


def test_the_examples_manifest_only_approves_what_an_owner_approved() -> None:
    text = MANIFEST.read_text(encoding="utf-8")
    rows = [
        [c.strip() for c in line.strip().strip("|").split("|")]
        for line in text.splitlines()
        if line.startswith("| E")
    ]
    assert rows, "the manifest table has no example rows (| E1 | ...)"
    header = next(
        [c.strip() for c in line.strip().strip("|").split("|")]
        for line in text.splitlines()
        if line.startswith("| ID")
    )
    col = {
        name: next(i for i, cell in enumerate(header) if cell.startswith(name))
        for name in ("ID", "Status", "Owner", "Approved on", "Files")
    }
    for row in rows:
        example, status = row[col["ID"]], row[col["Status"]].strip("*")
        assert status in STATUSES, f"{example}: status {status!r} not in {STATUSES}"
        if status != "approved":
            continue
        # Only the owner approves. An approved row therefore records who and
        # when, and its files have been copied here: promotion happens after
        # approval, never after generation (the Wavect article).
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", row[col["Approved on"]]), (
            f"{example}: approved with no approval date (YYYY-MM-DD)"
        )
        assert row[col["Owner"]] not in ("", "—", "-"), (
            f"{example}: approved with no owner"
        )
        files = re.findall(r"`([^`]+\.png)`", row[col["Files"]])
        assert files, f"{example}: approved with no files listed"
        for name in files:
            assert (MANIFEST.parent / name).exists(), (
                f"{example}: {name} is not in web/examples/"
            )


# ---------------------------------------------------------------------------
# The decision log (web/design/decision-log.md; web/DESIGN.md §12, §13 (a))
# ---------------------------------------------------------------------------

#: A rule ID: C-1, C-4r, C-8a, H-3s, D-TOK-5, D-ALLOW-1, OD-2, D-PREC.
_RULE_ID = r"(?:[A-Z]+-)+(?:\d+[a-z]?|PREC)"

#: Where a rule is defined. Most are bullets, ``- **C-1** · INFERRED · …``;
#: the Jev rules are a table whose last cell is the status.
_BULLET = re.compile(rf"^\s*- \*\*({_RULE_ID})\*\* · (APPROVED|INFERRED)\b", re.M)
_TABLE_ROW = re.compile(
    rf"^\| \*\*({_RULE_ID})\*\* \|.*\|\s*\**(APPROVED|INFERRED)\b[^|]*\|\s*$", re.M
)

#: What an APPROVED row may rest on: an owner decision, a repo CLAUDE.md rule,
#: or a test. Anything else is an agent approving its own draft. An owner
#: decision's own row rests on where the owner gave it ("owner decision, in
#: session", "owner decision, in review of #52").
_APPROVED_BASIS = re.compile(r"\bOD-\d+\b|CLAUDE\.md|\btest_|::Test")
_OWNER_DECISION_BASIS = "owner decision"


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    end = text.find("\n## ", start + len(heading))
    return text[start : end if end >= 0 else len(text)]


def _cells(line: str) -> list[str]:
    return [c.strip() for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]


def _log_rows(text: str) -> list[dict[str, str]]:
    """The rows of the decision log's table, from ``DECISION_LOG``'s text."""
    log = _section(text, "## The log")
    lines = log.splitlines()
    header_at = next(i for i, line in enumerate(lines) if line.startswith("| ID |"))
    header = _cells(lines[header_at])
    rows = []
    for line in lines[header_at + 2 :]:
        if not line.startswith("|"):
            break
        cells = _cells(line)
        assert len(cells) == len(header), f"malformed decision-log row: {line[:80]}"
        rows.append(dict(zip(header, cells, strict=True)))
    return rows


def _base_status(cell: str) -> str:
    return cell.strip("* ").split()[0].rstrip(",")


def _definitions(text: str) -> dict[str, list[str]]:
    """Every rule ``DESIGN.md`` defines, with the status it gives each."""
    body = text
    found: dict[str, list[str]] = {}
    for rule, status in _BULLET.findall(body):
        found.setdefault(rule, []).append(status)
    for rule, status in _TABLE_ROW.findall(_section(body, "## 10. ")):
        found.setdefault(rule, []).append(status)
    return found


def test_every_rule_has_one_decision_log_row_with_its_status() -> None:
    definitions = _definitions(DESIGN.read_text(encoding="utf-8"))
    rows = _log_rows(DECISION_LOG.read_text(encoding="utf-8"))
    assert len(definitions) > 100 and len(rows) > 100, (
        f"read {len(definitions)} rule definitions and {len(rows)} log rows; the "
        "parser has stopped finding them"
    )
    twice = sorted(r for r, statuses in definitions.items() if len(statuses) > 1)
    assert not twice, f"rules defined more than once: {twice}"
    ids = Counter(row["ID"] for row in rows)
    assert not [i for i, n in ids.items() if n > 1], (
        f"decision-log rows repeated: {[i for i, n in ids.items() if n > 1]}"
    )
    logged = {row["ID"]: _base_status(row["Status"]) for row in rows}
    defined = {rule: statuses[0] for rule, statuses in definitions.items()}
    assert set(defined) == set(logged), (
        f"defined but not logged: {sorted(set(defined) - set(logged))}; "
        f"logged but not defined: {sorted(set(logged) - set(defined))}"
    )
    differ = sorted(
        f"{rule}: {defined[rule]} in DESIGN.md, {logged[rule]} in the decision log"
        for rule in defined
        if defined[rule] != logged[rule]
    )
    assert not differ, (
        "A rule's status changes in both places or not at all (web/DESIGN.md "
        "§12, web/design/decision-log.md):\n" + "\n".join(differ)
    )


def test_only_design_md_defines_a_rule() -> None:
    """
    One definition per rule survives the split. DESIGN.md states each rule with
    its status; the documents beside it — the log, the notes that keep each
    rule's first wording, the checks, the evidence — name rules without
    defining them. A rule restated with a status in one of them would be a
    second definition the test above never compares, free to disagree with the
    first while an agent reads whichever it opened.
    """
    others = [
        DECISION_LOG,
        WEB / "design" / "notes.md",
        WEB / "design" / "checks.md",
        WEB / "REFERENCE.md",
    ]
    defined_elsewhere = {}
    for path in others:
        text = path.read_text(encoding="utf-8")
        rules = {rule for rule, _ in _BULLET.findall(text) + _TABLE_ROW.findall(text)}
        if rules:
            defined_elsewhere[path.relative_to(WEB).as_posix()] = sorted(rules)
    assert not defined_elsewhere, (
        "rules defined with a status outside web/DESIGN.md; cite them by ID "
        f"instead: {defined_elsewhere}"
    )
    # Guards the guard: the notes do carry every rule's first wording, under its
    # ID, so a reader that found nothing there would prove nothing.
    notes = (WEB / "design" / "notes.md").read_text(encoding="utf-8")
    assert len(re.findall(rf"^\s*- \*\*{_RULE_ID}\*\* — ", notes, re.M)) > 100


def test_an_approved_rule_names_who_approved_it_when_and_why() -> None:
    rows = _log_rows(DECISION_LOG.read_text(encoding="utf-8"))
    decisions = {row["ID"] for row in rows if row["ID"].startswith("OD-")}
    assert decisions, "the decision log records no owner decision (OD-n)"
    problems = []
    for row in rows:
        status = _base_status(row["Status"])
        if status not in ("APPROVED", "INFERRED"):
            problems.append(f"{row['ID']}: status {row['Status']!r}")
            continue
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["Date"]):
            problems.append(f"{row['ID']}: date {row['Date']!r} is not YYYY-MM-DD")
        if status == "INFERRED":
            continue
        # Only the owner approves (OD-1). An APPROVED row with no owner, or
        # resting on nothing the owner decided, is a draft that promoted itself.
        if row["Owner"] in ("", "—", "-"):
            problems.append(f"{row['ID']}: APPROVED with no owner")
        if row["ID"].startswith("OD-"):
            if not row["Basis"].startswith(_OWNER_DECISION_BASIS):
                problems.append(
                    f"{row['ID']}: an owner decision rests on {row['Basis']!r}, "
                    f"not on the owner's answer ({_OWNER_DECISION_BASIS!r})"
                )
            continue
        if not _APPROVED_BASIS.search(row["Basis"]):
            problems.append(
                f"{row['ID']}: APPROVED on {row['Basis']!r}, which is neither an "
                "owner decision (OD-n), a repo CLAUDE.md rule nor a test"
            )
        unknown = sorted(set(re.findall(r"\bOD-\d+\b", row["Basis"])) - decisions)
        if unknown:
            problems.append(
                f"{row['ID']}: APPROVED on {unknown}, which the log does not record"
            )
    assert not problems, "\n".join(problems)

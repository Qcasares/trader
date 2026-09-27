"""
test_web_taste.py
-----------------
The owner's decisions of 2026-09-27 (web/DESIGN.md §0.2, OD-5 to OD-8) as the
source of ``web/src`` can keep them or break them.

They were taken when a generic frontend "taste" skill met this contract. The
skill asks for things this system cannot have — perpetual micro-animations,
magnetic buttons, soft shadows, invented "organic" numbers — and for some it
can. The owner chose between them, and a choice is only as good as what holds
it once the session that made it has ended:

(a) *The type is Geist, and it comes from here* (OD-5, T-10). ``layout.tsx``
    puts both ``next/font`` variables on ``<html>``, the tokens lead with them,
    the package is pinned exactly, and nothing asks a third party for a font.
    Take a variable off ``<html>`` and the token that leads with it stops
    resolving: the page does not fall back to the system stack, it falls back
    to the browser's serif, and nothing fails.
(b) *Dense data, airier prose* (OD-8). Body prose is 15px; the table, the
    figures and the metadata keep the steps they had, so only prose grows.
(c) *Nothing loops unless it reports a state* (OD-6, M-1, M-10, M-12). The two
    loops in the stylesheet are each bound to what they report: the live
    pulse to a fresh reading, the skeleton to a load in flight. The pulse
    breathes on its halo and never on the chip, so the word and the glyph
    never dim; every animation has a reduced-motion alternative that is one —
    a fade for the entrance, a still halo for the pulse — rather than the
    0.01ms the global rule would otherwise cut it to.
(d) *A chip pulses only when asked* (M-10r). ``StatusBadge`` writes
    ``data-pulse`` only when given ``pulse``, so ``pulse={false}`` and no prop
    draw the same still chip.
(e) *A pulse reads every freshness* (M-10r). Every ``pulse=`` a page passes
    turns off when the row's own heartbeat is stale, when the page's own
    refresh has failed, *and* when the reading is older than two of the
    page's polls (``useFresh``). A row that said "alive" before the API went
    away is not alive now, and a halo that kept breathing on it would be the
    dead worker that looks alive, the one thing /system exists to prevent. A
    refresh that hangs has not failed, so only the age catches it; and the
    reads themselves time out, which makes a hang a failure too. The daily
    report, a record of its day, passes none.
(f) *A safety control never moves* (M-11, C-12). Every Button in the kill
    switch's card and the live-order gates' card on /system carries ``STILL``,
    and nothing there pulses or staggers.
(g) *Summary pages are an asymmetric grid* (OD-7, L-4): /system, /programme and
    /portfolio use ``summary-grid``, main column first.
(h) *One column until lg* (OD-7): the grid's rule, read from the stylesheet.

And two that came with them: every Button presses and ``STILL`` undoes it
(OD-6, K-8), and the sheet's scrim is a token rather than pure black (C-9).

And what review found once both halves had landed: the status glyphs Geist
Mono does not carry are the ones T-10 records (Q-36); a runner that is not
alive is warned of above /programme's controls (K-7); every table is named
(A-7); a DataTable stops staggering once a row it shows moves, and its rise
cannot scroll the table (M-12); and no side column holds a placeholder
sized for a chart.

And what the second review found: a process that shut down cleanly is not
alive, though its row stays fresh for a minute, and one helper decides it for
every page (G-4); heartbeat tables keep one order whatever the heartbeats'
times, so no poll restarts a halo (M-10r); running prose is 15px on every
intro, every banner and the three summary pages, and never a title's weight
(T-11); every sideways scroller is a focusable, named region (A-7); the
workers table fits its side column; and /programme reads "not read" when it
cannot read its switch, and keeps its heading when it cannot read anything
(G-2, E-13, E-9).

(e), (f) and (g) read pages another change owns. They are written against the
interface both changes were given — the class names, the ``pulse`` prop,
``STILL`` — and fail until those pages use it.

The conventions are ``test_design_tokens.py``'s, whose readers this reuses: a
reader that silently finds nothing passes every test, so each one here is
proved on synthetic sources that must trip it, and each real-tree test first
asserts it read what it is meant to read.

Standard library and pytest only; nothing here needs Node.
"""

from __future__ import annotations

import json
import re
import struct
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from functools import cmp_to_key
from itertools import permutations, product
from pathlib import Path

import pytest

from tests.unit.test_design_tokens import (
    _balanced,
    _blank_comments,
    _tokens,
    class_tokens,
    utility_of,
)
from tests.unit.test_web_components import _component_classes, _split_top, _tag_end

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
SRC = WEB / "src"
APP = SRC / "app"
GLOBALS = APP / "globals.css"
LAYOUT = APP / "layout.tsx"
PACKAGE = WEB / "package.json"
LOCK = WEB / "package-lock.json"
NOTES = WEB / "design" / "notes.md"
UI = SRC / "components" / "ui"
STATUS_BADGE = SRC / "components" / "StatusBadge.tsx"
DATA_TABLE = SRC / "components" / "DataTable.tsx"
MOTION = SRC / "lib" / "motion.ts"
SYSTEM_PAGE = APP / "system" / "page.tsx"
PROGRAMME_PAGE = APP / "programme" / "page.tsx"
PORTFOLIO_PAGE = APP / "portfolio" / "page.tsx"
REPORT_PAGE = APP / "programme" / "report" / "page.tsx"
#: The package's own modules, present only where ``npm ci`` has run in web/.
GEIST_DIST = WEB / "node_modules" / "geist" / "dist"

#: The exact release OD-5 adopted. A range would let a lockfile refresh change
#: the face, its metrics and so every wrap point, with no diff to review.
GEIST_VERSION = "1.7.2"

#: The system stacks the tokens held before OD-5, kept behind the face.
SANS_STACK = [
    "ui-sans-serif",
    "system-ui",
    "-apple-system",
    "Segoe UI",
    "Roboto",
    "sans-serif",
]
MONO_STACK = [
    "ui-monospace",
    "SF Mono",
    "JetBrains Mono",
    "Menlo",
    "Consolas",
    "monospace",
]


# ---------------------------------------------------------------------------
# A stylesheet reader that knows where each rule sits
# ---------------------------------------------------------------------------

_REDUCED = re.compile(r"prefers-reduced-motion\s*:\s*reduce")


@dataclass(frozen=True, eq=False)
class Rule:
    """One style rule, with the at-rules it sits in, outermost first."""

    index: int
    context: tuple[str, ...]
    selectors: tuple[str, ...]
    declarations: dict[str, str]

    @property
    def layer(self) -> str | None:
        return next((c for c in self.context if c.startswith("@layer")), None)

    @property
    def reduced_motion(self) -> bool:
        return any(_REDUCED.search(c) for c in self.context)

    @property
    def in_media(self) -> bool:
        return any(c.startswith("@media") for c in self.context)


@dataclass(frozen=True, eq=False)
class Keyframes:
    name: str
    context: tuple[str, ...]
    #: Each frame selector as written (``from``, ``50%``) with what it sets.
    frames: dict[str, dict[str, str]]

    @property
    def reduced_motion(self) -> bool:
        return any(_REDUCED.search(c) for c in self.context)


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _declarations(body: str) -> dict[str, str]:
    """Property to value, as written, ``!important`` kept."""
    found = {}
    for part in _split_top(body, ";"):
        if ":" in part:
            prop, _, value = part.partition(":")
            found[prop.strip().lower()] = _one_line(value)
    return found


def read_css(css: str) -> tuple[list[Rule], list[Keyframes]]:
    """Every style rule and every ``@keyframes`` in a stylesheet, in order."""
    text = _blank_comments(css, line_comments=False)
    rules: list[Rule] = []
    frames: list[Keyframes] = []

    def walk(chunk: str, context: tuple[str, ...]) -> None:
        i = 0
        while (brace := chunk.find("{", i)) >= 0:
            prelude = _one_line(re.split(r"[;}]", chunk[i:brace])[-1])
            end = _balanced(chunk, brace, "{", "}")
            body = chunk[brace + 1 : end - 1]
            if prelude.startswith("@keyframes"):
                steps: dict[str, dict[str, str]] = {}
                for inner in read_css(body)[0]:
                    for selector in inner.selectors:
                        steps[selector] = inner.declarations
                frames.append(Keyframes(prelude.split()[1], context, steps))
            elif prelude.startswith("@"):
                walk(body, (*context, prelude))
            else:
                selectors = tuple(_one_line(s) for s in _split_top(prelude))
                rules.append(Rule(len(rules), context, selectors, _declarations(body)))
            i = end

    walk(text, ())
    return rules, frames


def root_tokens(rules: list[Rule]) -> dict[str, str]:
    """The unconditional custom properties: every top-level ``:root`` block."""
    tokens: dict[str, str] = {}
    for rule in rules:
        if rule.selectors == (":root",) and not rule.context:
            tokens.update({k: v for k, v in rule.declarations.items() if k[:2] == "--"})
    return tokens


def light_tokens(rules: list[Rule]) -> dict[str, str]:
    tokens = dict(root_tokens(rules))
    for rule in rules:
        if rule.selectors == (":root",) and any(
            "prefers-color-scheme: light" in c for c in rule.context
        ):
            tokens.update({k: v for k, v in rule.declarations.items() if k[:2] == "--"})
    return tokens


def resolve(value: str, tokens: dict[str, str]) -> str:
    """``var(--x)`` replaced by the token's value, as often as it nests."""
    for _ in range(10):
        new = re.sub(
            r"var\((--[\w-]+)\)", lambda m: tokens.get(m.group(1), m.group(0)), value
        )
        if new == value:
            break
        value = new
    return value


def to_ms(value: str) -> float | None:
    """A resolved time as milliseconds: ``200ms``, ``1.4s``, ``calc(40ms * 3)``."""
    v = value.strip()
    if m := re.fullmatch(r"(-?\d*\.?\d+)(ms|s)", v):
        return float(m.group(1)) * (1000 if m.group(2) == "s" else 1)
    if m := re.fullmatch(r"calc\(\s*(.+?)\s*\*\s*(\d*\.?\d+)\s*\)", v):
        base = to_ms(m.group(1))
        return None if base is None else base * float(m.group(2))
    return None


def to_px(value: str) -> float | None:
    if m := re.fullmatch(r"(\d*\.?\d+)(px|rem)", value.strip()):
        return float(m.group(1)) * (16 if m.group(2) == "rem" else 1)
    return None


_EASING = re.compile(
    r"^(?:ease|ease-in|ease-out|ease-in-out|linear|step-start|step-end)$"
    r"|^(?:cubic-bezier|steps|linear)\("
)
_KEYWORDS = {
    "fill": {"none", "forwards", "backwards", "both"},
    "direction": {"normal", "reverse", "alternate", "alternate-reverse"},
    "play": {"running", "paused"},
}


@dataclass(frozen=True)
class Animation:
    name: str
    duration_ms: float | None
    delay_ms: float
    timing: str | None
    iterations: str
    fill: str
    important: bool


def _strip_important(value: str) -> tuple[str, bool]:
    if value.endswith("!important"):
        return value[: -len("!important")].strip(), True
    return value, False


def animation_of(
    declarations: dict[str, str], tokens: dict[str, str]
) -> Animation | None:
    """The animation a rule sets, its shorthand then its longhands; None if none."""
    props = {k: v for k, v in declarations.items() if k.startswith("animation")}
    if not props:
        return None
    name, timing, iterations, fill = "none", None, "1", "none"
    duration: float | None = 0.0
    delay, important = 0.0, False
    if "animation" in props:
        value, important = _strip_important(props["animation"])
        assert len(_split_top(value, ",")) == 1, (
            f"one animation per rule is all this reader reads: {value}"
        )
        words = _split_top(resolve(value, tokens), " ")
        if words == ["none"]:
            words = []
        times = []
        for word in words:
            if (ms := to_ms(word)) is not None:
                times.append(ms)
            elif word == "infinite" or re.fullmatch(r"\d*\.?\d+", word):
                iterations = word
            elif _EASING.match(word):
                timing = word
            elif word in _KEYWORDS["fill"]:
                fill = word
            elif word in _KEYWORDS["direction"] | _KEYWORDS["play"]:
                continue
            elif re.fullmatch(r"-?[A-Za-z_][\w-]*", word):
                name = word
        duration = times[0] if times else 0.0
        delay = times[1] if len(times) > 1 else 0.0
    for prop, raw in props.items():
        value, strong = _strip_important(raw)
        value = resolve(value, tokens)
        important = important or (
            strong and prop in ("animation-name", "animation-duration")
        )
        if prop == "animation-name":
            name = value
        elif prop == "animation-duration":
            duration = to_ms(value)
        elif prop == "animation-delay":
            delay = to_ms(value) or 0.0
        elif prop == "animation-iteration-count":
            iterations = value
        elif prop == "animation-timing-function":
            timing = value
        elif prop == "animation-fill-mode":
            fill = value
    return Animation(name, duration, delay, timing, iterations, fill, important)


def split_pseudo(selector: str) -> tuple[str, str]:
    """``('[data-slot="badge"]', '::after')`` from ``[data-slot="badge"]::after``."""
    m = re.search(r"::?(?:after|before)$", selector)
    if not m:
        return selector, ""
    return selector[: m.start()], "::" + m.group(0).lstrip(":")


_LAYER_ORDER = {"@layer theme": 0, "@layer base": 1, "@layer components": 2}


def wins(a: Rule, a_important: bool, b: Rule, b_important: bool) -> bool:
    """Whether ``a``'s declaration beats ``b``'s for the same selector.

    The cascade as it applies here: importance first; then layers, where for
    normal declarations an unlayered rule beats every layer and a later layer
    an earlier one, and for ``!important`` both orders reverse; then, in one
    layer, source order (the selectors compared are the same, so specificity
    ties).
    """
    if a_important != b_important:
        return a_important

    def rank(rule: Rule) -> int:
        layer = rule.layer
        return 99 if layer is None else _LAYER_ORDER.get(layer, 3)

    if rank(a) != rank(b):
        return rank(a) > rank(b) if not a_important else rank(a) < rank(b)
    return a.index > b.index


# --- the reader, proved -------------------------------------------------------


def test_the_stylesheet_reader_knows_where_each_rule_sits() -> None:
    css = """
    @import "tailwindcss";
    :root { --t: 40ms; --e: cubic-bezier(0.16, 1, 0.3, 1); }
    .a { animation: rise calc(var(--t) * 5) var(--e) backwards; }
    @layer base {
      @media (prefers-reduced-motion: reduce) {
        .a { animation: appear var(--t) var(--e) backwards !important; }
        @keyframes appear { from { opacity: 0; } }
      }
    }
    @keyframes rise { from { opacity: 0; transform: translateY(4px); } }
    """
    rules, frames = read_css(css)
    main, alternative = (r for r in rules if r.selectors == (".a",))
    assert (main.layer, main.reduced_motion) == (None, False)
    assert (alternative.layer, alternative.reduced_motion) == ("@layer base", True)
    tokens = root_tokens(rules)
    assert animation_of(main.declarations, tokens) == Animation(
        "rise", 200.0, 0.0, "cubic-bezier(0.16, 1, 0.3, 1)", "1", "backwards", False
    )
    assert animation_of(alternative.declarations, tokens).important
    assert {k.name: k.reduced_motion for k in frames} == {"appear": True, "rise": False}
    assert wins(alternative, True, main, False)


def test_the_reader_reads_the_real_stylesheet() -> None:
    # Guards the guards below: a reader that found no rules would find no loop,
    # no pulse and no grid, and every test would pass on nothing.
    rules, frames = read_css(GLOBALS.read_text(encoding="utf-8"))
    assert len(rules) > 100, f"read {len(rules)} rules"
    assert {"breathe", "rise", "appear", "sweep", "fade", "mark"} <= {
        k.name for k in frames
    }, sorted(k.name for k in frames)
    tokens = root_tokens(rules)
    assert to_ms(resolve("var(--base)", tokens)) == 200.0


# ---------------------------------------------------------------------------
# (a) The type is Geist, and it comes from here (OD-5, T-10)
# ---------------------------------------------------------------------------


def _jsx_attribute(tag: str, name: str) -> str | None:
    """The expression of ``name={…}`` in an opening tag, a string as a JS literal."""
    m = re.search(rf"(?<![\w-]){re.escape(name)}=", tag)
    if not m:
        return None
    j = m.end()
    if tag[j] == "{":
        return tag[j + 1 : _balanced(tag, j, "{", "}") - 1].strip()
    if tag[j] in "\"'":
        return json.dumps(tag[j + 1 : tag.index(tag[j], j + 1)])
    return None


def _opening_tag(text: str, tag: str) -> str:
    m = re.search(rf"<{tag}(?=[\s>/])", text)
    assert m, f"no <{tag}> in the source"
    return text[m.start() : _tag_end(text, m.start())]


def test_the_layout_puts_both_geist_variables_on_html() -> None:
    text = _blank_comments(LAYOUT.read_text(encoding="utf-8"))
    imports = dict(
        re.findall(r'import\s*\{\s*(\w+)\s*\}\s*from\s*"(geist/font/\w+)"', text)
    )
    assert imports == {
        "GeistSans": "geist/font/sans",
        "GeistMono": "geist/font/mono",
    }, (
        "layout.tsx loads Geist and Geist Mono from the geist package (web/DESIGN.md "
        f"OD-5, T-10): {imports}"
    )
    assert len(re.findall(r"<html(?=[\s>])", text)) == 1
    classes = _jsx_attribute(_opening_tag(text, "html"), "className") or ""
    missing = [
        v for v in ("GeistSans.variable", "GeistMono.variable") if v not in classes
    ]
    assert not missing, (
        f"<html> does not carry {missing}. Each defines the custom property that "
        "--sans or --mono leads with; without it the token is invalid and the page "
        "falls back to the browser's serif, not to the system stack"
    )
    assert ".className" not in classes, (
        "`.className` would set the family directly and bypass the tokens every "
        "rule and utility reads; the variables go on <html>, and the tokens carry "
        "the face"
    )


def _families(value: str) -> list[str]:
    return [part.strip().strip('"') for part in _split_top(value, ",")]


def test_the_font_tokens_lead_with_geist_and_keep_the_system_stacks() -> None:
    tokens = root_tokens(read_css(GLOBALS.read_text(encoding="utf-8"))[0])
    assert _families(tokens["--sans"]) == ["var(--font-geist-sans)", *SANS_STACK], (
        tokens["--sans"]
    )
    assert _families(tokens["--mono"]) == ["var(--font-geist-mono)", *MONO_STACK], (
        tokens["--mono"]
    )
    # The interchange copy says the same, so a tool reading it is not told the
    # UI renders the system stack.
    json_tokens = _tokens()
    assert json_tokens["type.family.sans"][0]["$value"][0] == "var(--font-geist-sans)"
    assert json_tokens["type.family.mono"][0]["$value"][0] == "var(--font-geist-mono)"


@pytest.mark.skipif(
    not GEIST_DIST.exists(), reason="web/node_modules is not installed (npm ci in web/)"
)
def test_the_package_defines_the_variables_the_tokens_read() -> None:
    """The names the tokens lead with are the names the pinned package sets.

    A release that renamed ``--font-geist-sans`` would build, type-check and
    ship a page set in the browser's serif. Read where the package is
    installed; CI's Python job has no node_modules.
    """
    for module, variable in (
        ("sans", "--font-geist-sans"),
        ("mono", "--font-geist-mono"),
    ):
        source = (GEIST_DIST / f"{module}.js").read_text(encoding="utf-8")
        assert 'from "next/font/local"' in source, (
            f"geist/font/{module} no longer loads a local file"
        )
        assert f'variable: "{variable}"' in source, f"geist/font/{module}: {source}"
    installed = json.loads((GEIST_DIST.parent / "package.json").read_text())["version"]
    assert installed == GEIST_VERSION, f"node_modules holds geist {installed}"


def character_map(font: bytes) -> set[int]:
    """The code points an sfnt font (a .ttf or .otf, not a WOFF) draws.

    Read from the ``cmap`` table's format 4 and format 12 subtables, the two a
    Unicode font carries. A code point mapped to glyph 0 is one the font does
    not have — the "missing glyph" box — so it is left out.
    """
    tables = {}
    for i in range(struct.unpack_from(">H", font, 4)[0]):
        tag, _, offset, _ = struct.unpack_from(">4sIII", font, 12 + 16 * i)
        tables[tag] = offset
    cmap = tables[b"cmap"]
    codes: set[int] = set()
    for i in range(struct.unpack_from(">H", font, cmap + 2)[0]):
        at = cmap + struct.unpack_from(">HHI", font, cmap + 4 + 8 * i)[2]
        kind = struct.unpack_from(">H", font, at)[0]
        if kind == 4:
            n = struct.unpack_from(">H", font, at + 6)[0] // 2
            ends = struct.unpack_from(f">{n}H", font, at + 14)
            starts = struct.unpack_from(f">{n}H", font, at + 16 + 2 * n)
            deltas = struct.unpack_from(f">{n}H", font, at + 16 + 4 * n)
            offsets_at = at + 16 + 6 * n
            offsets = struct.unpack_from(f">{n}H", font, offsets_at)
            for k in range(n):
                for code in range(starts[k], ends[k] + 1):
                    if code == 0xFFFF:
                        continue
                    glyph = code
                    if offsets[k]:
                        where = offsets_at + 2 * k + offsets[k] + 2 * (code - starts[k])
                        glyph = struct.unpack_from(">H", font, where)[0]
                        if glyph == 0:
                            continue
                    if (glyph + deltas[k]) & 0xFFFF:
                        codes.add(code)
        elif kind == 12:
            for g in range(struct.unpack_from(">I", font, at + 12)[0]):
                first, last, glyph = struct.unpack_from(">III", font, at + 16 + 12 * g)
                codes.update(c for c in range(first, last + 1) if glyph + c - first)
    return codes


def _a_font(*subtables: bytes) -> bytes:
    """An sfnt holding nothing but a ``cmap`` of the given subtables."""
    records, body = b"", b""
    at = 4 + 8 * len(subtables)
    for sub in subtables:
        records += struct.pack(">HHI", 3, 10, at + len(body))
        body += sub
    cmap = struct.pack(">HH", 0, len(subtables)) + records + body
    directory = struct.pack(">IHHHH", 0x00010000, 1, 16, 0, 0)
    record = struct.pack(">4sIII", b"cmap", 0, 12 + 16, len(cmap))
    return directory + record + cmap


def _format_4(segments: list[tuple[int, int, int, list[int] | None]]) -> bytes:
    """(start, end, delta, glyph ids or None) per segment, 0xFFFF appended."""
    segments = [*segments, (0xFFFF, 0xFFFF, 1, None)]
    n = len(segments)
    glyphs: list[int] = []
    offsets = []
    for k, (start, end, _, ids) in enumerate(segments):
        if ids is None:
            offsets.append(0)
        else:
            # From this offset's own position to its first glyph id.
            offsets.append(2 * (n - k) + 2 * len(glyphs))
            glyphs += ids
    body = struct.pack(f">{n}H", *(s[1] for s in segments)) + b"\0\0"
    body += struct.pack(f">{n}H", *(s[0] for s in segments))
    body += struct.pack(f">{n}H", *((s[2] & 0xFFFF) for s in segments))
    body += struct.pack(f">{n}H", *offsets) + struct.pack(f">{len(glyphs)}H", *glyphs)
    return struct.pack(">HHHHHHH", 4, 14 + len(body), 0, 2 * n, 0, 0, 0) + body


def test_the_character_map_reader() -> None:
    mapped = _a_font(
        _format_4(
            [
                (0x41, 0x43, 0, None),  # A-C, drawn: glyph = code + 0
                (0x2713, 0x2714, 0, [0, 9]),  # ✓ to the missing glyph, ✔ drawn
                (0x25A0, 0x25A0, -0x25A0, None),  # ■ lands on glyph 0: missing
            ]
        )
    )
    assert character_map(mapped) == {0x41, 0x42, 0x43, 0x2714}
    wide = struct.pack(">HHIII", 12, 0, 16 + 24, 0, 2)
    wide += struct.pack(">III", 0x2022, 0x2022, 5)  # •
    wide += struct.pack(">III", 0x1F600, 0x1F601, 0)  # 😀 missing, 😁 drawn
    assert character_map(_a_font(wide)) == {0x2022, 0x1F601}


#: The status glyphs neither Geist face draws, by the chip variant that shows
#: each (web/DESIGN.md T-10, E-12; REFERENCE Q-36). Every machine draws these
#: three from its own fonts, so a chip carrying one is not the same width
#: everywhere, against OD-5's "every OS renders identical glyphs". The list is
#: a recorded exception awaiting the owner, not a choice.
GLYPHS_THE_FACE_LACKS = {"settled": "✓", "blocked": "✕", "stopped": "■"}
GEIST_MONO = GEIST_DIST / "fonts" / "geist-mono" / "GeistMono-Variable.ttf"

_BADGE_GLYPH = re.compile(
    r'\[data-slot="badge"\]\[data-variant="([\w-]+)"\]::before\s*\{\s*'
    r'content:\s*"((?:[^"\\]|\\.)*)"'
)


def badge_glyphs(css: str) -> dict[str, str]:
    """Each chip variant's ``::before`` glyph, with its CSS escape decoded."""
    return {
        variant: re.sub(
            r"\\([0-9A-Fa-f]{1,6}) ?", lambda m: chr(int(m.group(1), 16)), written
        )
        for variant, written in _BADGE_GLYPH.findall(css)
    }


def test_the_badge_glyph_reader() -> None:
    css = "\n".join(
        f'[data-slot="badge"][data-variant="{variant}"]::before {{ content: {glyph}; }}'
        for variant, glyph in (("settled", '"\\2713" / ""'), ("unknown", '"?" / ""'))
    )
    assert badge_glyphs(css) == {"settled": "✓", "unknown": "?"}


def test_the_contract_records_the_glyphs_the_face_lacks() -> None:
    glyphs = badge_glyphs(GLOBALS.read_text(encoding="utf-8"))
    assert len(glyphs) == 6, glyphs
    assert {v: glyphs.get(v) for v in GLYPHS_THE_FACE_LACKS} == GLYPHS_THE_FACE_LACKS
    design = (WEB / "DESIGN.md").read_text(encoding="utf-8")
    t10 = design[design.index("- **T-10**") :].split("\n- **")[0]
    missing = [g for g in GLYPHS_THE_FACE_LACKS.values() if g not in t10]
    assert not missing and "Q-36" in t10, (
        "T-10 names each status glyph the faces do not carry, and the question it "
        f"waits on (Q-36); it does not name {missing}"
    )


@pytest.mark.skipif(
    not GEIST_MONO.exists(), reason="web/node_modules is not installed (npm ci in web/)"
)
def test_the_glyphs_the_face_lacks_are_the_ones_recorded() -> None:
    """What Geist Mono draws of the chips' glyphs, read from the face itself.

    The .ttf the package ships beside the .woff2 the build serves; the two carry
    the same map (889 code points, checked 2026-09-27 by decoding the .woff2).
    A face that gained ✓, or a glyph changed to one it lacks, changes which
    chips measure alike on every machine, and so what T-10 and E-12 promise.
    """
    drawn = character_map(GEIST_MONO.read_bytes())
    assert len(drawn) > 800, f"read {len(drawn)} code points from {GEIST_MONO.name}"
    glyphs = badge_glyphs(GLOBALS.read_text(encoding="utf-8"))
    lacking = {v: g for v, g in glyphs.items() if ord(g) not in drawn}
    assert lacking == GLYPHS_THE_FACE_LACKS, (
        "The status glyphs Geist Mono does not carry are drawn by each OS's own "
        f"fonts; web/DESIGN.md T-10 records {GLYPHS_THE_FACE_LACKS}, the face "
        f"lacks {lacking}"
    )


def test_geist_is_pinned_exactly() -> None:
    manifest = json.loads(PACKAGE.read_text(encoding="utf-8"))
    assert manifest["dependencies"].get("geist") == GEIST_VERSION, (
        "web/package.json pins geist exactly (web/DESIGN.md OD-5): a range lets a "
        f"lockfile refresh change the face and every wrap point, "
        f"{manifest['dependencies'].get('geist')!r}"
    )
    lock = json.loads(LOCK.read_text(encoding="utf-8"))["packages"]
    assert lock[""]["dependencies"]["geist"] == GEIST_VERSION
    entry = lock["node_modules/geist"]
    assert entry["version"] == GEIST_VERSION, entry
    assert entry["resolved"].startswith("https://registry.npmjs.org/geist/-/"), entry
    assert entry["integrity"].startswith("sha512-"), entry


#: Where a page would ask somebody else for a font.
_THIRD_PARTY_FONT = re.compile(
    r"next/font/google|fonts\.googleapis\.com|fonts\.gstatic\.com|use\.typekit\.net"
    r"|fonts\.bunny\.net|@import\s+url\(\s*[\"']?https?:"
)


def test_no_page_asks_a_third_party_for_its_type() -> None:
    files = [
        p
        for p in SRC.rglob("*")
        if p.suffix in (".ts", ".tsx", ".css") and "node_modules" not in p.parts
    ]
    assert LAYOUT in files and GLOBALS in files
    found = [
        f"{p.relative_to(WEB)}: {m.group(0)}"
        for p in files
        for m in _THIRD_PARTY_FONT.finditer(p.read_text(encoding="utf-8"))
    ]
    assert not found, (
        "The type is served from this app's own origin (web/DESIGN.md OD-5): "
        + ", ".join(found)
    )
    css = _blank_comments(GLOBALS.read_text(encoding="utf-8"), line_comments=False)
    assert not re.search(r"@font-face[^}]*url\(\s*[\"']?https?:", css)


@pytest.mark.parametrize(
    "source",
    [
        'import { Inter } from "next/font/google";',
        '@import url("https://fonts.googleapis.com/css2?family=Geist");',
        "src: url(https://fonts.gstatic.com/s/geist.woff2);",
    ],
    ids=["next-font-google", "css-import", "gstatic"],
)
def test_the_third_party_font_scan_trips_on(source: str) -> None:
    assert _THIRD_PARTY_FONT.search(source)


# ---------------------------------------------------------------------------
# (b) Dense data, airier prose (OD-8)
# ---------------------------------------------------------------------------

#: The steps that carry tables, figures and metadata, unchanged by OD-8.
DATA_STEPS = {"--t-xs": "0.6875rem", "--t-sm": "0.75rem", "--t-base": "0.8125rem"}

#: Text the body's growth must not reach, each on the step it keeps: a
#: metric's key and figure, an assumption's term and value, and a hint. The
#: term used to inherit the body size; left so, it would have grown two pixels
#: past the figure it names. A banner is not here: its text is running prose,
#: and grows with the body (T-11, below).
KEPT_SIZES = {
    ".metric dt": "var(--t-xs)",
    ".metric dd": "var(--t-md)",
    ".assumption-row dt": "var(--t-base)",
    ".assumption-row dd": "var(--t-base)",
    ".hint": "var(--t-sm)",
}


def test_body_prose_is_15px_and_the_data_keeps_its_steps() -> None:
    rules = read_css(GLOBALS.read_text(encoding="utf-8"))[0]
    tokens = root_tokens(rules)
    assert to_px(tokens["--t-body"]) == 15, tokens["--t-body"]
    assert {k: tokens[k] for k in DATA_STEPS} == DATA_STEPS
    assert to_px(tokens["--t-md"]) == 16
    sizes = {
        s: r.declarations.get("font-size")
        for r in rules
        if not r.in_media
        for s in r.selectors
        if s in KEPT_SIZES
    }
    assert sizes == KEPT_SIZES, (
        "Tables, figures and metadata keep their steps while body prose goes to "
        f"15px (web/DESIGN.md OD-8); none of these may inherit the body's: {sizes}"
    )


def test_the_table_base_size_stays_the_small_step() -> None:
    table = _component_classes(UI / "table.tsx", "table")
    assert "text-sm" in table, (
        "The shadcn Table sets its cells at text-sm, which is --t-sm (12px) here, "
        f"so a table holds as many rows as it did (OD-8): {table}"
    )
    source = DATA_TABLE.read_text(encoding="utf-8")
    assert '@/components/ui/table"' in source, "DataTable no longer renders the Table"
    larger = [
        t
        for t in class_tokens(source)
        if utility_of(t) in ("text-body", "text-md", "text-lg", "text-xl")
    ]
    assert not larger, f"DataTable sets text larger than the table's: {larger}"


# ---------------------------------------------------------------------------
# (c) Nothing loops unless it reports a state (OD-6, M-1, M-10, M-12)
# ---------------------------------------------------------------------------

PULSE = '[data-slot="badge"][data-pulse="true"]'

#: Every loop the stylesheet may hold, and the state each one reports. Nothing
#: else may loop: "Nothing loops unless it reports real state" (OD-6), because
#: a loop that runs whatever happens makes a dead worker look alive
#: (repo:CLAUDE.md, "A dead worker looks dead"; web/DESIGN.md E-13).
STATE_BOUND_LOOPS = {
    PULSE: "a reading that is fresh: the page passes pulse only then (M-10r)",
    ".skeleton": "a load in flight: the skeleton renders only while one is (M-8)",
}


def loops(css: str) -> list[str]:
    """Every selector that sets an infinite animation, pseudo-element included."""
    rules = read_css(css)[0]
    tokens = root_tokens(rules)
    found = []
    for rule in rules:
        animation = animation_of(rule.declarations, tokens)
        if (
            animation
            and animation.name != "none"
            and animation.iterations == "infinite"
        ):
            found.extend(rule.selectors)
    return found


def unbound_loops(css: str) -> list[str]:
    """Loops that report no state — or that sit on a chip's glyph."""
    found = []
    for selector in loops(css):
        subject, pseudo = split_pseudo(selector)
        if subject not in STATE_BOUND_LOOPS or pseudo == "::before":
            found.append(selector)
    return found


@pytest.mark.parametrize(
    ("css", "expected"),
    [
        (".card { animation: breathe 2s var(--ease) infinite; }", [".card"]),
        (
            ".dot { animation-name: blink; animation-iteration-count: infinite; }",
            [".dot"],
        ),
        ("@media (min-width: 1px) { .x { animation: a 1s infinite; } }", [".x"]),
        (".skeleton, .card { animation: sweep 1s infinite; }", [".card"]),
        (
            '[data-slot="badge"][data-pulse="false"]::after'
            " { animation: a 1s infinite; }",
            ['[data-slot="badge"][data-pulse="false"]::after'],
        ),
        (
            '[data-slot="badge"]::after { animation: a 1s infinite; }',
            ['[data-slot="badge"]::after'],
        ),
        (
            f"{PULSE}::before {{ animation: a 1s infinite; }}",
            [f"{PULSE}::before"],
        ),
        (f"{PULSE}::after {{ animation: breathe 2400ms infinite; }}", []),
        (".skeleton { animation: sweep 1.4s infinite; }", []),
        (".x { animation: rise 200ms both; }", []),
        (".x { animation: none; }", []),
    ],
    ids=[
        "a-card",
        "longhands",
        "in-a-media-query",
        "one-selector-of-two",
        "a-still-chip",
        "every-chip",
        "the-glyph",
        "the-pulse",
        "the-skeleton",
        "runs-once",
        "none",
    ],
)
def test_the_loop_check(css: str, expected: list[str]) -> None:
    assert unbound_loops(css) == expected


def test_nothing_loops_but_what_reports_a_state() -> None:
    css = GLOBALS.read_text(encoding="utf-8")
    found = loops(css)
    # Guards the guard: the two loops the stylesheet does hold are found.
    assert f"{PULSE}::after" in found and ".skeleton" in found, found
    unbound = unbound_loops(css)
    assert not unbound, (
        "Nothing loops unless it reports real state (owner decision OD-6, "
        "web/DESIGN.md M-1, M-3). These loop and report nothing, so they would "
        "keep moving on a page whose system has stopped:\n  " + "\n  ".join(unbound)
    )


#: What a pulse rule may set on the chip itself: enough to let a halo out of
#: its box, and nothing a reader sees on the chip.
CHIP_MAY_SET = frozenset({"position", "overflow"})
#: What the pulse's keyframes may move, on the halo: its strength and its size.
HALO_MAY_ANIMATE = frozenset({"opacity", "transform", "scale"})
#: Never on a pulse: a shadow is elevation (S-7), and a glow is one.
NEVER_ON_A_PULSE = frozenset({"box-shadow", "filter", "text-shadow", "backdrop-filter"})


def pulse_problems(css: str) -> list[str]:
    """Where a pulse rule reaches the chip's word or glyph, or reads a still chip."""
    rules, frames = read_css(css)
    tokens = root_tokens(rules)
    by_name = {k.name: k for k in frames}
    problems, reads_true = [], False
    for rule in rules:
        for selector in rule.selectors:
            if "data-pulse" not in selector:
                continue
            if '[data-pulse="true"]' not in selector:
                problems.append(
                    f"{selector}: reads a data-pulse other than true, so "
                    "pulse={false} would draw something no pulse does not"
                )
                continue
            reads_true = True
            _, pseudo = split_pseudo(selector)
            props = set(rule.declarations)
            if pseudo == "::before":
                problems.append(f"{selector}: reaches the glyph (A-6)")
            elif not pseudo and props - CHIP_MAY_SET:
                problems.append(
                    f"{selector}: sets {sorted(props - CHIP_MAY_SET)} on the chip "
                    "itself, where its word and glyph are (A-2, A-6)"
                )
            if props & NEVER_ON_A_PULSE:
                problems.append(f"{selector}: {sorted(props & NEVER_ON_A_PULSE)} (S-7)")
            animation = animation_of(rule.declarations, tokens)
            if not animation or animation.name == "none":
                continue
            keyframes = by_name.get(animation.name)
            if keyframes is None:
                problems.append(
                    f"{selector}: @keyframes {animation.name} is not defined"
                )
                continue
            moved = {p for frame in keyframes.frames.values() for p in frame}
            allowed = HALO_MAY_ANIMATE - (set() if pseudo == "::after" else {"opacity"})
            if moved - allowed:
                problems.append(
                    f"{selector}: @keyframes {animation.name} moves "
                    f"{sorted(moved - allowed)}; on the halo it may move only "
                    f"{sorted(allowed)}, and never the chip's colour or opacity"
                )
    if not reads_true:
        problems.append('no rule reads data-pulse="true": the pulse draws nothing')
    return problems


_A_PULSE = f"""
{PULSE} {{ position: relative; overflow: visible; }}
{PULSE}::after {{
  content: ""; position: absolute; inset: -3px; border: 1px solid currentColor;
  opacity: 0.4; animation: breathe 2400ms infinite;
}}
@keyframes breathe {{ 0%, 100% {{ opacity: 0.1; }} 50% {{ opacity: 0.6; }} }}
"""


@pytest.mark.parametrize(
    ("css", "problem"),
    [
        (
            f"{PULSE} {{ animation: glow 2s infinite; }}"
            " @keyframes glow { 50% { opacity: .5; } }",
            "on the chip itself",
        ),
        (f"{PULSE} {{ color: var(--muted); }}", "on the chip itself"),
        (f"{PULSE}::before {{ opacity: .5; }}", "reaches the glyph"),
        (
            _A_PULSE + f"{PULSE}::after {{ box-shadow: 0 0 6px currentColor; }}",
            "box-shadow",
        ),
        (
            _A_PULSE + '[data-slot="badge"][data-pulse="false"] { outline: 0; }',
            "other than true",
        ),
        (
            _A_PULSE + '[data-slot="badge"][data-pulse] { position: relative; }',
            "other than true",
        ),
        (
            _A_PULSE.replace("opacity: 0.6", "border-color: red"),
            "moves ['border-color']",
        ),
        (".x { color: red; }", "the pulse draws nothing"),
    ],
    ids=[
        "dims-the-chip",
        "recolours-the-chip",
        "dims-the-glyph",
        "a-shadow",
        "reads-false",
        "reads-any",
        "recolours-the-halo",
        "no-pulse-at-all",
    ],
)
def test_the_pulse_check_trips_on(css: str, problem: str) -> None:
    problems = pulse_problems(css)
    assert any(problem in p for p in problems), problems


def test_the_pulse_check_passes_a_halo() -> None:
    assert pulse_problems(_A_PULSE) == []


def test_the_pulse_breathes_on_its_halo_and_never_dims_the_chip() -> None:
    css = GLOBALS.read_text(encoding="utf-8")
    problems = pulse_problems(css)
    assert not problems, (
        "The live pulse is a halo on the chip's ::after (web/DESIGN.md M-10r): the "
        "word and the glyph keep their colour and opacity in every frame, and "
        "pulse={false} draws what no pulse draws:\n  " + "\n  ".join(problems)
    )
    rules = read_css(css)[0]
    halo = [r for r in rules if f"{PULSE}::after" in r.selectors and not r.in_media]
    assert halo, "no rule draws the pulse's halo"
    ring = halo[0].declarations
    assert "content" in ring and "border" in ring, (
        f"the halo is a ring drawn on the ::after: {ring}"
    )


#: Animations with no reduced-motion alternative yet, each a gap on record.
REDUCED_MOTION_GAPS = {
    ".changed": "the value-changed mark, applied nowhere (REFERENCE Q-17); "
    "web/DESIGN.md M-6 records that it still needs a still alternative",
}


def reduced_motion_problems(css: str) -> list[str]:
    """Animations whose reduced-motion alternative is missing or cannot apply.

    The stylesheet stops every animation under ``prefers-reduced-motion`` with
    a rule that is ``!important`` in ``@layer base``; an alternative is only an
    alternative if it survives that rule, and if it beats the animation it
    replaces.
    """
    rules = read_css(css)[0]
    tokens = root_tokens(rules)
    universal = [
        r
        for r in rules
        if r.reduced_motion
        and "*" in r.selectors
        and "!important" in r.declarations.get("animation-duration", "")
    ]
    problems = []
    for rule in rules:
        animation = animation_of(rule.declarations, tokens)
        if rule.reduced_motion or not animation or animation.name == "none":
            continue
        for selector in rule.selectors:
            if selector in REDUCED_MOTION_GAPS:
                continue
            candidates = [
                r
                for r in rules
                if r.reduced_motion
                and selector in r.selectors
                and animation_of(r.declarations, tokens)
            ]
            if not candidates:
                problems.append(
                    f"{selector}: no prefers-reduced-motion alternative, so the rule "
                    "that stops everything cuts it to 0.01ms: a removal (M-6)"
                )
                continue
            alternative = candidates[-1]
            instead = animation_of(alternative.declarations, tokens)
            if not wins(alternative, instead.important, rule, animation.important):
                problems.append(
                    f"{selector}: its alternative loses the cascade to the animation "
                    "it replaces"
                )
            if instead.name != "none" and any(
                not (instead.important and alternative.layer == u.layer)
                for u in universal
            ):
                problems.append(
                    f"{selector}: its alternative animates, and is not !important in "
                    "the layer of the rule that stops everything, which therefore "
                    "cuts it to 0.01ms"
                )
    return problems


_UNIVERSAL = """
@layer base {
  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after { animation-duration: 0.01ms !important; }
    %s
  }
  .x { animation: rise 200ms both; }
}
%s
"""


@pytest.mark.parametrize(
    ("css", "tripped"),
    [
        (_UNIVERSAL % ("", ""), True),
        (_UNIVERSAL % (".x { animation: appear 200ms; }", ""), True),
        (_UNIVERSAL % (".x { animation: appear 200ms !important; }", ""), False),
        (
            _UNIVERSAL
            % ("", f"{PULSE}::after {{ animation: breathe 2s infinite; }}")
            + f"@media (prefers-reduced-motion: reduce) {{ {PULSE}::after"
            " { animation: none; } }",
            True,  # .x still has none
        ),
        (
            _UNIVERSAL
            % (
                f".x {{ animation: appear 200ms !important; }} {PULSE}::after"
                " { animation: none; }",
                f"{PULSE}::after {{ animation: breathe 2s infinite; }}",
            ),
            True,  # a layered `none` loses to the unlayered pulse
        ),
        (
            _UNIVERSAL % (".x { animation: appear 200ms !important; }", "")
            + f"{PULSE}::after {{ animation: breathe 2s infinite; }}"
            + f"@media (prefers-reduced-motion: reduce) {{ {PULSE}::after"
            " { animation: none; } }",
            False,
        ),
    ],
    ids=[
        "none",
        "cut-to-a-hundredth",
        "an-alternative",
        "one-of-two",
        "a-none-that-loses",
        "both",
    ],
)
def test_the_reduced_motion_check(css: str, tripped: bool) -> None:
    assert bool(reduced_motion_problems(css)) is tripped, reduced_motion_problems(css)


def test_every_animation_has_a_reduced_motion_alternative() -> None:
    problems = reduced_motion_problems(GLOBALS.read_text(encoding="utf-8"))
    assert not problems, (
        "Reduced motion gets an alternative, not a removal (web/DESIGN.md M-6):\n  "
        + "\n  ".join(problems)
    )


def _rule_for(rules: list[Rule], selector: str, *, reduced: bool) -> Rule:
    found = [
        r for r in rules if selector in r.selectors and r.reduced_motion is reduced
    ]
    assert found, f"no {'reduced-motion ' if reduced else ''}rule for {selector}"
    return found[-1]


ENTRANCE = ".enter-stagger > *"


def test_reduced_motion_keeps_the_entrance_as_a_fade_in_place() -> None:
    rules, frames = read_css(GLOBALS.read_text(encoding="utf-8"))
    tokens = root_tokens(rules)
    main = animation_of(_rule_for(rules, ENTRANCE, reduced=False).declarations, tokens)
    still = animation_of(_rule_for(rules, ENTRANCE, reduced=True).declarations, tokens)
    assert still.name != "none", (
        "The entrance keeps its arrival under reduced motion; `animation: none` is "
        "a removal (web/DESIGN.md M-6, M-12)"
    )
    moved = {
        p for k in frames if k.name == still.name for f in k.frames.values() for p in f
    }
    assert moved == {"opacity"}, (
        f"@keyframes {still.name} moves {sorted(moved)}; under reduced motion a row "
        "fades in where it will sit, and nothing travels"
    )
    assert (still.duration_ms, still.delay_ms, still.iterations) == (
        main.duration_ms,
        0.0,
        "1",
    ), still
    # No stagger either: the important shorthand resets every row's delay to 0,
    # which only holds while no delay is itself !important.
    delays = [
        r.declarations["animation-delay"]
        for r in rules
        if "animation-delay" in r.declarations
        and any(s.startswith(".enter-stagger") for s in r.selectors)
    ]
    assert delays and not [d for d in delays if "!important" in d], delays


def test_reduced_motion_holds_the_pulse_as_a_still_halo() -> None:
    rules = read_css(GLOBALS.read_text(encoding="utf-8"))[0]
    tokens = root_tokens(rules)
    main = _rule_for(rules, f"{PULSE}::after", reduced=False)
    still = _rule_for(rules, f"{PULSE}::after", reduced=True)
    assert animation_of(still.declarations, tokens).name == "none", still.declarations
    opacity = still.declarations.get("opacity", main.declarations.get("opacity", "1"))
    assert float(opacity) > 0, (
        "Under reduced motion the halo stays, still (web/DESIGN.md M-10r): the chip "
        f"still says it is live without anything moving. opacity {opacity}"
    )
    assert "content" in main.declarations and "border" in main.declarations


def _nth_matches(expression: str, k: int) -> bool:
    """Whether child ``k`` (1-based) matches ``:nth-child(expression)``."""
    e = expression.replace(" ", "")
    if re.fullmatch(r"\d+", e):
        return k == int(e)
    m = re.fullmatch(r"(-?\d*)n(?:\+(\d+))?", e)
    assert m, f"this reader does not read :nth-child({expression})"
    a = {"": 1, "-": -1}.get(m.group(1), None)
    a = int(m.group(1)) if a is None else a
    b = int(m.group(2) or 0)
    return (k - b) * a >= 0 and (k - b) % a == 0 if a else k == b


def entrance_delays(css: str, children: int = 12) -> list[float]:
    """Each child's delay, in milliseconds, as the cascade gives it."""
    rules = read_css(css)[0]
    tokens = root_tokens(rules)
    base = animation_of(_rule_for(rules, ENTRANCE, reduced=False).declarations, tokens)
    delays = []
    for k in range(1, children + 1):
        delay = base.delay_ms
        for rule in rules:
            if rule.reduced_motion or "animation-delay" not in rule.declarations:
                continue
            for selector in rule.selectors:
                m = re.fullmatch(r"\.enter-stagger > :nth-child\((.+)\)", selector)
                if m and _nth_matches(m.group(1), k):
                    value = resolve(rule.declarations["animation-delay"], tokens)
                    delay = to_ms(value)
        delays.append(delay)
    return delays


def test_the_nth_child_reader() -> None:
    assert [k for k in range(1, 13) if _nth_matches("n + 9", k)] == [9, 10, 11, 12]
    assert [k for k in range(1, 13) if _nth_matches("2", k)] == [2]
    assert [k for k in range(1, 8) if _nth_matches("2n+1", k)] == [1, 3, 5, 7]


def test_the_entrance_staggers_once_and_lets_go() -> None:
    css = GLOBALS.read_text(encoding="utf-8")
    rules, frames = read_css(css)
    tokens = root_tokens(rules)
    step = to_ms(tokens["--stagger-step"])
    assert step == 40, tokens["--stagger-step"]
    rise = animation_of(_rule_for(rules, ENTRANCE, reduced=False).declarations, tokens)
    assert (rise.duration_ms, rise.iterations) == (to_ms(tokens["--base"]), "1"), rise
    assert rise.timing == tokens["--ease"], (
        f"the entrance eases on --ease like everything else (M-2): {rise.timing}"
    )
    keyframes = next(k for k in frames if k.name == rise.name)
    first = keyframes.frames.get("from", keyframes.frames.get("0%"))
    assert first == {"opacity": "0", "transform": "translateY(4px)"}, keyframes.frames
    # A row keeps its own opacity once it has arrived: a last frame held by
    # `forwards` or `both` would pin every row at 1, a disabled control too.
    holds = rise.fill in ("forwards", "both")
    last = {
        p for sel, f in keyframes.frames.items() if sel in ("to", "100%") for p in f
    }
    assert not (holds and "opacity" in last), (rise.fill, keyframes.frames)
    delays = entrance_delays(css)
    assert delays == [min(k, 8) * step for k in range(12)], (
        "Each row starts one --stagger-step after the one before, and none after the "
        f"ninth waits longer than the ninth (web/DESIGN.md M-12): {delays}"
    )
    assert max(delays) + rise.duration_ms <= 520


def durations(css: str) -> list[tuple[str, float]]:
    """(selector, ms) for every transition and every animation that runs once."""
    rules = read_css(css)[0]
    tokens = root_tokens(rules)
    found = []
    for rule in rules:
        for prop in ("transition", "transition-duration"):
            if prop not in rule.declarations:
                continue
            value = _strip_important(resolve(rule.declarations[prop], tokens))[0]
            for item in _split_top(value, ","):
                times = [to_ms(w) for w in _split_top(item, " ")]
                times = [t for t in times if t is not None]
                if times:
                    found.append((rule.selectors[0], times[0]))
        animation = animation_of(rule.declarations, tokens)
        if (
            animation
            and animation.name != "none"
            and animation.iterations != "infinite"
        ):
            found.append((rule.selectors[0], animation.duration_ms or 0.0))
    return found


def test_nothing_that_runs_once_runs_longer_than_250ms() -> None:
    found = durations(GLOBALS.read_text(encoding="utf-8"))
    # Guards the guard: the skip link's transition and the entrance are read.
    assert (".skip-link", 140.0) in found and (ENTRANCE, 200.0) in found, found
    slow = [(s, ms) for s, ms in found if ms > 250]
    assert not slow, (
        "Nothing that runs once runs longer than 250ms; the two loops are the "
        f"exception and are held above (web/DESIGN.md M-1): {slow}"
    )


# ---------------------------------------------------------------------------
# A reader for the few JavaScript expressions these rules turn on
# ---------------------------------------------------------------------------


class _Undefined:
    def __repr__(self) -> str:
        return "undefined"


UNDEFINED = _Undefined()

_JS_TOKEN = re.compile(
    r"\s*(?:(?P<str>\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*')"
    r"|(?P<num>\d+(?:\.\d+)?)"
    r"|(?P<op>===|!==|==|!=|<=|>=|&&|\|\||\?\?|[!?:()<>-])"
    r"|(?P<name>[A-Za-z_$][\w$]*(?:\??\.[A-Za-z_$][\w$]*)*))"
)
_LITERALS = {"true": True, "false": False, "null": None, "undefined": UNDEFINED}


def _alive(row: object) -> bool:
    """``isAlive`` in ``web/src/lib/heartbeat.ts``, as that file's own test
    below reads it: fresh, *and* the stored status says 'alive'."""
    return (
        isinstance(row, dict)
        and not _truthy(row.get("stale"))
        and row.get("status") == "alive"
    )


#: The one function a page may call inside an expression these rules read:
#: the heartbeat helper, which decides liveness so that no page does.
JS_HELPERS = {"isAlive": _alive}


def parse_js(source: str) -> tuple:
    """A JS expression built from names, literals, ``String()``, a call to one
    of ``JS_HELPERS``, ``!``, unary ``-``, ``&&``, ``||``, ``??``, the four
    equalities, the four comparisons and ``?:``, as a tree. Anything else is
    refused with a ``ValueError``: a reader that guessed would prove nothing.
    """
    source, tokens, i = source.strip(), [], 0
    while i < len(source):
        m = _JS_TOKEN.match(source, i)
        if not m or m.end() == i:
            raise ValueError(f"cannot read {source[i:]!r}")
        tokens.append((m.lastgroup, m.group(m.lastgroup)))
        i = m.end()
    at = 0

    def peek() -> tuple[str | None, str | None]:
        return tokens[at] if at < len(tokens) else (None, None)

    def take(value: str | None = None) -> tuple[str, str]:
        nonlocal at
        if at >= len(tokens) or (value is not None and tokens[at][1] != value):
            raise ValueError(f"expected {value!r} in {source!r}")
        at += 1
        return tokens[at - 1]

    def conditional() -> tuple:
        test = binary(0)
        if peek() == ("op", "?"):
            take("?")
            yes = conditional()
            take(":")
            return ("cond", test, yes, conditional())
        return test

    levels = [
        ("??",),
        ("||",),
        ("&&",),
        ("===", "!==", "==", "!="),
        ("<", ">", "<=", ">="),
    ]

    def binary(level: int) -> tuple:
        if level == len(levels):
            return unary()
        left = binary(level + 1)
        while peek()[0] == "op" and peek()[1] in levels[level]:
            op = take()[1]
            left = ("op", op, left, binary(level + 1))
        return left

    def unary() -> tuple:
        if peek() == ("op", "!"):
            take("!")
            return ("not", unary())
        if peek() == ("op", "-"):
            take("-")
            return ("neg", unary())
        kind, value = take()
        if (kind, value) == ("op", "("):
            node = conditional()
            take(")")
            return node
        if kind == "str":
            return ("lit", value[1:-1])
        if kind == "num":
            return ("lit", float(value))
        if kind == "name" and value in _LITERALS:
            return ("lit", _LITERALS[value])
        if kind == "name" and value == "String" and peek() == ("op", "("):
            take("(")
            argument = conditional()
            take(")")
            return ("string", argument)
        if kind == "name" and value in JS_HELPERS and peek() == ("op", "("):
            take("(")
            argument = conditional()
            take(")")
            return ("call", value, argument)
        if kind == "name":
            return ("name", value.replace("?.", "."))
        raise ValueError(f"cannot read {value!r} in {source!r}")

    tree = conditional()
    if at != len(tokens):
        raise ValueError(f"cannot read past {tokens[at][1]!r} in {source!r}")
    return tree


def js_names(tree: tuple) -> set[str]:
    if tree[0] == "name":
        return {tree[1]}
    return {n for part in tree[1:] if isinstance(part, tuple) for n in js_names(part)}


def js_calls(tree: tuple) -> list[tuple[str, tuple]]:
    """(helper, argument) for every helper call in the tree."""
    found = [(tree[1], tree[2])] if tree[0] == "call" else []
    for part in tree[1:]:
        if isinstance(part, tuple):
            found.extend(js_calls(part))
    return found


def _truthy(value: object) -> bool:
    if value is UNDEFINED or value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0 and value == value
    if isinstance(value, str):
        return value != ""
    return True


def _nullish(value: object) -> bool:
    return value is None or value is UNDEFINED


def _strict_equal(a: object, b: object) -> bool:
    if _nullish(a) or _nullish(b):
        return a is b
    return type(a) is type(b) and a == b


def js_string(value: object) -> str:
    if value is UNDEFINED:
        return "undefined"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def evaluate(tree: tuple, env: dict[str, object]) -> object:
    kind = tree[0]
    if kind == "lit":
        return tree[1]
    if kind == "name":
        return env[tree[1]]
    if kind == "not":
        return not _truthy(evaluate(tree[1], env))
    if kind == "neg":
        return -evaluate(tree[1], env)
    if kind == "string":
        return js_string(evaluate(tree[1], env))
    if kind == "call":
        return JS_HELPERS[tree[1]](evaluate(tree[2], env))
    if kind == "cond":
        return evaluate(tree[2] if _truthy(evaluate(tree[1], env)) else tree[3], env)
    op, left = tree[1], evaluate(tree[2], env)
    if op == "&&":
        return evaluate(tree[3], env) if _truthy(left) else left
    if op == "||":
        return left if _truthy(left) else evaluate(tree[3], env)
    if op == "??":
        return evaluate(tree[3], env) if _nullish(left) else left
    right = evaluate(tree[3], env)
    if op in ("<", ">", "<=", ">="):
        # Only what a comparator here compares: two strings, or two numbers.
        if not (
            (isinstance(left, str) and isinstance(right, str))
            or (isinstance(left, (int, float)) and isinstance(right, (int, float)))
        ):
            raise ValueError(f"cannot compare {left!r} {op} {right!r}")
        return {
            "<": left < right,
            ">": left > right,
            "<=": left <= right,
            ">=": left >= right,
        }[op]
    if op in ("==", "!="):
        equal = (_nullish(left) and _nullish(right)) or _strict_equal(left, right)
    else:
        equal = _strict_equal(left, right)
    return equal if op in ("===", "==") else not equal


def rendered_data_attribute(value: object) -> str | None:
    """What React writes for a ``data-*`` attribute given ``value``; None: omitted.

    React omits ``undefined`` and ``null`` and writes a boolean as its word,
    so ``data-pulse={false}`` renders ``data-pulse="false"``.
    """
    return None if _nullish(value) else js_string(value)


@pytest.mark.parametrize(
    ("expression", "env", "expected"),
    [
        ("!worker.stale && !stale", {"worker.stale": False, "stale": False}, True),
        ("!worker.stale && !stale", {"worker.stale": False, "stale": True}, False),
        ("!runner?.stale && fresh", {"runner.stale": None, "fresh": True}, True),
        ("pulse === undefined ? undefined : String(pulse)", {"pulse": False}, "false"),
        ("pulse === undefined ? undefined : String(pulse)", {"pulse": UNDEFINED}, None),
        ("pulse == null ? undefined : pulse", {"pulse": None}, None),
        ("pulse ?? false", {"pulse": UNDEFINED}, "false"),
        ("(a || b) && !c", {"a": False, "b": "x", "c": False}, True),
        ("failure === null", {"failure": UNDEFINED}, "false"),
        (
            "isAlive(worker) && fresh",
            {"worker": {"stale": False, "status": "alive"}, "fresh": True},
            True,
        ),
        (
            "isAlive(worker) && fresh",
            {"worker": {"stale": False, "status": "stopped"}, "fresh": True},
            False,
        ),
        ("isAlive(worker)", {"worker": {"stale": True, "status": "alive"}}, False),
        ("a < b ? -1 : a > b ? 1 : 0", {"a": "w-1", "b": "w-2"}, "-1"),
        ("a < b ? -1 : a > b ? 1 : 0", {"a": "w-2", "b": "w-1"}, "1"),
        ("a < b ? -1 : a > b ? 1 : 0", {"a": "w-1", "b": "w-1"}, "0"),
    ],
)
def test_the_expression_reader(expression: str, env: dict, expected: object) -> None:
    value = evaluate(parse_js(expression), env)
    if isinstance(expected, bool):
        assert _truthy(value) is expected
    else:
        assert rendered_data_attribute(value) == expected


@pytest.mark.parametrize(
    "expression",
    ["a + b", "f(x)", "a ? b", "[a]", "a => b", "a - b", "alive(worker)"],
)
def test_the_expression_reader_refuses_what_it_cannot_read(expression: str) -> None:
    with pytest.raises(ValueError):
        parse_js(expression)


# ---------------------------------------------------------------------------
# (d) A chip pulses only when asked (M-10r)
# ---------------------------------------------------------------------------


def _function(text: str, name: str) -> tuple[int, int, int]:
    """(start, end of its parameters, end of its body) of ``function name(``."""
    m = re.search(rf"\bfunction {re.escape(name)}\s*\(", text)
    assert m, f"no function {name}"
    params_end = _balanced(text, m.end() - 1, "(", ")")
    body = text.index("{", params_end)
    return m.start(), params_end, _balanced(text, body, "{", "}")


def badge_pulse_attribute(source: str) -> tuple[str, list[str]]:
    """StatusBadge's ``data-pulse`` expression, and every other place it reads
    ``pulse``: a class or a variant chosen by it would make ``false`` differ
    from no prop at all."""
    text = _blank_comments(source)
    start, params_end, end = _function(text, "StatusBadge")
    assert re.search(r"\bpulse\?\s*:\s*boolean\b", text[start:params_end]), (
        "StatusBadge takes an optional `pulse?: boolean`"
    )
    body = text[params_end:end]
    badge = re.search(r"<Badge(?=[\s>/])", body)
    assert badge, "StatusBadge no longer renders the Badge"
    tag = body[badge.start() : _tag_end(body, badge.start())]
    expression = _jsx_attribute(tag, "data-pulse")
    assert expression is not None, "the Badge is given no data-pulse"
    at = body.index(expression, badge.start())
    elsewhere = [
        " ".join(body[max(0, m.start() - 30) : m.end() + 30].split())
        for m in re.finditer(r"(?<![\w-])pulse\b", body)
        if not at <= m.start() < at + len(expression)
    ]
    return expression, elsewhere


def rendered_pulse(expression: str) -> dict[str, str | None]:
    tree = parse_js(expression)
    return {
        label: rendered_data_attribute(evaluate(tree, {"pulse": value}))
        for label, value in (("omitted", UNDEFINED), ("true", True), ("false", False))
    }


@pytest.mark.parametrize(
    ("expression", "right"),
    [
        ("pulse === undefined ? undefined : String(pulse)", True),
        ("pulse", True),
        ('pulse == null ? undefined : pulse ? "true" : "false"', True),
        ('pulse ? "true" : undefined', False),
        ("String(pulse)", False),
        ("pulse ?? false", False),
    ],
    ids=[
        "explicit",
        "react-stringifies",
        "nested",
        "false-omitted",
        "always",
        "default",
    ],
)
def test_the_pulse_attribute_reader(expression: str, right: bool) -> None:
    wanted = {"omitted": None, "true": "true", "false": "false"}
    assert (rendered_pulse(expression) == wanted) is right


def test_the_badge_carries_data_pulse_only_when_pulse_is_given() -> None:
    expression, elsewhere = badge_pulse_attribute(
        STATUS_BADGE.read_text(encoding="utf-8")
    )
    assert rendered_pulse(expression) == {
        "omitted": None,
        "true": "true",
        "false": "false",
    }, (
        f'data-pulse={{{expression}}}: given, the chip carries data-pulse="true" or '
        '"false"; omitted, no attribute at all (web/DESIGN.md M-10r)'
    )
    assert not elsewhere, (
        "StatusBadge reads `pulse` somewhere other than data-pulse, so pulse={false} "
        f"could draw something no prop does not: {elsewhere}"
    )


# ---------------------------------------------------------------------------
# (e) A pulse reads every freshness (M-10r)
# ---------------------------------------------------------------------------

#: How a page's freshness is named, and which way round it reads.
STALE_WORDS = re.compile(r"stale|fail|error", re.I)
FRESH_WORDS = re.compile(r"fresh|current|live", re.I)

#: Values an atom may take in the truth table: booleans, and the nullable
#: objects a page keeps its failure in.
_DOMAIN = (False, True, None, UNDEFINED, "x")


def jsx_attributes(source: str, name: str) -> list[tuple[str, str, str]]:
    """(component, opening tag, expression) for every ``name=`` on a component."""
    text = _blank_comments(source)
    found = []
    for m in re.finditer(r"<([A-Z][\w.]*)(?=[\s>/])", text):
        tag = text[m.start() : _tag_end(text, m.start())]
        expression = _jsx_attribute(tag, name)
        if expression is not None:
            found.append((m.group(1), tag, expression))
    return found


def _declared(text: str, name: str) -> bool:
    n = re.escape(name)
    return bool(re.search(rf"\b(?:const|let|var)\s+{n}\b|[{{,(]\s*{n}\s*[,}}:)]", text))


#: The hook that bounds a reading's age (web/src/lib/fresh.ts, M-10r).
AGE_HOOK = "useFresh"
FRESH_MODULE = SRC / "lib" / "fresh.ts"
API_MODULE = SRC / "lib" / "api.ts"


def age_bound(text: str, name: str) -> str | None:
    """The bound ``name`` is declared with when it is ``useFresh(since, bound)``.

    None when ``name`` is not declared from the hook; "" when it is, but not
    with the two arguments the hook takes.
    """
    m = re.search(rf"\b(?:const|let)\s+{re.escape(name)}\s*=\s*{AGE_HOOK}\s*\(", text)
    if not m:
        return None
    end = _balanced(text, m.end() - 1, "(", ")")
    arguments = _split_top(text[m.end() : end - 1], ",")
    return arguments[1] if len(arguments) == 2 else ""


#: What a heartbeat row may hold in the truth table: its own staleness, and its
#: stored status — 'alive' while the process runs, 'stopped' once it has shut
#: down cleanly, and nothing at all from an API that sends none.
_ROW_STALE = (False, True)
_ROW_STATUS = ("alive", "stopped", UNDEFINED)


def _row_of(name: str) -> str | None:
    """The row a dotted name reads a heartbeat field of: ``worker.stale``."""
    head, dot, field = name.partition(".")
    return head if dot and field in ("stale", "status") else None


def page_pulse_problems(source: str) -> list[str]:
    """Where a ``pulse=`` could breathe on a row, or a page, that is not fresh.

    Fresh takes three things, each read by name in the expression (M-10r): the
    row's own heartbeat, alive — fresh *and* saying so, which ``isAlive``
    (``lib/heartbeat.ts``) decides; a page flag its failed refreshes set; and
    the reading's age, bounded by ``useFresh`` in the page's own polls. The
    last is the one a refresh that never comes back leaves standing: it has
    not failed, so every failure flag still reads fresh.

    A row is modelled whole, its staleness and its stored status together. A
    process that shuts down cleanly writes 'stopped' with a fresh last_seen, so
    a halo that read the staleness alone breathed on it for a minute: /system's
    green "stopped", /programme's "alive" (found in review, 2026-09-27).
    """
    text = _blank_comments(source)
    problems = []
    for component, tag, expression in jsx_attributes(source, "pulse"):
        where = f"<{component} pulse={{{expression}}}>"
        try:
            tree = parse_js(expression)
        except ValueError as err:
            problems.append(f"{where}: {err}; keep it a conjunction this can read")
            continue
        names = js_names(tree)
        rows = sorted(
            {row for n in names if (row := _row_of(n))}
            | {arg[1] for _, arg in js_calls(tree) if arg[0] == "name"}
        )
        dotted = {n for n in names if "." in n and _row_of(n) is None}
        pages = sorted(n for n in names if "." not in n and n not in rows)
        others = sorted(dotted)
        aged = {p: bound for p in pages if (bound := age_bound(text, p)) is not None}
        status = (_jsx_attribute(tag, "status") or "").replace("?.", ".")
        found = []
        if not rows:
            found.append("reads no row's own heartbeat (`isAlive(<row>)`)")
        elif component == "StatusBadge" and not [
            r for r in rows if re.search(rf"\b{re.escape(r)}\b", status)
        ]:
            found.append(
                f"reads {rows}, and the chip's own status reads none: {status}"
            )
        if not pages:
            found.append(
                "reads no page freshness, so a page whose refreshes fail breathes"
            )
        elif not aged:
            found.append(
                f"reads no bound on the reading's age (`{AGE_HOOK}`), so a refresh "
                "that never comes back — which has not failed — keeps it breathing"
            )
        elif not [p for p in pages if p not in aged]:
            found.append(
                "reads no failed refresh, so a page whose last refresh failed breathes "
                "until the reading ages out"
            )
        for page, bound in aged.items():
            if "POLL_MS" not in bound or not re.search(r"\bconst\s+POLL_MS\s*=", text):
                found.append(
                    f"`{page}` is bounded by `{bound}`, not in this page's own polls "
                    "(`POLL_MS`)"
                )
        for page in pages:
            if not (STALE_WORDS.search(page) or FRESH_WORDS.search(page)):
                found.append(f"cannot tell whether `{page}` means stale or fresh")
            elif not _declared(text, page):
                found.append(f"`{page}` is declared nowhere in this file")
            elif re.search(rf"\b(?:const|let)\s+{page}\s*=\s*(?:true|false)\b", text):
                found.append(f"`{page}` is a constant")
        if not found:
            breathes, not_current, not_alive = False, [], []
            heartbeats = list(product(_ROW_STALE, _ROW_STATUS))
            for row_values in product(heartbeats, repeat=len(rows)):
                for values in product(_DOMAIN, repeat=len(pages) + len(others)):
                    env: dict[str, object] = dict(
                        zip(pages + others, values, strict=True)
                    )
                    for row, (stale, stored) in zip(rows, row_values, strict=True):
                        env[row] = {"stale": stale, "status": stored}
                        env[f"{row}.stale"] = stale
                        env[f"{row}.status"] = stored
                    if not _truthy(evaluate(tree, env)):
                        continue
                    breathes = True
                    shown = {k: v for k, v in env.items() if "." not in k}
                    if any(
                        _truthy(env[p]) != bool(FRESH_WORDS.search(p)) for p in pages
                    ):
                        not_current.append(shown)
                    elif not all(_alive(env[r]) for r in rows):
                        not_alive.append(shown)
            if not_current:
                found.append(
                    "breathes while the page's reading is not current, e.g. "
                    f"{not_current[0]}"
                )
            if not_alive:
                found.append(
                    "breathes on a row that is not alive — stale, or shut down "
                    "cleanly, which writes 'stopped' with a fresh last_seen — e.g. "
                    f"{not_alive[0]}"
                )
            if not breathes:
                found.append("never breathes")
        problems.extend(f"{where}: {p}" for p in found)
    return problems


_A_WORKERS_PAGE = """
const POLL_MS = 5000;
function Loaded({ reading, failure }: { reading: Reading; failure: Failure | null }) {
  const stale = failure !== null;
  const fresh = useFresh(reading.readAt, 2 * POLL_MS);
  return byWorkerId(status.workers).map((worker) => (
    <StatusBadge status={livenessStatus(worker)} pulse={PULSE}>
      {livenessWord(worker)}
    </StatusBadge>
  ));
}
"""


@pytest.mark.parametrize(
    ("pulse", "problem"),
    [
        ("isAlive(worker) && !stale && fresh", None),
        ("fresh && !stale && isAlive(worker)", None),
        # /system and /programme as they shipped: the row's staleness alone,
        # so a process that shut down cleanly breathed for a minute.
        ("!worker.stale && !stale && fresh", "breathes on a row that is not alive"),
        (
            '!worker.stale && worker.status === "alive" && !stale && fresh',
            None,
        ),
        # The page as it shipped before that: a refresh that never came back
        # had not failed, so `stale` stayed false and the halo breathed on a
        # reading a minute old, with two dozen requests still pending.
        ("isAlive(worker) && !stale", "reads no bound on the reading's age"),
        ("isAlive(worker) && fresh", "reads no failed refresh"),
        ("isAlive(worker)", "reads no page freshness"),
        ("!stale && fresh", "reads no row's own heartbeat"),
        ("true", "reads no row's own heartbeat"),
        (
            "isAlive(worker) || (!stale && fresh)",
            "breathes while the page's reading is not current",
        ),
        (
            "isAlive(worker) && !stale && !fresh",
            "breathes while the page's reading is not current",
        ),
        ("isAlive(job) && !stale && fresh", "the chip's own status reads none"),
        ("isAlive(worker) && !paused && fresh", "cannot tell whether `paused`"),
        ("isAlive(worker) && !stale && fresh && false", "never breathes"),
        ("!isAlive(worker) || stale || !fresh ? false : true", None),
        ("alive(worker) && !stale && fresh", "keep it a conjunction"),
    ],
    ids=[
        "all-three",
        "all-three-reversed",
        "staleness-only",
        "staleness-and-status-inline",
        "a-refresh-that-never-returns",
        "age-only",
        "row-only",
        "page-only",
        "a-constant",
        "either",
        "backwards",
        "another-row",
        "a-name-with-no-direction",
        "never",
        "a-ternary",
        "an-unknown-call",
    ],
)
def test_the_page_pulse_check(pulse: str, problem: str | None) -> None:
    problems = page_pulse_problems(_A_WORKERS_PAGE.replace("PULSE", pulse))
    if problem is None:
        assert problems == []
    else:
        assert problems and problem in problems[0], problems


@pytest.mark.parametrize(
    ("declaration", "problem"),
    [
        ("const fresh = useFresh(readAt, 2 * POLL_MS);", None),
        ("const fresh = useFresh(readAt, 60000);", "not in this page's own polls"),
        ("const fresh = useFresh(readAt);", "not in this page's own polls"),
        ("const fresh = readAt !== null;", "reads no bound on the reading's age"),
    ],
    ids=["in-polls", "a-literal", "no-bound", "not-the-hook"],
)
def test_the_age_bound_is_counted_in_the_pages_polls(
    declaration: str, problem: str | None
) -> None:
    source = _A_WORKERS_PAGE.replace(
        "const fresh = useFresh(reading.readAt, 2 * POLL_MS);", declaration
    ).replace("PULSE", "isAlive(worker) && !stale && fresh")
    problems = page_pulse_problems(source)
    if problem is None:
        assert problems == []
    else:
        assert problems and problem in problems[0], problems


def test_the_page_pulse_check_reads_a_fresh_flag_and_an_error_flag() -> None:
    source = """
    const POLL_MS = 10000;
    const fresh = useFresh(readAt, 2 * POLL_MS);
    <StatusBadge
      status={livenessStatus(runner)}
      pulse={isAlive(runner) && error === null && fresh}
    >
      alive
    </StatusBadge>
    {error}
    """
    assert page_pulse_problems(source) == []
    constant = source.replace(
        "const fresh = useFresh(readAt, 2 * POLL_MS);", "const fresh = true;"
    )
    assert "reads no bound on the reading's age" in page_pulse_problems(constant)[0]
    # /programme's runner as it shipped, through optional chaining.
    shipped = source.replace("isAlive(runner) &&", "!runner?.stale &&")
    assert "breathes on a row that is not alive" in page_pulse_problems(shipped)[0]


def _pages() -> list[Path]:
    return sorted(p for p in APP.rglob("*.tsx") if "node_modules" not in p.parts)


def test_every_pulse_reads_the_row_and_the_page() -> None:
    pages = _pages()
    assert SYSTEM_PAGE in pages and REPORT_PAGE in pages
    problems = [
        f"{p.relative_to(APP)}: {problem}"
        for p in pages
        for problem in page_pulse_problems(p.read_text(encoding="utf-8"))
    ]
    assert not problems, (
        "A chip pulses only while the reading it reports is fresh (web/DESIGN.md "
        "M-10r): the row's own heartbeat, the page's last refresh and the "
        "reading's age, all three. A row that said 'alive' before the page lost "
        "the API is not alive now, whether the refresh failed or never came "
        "back:\n  " + "\n  ".join(problems)
    )


def test_the_worker_heartbeat_pulses_on_system() -> None:
    """Where the owner put the pulse: the worker's heartbeat (OD-6).

    Guards the check above, which a page that passed no pulse at all would pass.
    """
    badges = [
        (tag, _jsx_attribute(tag, "pulse"))
        for component, tag, status in jsx_attributes(
            SYSTEM_PAGE.read_text(encoding="utf-8"), "status"
        )
        if component == "StatusBadge" and status.startswith("livenessStatus(")
    ]
    assert badges, "/system shows no worker heartbeat through livenessStatus"
    still = [" ".join(tag.split()) for tag, pulse in badges if pulse is None]
    assert not still, (
        "The worker heartbeat on /system is the live dot the owner chose (OD-6, "
        f"web/DESIGN.md M-10); these chips take no pulse: {still}"
    )


def test_the_report_passes_no_pulse() -> None:
    source = REPORT_PAGE.read_text(encoding="utf-8")
    assert "livenessStatus(" in source, "the report no longer shows the workers"
    assert not jsx_attributes(source, "pulse"), (
        "The daily report is an artefact of its day, a record rather than a reading "
        "(web/DESIGN.md M-10r): nothing on it is live, so nothing on it breathes"
    )


def test_every_pulsing_page_bounds_its_reading_in_its_own_polls() -> None:
    """Guards the check above on the two pages that pulse: each names the age
    hook, imports it from the one module, and the bound it passes is a
    multiple of the cadence it polls at, so "fresh" means "the next poll has
    not been missed twice", on /system's five seconds and /programme's ten."""
    for page in (SYSTEM_PAGE, PROGRAMME_PAGE):
        text = _blank_comments(page.read_text(encoding="utf-8"))
        assert re.search(rf"import \{{ {AGE_HOOK} \}} from \"@/lib/fresh\"", text), page
        bounds = re.findall(rf"\b{AGE_HOOK}\(([^;]*)\);", text)
        assert bounds == ["readAt, 2 * POLL_MS"], (page.name, bounds)
        assert re.search(r"\bconst POLL_MS = \d+;", text) and re.search(
            r"setInterval\(refresh, POLL_MS\)", text
        ), f"{page.relative_to(APP)} polls at POLL_MS, the cadence its bound counts"


def test_a_late_answer_never_replaces_a_newer_one() -> None:
    """With reads that may take ten seconds and polls every five, refreshes
    overlap and settle in any order. Each outcome applies only if no later one
    has: a read that timed out must not mark stale a page a newer read brought
    up to date, a slow answer must not put an older reading back, and neither
    may undo what a switch just answered — on /system, the kill switch."""
    for page in (SYSTEM_PAGE, PROGRAMME_PAGE):
        text = _blank_comments(page.read_text(encoding="utf-8"))
        start = text.index("const refresh = useCallback(async () => {")
        body = text[start : _balanced(text, text.index("{", start), "{", "}")]
        assert "const turn = ++asked.current;" in body, page.name
        guards = re.findall(
            r"if \(turn < settled\.current\) return;\s*settled\.current = turn;", body
        )
        assert len(guards) == 2, f"{page.name}: success and failure each check turns"
        adopt = text[text.index("const adopt = ") :]
        adopt = adopt[: _balanced(adopt, adopt.index("{"), "{", "}")]
        assert "settled.current = ++asked.current;" in adopt, (
            f"{page.name}: a switch's own answer takes a turn, so a refresh read "
            "before the change cannot land after it"
        )


def test_the_fresh_hook_expires_a_reading_when_it_ages_out() -> None:
    """``useFresh`` sets a timer for the moment the reading expires, looks again
    rather than trusting a timer that fires early, and looks again when a
    hidden tab comes back, since a browser holds a hidden tab's timers."""
    text = _blank_comments(FRESH_MODULE.read_text(encoding="utf-8"))
    assert re.search(
        rf"export function {AGE_HOOK}\(\s*readAt: string \| null \| undefined,"
        r"\s*maxAgeMs: number,?\s*\): boolean",
        text,
    ), "useFresh(readAt, maxAgeMs): boolean"
    for needed in (
        "at + maxAgeMs - Date.now()",
        "setTimeout(check, left)",
        '"visibilitychange"',
        "clearTimeout(timer)",
    ):
        assert needed in text, f"lib/fresh.ts: no `{needed}`"
    assert not re.search(r"\bsetInterval\(", text), (
        "one timer per reading, not a clock that re-renders the page every tick"
    )


def test_a_read_that_never_answers_becomes_a_failure() -> None:
    """A read times out, so a refresh that hangs is a failed refresh: the page
    marks what it would have refreshed stale (E-13), and the pulse stops for
    the same reason as for any other failure. Reads only — an unanswered write
    may still commit, so calling it failed would report the wrong fact."""
    text = _blank_comments(API_MODULE.read_text(encoding="utf-8"))
    timeout = re.search(r"export const READ_TIMEOUT_MS = ([\d_]+);", text)
    assert timeout, "api.ts exports READ_TIMEOUT_MS"
    ms = int(timeout.group(1).replace("_", ""))
    poll = re.search(
        r"\bconst POLL_MS = (\d+);", SYSTEM_PAGE.read_text(encoding="utf-8")
    )
    assert poll and 0 < ms <= 2 * int(poll.group(1)), (
        f"a read that has waited {ms}ms is a failure long before /system's polls "
        "have piled up behind it; no later than two of them"
    )
    start = text.index("async function request<T>(")
    body = text[start : _balanced(text, text.index("{", start), "{", "}")]
    # Writes go straight through, unbounded; only a read is given a timer.
    assert re.search(
        r'const reads = \(init\?\.method \?\? "GET"\)\.toUpperCase\(\) === "GET";'
        r"\s*if \(!reads \|\| init\?\.signal\) return exchange",
        body,
    ), "the timeout is on reads only"
    assert (
        re.search(
            r"setTimeout\(\(\) => \{\s*expired = true;\s*controller\.abort\(\);\s*\}, "
            r"READ_TIMEOUT_MS\)",
            body,
        )
        and "signal: controller.signal" in body
    ), "a read is aborted at READ_TIMEOUT_MS"
    assert re.search(r"finally \{\s*clearTimeout\(timer\);", body), (
        "an answered read clears its timer, so a late timer cannot fail it"
    )
    assert re.search(
        r"if \(!expired\) throw err;[\s\S]{0,300}?new ApiError\(\s*0,", body
    ), (
        "a read that timed out is reported as an ApiError, which every page "
        "already catches and marks stale"
    )


# ---------------------------------------------------------------------------
# (f) A safety control never moves (M-11, C-12)
# ---------------------------------------------------------------------------

#: The cards on /system that hold a safety control (C-12), by their titles.
SAFETY_HEADINGS = {
    "kill switch": re.compile(r"^(?:Trading|Kill switch)\b"),
    "live-order gates": re.compile(r"^Gates on a live order\b"),
}


def jsx_element_end(text: str, start: int) -> int:
    """Index just past the element whose opening tag begins at ``start``."""
    name = re.match(r"<([A-Za-z][\w.]*)", text[start:]).group(1)
    tag_end = _tag_end(text, start)
    if text[start:tag_end].rstrip(">").rstrip().endswith("/"):
        return tag_end
    pattern = re.compile(rf"<(/?){re.escape(name)}(?=[\s>/])")
    depth, i = 1, tag_end
    while depth:
        m = pattern.search(text, i)
        if not m:
            return len(text)
        if m.group(1):
            depth -= 1
            i = text.index(">", m.end()) + 1
        else:
            end = _tag_end(text, m.start())
            depth += not text[m.start() : end].rstrip(">").rstrip().endswith("/")
            i = end
    return i


def jsx_text(fragment: str) -> str:
    """The words of a JSX fragment: tags and ``{…}`` expressions left out."""
    out, i = [], 0
    while i < len(fragment):
        if fragment[i] == "<":
            i = _tag_end(fragment, i)
        elif fragment[i] == "{":
            i = _balanced(fragment, i, "{", "}")
        else:
            out.append(fragment[i])
            i += 1
    return " ".join("".join(out).split())


def safety_regions(source: str) -> dict[str, list[str]]:
    """The markup of each safety control's card, with the components it renders
    that the same file defines — the kill switch's chip lives in one — and any
    element a page marks ``data-safety-control``, as /system marks both of its
    cards, so a control moved out from under its title is still held still."""
    text = _blank_comments(source)
    cards = [
        (m.start(), jsx_element_end(text, m.start()))
        for m in re.finditer(r"<Card(?=[\s>/])", text)
    ]
    spans: dict[str, list[tuple[int, int]]] = {name: [] for name in SAFETY_HEADINGS}
    for m in re.finditer(r"<CardTitle(?=[\s>/])", text):
        title = jsx_text(
            text[_tag_end(text, m.start()) : jsx_element_end(text, m.start())]
        )
        for name, heading in SAFETY_HEADINGS.items():
            holders = [c for c in cards if c[0] < m.start() < c[1]]
            if heading.search(title) and holders:
                spans[name].append(min(holders, key=lambda c: c[1] - c[0]))
    for m in re.finditer(r"\sdata-safety-control=\"([^\"]+)\"", text):
        start = text.rfind("<", 0, m.start())
        spans.setdefault(m.group(1), []).append((start, jsx_element_end(text, start)))
    defined = {m.group(1) for m in re.finditer(r"\bfunction ([A-Z]\w*)\s*\(", text)}

    def with_helpers(fragment: str, seen: set[str]) -> Iterator[str]:
        yield fragment
        for m in re.finditer(r"<([A-Z]\w*)(?=[\s>/])", fragment):
            helper = m.group(1)
            if helper in defined and helper not in seen:
                seen.add(helper)
                start, _, end = _function(text, helper)
                yield from with_helpers(text[start:end], seen)

    return {
        name: [f for a, b in found for f in with_helpers(text[a:b], set())]
        for name, found in spans.items()
    }


def moving_safety_controls(source: str) -> list[str]:
    """Whatever on a safety control could move: a press, a pulse, an entrance."""
    problems = []
    for name, fragments in safety_regions(source).items():
        if not fragments:
            problems.append(f"no {name} card found; SAFETY_HEADINGS names it by title")
        for fragment in fragments:
            for m in re.finditer(r"<Button(?=[\s>/])", fragment):
                tag = fragment[m.start() : _tag_end(fragment, m.start())]
                classes = _jsx_attribute(tag, "className") or ""
                if not re.search(r"\bSTILL\b", classes):
                    problems.append(
                        f"{name}: a Button without STILL: {' '.join(tag.split())}"
                    )
            problems += [
                f"{name}: <{component}> pulses"
                for component, _, _ in jsx_attributes(fragment, "pulse")
            ]
            if "enter-stagger" in class_tokens(fragment):
                problems.append(f"{name}: an entrance (enter-stagger)")
    return problems


_A_SYSTEM_PAGE = """
import { STILL } from "@/lib/motion";

function KillControls({ engage }: { engage: () => void }) {
  return (
    <Button variant="destructive" className={STILL} onClick={engage}>
      Engage kill switch
    </Button>
  );
}

export default function Page() {
  return (
    <div className="summary-grid">
      <Card>
        <CardHeader>
          <CardTitle className="flex gap-2">
            Trading
            <SafetyState status={killSwitchStatus(on)} word="stopped" stale={stale} />
          </CardTitle>
        </CardHeader>
        <CardContent>
          <KillControls engage={engage} />
          <Button className={cn(STILL, "w-full")} onClick={release}>
            Re-enable trading
          </Button>
          <Card><CardContent>nested</CardContent></Card>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Gates on a live order</CardTitle></CardHeader>
        <CardContent><Gate name="LIVE_TRADING_ENABLED" open={false} /></CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Jobs</CardTitle></CardHeader>
        <CardContent><Button onClick={refresh}>Refresh</Button></CardContent>
      </Card>
    </div>
  );
}

function Gate({ name, open }: { name: string; open: boolean }) {
  return <StatusBadge status={liveGateStatus(open)}>{name}</StatusBadge>;
}
"""


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        (("", ""), None),
        (
            ('className={cn(STILL, "w-full")} ', ""),
            "kill switch: a Button without STILL",
        ),
        (('variant="destructive" className={STILL}', 'variant="destructive"'), "kill"),
        (("<Button onClick={refresh}>", "<Button onClick={refresh}>"), None),
        (("liveGateStatus(open)}>", "liveGateStatus(open)} pulse={!stale}>"), "pulses"),
        (
            ("<CardContent><Gate", '<CardContent className="enter-stagger"><Gate'),
            "entrance",
        ),
        (("Trading\n", "Positions\n"), "no kill switch card"),
        (
            (
                'className={cn(STILL, "w-full")}',
                'className="active:translate-y-0 w-full"',
            ),
            "kill",
        ),
        (
            (
                "<Card>\n        <CardHeader><CardTitle>Jobs",
                '<Card data-safety-control="venue-cancel">\n'
                "        <CardHeader><CardTitle>Jobs",
            ),
            "venue-cancel: a Button without STILL",
        ),
    ],
    ids=[
        "still",
        "a-press",
        "a-press-in-a-helper",
        "a-button-elsewhere",
        "a-pulsing-gate",
        "an-entrance",
        "no-heading",
        "the-class-without-the-name",
        "a-region-marked-by-attribute",
    ],
)
def test_the_safety_control_check(change: tuple[str, str], problem: str | None) -> None:
    old, new = change
    assert old in _A_SYSTEM_PAGE
    problems = moving_safety_controls(_A_SYSTEM_PAGE.replace(old, new, 1))
    if problem is None:
        assert problems == []
    else:
        assert problems and problem in problems[0], problems


def test_every_control_on_a_safety_card_is_still() -> None:
    source = SYSTEM_PAGE.read_text(encoding="utf-8")
    regions = safety_regions(source)
    # Guards the guard: both cards are found, and the kill switch's holds the
    # engage and release buttons the check is for.
    assert all(regions[name] for name in SAFETY_HEADINGS), sorted(
        n for n in SAFETY_HEADINGS if not regions[n]
    )
    assert "<Button" in "".join(regions["kill switch"])
    problems = moving_safety_controls(source)
    assert not problems, (
        "A safety control never moves (web/DESIGN.md M-11, C-12): no press, no "
        "pulse, no entrance on the kill switch or beside the live-order gates. "
        "Give every Button there className={STILL} (lib/motion.ts):\n  "
        + "\n  ".join(problems)
    )


# ---------------------------------------------------------------------------
# (g) Summary pages are an asymmetric grid (OD-7, L-4)
# ---------------------------------------------------------------------------

SUMMARY_PAGES = {
    "system": SYSTEM_PAGE,
    "programme": PROGRAMME_PAGE,
    "portfolio": PORTFOLIO_PAGE,
}


def summary_layout_problems(source: str) -> list[str]:
    text = _blank_comments(source)
    tags = [
        (m.start(), class_tokens(text[m.start() : _tag_end(text, m.start())]))
        for m in re.finditer(r"<[A-Za-z][\w.]*(?=[\s>/])", text)
    ]
    grids = [at for at, classes in tags if "summary-grid" in classes]
    if not grids:
        return ["no element carries summary-grid"]
    start, end = grids[0], jsx_element_end(text, grids[0])

    def first(name: str) -> int | None:
        return next((at for at, c in tags if start < at < end and name in c), None)

    main, side = first("summary-main"), first("summary-side")
    problems = []
    if main is None:
        problems.append("no summary-main inside the summary-grid")
    if side is None:
        problems.append("no summary-side inside the summary-grid")
    if main is not None and side is not None and side < main:
        problems.append("summary-side comes before summary-main")
    return problems


_A_SUMMARY = """
<div className={cn("summary-grid", className)}>
  <div className="summary-main"><Card>A</Card></div>
  <aside className="summary-side"><Card>B</Card></aside>
</div>
"""


@pytest.mark.parametrize(
    ("source", "problem"),
    [
        (_A_SUMMARY, None),
        (
            _A_SUMMARY.replace("summary-main", "X")
            .replace("summary-side", "summary-main")
            .replace("X", "summary-side"),
            "comes before",
        ),
        (_A_SUMMARY.replace("summary-side", "summary-wide"), "no summary-side"),
        (_A_SUMMARY.replace("summary-grid", "grid gap-3"), "no element carries"),
        (
            '<div className="summary-grid"><div>A</div></div>'
            '<div className="summary-main" /><div className="summary-side" />',
            "no summary-main",
        ),
    ],
    ids=["main-then-side", "side-first", "no-side", "no-grid", "outside-the-grid"],
)
def test_the_summary_layout_check(source: str, problem: str | None) -> None:
    problems = summary_layout_problems(source)
    if problem is None:
        assert problems == []
    else:
        assert problems and problem in problems[0], problems


@pytest.mark.parametrize("page", sorted(SUMMARY_PAGES))
def test_the_summary_pages_use_the_summary_grid(page: str) -> None:
    problems = summary_layout_problems(SUMMARY_PAGES[page].read_text(encoding="utf-8"))
    assert not problems, (
        f"/{page} is a summary page, laid out as the asymmetric grid the owner "
        "chose (OD-7, web/DESIGN.md L-4): summary-grid, its main column first in "
        f"source order so a phone reads it first: {problems}"
    )


def _region(text: str, name: str) -> tuple[int, int]:
    """Where the element carrying class ``name`` starts and ends."""
    for m in re.finditer(r"<[A-Za-z][\w.]*(?=[\s>/])", text):
        if name in class_tokens(text[m.start() : _tag_end(text, m.start())]):
            return m.start(), jsx_element_end(text, m.start())
    raise AssertionError(f"no element carries {name}")


def test_a_runner_that_is_not_alive_is_warned_of_above_the_controls() -> None:
    """A caveat sits above the figure it qualifies (K-7), and a runner that is
    not alive qualifies /programme's switch: "enabled" means nothing while no
    process acts on it. One column on a phone, the side column follows every
    control in the main one, so the warning in the runner's card came after
    the switch and "Run a pass now" — at 390px, off the first screen."""
    text = _blank_comments(PROGRAMME_PAGE.read_text(encoding="utf-8"))
    main, side = _region(text, "summary-main"), _region(text, "summary-side")
    controls = min(
        m.start()
        for m in re.finditer(
            r"Disable the programme|Enable the programme|Run a pass now", text
        )
    )
    warnings = [m.start() for m in re.finditer(r"do\s+nothing\s+until", text)]
    assert len(warnings) == 2, (
        "a warning for a runner never seen, and one for a runner that is not alive"
    )
    assert all(main[0] < at < min(main[1], controls) for at in warnings), (
        "the warning opens the Autonomy card, above the controls a dead runner "
        "leaves idle"
    )
    assert not [at for at in warnings if side[0] < at < side[1]]
    lead = text[main[0] : controls]
    # "Not alive", through the one helper: a stale heartbeat, and a runner that
    # shut down cleanly, whose row stays fresh for a minute after it stopped.
    assert "runner === null" in lead and "!isAlive(runner)" in lead, (
        "both a runner never seen and one that is not alive are warned of"
    )
    assert "runner.stale" not in lead, "staleness alone misses a clean shutdown"


# ---------------------------------------------------------------------------
# (h) One column until lg (OD-7)
# ---------------------------------------------------------------------------

_LG = re.compile(r"^@media \((?:min-width:\s*|width\s*>=\s*)(?:64rem|1024px)\)$")


def test_the_summary_grid_is_one_column_until_lg() -> None:
    rules = read_css(GLOBALS.read_text(encoding="utf-8"))[0]
    tokens = root_tokens(rules)

    def only(selector: str, *, in_media: bool) -> list[Rule]:
        return [r for r in rules if selector in r.selectors and r.in_media is in_media]

    base = only(".summary-grid", in_media=False)
    assert len(base) == 1, base
    grid = base[0].declarations
    assert grid.get("display") == "grid", grid
    # Spelled out, and never a bare `1fr` or left implicit: either takes the
    # widest unbreakable content as the column's floor, and with an implicit
    # column /programme's board made a 390px phone's page 2018px wide
    # (measured 2026-09-27). The grid carries the guarantee, so no page using
    # it needs a `min-w-0` of its own.
    assert grid.get("grid-template-columns") == "minmax(0, 1fr)", (
        f"one column below lg, a phone included, which no content can widen: {grid}"
    )
    assert to_px(resolve(grid.get("gap", ""), tokens)) == 24, grid
    wide = only(".summary-grid", in_media=True)
    assert len(wide) == 1 and _LG.match(wide[0].context[-1]), [r.context for r in wide]
    assert wide[0].declarations == {
        "grid-template-columns": "minmax(0, 2fr) minmax(0, 1fr)"
    }, wide[0].declarations
    for column in (".summary-main", ".summary-side"):
        (rule,) = only(column, in_media=False)
        d = rule.declarations
        assert (d.get("display"), d.get("flex-direction"), d.get("min-width")) == (
            "flex",
            "column",
            "0",
        ), d
        assert to_px(resolve(d.get("gap", ""), tokens)) == 24, d
    (spanning,) = only(".summary-wide", in_media=False)
    assert spanning.declarations.get("grid-column") == "1 / -1"
    # The region that holds the widest content — the jobs table, the board —
    # may shrink below it like the other two, so its table scrolls in its own
    # region rather than the page scrolling sideways (L-6).
    assert spanning.declarations.get("min-width") == "0", spanning.declarations


# ---------------------------------------------------------------------------
# Tables: named, still once a row moves, never scrolled by an entrance
# (A-7, M-12, K-8)
# ---------------------------------------------------------------------------


def test_every_table_is_named() -> None:
    """A table wider than its column scrolls in a focusable region, and a focus
    stop with no name is announced as nothing (A-7). Which tables overflow
    depends on the column and the zoom — /portfolio's positions did from 1024
    to about 1190px once they moved into the side column — so every one is
    named, and the components require it rather than hoping."""
    table = _blank_comments((UI / "table.tsx").read_text(encoding="utf-8"))
    data = _blank_comments(DATA_TABLE.read_text(encoding="utf-8"))
    for name, text in (("ui/table.tsx", table), ("DataTable.tsx", data)):
        assert re.search(r"\blabel: string\b", text) and not re.search(
            r"\blabel\?:", text
        ), f"{name}: `label` is a required string"
    assert "<Table label={label}>" in data
    assert re.search(r'role=\{scrolls \? "region" : undefined\}', table), (
        "a scrolling table is always a named region, never a nameless stop"
    )
    unnamed = []
    for path in sorted(SRC.rglob("*.tsx")):
        if UI in path.parents or "node_modules" in path.parts:
            continue
        text = _blank_comments(path.read_text(encoding="utf-8"))
        for m in re.finditer(r"<(Table|DataTable)(?=[\s>/])", text):
            tag = text[m.start() : _tag_end(text, m.start())]
            if not _jsx_attribute(tag, "label"):
                unnamed.append(f"{path.relative_to(SRC)}: <{m.group(1)}>")
    assert not unnamed, f"tables with no name: {unnamed}"


def test_a_data_table_stops_staggering_once_a_row_it_shows_moves() -> None:
    """A moved row is re-inserted, and the browser restarts its entrance: the
    findings register sorts blocking findings first, and a closed finding fell
    below the next and rose again as if it had just arrived (M-12). DataTable
    compares the order it renders with the order it last rendered, in the
    render itself — an effect runs after React has moved the row with the
    class still on — and drops the class from the first move on."""
    text = _blank_comments(DATA_TABLE.read_text(encoding="utf-8"))
    assert re.search(r'stagger && !rearranged && "enter-stagger"', text), (
        "the entrance is withdrawn once the table has been rearranged"
    )
    assert not re.search(r"\buse(?:Layout)?Effect\(", text), (
        "the move is found during render, not after the commit that made it"
    )
    detection = re.search(
        r"if \(!same\(shown, order\)\) \{\s*setShown\(order\);\s*"
        r"if \(stagger && !rearranged && moved\(shown, order\)\) "
        r"setRearranged\(true\);",
        text,
    )
    assert detection, "DataTable compares the rows it shows with its last render's"
    moved = text[text.index("function moved(") :]
    moved = moved[: _balanced(moved, moved.index("{"), "{", "}")]
    assert "then.has(id)" in moved and "now.has(id)" in moved, (
        "only rows shown both before and now count: an arrival moves nothing"
    )
    # The operator's own sort and filter still count as rearranging.
    assert text.count("setRearranged(true)") == 3, text.count("setRearranged(true)")


def test_a_rising_row_cannot_scroll_its_table() -> None:
    """The entrance starts a row below where it ends, and `overflow-x: auto`
    makes the y axis `auto` as well: for the length of the entrance the last
    rows overhung the table's scroller, and wherever scrollbars take space a
    15px vertical bar came and went and every column shifted with it. A rise
    from below needs a scroller that clips its y axis."""
    frames = {k.name: k for k in read_css(GLOBALS.read_text(encoding="utf-8"))[1]}
    start = frames["rise"].frames["from"].get("transform", "")
    rises = re.fullmatch(r"translateY\((\d*\.?\d+)px\)", start)
    table = _blank_comments((UI / "table.tsx").read_text(encoding="utf-8"))
    container = table[table.index('data-slot="table-container"') :]
    classes = re.search(r'className="([^"]*)"', container)
    assert classes, "the table container's classes are a plain string"
    tokens = classes.group(1).split()
    if rises and float(rises.group(1)) > 0:
        assert "overflow-x-auto" in tokens and (
            {"overflow-y-hidden", "overflow-y-clip"} & set(tokens)
        ), f"the table scroller must clip its y axis: {tokens}"


def test_no_side_column_holds_a_chart_sized_placeholder() -> None:
    """`.chart-empty` pads 48px on every side, for a placeholder the width of a
    chart. /portfolio's empty positions kept it in the side column, which left
    its sentence 118px — about twelve characters — to a line at 1024px."""
    assert re.search(
        r"\.chart-empty \{[^}]*padding: var\(--s-7\)",
        GLOBALS.read_text(encoding="utf-8"),
    )
    for name, page in SUMMARY_PAGES.items():
        text = _blank_comments(page.read_text(encoding="utf-8"))
        start, end = _region(text, "summary-side")
        assert "chart-empty" not in text[start:end], f"/{name}'s side column"


# ---------------------------------------------------------------------------
# The press, and the one exception to it (OD-6, M-11, K-8)
# ---------------------------------------------------------------------------


def _base_button_classes() -> list[str]:
    source = _blank_comments((UI / "button.tsx").read_text(encoding="utf-8"))
    m = re.search(r"cva\(\s*\"([^\"]*)\"", source)
    assert m, "button.tsx no longer opens cva() with its base classes"
    return m.group(1).split()


def test_every_button_presses_and_still_undoes_it() -> None:
    base = _base_button_classes()
    presses = [t for t in base if t.startswith("active:") and "translate" in t]
    assert presses == ["active:translate-y-px"], (
        f"every Button steps down a pixel while held (OD-6): {presses}"
    )
    # A step, not a travel: nothing in the Button transitions its position, so
    # reduced motion has nothing to take away.
    moving = [
        t
        for t in base
        if utility_of(t) in ("transition", "transition-all", "transition-transform")
    ]
    assert "transition-colors" in base and not moving, base
    motion = _blank_comments(MOTION.read_text(encoding="utf-8"))
    still = re.search(r'export const STILL = "([^"]+)";', motion)
    assert still and still.group(1) == "active:translate-y-0", motion
    # tailwind-merge drops the earlier of two classes in one group under one
    # variant; the press and STILL must be exactly that pair to cancel.
    for token in (presses[0], still.group(1)):
        assert token.split(":")[0] == "active"
        assert utility_of(token).startswith("translate-y-"), token
    button = _blank_comments((UI / "button.tsx").read_text(encoding="utf-8"))
    assert "cn(buttonVariants({ variant, size, className }))" in button, (
        "the caller's className reaches cn() last, which is what lets STILL win"
    )


def test_the_press_is_logged_where_vendored_edits_are() -> None:
    comment = (
        (UI / "button.tsx").read_text(encoding="utf-8").split("const buttonVariants")[0]
    )
    assert "active:translate-y-px" in comment and "OD-6" in comment, (
        "a vendored edit is commented in the file (web/DESIGN.md K-8)"
    )
    notes = NOTES.read_text(encoding="utf-8")
    log = notes[notes.index("- **K-8**") : notes.index("- **K-9**")]
    button_line = next(line for line in log.splitlines() if "`button.tsx`" in line)
    assert "OD-6" in log[log.index(button_line) :].split("\n  - ")[0], (
        "design/notes.md K-8 logs the press among the button's vendored edits"
    )


# ---------------------------------------------------------------------------
# The scrim is a token, and not pure black (C-9)
# ---------------------------------------------------------------------------

_OKLCH = re.compile(r"oklch\(([\d.]+)\s+([\d.]+)\s+([\d.]+)\)")


def test_the_scrim_is_a_token_and_not_pure_black() -> None:
    overlay = _component_classes(UI / "sheet.tsx", "sheet-overlay")
    assert any(utility_of(t).startswith("bg-scrim") for t in overlay), overlay
    assert not [t for t in overlay if utility_of(t).startswith("bg-black")], overlay
    css = GLOBALS.read_text(encoding="utf-8")
    rules = read_css(css)[0]
    assert re.search(r"--color-scrim:\s*var\(--scrim\);", css), (
        "@theme maps bg-scrim to the token"
    )
    for scheme, tokens in (
        ("dark", root_tokens(rules)),
        ("light", light_tokens(rules)),
    ):
        scrim, page = (_OKLCH.fullmatch(tokens[t]) for t in ("--scrim", "--bg"))
        assert scrim and page, (scheme, tokens["--scrim"])
        lightness, chroma = float(scrim.group(1)), float(scrim.group(2))
        assert (lightness, chroma) != (0.0, 0.0), f"{scheme}: the scrim is pure black"
        assert lightness < float(page.group(1)), (
            f"{scheme}: a scrim lighter than the page fogs it rather than shading it"
        )


# ---------------------------------------------------------------------------
# What the second review found, 2026-09-27
# ---------------------------------------------------------------------------
#
# A process that shut down cleanly read as alive for a minute (G-4, M-10r); the
# halo restarted whenever two heartbeats traded places (M-10r); OD-8's prose was
# nowhere 15px on the summary pages (T-11); the pipeline board scrolled with no
# name and no focus (L-6, A-7); the workers table hid its Age from 1024 to about
# 1270px (E-2); and /programme kept its switch's last value when it could no
# longer read it (G-2, E-13).

HEARTBEAT = SRC / "lib" / "heartbeat.ts"
OVERFLOW = SRC / "lib" / "overflow.ts"

#: The pages that show a heartbeat: the workers, the runner, the daily report.
HEARTBEAT_PAGES = {
    "system": SYSTEM_PAGE,
    "programme": PROGRAMME_PAGE,
    "report": REPORT_PAGE,
}


def _exported_function(text: str, name: str) -> tuple[str, str]:
    """(parameters, body) of ``export function name(…)``, type parameters and
    all, from a source with its comments blanked."""
    m = re.search(rf"\bexport function {re.escape(name)}\s*(?:<[^()]*>)?\s*\(", text)
    assert m, f"no exported function {name}"
    params_end = _balanced(text, m.end() - 1, "(", ")")
    body = text.index("{", params_end)
    end = _balanced(text, body, "{", "}")
    return text[m.end() : params_end - 1], text[body + 1 : end - 1]


def return_chain(body: str) -> list[tuple[tuple | None, tuple]]:
    """A body of ``if (cond) return expr;`` steps ending in ``return expr;``,
    each part read by ``parse_js``: (condition, or None for the last; value)."""
    steps, rest = [], body.strip()
    while rest:
        if rest.startswith("if"):
            opening = rest.index("(")
            closing = _balanced(rest, opening, "(", ")")
            condition = rest[opening + 1 : closing - 1]
            rest = rest[closing:].lstrip()
        elif rest.startswith("return "):
            condition = None
        else:
            raise ValueError(f"cannot read {rest[:60]!r}")
        if not rest.startswith("return "):
            raise ValueError(f"a step that does not return: {rest[:60]!r}")
        semicolon = rest.index(";")
        value = rest[len("return ") : semicolon]
        steps.append(
            (None if condition is None else parse_js(condition), parse_js(value))
        )
        rest = rest[semicolon + 1 :].lstrip()
        if condition is None and rest:
            raise ValueError(f"unreachable after the last return: {rest[:60]!r}")
    if not steps or steps[-1][0] is not None:
        raise ValueError("the chain does not end in a return")
    return steps


def run_chain(steps: list[tuple[tuple | None, tuple]], env: dict) -> object:
    for condition, value in steps:
        if condition is None or _truthy(evaluate(condition, env)):
            return evaluate(value, env)
    raise AssertionError("unreachable")


def _heartbeat_env(parameter: str, stale: object, status: object) -> dict:
    row = {"stale": stale, "status": status}
    return {parameter: row, f"{parameter}.stale": stale, f"{parameter}.status": status}


#: Every heartbeat a row can hold: fresh or stale; 'alive' while running,
#: 'stopped' after a clean shutdown, the column's default 'idle', which nothing
#: writes, and none at all, from a daily report whose API predates the field.
_HEARTBEATS = list(
    product((False, True), ("alive", "stopped", "idle", None, UNDEFINED))
)


def test_the_return_chain_reader() -> None:
    steps = return_chain(
        'if (h.status === "stopped") return "shut down"; '
        'if (h.stale) return "no heartbeat"; return h.status ? h.status : "none";'
    )
    words = [run_chain(steps, _heartbeat_env("h", s, t)) for s, t in _HEARTBEATS]
    assert words[:5] == ["alive", "shut down", "idle", "none", "none"], words
    for unreadable in ("x = 1; return 2;", 'if (a) b(); return "c";', ""):
        with pytest.raises(ValueError):
            return_chain(unreadable)


def test_a_heartbeat_is_alive_only_while_fresh_and_saying_so() -> None:
    """``isAlive`` is where liveness is decided, and the only place (G-4).

    A crash writes nothing, so a dead process's row goes on saying 'alive'
    until it is old: the age is the input. A clean shutdown writes 'stopped'
    with a fresh last_seen, so for the next minute the age says nothing is
    wrong: the stored status is the other half. Alive takes both. The pulse
    check above models the helper as this reads it (``_alive``).
    """
    text = _blank_comments(HEARTBEAT.read_text(encoding="utf-8"))
    params, body = _exported_function(text, "isAlive")
    parameter = re.match(r"\s*(\w+)\s*:\s*Heartbeat\b", params)
    assert parameter, f"isAlive takes a Heartbeat: ({params})"
    steps = return_chain(body)
    for stale, status in _HEARTBEATS:
        env = _heartbeat_env(parameter.group(1), stale, status)
        alive = _truthy(run_chain(steps, env))
        assert alive is (not stale and status == "alive"), (stale, status, alive)
        assert alive is _alive({"stale": stale, "status": status})


#: What the chip says of each heartbeat (web/DESIGN.md G-4). Never the stored
#: word: "stopped" is the kill switch's word (C-12r), and "alive" on a stale
#: row is the dead worker that looks alive.
_WORDS = {
    (False, "alive"): "alive",
    (True, "alive"): "no heartbeat",
    (False, "stopped"): "shut down",
    (True, "stopped"): "shut down",
}


def test_the_chip_says_what_became_of_the_process() -> None:
    text = _blank_comments(HEARTBEAT.read_text(encoding="utf-8"))
    params, body = _exported_function(text, "livenessWord")
    parameter = re.match(r"\s*(\w+)\s*:\s*Heartbeat\b", params)
    assert parameter, f"livenessWord takes a Heartbeat: ({params})"
    steps = return_chain(body)
    for stale, status in _HEARTBEATS:
        word = run_chain(steps, _heartbeat_env(parameter.group(1), stale, status))
        wanted = _WORDS.get((stale, status))
        if wanted is not None:
            assert word == wanted, (stale, status, word)
        else:
            assert isinstance(word, str) and word, (stale, status, word)
            assert word not in ("alive", "stopped"), (
                f"a heartbeat that is {'stale' if stale else 'fresh'} and says "
                f"{status!r} reads {word!r}"
            )


#: A heartbeat row, by the names the pages give one.
_ROW_NAMES = r"(?:worker|runner|w|row|heartbeat)"


def liveness_problems(source: str) -> list[str]:
    """Where a page decides a heartbeat's liveness, or its word, itself."""
    text = _blank_comments(source)
    problems = [
        f"reads `{m.group(0)}` itself" for m in re.finditer(r"\b\w+\??\.stale\b", text)
    ]
    problems += [
        f"shows the stored `{m.group(0)}`"
        for m in re.finditer(rf"\b{_ROW_NAMES}\??\.status\b", text)
    ]
    for component, _, status in jsx_attributes(source, "status"):
        if component == "StatusBadge" and status.startswith("livenessStatus("):
            if not re.fullmatch(r"livenessStatus\(\w+\)", status):
                problems.append(f"asks for {status} rather than for the row")
    return problems


@pytest.mark.parametrize(
    ("source", "problem"),
    [
        (
            "<StatusBadge status={livenessStatus(worker)} pulse={isAlive(worker)}>"
            "{livenessWord(worker)}</StatusBadge>",
            None,
        ),
        # /system as it shipped: the green "stopped".
        (
            "<StatusBadge status={livenessStatus(worker.stale)}>"
            '{worker.stale ? "no heartbeat" : worker.status}</StatusBadge>',
            "reads `worker.stale` itself",
        ),
        ("const noWorkerAlive = status.workers.every((w) => w.stale);", "`w.stale`"),
        ('{runner?.stale ? "stale" : "alive"}', "`runner?.stale`"),
        ("<span>{worker.status}</span>", "shows the stored `worker.status`"),
        ("<StatusBadge status={jobStatus(job.status)}>x</StatusBadge>", None),
    ],
    ids=[
        "the-helper",
        "the-shipped-chip",
        "no-worker-alive",
        "runner",
        "word",
        "a-job",
    ],
)
def test_the_liveness_check(source: str, problem: str | None) -> None:
    problems = liveness_problems(source)
    if problem is None:
        assert problems == []
    else:
        assert problems and problem in problems[0], problems


def test_every_page_decides_liveness_through_the_one_helper() -> None:
    """One helper, not three expressions (G-4). Each page read a row's
    staleness itself, and /system then showed the stored word: a clean stop was
    a green "✓ stopped" with a live halo, and /programme's "✓ alive"."""
    for name, page in HEARTBEAT_PAGES.items():
        source = page.read_text(encoding="utf-8")
        text = _blank_comments(source)
        assert re.search(r'from "@/lib/heartbeat"', text), (
            f"/{name} does not take liveness from lib/heartbeat.ts"
        )
        assert "livenessStatus(" in text and "livenessWord(" in text, name
        problems = liveness_problems(source)
        assert not problems, f"/{name} decides liveness itself: {problems}"
    # Where /system decides that no worker is alive, a clean stop counts as
    # not alive too: the banner, and the kill switch's cancel "will not finish
    # until one does".
    system = _blank_comments(SYSTEM_PAGE.read_text(encoding="utf-8"))
    declared = re.search(r"const noWorkerAlive = ([^;]+);", system)
    assert declared and "isAlive" in declared.group(1), declared


def comparator(source: str, name: str = "byWorkerId") -> tuple[str, str, tuple]:
    """The two parameters and the body of the comparator ``name`` sorts with."""
    text = _blank_comments(source)
    _, body = _exported_function(text, name)
    m = re.search(r"\.sort\(\s*\(\s*(\w+)\s*,\s*(\w+)\s*\)\s*=>\s*", body)
    assert m, f"{name} does not sort with a two-argument comparator"
    opening = body.index("(", body.index(".sort", m.start()))
    closing = _balanced(body, opening, "(", ")")
    expression = body[m.end() : closing - 1].strip().rstrip(",").strip()
    return m.group(1), m.group(2), parse_js(expression)


_ROWS = (
    {"worker_id": "worker-1", "status": "alive"},
    {"worker_id": "programme", "status": "alive"},
    {"worker_id": "gha-18034567890", "status": "stopped"},
)


def orders(a: str, b: str, tree: tuple) -> set[tuple[str, ...]]:
    """Every order the comparator leaves the rows in, over every order the API
    could answer them in and every way their heartbeats could be timed."""
    found = set()
    for arrival in permutations(range(len(_ROWS))):
        for timing in permutations(range(len(_ROWS))):
            rows = [
                dict(
                    _ROWS[i],
                    last_seen=f"2026-09-27T18:00:0{t}+00:00",
                    age_seconds=float(9 - t),
                    stale=False,
                )
                for i, t in zip(arrival, timing, strict=True)
            ]

            def compare(x: dict, y: dict) -> float:
                env = {f"{a}.{k}": v for k, v in x.items()}
                env.update({f"{b}.{k}": v for k, v in y.items()})
                return evaluate(tree, env)

            found.add(
                tuple(r["worker_id"] for r in sorted(rows, key=cmp_to_key(compare)))
            )
    return found


@pytest.mark.parametrize(
    ("expression", "stable"),
    [
        ("x.worker_id < y.worker_id ? -1 : x.worker_id > y.worker_id ? 1 : 0", True),
        ("x.last_seen < y.last_seen ? 1 : -1", False),
        ("x.age_seconds < y.age_seconds ? -1 : 1", False),
        ("0", False),
    ],
    ids=["by-id", "newest-first", "by-age", "as-answered"],
)
def test_the_order_reader(expression: str, stable: bool) -> None:
    assert (len(orders("x", "y", parse_js(expression))) == 1) is stable


def test_a_heartbeat_table_keeps_its_order_whatever_last_seen_says() -> None:
    """The API answers heartbeats newest first (``ORDER BY last_seen DESC``),
    so two live processes traded places on most polls, and a keyed row React
    moves restarts its animation: the halo jumped back to the start of its
    breath on whichever row moved (M-10r). The tables order by worker id, so a
    poll moves no row. Proved on the comparator itself, over every order the
    rows could arrive in and every timing of their heartbeats."""
    a, b, tree = comparator(HEARTBEAT.read_text(encoding="utf-8"))
    assert orders(a, b, tree) == {("gha-18034567890", "programme", "worker-1")}
    for page in (SYSTEM_PAGE, REPORT_PAGE):
        text = _blank_comments(page.read_text(encoding="utf-8"))
        receivers = re.findall(r"([\w.]+(?:\([\w.]*\))?)\.map\(\(\s*worker\s*\)", text)
        assert receivers, f"{page.relative_to(APP)} maps no worker rows"
        unordered = [r for r in receivers if not r.startswith("byWorkerId(")]
        assert not unordered, (
            f"{page.relative_to(APP)} renders heartbeats in the order the API "
            f"answered them: {unordered}"
        )


def test_the_runner_id_is_the_programmes() -> None:
    """The page tells the programme's runner from a worker by the id the
    runner writes its heartbeat under, which is the programme's constant: a
    rename on either side would leave the runner counted as a worker again."""
    from src.programme.flags import PROGRAMME_WORKER_ID

    text = _blank_comments(HEARTBEAT.read_text(encoding="utf-8"))
    declared = re.search(r'export const PROGRAMME_RUNNER_ID\s*=\s*"([^"]+)"', text)
    assert declared, "heartbeat.ts exports no PROGRAMME_RUNNER_ID"
    assert declared.group(1) == PROGRAMME_WORKER_ID
    _, body = _exported_function(text, "isWorkerProcess")
    assert re.fullmatch(
        r"\s*return\s+\w+\.worker_id\s*!==\s*PROGRAMME_RUNNER_ID\s*;\s*", body
    ), f"isWorkerProcess is not the runner's id test: {body!r}"


def test_no_worker_is_alive_counts_the_workers_only() -> None:
    """/system says no worker is alive, and the kill switch's cancel note says
    nothing is running to carry the cancel out, from one flag. The programme's
    runner writes a heartbeat to the same table and claims none of the
    worker's jobs, the cancel among them, so the flag reads a worker's rows
    only: counted as a worker, a live runner beside a dead worker kept both
    silent (found in review, 2026-09-27)."""
    text = _blank_comments(SYSTEM_PAGE.read_text(encoding="utf-8"))
    kept = re.search(r"const (\w+) = status\.workers\.filter\(isWorkerProcess\);", text)
    assert kept, "the page does not keep a worker's rows apart from the runner's"
    rows = kept.group(1)
    assert re.search(rf"const noWorkerAlive = !{rows}\.some\(isAlive\);", text), (
        "noWorkerAlive is not decided from the workers' rows alone"
    )
    assert re.search(rf"\b{rows}\.length === 0\b", text), (
        "'None has ever checked in' counts the runner's row"
    )
    assert "venueCancelSentence(status.venue_cancel, noWorkerAlive)" in text


# --- T-11: what counts as prose (OD-8) --------------------------------------

#: A size that sets running prose below the body's 15px (T-11).
SMALL_PROSE = {"text-xs", "text-sm", "text-base"}
#: A weight that would make prose read as the card title above it: hierarchy
#: is carried by weight and colour, not size (OD-8), so prose keeps the body's.
HEAVY = {"font-medium", "font-semibold", "font-bold"}

_JS_STRING = re.compile(r'"((?:[^"\\\n]|\\.)*)"|`((?:[^`\\]|\\.)*)`')
_WORD = re.compile(r"[A-Za-z][A-Za-z'’-]*")


def rendered_words(fragment: str) -> str:
    """The words a JSX fragment renders: its text, its children's text, and the
    string literals in its expressions — both sentences of a ternary — but not
    what an expression computes (a name, a call, a formatted figure)."""
    out, i = [], 0
    while i < len(fragment):
        if fragment[i] == "<":
            i = _tag_end(fragment, i)
        elif fragment[i] == "{":
            end = _balanced(fragment, i, "{", "}")
            for m in _JS_STRING.finditer(fragment[i:end]):
                literal = next(g for g in m.groups() if g is not None)
                out.append(" " + re.sub(r"\$\{[^}]*\}", " ", literal) + " ")
            i = end
        else:
            out.append(fragment[i])
            i += 1
    return " ".join("".join(out).split())


def reads_as_a_sentence(words: str) -> bool:
    """Four words or more, and a full stop, a question or an exclamation among
    them: a timestamp, a count, a label or an id is none of those."""
    return len(_WORD.findall(words)) >= 4 and bool(re.search(r"\w[.!?](?=\s|$)", words))


def paragraph_starts(text: str) -> list[int]:
    return [m.start() for m in re.finditer(r"<p(?=[\s>/])", text)]


def intro_starts(text: str) -> list[int]:
    """The paragraph straight after each ``h1``: the page's intro (L-7)."""
    return [
        m.start(1) for m in re.finditer(r"</h1>(?:\s|\{\s*\})*(<p)(?=[\s>/])", text)
    ]


def legacy_font_sizes() -> dict[str, float]:
    """Each plain class ``globals.css`` sizes, in px: ``{"banner": 15.0}``."""
    rules = read_css(GLOBALS.read_text(encoding="utf-8"))[0]
    tokens = root_tokens(rules)
    sizes = {}
    for rule in rules:
        size = rule.declarations.get("font-size")
        if rule.in_media or size is None:
            continue
        for selector in rule.selectors:
            px = to_px(resolve(size, tokens))
            if re.fullmatch(r"\.[\w-]+", selector) and px is not None:
                sizes[selector[1:]] = px
    return sizes


def prose_problems(
    source: str, starts: Callable[[str], list[int]], sizes: dict[str, float]
) -> tuple[list[str], int]:
    """Running prose set below the body's size, or at a title's weight; and how
    many paragraphs of running prose were read (T-11).

    Running prose is a paragraph that reads as a sentence, and every banner.
    A hint tied to its control by ``aria-describedby`` is a hint, however
    sentence-like, and keeps its small step.
    """
    text = _blank_comments(source)
    described = {
        literal
        for m in re.finditer(r"aria-describedby=(\"[^\"]*\"|\{)", text)
        for literal in re.findall(
            r'"([^"]+)"',
            m.group(1)
            if m.group(1) != "{"
            else text[m.end() - 1 : _balanced(text, m.end() - 1, "{", "}")],
        )
    }
    problems, read = [], 0
    for start in starts(text):
        opening = _tag_end(text, start)
        tag = text[start:opening]
        words = rendered_words(text[opening : jsx_element_end(text, start)])
        classes = class_tokens(tag)
        if "banner" not in classes and not reads_as_a_sentence(words):
            continue
        ident = _jsx_attribute(tag, "id")
        if (
            ident is not None
            and ident.startswith('"')
            and json.loads(ident) in described
        ):
            continue
        read += 1
        small = [t for t in classes if utility_of(t) in SMALL_PROSE]
        small += [f".{c} ({sizes[c]:g}px)" for c in classes if sizes.get(c, 15) < 15]
        heavy = [t for t in classes if utility_of(t) in HEAVY]
        label = f"“{words[:50]}…”" if words else f"<p {' '.join(classes)}>"
        if small:
            problems.append(f"{label} is set at {small}, below the body's 15px")
        if heavy:
            problems.append(f"{label} is {heavy}, a card title's weight")
    return problems, read


_A_PROSE_PAGE = """
<h1 className="mb-1">A page</h1>
{/* A comment between the title and the intro. */}
<p className="m-0 text-base text-ink-muted">An intro that is a whole sentence.</p>
<Card>
  <CardHeader>
    <CardTitle>A card</CardTitle>
    <p className="m-0 text-sm text-ink-muted">This card explains itself in prose.</p>
  </CardHeader>
  <CardContent>
    <p className="mt-0 text-xs text-ink-muted">last changed by {who} at {when}</p>
    <p className="m-0 text-sm" id="the-hint">Raising this needs a typed phrase.</p>
    <SelectTrigger aria-describedby={raised ? "the-hint" : undefined} />
    <p className="m-0 font-semibold">Set at the body size, and far too heavy.</p>
    <p className="banner banner-warn">{error}</p>
    <p className="m-0">
      {stale ? "When last read, nothing could move." : "Nothing can."}
    </p>
    <p className="m-0 text-sm">{count} candidates</p>
  </CardContent>
</Card>
"""


def test_the_prose_reader() -> None:
    problems, read = prose_problems(_A_PROSE_PAGE, paragraph_starts, {"banner": 13.0})
    assert read == 5, read
    assert [p.rsplit(" is ", 1)[0] for p in problems] == [
        "“An intro that is a whole sentence.…”",
        "“This card explains itself in prose.…”",
        "“Set at the body size, and far too heavy.…”",
        "<p banner banner-warn>",
    ], problems
    intros, read = prose_problems(_A_PROSE_PAGE, intro_starts, {})
    assert read == 1 and len(intros) == 1 and "An intro" in intros[0], intros


def test_a_banner_is_running_prose_at_the_body_size() -> None:
    """A banner's text is a running sentence (T-11): the caveat above a figure,
    a failure, what an operator must do. It was 13px, a step under the prose
    around it since OD-8, and read as a footnote to the page it qualifies."""
    rules = read_css(GLOBALS.read_text(encoding="utf-8"))[0]
    (banner,) = [r for r in rules if r.selectors == (".banner",) and not r.in_media]
    assert banner.declarations.get("font-size") == "var(--t-body)", banner.declarations
    problems = []
    for path in sorted(SRC.rglob("*.tsx")):
        if "node_modules" in path.parts:
            continue
        text = _blank_comments(path.read_text(encoding="utf-8"))
        for m in re.finditer(r"<[A-Za-z][\w.]*(?=[\s>/])", text):
            classes = class_tokens(text[m.start() : _tag_end(text, m.start())])
            if "banner" in classes:
                problems += [
                    f"{path.relative_to(SRC)}: a banner set {t}"
                    for t in classes
                    if utility_of(t) in SMALL_PROSE | HEAVY
                ]
    assert not problems, problems


def test_every_page_intro_is_running_prose_at_the_body_size() -> None:
    """The paragraph under a page's title is prose, at the body's 15px, on
    every page (T-11, L-7). Intros were 15px on two pages and 13px on the
    rest. A header line of identifiers or chips is metadata, and keeps its
    13px: it does not read as a sentence."""
    sizes = legacy_font_sizes()
    problems, read = [], 0
    for page in _pages():
        found, n = prose_problems(page.read_text(encoding="utf-8"), intro_starts, sizes)
        problems += [f"{page.relative_to(APP)}: {p}" for p in found]
        read += n
    assert read >= 10, f"read {read} intros; the reader has stopped finding them"
    assert not problems, "\n".join(problems)


def test_every_page_intro_and_every_banner_keeps_a_measure() -> None:
    """At 15px an intro with no measure ran the width of the page: one line of
    179 characters on /programme/findings, and a full-width stale banner 172
    (found in review, 2026-09-27). An intro keeps L-7's 68ch through the
    ``.intro`` class (or the legacy ``.subtitle``, which carries the same
    68ch), and a banner T-8's 75ch through its own rule."""
    rules = read_css(GLOBALS.read_text(encoding="utf-8"))[0]
    (intro,) = [r for r in rules if r.selectors == (".intro",) and not r.in_media]
    assert intro.declarations.get("max-width") == "68ch", intro.declarations
    (banner,) = [r for r in rules if r.selectors == (".banner",) and not r.in_media]
    assert banner.declarations.get("max-width") == "75ch", banner.declarations
    unmeasured, read = [], 0
    for page in _pages():
        text = _blank_comments(page.read_text(encoding="utf-8"))
        for start in intro_starts(text):
            opening = _tag_end(text, start)
            words = rendered_words(text[opening : jsx_element_end(text, start)])
            if not reads_as_a_sentence(words):
                continue
            read += 1
            classes = class_tokens(text[start:opening])
            if not {"intro", "subtitle"}.intersection(classes) and not [
                t for t in classes if re.fullmatch(r"max-w-(?:prose|\[\d+ch\])", t)
            ]:
                unmeasured.append(f"{page.relative_to(APP)}: {words[:60]}")
    assert read >= 10, f"read {read} intros; the reader has stopped finding them"
    assert not unmeasured, "intros with no measure:\n" + "\n".join(unmeasured)


def test_the_summary_pages_set_their_prose_at_the_body_size() -> None:
    """Every sentence on /system, /programme and /portfolio was 12 or 13px,
    and the only 15px text there was card titles (T-11, OD-8). And a card's
    prose keeps T-8's measure: at 15px across a 740px card a line ran to 110
    characters, and across the full-width board's card to 150."""
    sizes = legacy_font_sizes()
    for name, page in SUMMARY_PAGES.items():
        source = page.read_text(encoding="utf-8")
        problems, read = prose_problems(source, paragraph_starts, sizes)
        assert read >= 4, f"/{name}: read {read} paragraphs of prose"
        assert not problems, f"/{name}:\n" + "\n".join(problems)
        text = _blank_comments(source)
        intros = set(intro_starts(text))
        unmeasured = []
        for start in paragraph_starts(text):
            opening = _tag_end(text, start)
            classes = class_tokens(text[start:opening])
            words = rendered_words(text[opening : jsx_element_end(text, start)])
            if start in intros or "banner" in classes or not reads_as_a_sentence(words):
                continue
            if "text-body" in classes and not [
                t for t in classes if re.fullmatch(r"max-w-(?:prose|\[\d+ch\])", t)
            ]:
                unmeasured.append(words[:50])
        assert not unmeasured, f"/{name}: prose with no measure (T-8): {unmeasured}"


def test_a_card_title_stays_apart_from_the_prose_under_it() -> None:
    """Hierarchy by weight and colour, not size (OD-8): with prose at 15px, a
    card's title is the body's size too, and its weight is what sets it apart."""
    title = _component_classes(UI / "card.tsx", "card-title")
    assert "font-semibold" in title, title
    assert not [t for t in title if utility_of(t).startswith("text-")], title
    for name, page in SUMMARY_PAGES.items():
        for _, tag, _ in jsx_attributes(page.read_text(encoding="utf-8"), "className"):
            if tag.startswith("<CardTitle"):
                smaller = [t for t in class_tokens(tag) if utility_of(t) in SMALL_PROSE]
                assert not smaller, f"/{name}: a card title set {smaller}"


# --- L-6, A-7: a sideways scroller is a focusable, named region ---------------

_SIDEWAYS = {"overflow-x-auto", "overflow-x-scroll", "overflow-auto", "overflow-scroll"}


def unnamed_scrollers(source: str) -> list[str]:
    """Elements that scroll sideways without being a focusable, named region."""
    text = _blank_comments(source)
    problems = []
    for m in re.finditer(r"<([A-Za-z][\w.]*)(?=[\s>/])", text):
        tag = text[m.start() : _tag_end(text, m.start())]
        if not {utility_of(t) for t in class_tokens(tag)} & _SIDEWAYS:
            continue
        missing = [
            a
            for a in ("tabIndex", "role", "aria-label")
            if _jsx_attribute(tag, a) is None
        ]
        if missing:
            problems.append(
                f"<{m.group(1)}> scrolls sideways with no {', '.join(missing)}"
            )
    return problems


@pytest.mark.parametrize(
    ("source", "problems"),
    [
        ('<div className="flex gap-3 overflow-x-auto pb-2">', 1),
        (
            '<div className="overflow-x-auto" tabIndex={0} role="region" '
            'aria-label="Pipeline, scrolls sideways">',
            0,
        ),
        ('<div ref={r} className={cn("md:overflow-auto", x)} role="region">', 1),
        ('<div className="overflow-y-auto">', 0),
        ('<div className="overflow-x-hidden overflow-y-auto">', 0),
    ],
    ids=["the-board-as-shipped", "named", "half-named", "vertical", "menu"],
)
def test_the_scroller_check(source: str, problems: int) -> None:
    assert len(unnamed_scrollers(source)) == problems


def test_every_sideways_scroller_is_a_focusable_named_region() -> None:
    """The pipeline board scrolled sideways in a plain div. With a candidate in
    it, the links inside made it reachable; with none, a keyboard could not
    scroll it and axe reported `scrollable-region-focusable` (serious). It is
    now the region the table's scroller is: focusable and named while — and
    only while — its content is wider than it, through the one hook."""
    scrollers, problems = 0, []
    for path in sorted(SRC.rglob("*.tsx")):
        if "node_modules" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        text = _blank_comments(source)
        scrollers += sum(
            1
            for m in re.finditer(r"<[A-Za-z][\w.]*(?=[\s>/])", text)
            if {
                utility_of(t)
                for t in class_tokens(text[m.start() : _tag_end(text, m.start())])
            }
            & _SIDEWAYS
        )
        problems += [f"{path.relative_to(SRC)}: {p}" for p in unnamed_scrollers(source)]
    assert scrollers >= 2, "the table's scroller and the board are both read"
    assert not problems, "\n".join(problems)
    hook = re.compile(r'import \{ useOverflows \} from "@/lib/overflow"')
    for owner in (UI / "table.tsx", PROGRAMME_PAGE):
        text = _blank_comments(owner.read_text(encoding="utf-8"))
        assert hook.search(text), f"{owner.name} decides its own overflow"
        assert not re.search(r"\bfunction useOverflows\b", text), owner.name
        assert re.search(r'role=\{(\w+) \? "region" : undefined\}', text), owner.name
    assert re.search(
        r"export function useOverflows\(", OVERFLOW.read_text(encoding="utf-8")
    )


# --- E-2: the workers table fits the side column --------------------------------


def test_the_workers_table_fits_its_side_column() -> None:
    """In the side column the table scrolled sideways and hid its Age, the one
    figure it is there for, at every width from 1024 to about 1270px: four
    columns, where the column leaves the table 214px at 1024. Folding the
    last-seen instant into the Age cell alone left it 40px short, since the
    status chip is 126px and does not wrap. Two columns now: each value is a
    second line under the one it belongs to — the chip under the process's id,
    the instant, muted and free to wrap, under its age — and every value is
    still there as text."""
    text = _blank_comments(SYSTEM_PAGE.read_text(encoding="utf-8"))
    m = re.search(r'<Table label="Workers"', text)
    assert m, "/system has no Workers table"
    table = text[m.start() : jsx_element_end(text, m.start())]

    def elements(name: str) -> list[str]:
        return [
            table[e.start() : jsx_element_end(table, e.start())]
            for e in re.finditer(rf"<{name}(?=[\s>/])", table)
        ]

    heads = [jsx_text(h[_tag_end(h, 0) :]) for h in elements("TableHead")]
    assert heads == ["Worker", "Age"], heads
    worker, age = elements("TableCell")
    assert "{worker.worker_id}" in worker and "livenessWord(worker)" in worker, worker
    assert "fmtAge(worker.age_seconds)" in age, age
    assert "fmtInstant(worker.last_seen)" in age, age

    def line(cell: str, value: str) -> list[str]:
        """The classes of the element holding ``value`` as its only child."""
        found = re.search(rf"<(\w+)(?=[\s>/])[^>]*>\s*\{{{re.escape(value)}\}}", cell)
        assert found, f"{value} sits in no element of its own"
        return class_tokens(found.group(0))

    assert {"block", "text-ink-muted", "whitespace-normal"} <= set(
        line(age, "fmtInstant(worker.last_seen)")
    )
    assert {"block", "wrap-anywhere"} <= set(line(worker, "worker.worker_id"))
    assert "whitespace-normal" in class_tokens(worker[: _tag_end(worker, 0)]), (
        "the id's cell may wrap: table cells are nowrap"
    )
    chip = re.search(r"<(\w+)(?=[\s>/])[^>]*>\s*<StatusBadge", worker)
    assert chip and "block" in class_tokens(chip.group(0)), (
        "the chip is a line of its own"
    )


# --- G-2, E-13: /programme says when its switch is not read ---------------------


def test_programme_shows_its_switch_unread_when_its_reading_is_stale() -> None:
    """/system's kill switch reads "not read" beside its last reading once a
    refresh fails; /programme kept "✓ enabled", and the runner's "✓ alive",
    with no mark and no time (G-2, E-13). The switch fails closed on the
    server, and a page that keeps showing "enabled" when it cannot find out is
    that switch failing open on the screen."""
    badge = _blank_comments(STATUS_BADGE.read_text(encoding="utf-8"))
    _, body = _exported_function(badge, "SafetyState")
    assert '<StatusBadge status="unknown">not read</StatusBadge>' in body, body
    assert "last read: {word}" in body, body
    for page, switch in (
        (SYSTEM_PAGE, "killSwitchStatus("),
        (PROGRAMME_PAGE, "enabled"),
    ):
        text = _blank_comments(page.read_text(encoding="utf-8"))
        assert re.search(
            r"import \{[^}]*\bSafetyState\b[^}]*\} from \"@/components/StatusBadge\"",
            text,
        ), page.name
        assert not re.search(r"\bfunction SafetyState\b", text), page.name
        states = re.findall(r"<SafetyState\b(?:[^>{]|\{[^}]*\})*>", text)
        assert [s for s in states if switch in s], (page.name, states)
        assert all("stale={stale}" in s for s in states), (page.name, states)
    text = _blank_comments(PROGRAMME_PAGE.read_text(encoding="utf-8"))
    # Stale is a refresh that failed, never an action that did: a refused
    # "Run a pass now" says nothing about whether the page is current.
    assert re.search(r"\bconst stale = failure !== null;", text), (
        "stale is a failed read"
    )
    refresh = text[text.index("const refresh = useCallback(") :]
    refresh = refresh[: _balanced(refresh, refresh.index("{"), "{", "}")]
    assert "setFailure(" in refresh
    assert text.count("setFailure(") == refresh.count("setFailure("), (
        "only a refresh marks the reading stale"
    )
    # When it is stale, the page says since when and as of when.
    stale_banner = re.search(
        r'<p className="banner banner-warn" role="status" data-stale="true">', text
    )
    assert stale_banner, "no stale banner"
    banner = text[stale_banner.start() : jsx_element_end(text, stale_banner.start())]
    assert "fmtInstant(failure.since)" in banner and "fmtInstant(readAt)" in banner, (
        banner
    )
    # The runner and the board say it too, as /system's cards do.
    marks = re.findall(
        r'\{stale \? <StatusBadge status="unknown">stale</StatusBadge> : null\}', text
    )
    assert len(marks) >= 2, marks


def test_programme_keeps_its_heading_in_every_state() -> None:
    """A first load that failed used to leave a bare banner with no ``h1``
    (E-9, T-5); /system keeps its heading and says what failed, and so does
    /programme now that it mirrors /system's reading."""
    text = _blank_comments(PROGRAMME_PAGE.read_text(encoding="utf-8"))
    _, _, end = _function(text, "ProgrammePage")
    start = text.index("export default function ProgrammePage")
    body = text[start:end]
    returns = [m.start() for m in re.finditer(r"\breturn\b", body)]
    page_returns = [
        r
        for r in returns
        if re.match(r"return\s*\(\s*<", body[r:]) or re.match(r"return\s*<", body[r:])
    ]
    assert len(page_returns) == 1, "one render, whatever the state"
    rendered = body[page_returns[0] :]
    assert rendered.index("<h1") < rendered.index("<Skeleton"), (
        "the heading comes before the loading state, not instead of it"
    )

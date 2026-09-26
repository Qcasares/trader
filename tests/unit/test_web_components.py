"""
test_web_components.py
----------------------
Two of the owner's decisions of 2026-09-26 (web/DESIGN.md §0.2) as the source
of ``web/src`` can keep them or break them.

**OD-3, canonical components.** shadcn is canonical, the legacy base-layer
rules that restyled it are scoped away, there is one card with a hairline
edge, one chip, and one focus indicator — the accent outline, which passes
3:1 where shadcn's ring measured 1.50-2.94:1.

1. *The legacy element rules stop at legacy markup* (K-15). Tailwind puts the
   legacy sheet in ``@layer base``, under the utilities, and that was not far
   enough: a utility only wins for the properties it sets, so ``button {…}``
   still filled in a 1px edge, a grey fill and 7px 16px of padding on every
   shadcn ``Button``, ``label {…}`` a 12px margin under every ``Label``, and
   ``h2 {…}`` 19px on the sheet's title. Nothing failed: the build, the type
   checker and every test passed, and the rendering was simply the page's
   rather than the component's. So an element rule that names an element a
   component also renders must be scoped — ``:not([data-slot])`` or a legacy
   class — unless all it sets is the pointer cursor or the focus indicator.
2. *One card, one chip* (K-16, C-8a). No legacy ``.card``, ``.pill`` or
   ``.badge``, in the stylesheet or in a class list; the card's edge names the
   hairline, and a bare ``border`` defaults to it rather than to
   ``currentColor``, which outlined every card in the text colour.
3. *One focus indicator* (A-4). No component suppresses the outline or draws
   a ring on focus; the stylesheet draws the outline, including on the date
   input's calendar stop, where the input matches no ``:focus`` at all; and
   the outline clears 3:1 against every backdrop a control sits on, in both
   schemes — recomputed here from the tokens, and held equal to the table the
   stylesheet records.

**OD-2, the alarm state on /system.** Red is reserved for live money
reachable; a halted kill switch is the safe state and renders as a strong
amber "stopped".

4. *The kill switch is never red* (C-12, C-12r). ``StatusBadge`` has a
   ``stopped`` state, drawn as an amber plate that cannot be mistaken for the
   amber *text* of ``unknown``; the kill switch maps to it; an open live gate
   is the one red on the page; and ``/system`` asks for states through those
   mappers rather than writing a colour. It used to write
   ``trading_enabled ? "settled" : "blocked"``, so a fresh deployment — which
   the migration leaves halted — opened on the same red cross as an open
   live-trading gate. And because the page now calls that state safe, it says
   what the switch does not do: ``POST /system/kill`` only sets the flag, so an
   order already at the venue stays there. That sentence is tied to the
   route's own calls, and fails the other way once the route cancels.

And one motion rule (5), because a class that compiles to nothing is a
promise the page does not keep (M-4): no ``tw-animate-css`` class unless the
package is installed and imported. 55 of them were, and nothing ever moved.

**What scoping the legacy sheet took with it.** The legacy element rules were
doing three jobs nobody had written down, and scoping them away from the
components (1, K-15) ended all three without anyone deciding to:

6. *The sidebar's groups sit 48px apart*, and in the desktop rail the first
   sits 48px under the wordmark. The 32px above each group heading was the
   legacy ``h2`` rule's top margin; without it the groups closed up to the
   nav's 16px gap.
7. *A ghost or outline Button rendered as a link is the link colour* — the
   back links, the per-row "view", the header "Configuration". The legacy
   ``a`` rule coloured them; scoped to markup with no ``data-slot``, it no
   longer reached them, and they fell back to the body text colour.
8. *Only a link in running text is underlined* (A-5). The rule that replaced
   the legacy ``a`` rule underlined every link on the site, where axe's
   ``link-in-text-block`` asks for the links a reader meets inside running
   text: a paragraph, a list item, a table cell, a definition, a banner.
   Every other link is drawn by its own component.

And one colour that moved the other way when the chips became one:

9. *An unmet gate is amber, not red.* Its summary chip shipped as the amber
   "▲ N unmet" and turned into the red of a failure on its way onto
   ``StatusBadge``. The owner reserved red for live money reachable on the
   safety controls (OD-2) and has not said how much further that reaches
   (Q-33); a research gate that has not passed yet is not an alarm, so it is
   ``caution`` again, told apart from "not measured" by its glyph. The
   criteria inside it, failed jobs and a dead worker stay red.

And the contract that has to say so:

10. *Every state the chip draws, and every mapper a page asks for one, is in
    ``web/DESIGN.md``* (C-5, §5.1). ``caution`` reached ``StatusBadge`` while
    the contract was being cut to its rules, and C-5 went on giving four
    states their meanings and §5.1 four mappers. An agent reading the
    contract before a UI change, as ``web/CLAUDE.md`` asks, would not learn
    that the state existed, nor what keeps it apart from ``unknown``, and
    would give an unmet gate one of the two readings the state exists to
    avoid: a failure, or no measurement at all.

The conventions are ``test_design_tokens.py``'s, whose scanner this reuses: a
scanner that silently finds nothing passes every test, so each is applied to
synthetic sources that must trip it and ones that must not, and each
real-tree test first asserts it read what it is meant to read.

Standard library and pytest only; nothing here needs Node.
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from tests.unit.test_design_tokens import (
    _balanced,
    _blank_comments,
    _oklch_hex,
    class_tokens,
    utility_of,
)

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
SRC = WEB / "src"
GLOBALS = SRC / "app" / "globals.css"
UI = SRC / "components" / "ui"
STATUS_BADGE = SRC / "components" / "StatusBadge.tsx"
SYSTEM_PAGE = SRC / "app" / "system" / "page.tsx"
SYSTEM_ROUTES = ROOT / "src" / "api" / "routers" / "system.py"

# ---------------------------------------------------------------------------
# A small reader for the stylesheet: rules as (selectors, declarations)
# ---------------------------------------------------------------------------


def _split_top(text: str, sep: str = ",") -> list[str]:
    """Split on ``sep`` outside parentheses and brackets."""
    parts, depth, start = [], 0, 0
    for i, c in enumerate(text):
        if c in "([":
            depth += 1
        elif c in ")]":
            depth -= 1
        elif c == sep and depth == 0:
            parts.append(text[start:i])
            start = i + 1
    parts.append(text[start:])
    return [p.strip() for p in parts if p.strip()]


def _declarations(body: str) -> dict[str, str]:
    found = {}
    for part in _split_top(body, ";"):
        if ":" in part and not part.lstrip().startswith("@"):
            prop, _, value = part.partition(":")
            found[prop.strip().lower()] = value.strip()
    return found


def css_rules(css: str) -> Iterator[tuple[list[str], dict[str, str]]]:
    """Every style rule in a stylesheet, with at-rule blocks walked into.

    ``@keyframes`` bodies are skipped: their "selectors" are percentages.
    """
    text = _blank_comments(css, line_comments=False)
    i = 0
    while i < len(text):
        brace = text.find("{", i)
        if brace < 0:
            return
        prelude = text[i:brace].strip()
        end = _balanced(text, brace, "{", "}")
        body = text[brace + 1 : end - 1]
        # A prelude is whatever follows the last statement or block closed
        # before it.
        prelude = re.split(r"[;}]", prelude)[-1].strip()
        if prelude.startswith("@keyframes"):
            pass
        elif prelude.startswith("@"):
            yield from css_rules(body)
        elif "{" in body:
            # Nesting is not used in this sheet; read the nested block as its own.
            yield from css_rules(body)
        else:
            yield _split_top(prelude), _declarations(body)
        i = end


def base_layer(css: str) -> str:
    """The body of the ``@layer base`` block."""
    text = _blank_comments(css, line_comments=False)
    m = re.search(r"@layer base\s*\{", text)
    assert m, "globals.css has no @layer base block"
    start = m.end() - 1
    return text[start + 1 : _balanced(text, start, "{", "}") - 1]


# ---------------------------------------------------------------------------
# 1. The legacy element rules stop at legacy markup (K-15)
# ---------------------------------------------------------------------------

#: Elements a shadcn or Radix component renders, or renders inside.
COMPONENT_ELEMENTS = frozenset(
    {
        "a",
        "button",
        "input",
        "select",
        "textarea",
        "label",
        "table",
        "thead",
        "tbody",
        "tfoot",
        "tr",
        "th",
        "td",
        "caption",
        "h1",
        "h2",
        "h3",
    }
)

#: What may still reach every element: the pointer cursor, and the one focus
#: indicator (A-4) — its geometry at rest, and on focus its style, width and
#: the radius the outline follows.
REST_DEFAULTS = frozenset({"cursor", "outline-color", "outline-offset"})
FOCUS_DEFAULTS = frozenset(
    {
        "outline",
        "outline-color",
        "outline-offset",
        "outline-style",
        "outline-width",
        "border-radius",
    }
)

_WHERE = re.compile(r":(?:where|is)\(")


def _expand(selector: str) -> list[str]:
    """``:where(a, b):x`` as ``a:x`` and ``b:x``, recursively."""
    m = _WHERE.search(selector)
    if not m:
        return [selector]
    open_at = m.end() - 1
    close = _balanced(selector, open_at, "(", ")")
    head, inner, tail = (
        selector[: m.start()],
        selector[open_at + 1 : close - 1],
        selector[close:],
    )
    out = []
    for alternative in _split_top(inner):
        out.extend(_expand(head + alternative + tail))
    return out


def _subject(selector: str) -> str:
    """The compound selector a rule styles: the one after the last combinator."""
    depth, last = 0, 0
    for i, c in enumerate(selector):
        if c in "([":
            depth += 1
        elif c in ")]":
            depth -= 1
        elif depth == 0 and c in " >+~":
            last = i + 1
    return selector[last:].strip()


def _scoped(compound: str) -> bool:
    return ":not([data-slot])" in compound.replace(" ", "") or bool(
        re.search(r"\.[A-Za-z_-]", re.sub(r"\([^)]*\)", "", compound))
    )


def unscoped_component_rules(css: str) -> list[str]:
    """Selectors in the base layer that restyle a component's element.

    A selector counts when its subject is one of COMPONENT_ELEMENTS and it is
    neither scoped to ``:not([data-slot])`` nor qualified by a legacy class —
    unless everything it sets is the cursor or the focus indicator.
    """
    found = []
    for selectors, declarations in css_rules(base_layer(css)):
        props = set(declarations)
        for selector in selectors:
            for plain in _expand(selector):
                compound = _subject(plain)
                element = re.match(r"[a-z][a-z0-9]*", compound)
                if not element or element.group(0) not in COMPONENT_ELEMENTS:
                    continue
                if _scoped(compound):
                    continue
                if props <= REST_DEFAULTS:
                    continue
                if re.search(r":focus(?:-visible|-within)\b", compound) and (
                    props <= FOCUS_DEFAULTS
                ):
                    continue
                found.append(f"{selector} {{{', '.join(sorted(props))}}}")
                break
    return found


def _sheet(body: str) -> str:
    return "@layer base {\n" + body + "\n}"


@pytest.mark.parametrize(
    ("css", "expected"),
    [
        # The four the owner's decision named, as they stood at 0ec084f.
        ("button { padding: 7px 16px; border: 1px solid; }", ["button"]),
        ("label { display: block; margin-bottom: 12px; }", ["label"]),
        ("h2 { font-size: 19px; margin: 32px 0 12px; }", ["h2"]),
        ("th { text-transform: uppercase; }", ["th"]),
        ("a:hover { text-decoration-thickness: 2px; }", ["a:hover"]),
        ("tbody tr:hover { background: grey; }", ["tbody tr:hover"]),
        (
            "input, select, textarea { font-family: mono; }",
            ["input", "select", "textarea"],
        ),
        (".card button { border: 0; }", [".card button"]),
        ("@media (max-width: 640px) { h1 { font-size: 19px; } }", ["h1"]),
        (":where(button):hover { background: grey; }", [":where(button):hover"]),
        # A focus rule is allowed to reach everything only while it draws the
        # focus indicator.
        (
            ":where(a):focus-visible { background: yellow; }",
            [":where(a):focus-visible"],
        ),
    ],
    ids=[
        "button",
        "label",
        "h2",
        "th",
        "link-hover",
        "row-hover",
        "fields",
        "ancestor-class",
        "in-media",
        "where-only",
        "focus-that-restyles",
    ],
)
def test_the_scoping_check_trips_on(css: str, expected: list[str]) -> None:
    found = unscoped_component_rules(_sheet(css))
    assert [f.split(" {")[0] for f in found] == expected, found


@pytest.mark.parametrize(
    "css",
    [
        "button:where(:not([data-slot])) { padding: 7px; }",
        "input:where(:not([data-slot])), select:where(:not([data-slot]))"
        " { width: 100%; }",
        "button.primary { background: blue; }",
        "label:where(:not([data-slot])) > span { display: block; }",
        "tbody > tr:where(:not([data-slot])):hover { background: grey; }",
        ":where(button, [role='button']):not(:disabled) { cursor: pointer; }",
        ":where(a, button, input) { outline-color: blue; outline-offset: 2px; }",
        ":where(a, button):focus-visible { outline-style: solid; outline-width: 2px;"
        " border-radius: 4px; }",
        ":where(input[type='date']):focus-within { outline-style: solid; }",
        "p { margin: 0; } ul { list-style: disc; } body { margin: 0; }",
        "*, ::before, ::after { border-color: grey; }",
        "@keyframes sweep { from { opacity: 0; } to { opacity: 1; } }",
    ],
    ids=[
        "scoped",
        "scoped-list",
        "legacy-class",
        "scoped-ancestor",
        "scoped-row",
        "cursor",
        "focus-at-rest",
        "focus",
        "date-focus",
        "not-component-elements",
        "border-default",
        "keyframes",
    ],
)
def test_the_scoping_check_passes(css: str) -> None:
    assert unscoped_component_rules(_sheet(css)) == []


def test_the_reader_reads_the_real_base_layer() -> None:
    # Guards the guard: a reader that finds no rules makes the check below
    # compare nothing and pass.
    rules = list(css_rules(base_layer(GLOBALS.read_text(encoding="utf-8"))))
    assert len(rules) > 80, f"read {len(rules)} rules from @layer base"
    selectors = {s for sel, _ in rules for s in sel}
    assert "body" in selectors and "button.primary" in selectors, sorted(selectors)[:20]


def test_no_legacy_element_rule_restyles_a_component() -> None:
    found = unscoped_component_rules(GLOBALS.read_text(encoding="utf-8"))
    assert not found, (
        "shadcn is canonical (owner decision OD-3, web/DESIGN.md K-15): an "
        "element rule in the legacy sheet must not reach an element a component "
        "renders. Scope it to el:where(:not([data-slot])) or a legacy class, or "
        "move the look into the component:\n  " + "\n  ".join(found)
    )


def zero_specificity_element_rules(css: str) -> list[str]:
    """Scoped element rules that can no longer beat Tailwind's preflight.

    Preflight sits in the same ``@layer base`` and styles ``h1``-``h6``,
    ``a``, the form controls and ``table`` with the element's specificity. A
    legacy rule wrapped whole in ``:where(…)`` has none, so it loses every
    property preflight also sets, silently: written that way, the scoping in
    this change first dropped every page title to body size. Only the cursor
    and the focus indicator are meant to have no specificity at all.
    """
    found = []
    for selectors, declarations in css_rules(base_layer(css)):
        props = set(declarations)
        if props <= REST_DEFAULTS or props <= FOCUS_DEFAULTS:
            continue
        for selector in selectors:
            compound = _subject(selector)
            if not compound.startswith(":where("):
                continue
            elements = {
                re.match(r"[a-z][a-z0-9]*", _subject(plain))
                for plain in _expand(compound)
            }
            if {e.group(0) for e in elements if e} & COMPONENT_ELEMENTS:
                found.append(selector)
    return found


@pytest.mark.parametrize(
    ("css", "expected"),
    [
        (":where(h1:not([data-slot])) { font-size: 23px; }", 1),
        (":where(a:not([data-slot])):hover { text-decoration-thickness: 2px; }", 1),
        ("h1:where(:not([data-slot])) { font-size: 23px; }", 0),
        (":where(button, [role='button']):not(:disabled) { cursor: pointer; }", 0),
        (":where(a, button):focus-visible { outline-style: solid; }", 0),
        (":where(.x) { color: red; }", 0),
    ],
    ids=[
        "wrapped-heading",
        "wrapped-link",
        "element-keeps-its-weight",
        "cursor",
        "focus",
        "class-only",
    ],
)
def test_the_specificity_check(css: str, expected: int) -> None:
    assert len(zero_specificity_element_rules(_sheet(css))) == expected


def test_a_scoped_rule_keeps_its_elements_specificity() -> None:
    found = zero_specificity_element_rules(GLOBALS.read_text(encoding="utf-8"))
    assert not found, (
        "Write the scope as el:where(:not([data-slot])), which keeps the "
        "element's specificity and so still beats Tailwind's preflight: "
        + ", ".join(found)
    )


# ---------------------------------------------------------------------------
# 2. One card, one chip (K-16, C-8a)
# ---------------------------------------------------------------------------

LEGACY_SURFACE_CLASSES = re.compile(r"^(?:card|card-head|badge|pill(?:-[a-z]+)?)$")


def _tsx_files() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.tsx") if "node_modules" not in p.parts)


def test_the_class_scan_reads_the_tree() -> None:
    files = _tsx_files()
    assert len(files) >= 30, f"found {len(files)} TSX files under web/src"
    assert sum(len(class_tokens(p.read_text(encoding="utf-8"))) for p in files) > 500


def test_no_class_list_names_a_legacy_card_or_chip() -> None:
    found = sorted(
        f"{p.relative_to(SRC).as_posix()}: {token}"
        for p in _tsx_files()
        for token in class_tokens(p.read_text(encoding="utf-8"))
        if LEGACY_SURFACE_CLASSES.match(utility_of(token))
    )
    assert not found, (
        "One card and one chip (owner decision OD-3, web/DESIGN.md K-16): a "
        "section is the shadcn Card and a status is StatusBadge, not the "
        "legacy .card / .pill / .badge:\n  " + "\n  ".join(found)
    )


def test_the_stylesheet_defines_no_legacy_card_or_chip() -> None:
    css = _blank_comments(GLOBALS.read_text(encoding="utf-8"), line_comments=False)
    found = [
        selector
        for selectors, _ in css_rules(css)
        for selector in selectors
        if re.search(r"\.(?:card|card-head|badge|pill)(?![\w-])|\.pill-\w", selector)
    ]
    assert not found, f"legacy card or chip rules remain: {found}"


def _component_classes(path: Path, slot: str) -> list[str]:
    """The class list of the element a component marks ``data-slot={slot}``."""
    source = _blank_comments(path.read_text(encoding="utf-8"))
    at = source.index(f'data-slot="{slot}"')
    m = re.compile(r"className=\{cn\(").search(source, at)
    assert m and m.start() - at < 200, f"{path.name}: no cn() class list after {slot}"
    end = _balanced(source, m.end() - 1, "(", ")")
    return class_tokens(source[m.start() : end] + "}")


def test_the_card_edge_is_the_hairline() -> None:
    classes = _component_classes(UI / "card.tsx", "card")
    assert "border" in classes, classes
    assert {"border-border", "border-line"} & set(classes), (
        "The card's edge names its colour, the hairline --border (owner decision "
        "OD-3, web/DESIGN.md C-8a); a bare `border` fell back to currentColor: "
        f"{classes}"
    )


def test_a_bare_border_defaults_to_the_hairline() -> None:
    rules = css_rules(base_layer(GLOBALS.read_text(encoding="utf-8")))
    defaults = [
        decl
        for selectors, decl in rules
        if "*" in selectors and decl.get("border-color") == "var(--border)"
    ]
    assert defaults, (
        "No base rule gives `*` the hairline border colour, so a bare `border` "
        "falls back to currentColor (web/DESIGN.md C-8)"
    )


def test_card_title_is_a_heading() -> None:
    source = (UI / "card.tsx").read_text(encoding="utf-8")
    m = re.search(r"function CardTitle\(.*?\n\}", source, re.S)
    assert m and re.search(r"<h2\b[^>]*data-slot=\"card-title\"", m.group(0)), (
        "CardTitle renders the section's heading (web/DESIGN.md T-5, A-8); as a "
        "div, pages went from h1 straight to h3"
    )


# ---------------------------------------------------------------------------
# 3. One focus indicator (A-4)
# ---------------------------------------------------------------------------


def suppressing_focus(token: str) -> bool:
    """A class that removes the outline, or draws a ring on focus instead."""
    utility = utility_of(token)
    variants = token[: len(token) - len(utility)] if token.endswith(utility) else ""
    if utility in ("outline-none", "outline-hidden") or utility.startswith(
        "ring-offset"
    ):
        return True
    return "focus" in variants and (utility == "ring" or utility.startswith("ring-"))


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("outline-none", True),
        ("focus:outline-hidden", True),
        ("focus-visible:ring-[3px]", True),
        ("focus-visible:ring-ring/50", True),
        ("focus:ring-2", True),
        ("dark:focus-visible:ring-destructive/40", True),
        ("ring-offset-background", True),
        ("focus-visible:opacity-100", False),
        ("aria-invalid:border-destructive", False),
        ("outline-offset-2", False),
        ("border-ring", False),
    ],
)
def test_the_focus_scan(token: str, expected: bool) -> None:
    assert suppressing_focus(token) is expected


def test_no_component_suppresses_the_outline_or_draws_a_ring() -> None:
    found = sorted(
        f"{p.relative_to(SRC).as_posix()}: {token}"
        for p in _tsx_files()
        for token in class_tokens(p.read_text(encoding="utf-8"))
        if suppressing_focus(token)
    )
    assert not found, (
        "One focus indicator on every control, the accent outline (owner "
        "decision OD-3, web/DESIGN.md A-4). shadcn's ring measured 1.50-2.94:1 "
        "and replaced the outline:\n  " + "\n  ".join(found)
    )


def _focus_rules() -> tuple[dict[str, str], dict[str, str], list[str]]:
    rest, focus, date_selectors = {}, {}, []
    for selectors, decl in css_rules(base_layer(GLOBALS.read_text(encoding="utf-8"))):
        joined = " ".join(selectors)
        if any(re.fullmatch(r":where\([^)]*\bbutton\b[^)]*\)", s) for s in selectors):
            if "outline-color" in decl:
                rest = decl
        if ":focus-visible" in joined and "button" in joined:
            focus = decl
        if ":focus-within" in joined:
            date_selectors += [s for s in selectors if ":focus-within" in s]
    return rest, focus, date_selectors


def test_the_stylesheet_draws_the_one_focus_indicator() -> None:
    rest, focus, date_selectors = _focus_rules()
    assert rest.get("outline-color") == "var(--accent)", rest
    assert rest.get("outline-offset") == "2px", rest
    assert (
        focus.get("outline-style") == "solid" and focus.get("outline-width") == "2px"
    ), focus
    assert any('type="date"' in s for s in date_selectors), (
        "A date input's calendar stop matches neither :focus nor :focus-visible "
        "in Chromium; it needs :focus-within to show the outline at all"
    )


# --- the ratios the outline is read against ------------------------------------

_OKLCH = re.compile(r"oklch\(([\d.]+)\s+([\d.]+)\s+([\d.]+)\)")


def _palettes() -> dict[str, dict[str, str]]:
    """{'dark': {'--bg': '#0e1116', ...}, 'light': {...}} from the token blocks."""
    css = _blank_comments(GLOBALS.read_text(encoding="utf-8"), line_comments=False)
    dark: dict[str, str] = {}
    for m in re.finditer(r"^:root \{", css, re.M):
        body = css[m.end() : _balanced(css, m.end() - 1, "{", "}") - 1]
        for prop, value in re.findall(r"(--[a-z0-9-]+)\s*:\s*([^;]+);", body):
            if c := _OKLCH.fullmatch(value.strip()):
                dark[prop] = _oklch_hex(*(float(x) for x in c.groups()))
    light = dict(dark)
    m = re.search(r"^@media \(prefers-color-scheme: light\) \{", css, re.M)
    assert m, "no light block"
    body = css[m.end() : _balanced(css, m.end() - 1, "{", "}") - 1]
    for prop, value in re.findall(r"(--[a-z0-9-]+)\s*:\s*([^;]+);", body):
        if c := _OKLCH.fullmatch(value.strip()):
            light[prop] = _oklch_hex(*(float(x) for x in c.groups()))
    return {"dark": dark, "light": light}


def _rgb(hex_: str) -> list[float]:
    return [int(hex_[i : i + 2], 16) / 255 for i in (1, 3, 5)]


def _over(top: list[float], under: list[float], alpha: float) -> list[float]:
    """Alpha compositing, as the browser does it: in gamma-encoded sRGB."""
    return [alpha * t + (1 - alpha) * u for t, u in zip(top, under, strict=True)]


def contrast(a: list[float], b: list[float]) -> float:
    def luminance(rgb: list[float]) -> float:
        lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]

    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _tint(css: str, name: str) -> tuple[str, float]:
    """A banner's fill: the token it mixes and the share, from globals.css."""
    m = re.search(
        rf"\.banner-{name}\s*\{{[^}}]*background:\s*"
        r"color-mix\(in oklab, var\((--[a-z-]+)\) (\d+)%, transparent\)",
        css,
    )
    assert m, f".banner-{name} no longer mixes a token into its fill"
    return m.group(1), int(m.group(2)) / 100


def focus_ratios() -> dict[str, list[float]]:
    """The accent outline against each backdrop, in the stylesheet's table order.

    --bg, --panel, --panel-2, a hovered row (--panel-2 at 50% over --panel),
    then each banner on a card and on the page: warn, info, bad.
    """
    css = _blank_comments(GLOBALS.read_text(encoding="utf-8"), line_comments=False)
    out = {}
    for theme, palette in _palettes().items():
        accent = _rgb(palette["--accent"])
        bg, panel, panel2 = (_rgb(palette[t]) for t in ("--bg", "--panel", "--panel-2"))
        backdrops = [bg, panel, panel2, _over(panel2, panel, 0.5)]
        for name in ("warn", "info", "bad"):
            token, share = _tint(css, name)
            tone = _rgb(palette[token])
            backdrops += [_over(tone, panel, share), _over(tone, bg, share)]
        out[theme] = [round(contrast(accent, b), 2) for b in backdrops]
    return out


def test_the_focus_outline_clears_three_to_one_on_every_backdrop() -> None:
    ratios = focus_ratios()
    failing = {t: [r for r in rs if r < 3.0] for t, rs in ratios.items()}
    assert not any(failing.values()), (
        "A focus indicator needs 3:1 against what it is drawn on (WCAG 1.4.11, "
        f"web/DESIGN.md A-3, A-4): {ratios}"
    )


def test_the_recorded_ratios_are_the_computed_ones() -> None:
    """The table in globals.css's focus comment is what the tokens produce."""
    source = GLOBALS.read_text(encoding="utf-8")
    recorded = {}
    for theme in ("dark", "light"):
        m = re.search(rf"^\s*{theme}\s+#[0-9a-f]{{6}}\s+(.*)$", source, re.M)
        assert m, f"globals.css records no {theme} row of focus ratios"
        recorded[theme] = [float(x) for x in re.findall(r"\d+\.\d+", m.group(1))]
    computed = focus_ratios()
    for theme in recorded:
        # The table lists the banners as "on a card / on the page" pairs, in
        # the same order focus_ratios() computes them.
        assert recorded[theme] == computed[theme], (
            f"{theme}: globals.css records {recorded[theme]}, the tokens give "
            f"{computed[theme]}; recompute the table"
        )


# ---------------------------------------------------------------------------
# 4. The kill switch is never red (OD-2, C-12)
# ---------------------------------------------------------------------------


def _mapper(source: str, name: str) -> tuple[str, str]:
    """(value when true, value when false) of a one-line boolean mapper."""
    m = re.search(
        rf"export function {name}\((\w+): boolean\): Status \{{\s*"
        rf'return (\w+) \? "(\w+)" : "(\w+)";\s*\}}',
        _blank_comments(source),
    )
    assert m, f"StatusBadge.tsx has no one-line boolean mapper {name}()"
    assert m.group(1) == m.group(2), f"{name} does not branch on its argument"
    return m.group(3), m.group(4)


def test_stopped_is_a_state_of_its_own() -> None:
    source = STATUS_BADGE.read_text(encoding="utf-8")
    union = re.search(r"export type Status =\s*([^;]+);", source)
    assert union and '"stopped"' in union.group(1), (
        "StatusBadge has no stopped state; a halted switch would have to borrow "
        "`blocked` (red) or `unknown` (not measured)"
    )


def test_the_kill_switch_maps_to_stopped_and_never_to_blocked() -> None:
    source = STATUS_BADGE.read_text(encoding="utf-8")
    enabled, halted = _mapper(source, "killSwitchStatus")
    assert halted == "stopped", f"a halted kill switch reads {halted!r}"
    assert "blocked" not in (enabled, halted)


def test_an_open_live_gate_is_the_red() -> None:
    open_, closed = _mapper(STATUS_BADGE.read_text(encoding="utf-8"), "liveGateStatus")
    assert (open_, closed) == ("blocked", "settled")


def _variant(name: str, component: str = "badge.tsx") -> list[str]:
    """The class list of one of a vendored component's variants.

    The first key of that name, which in both files is the ``variant`` one
    (``button.tsx`` has a ``default`` size as well, after it).
    """
    source = _blank_comments((UI / component).read_text(encoding="utf-8"))
    m = re.search(rf'^\s*{name}:\s*"([^"]*)"', source, re.M)
    assert m, f"{component} has no {name} variant"
    return m.group(1).split()


def test_stopped_is_a_plate_and_unknown_is_not() -> None:
    stopped, unknown = _variant("stopped"), _variant("unknown")
    assert "bg-stopped" in stopped and "text-stopped-ink" in stopped, stopped
    assert "bg-panel-2" in unknown, unknown
    css = GLOBALS.read_text(encoding="utf-8")
    assert re.search(
        r'\[data-slot="badge"\]\[data-variant="stopped"\]::before\s*\{\s*content:\s*"[^"]+"\s*/\s*""',
        css,
    ), "the stopped chip carries no glyph with an empty alternative (A-6)"


def test_the_stopped_ink_is_legible_on_its_plate() -> None:
    for theme, palette in _palettes().items():
        assert "--stopped" in palette and "--stopped-ink" in palette, theme
        ratio = contrast(_rgb(palette["--stopped"]), _rgb(palette["--stopped-ink"]))
        assert ratio >= 4.5, f"{theme}: stopped ink on its plate is {ratio:.2f}:1"


def test_system_asks_for_states_and_never_writes_blocked() -> None:
    source = _blank_comments(SYSTEM_PAGE.read_text(encoding="utf-8"))
    assert "killSwitchStatus(" in source and "trading_enabled" in source
    assert "liveGateStatus(" in source
    # The page never names the red state itself: it arrives only through a
    # mapper (an open gate, a failed job, a dead worker).
    written = re.findall(r'"blocked"', source)
    assert not written, (
        "/system writes the blocked (red) state directly; on this page red is "
        "the mappers' to give (owner decision OD-2, web/DESIGN.md C-12, K-2)"
    )


def _kill_cancels(source: str) -> bool:
    """Whether the ``POST /kill`` route itself cancels anything at the venue.

    Read from the route's own calls, not its docstring, which describes the
    cancel a live deployment would make rather than one it does. A cancel made
    inside a helper the route calls is not seen: that would be a reviewer's to
    catch, and this test's message says where to look.
    """
    routes = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(
            isinstance(d, ast.Call)
            and isinstance(d.func, ast.Attribute)
            and d.func.attr == "post"
            and d.args
            and isinstance(d.args[0], ast.Constant)
            and d.args[0].value == "/kill"
            for d in node.decorator_list
        )
    ]
    assert len(routes) == 1, f"expected one POST /kill route, found {len(routes)}"
    return any(
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr.startswith("cancel")
        for call in ast.walk(routes[0])
    )


_KILL_THAT_SETS_A_FLAG = '''
@router.post("/kill")
async def kill(conn):
    """In a live deployment this would also call broker.cancel_all()."""
    await flags.engage_kill_switch(conn)
'''

_KILL_THAT_CANCELS = """
@router.post("/kill")
async def kill(conn, broker):
    await flags.engage_kill_switch(conn)
    await broker.cancel_all()
"""


@pytest.mark.parametrize(
    "source, cancels",
    [(_KILL_THAT_SETS_A_FLAG, False), (_KILL_THAT_CANCELS, True)],
)
def test_the_cancel_check(source: str, cancels: bool) -> None:
    assert _kill_cancels(source) is cancels


def test_system_says_what_a_stopped_switch_does_not_do() -> None:
    """The halted note says the switch leaves orders at the venue, while it does.

    /system calls a halted switch the safe state, and the note under it says
    what stops: no live decision, no submission. The route that halts only
    sets the flag, so an order already sent stays at the venue. Without that
    sentence, "stopped" reads as "nothing in flight" — the one belief an
    operator reaching for this switch must not hold. If the route learns to
    cancel, the sentence becomes false, and this fails the other way.
    """
    text = " ".join(_blank_comments(SYSTEM_PAGE.read_text(encoding="utf-8")).split())
    assert "no order is submitted" in text, "the halted note no longer says what stops"
    says_so = "Orders already at the venue are not cancelled" in text
    if _kill_cancels(SYSTEM_ROUTES.read_text(encoding="utf-8")):
        assert not says_so, (
            "POST /system/kill now cancels at the venue, and /system still says "
            "it does not"
        )
    else:
        assert says_so, (
            "POST /system/kill only sets the flag (src/api/routers/system.py), "
            "so an order already at the venue stays there, and /system calls the "
            "halted state safe without saying so"
        )


# ---------------------------------------------------------------------------
# 5. No class that compiles to nothing (M-4)
# ---------------------------------------------------------------------------

_TW_ANIMATE = re.compile(
    r"^(?:animate-in|animate-out|(?:fade|zoom|spin)-(?:in|out)(?:-\d+)?"
    r"|slide-(?:in-from|out-to)-[a-z]+(?:-\d+)?)$"
)


def test_no_animation_class_without_its_library() -> None:
    package = json.loads((WEB / "package.json").read_text(encoding="utf-8"))
    installed = "tw-animate-css" in {
        **package.get("dependencies", {}),
        **package.get("devDependencies", {}),
    }
    imported = '@import "tw-animate-css"' in GLOBALS.read_text(encoding="utf-8")
    if installed and imported:
        pytest.skip("tw-animate-css is installed and imported; its classes compile")
    found = sorted(
        f"{p.relative_to(SRC).as_posix()}: {token}"
        for p in _tsx_files()
        for token in class_tokens(p.read_text(encoding="utf-8"))
        if _TW_ANIMATE.match(utility_of(token))
    )
    assert not found, (
        "These classes come from tw-animate-css, which is not installed and "
        "imported, so they compile to nothing (web/DESIGN.md M-4):\n  "
        + "\n  ".join(found)
    )


# ---------------------------------------------------------------------------
# 6. The sidebar's groups sit as far apart as they shipped (K-15)
# ---------------------------------------------------------------------------

APP_NAV = SRC / "components" / "AppNav.tsx"
APP_SHELL = SRC / "components" / "AppShell.tsx"

#: Tailwind 4's spacing step, ``--spacing: 0.25rem``: ``gap-4`` is 16px. Not
#: bridged to the ``--s-*`` scale (web/DESIGN.md §3), so compared by value.
SPACING_STEP_PX = 4

#: Utilities that put space above a box, and between the items of a flex box.
ABOVE = ("m", "my", "mt", "p", "py", "pt")
GAP = ("gap", "gap-y")

_SPACE = re.compile(r"(gap(?:-y)?|m[ty]?|p[ty]?)-(\d+(?:\.\d+)?)")


def _tag_end(text: str, start: int) -> int:
    """Index just past the ``>`` that closes the JSX opening tag at ``start``.

    Attribute values are skipped whole, so an ``=>`` inside ``{…}`` does not
    end the tag.
    """
    i = start + 1
    while i < len(text):
        c = text[i]
        if c == "{":
            i = _balanced(text, i, "{", "}")
        elif c in "\"'":
            i = text.index(c, i + 1) + 1
        elif c == ">":
            return i + 1
        else:
            i += 1
    return len(text)


def tag_classes(source: str, tag: str) -> list[str]:
    """The class list on the first ``<tag …>`` of a TSX source; [] if none."""
    text = _blank_comments(source)
    m = re.search(rf"<{tag}\b", text)
    assert m, f"no <{tag}> in the source"
    return class_tokens(text[m.start() : _tag_end(text, m.start())])


def space_px(classes: list[str], *kinds: str) -> float:
    """What the unconditional spacing utilities of these kinds add, in px.

    A responsive or state variant (``md:gap-6``) is not counted: the value it
    sets is not the one at every width.
    """
    total = 0.0
    for token in classes:
        m = _SPACE.fullmatch(token)
        if m and m.group(1) in kinds:
            total += float(m.group(2)) * SPACING_STEP_PX
    return total


def _spacing_token_px(name: str) -> float:
    css = _blank_comments(GLOBALS.read_text(encoding="utf-8"), line_comments=False)
    m = re.search(rf"^\s*{re.escape(name)}:\s*(\d+)px;", css, re.M)
    assert m, f"globals.css declares no {name} in px"
    return float(m.group(1))


def sidebar_spacing() -> tuple[float, float]:
    """(between one group and the next, wordmark to the first group), in px.

    Read from the utilities that set those distances, not from a layout: the
    nav's gap between groups and whatever is written above a group and above
    its heading; for the first group, the rail's gap under the wordmark and
    the nav's own top spacing as well.
    """
    source = APP_NAV.read_text(encoding="utf-8")
    nav = tag_classes(source, "nav")
    above_heading = space_px(tag_classes(source, "div"), *ABOVE) + space_px(
        tag_classes(source, "h2"), *ABOVE
    )
    rail = tag_classes(APP_SHELL.read_text(encoding="utf-8"), "aside")
    between = space_px(nav, *GAP) + above_heading
    under_wordmark = space_px(rail, *GAP) + space_px(nav, *ABOVE) + above_heading
    return between, under_wordmark


@pytest.mark.parametrize(
    ("classes", "kinds", "px"),
    [
        (["flex", "flex-col", "gap-4"], GAP, 16),
        (["gap-y-12"], GAP, 48),
        (["mt-8", "mb-1", "px-2"], ABOVE, 32),
        (["md:mt-8", "mt-2"], ABOVE, 8),
        (["py-1.5"], ABOVE, 6),
        (["text-xs", "tracking-[0.045em]", "mx-4", "pb-2"], ABOVE + GAP, 0),
    ],
    ids=["gap", "gap-y", "margin-top", "responsive", "fraction", "none"],
)
def test_the_spacing_reader(
    classes: list[str], kinds: tuple[str, ...], px: int
) -> None:
    assert space_px(classes, *kinds) == px


def test_the_spacing_reader_reads_the_sidebar() -> None:
    # Guards the guard: the elements it reads are the ones it means.
    source = APP_NAV.read_text(encoding="utf-8")
    assert "flex-col" in tag_classes(source, "nav")
    assert "uppercase" in tag_classes(source, "h2"), "not the group heading"
    assert "border-r" in tag_classes(APP_SHELL.read_text(encoding="utf-8"), "aside")
    assert tag_classes('<div key={x.y} onClick={() => go(">")}>', "div") == []


def test_the_sidebar_groups_sit_as_far_apart_as_they_shipped() -> None:
    between, under_wordmark = sidebar_spacing()
    wide = _spacing_token_px("--s-7")
    assert (between, under_wordmark) == (wide, wide), (
        f"The sidebar's groups sit {between:g}px apart and the first sits "
        f"{under_wordmark:g}px under the rail's wordmark; both shipped at {wide:g}px "
        "(--s-7), when the legacy h2 rule put 32px above every group heading. "
        "Scoping that rule away from the components (web/DESIGN.md K-15) took "
        "the spacing with it, which nobody decided; AppNav sets it itself."
    )


# ---------------------------------------------------------------------------
# 7. A Button rendered as a link is drawn in a colour of its own
# ---------------------------------------------------------------------------


def _theme_colours() -> set[str]:
    """The colour names a ``text-*`` utility can take: this theme's, plus the
    two literals Tailwind keeps whatever the theme says."""
    css = _blank_comments(GLOBALS.read_text(encoding="utf-8"), line_comments=False)
    return set(re.findall(r"--color-([a-z0-9-]+)\s*:", css)) | {"white", "black"}


def link_colours(classes: list[str]) -> list[str]:
    """The tokens that give an anchor its text colour at rest.

    Unconditional (``text-primary``) or for an anchor only
    (``[a&]:text-primary``). A hover, focus or dark-only colour is not the
    colour at rest.
    """
    colours = _theme_colours()
    found = []
    for token in classes:
        utility = utility_of(token)
        if token[: len(token) - len(utility)] not in ("", "[a&]:"):
            continue
        m = re.fullmatch(r"text-([a-z0-9-]+?)(?:/\d+)?", utility)
        if m and m.group(1) in colours:
            found.append(token)
    return found


def button_links() -> list[tuple[str, str]]:
    """(file, variant) for every ``<Button asChild>`` whose child is a link."""
    found = []
    for path in _tsx_files():
        text = _blank_comments(path.read_text(encoding="utf-8"))
        for m in re.finditer(r"<Button\b", text):
            end = _tag_end(text, m.start())
            tag = text[m.start() : end]
            if not re.search(r"\basChild\b", tag):
                continue
            if not re.match(r"\s*<(?:Link|a)\b", text[end:]):
                continue
            variant = re.search(r'\bvariant="(\w+)"', tag)
            found.append(
                (
                    path.relative_to(SRC).as_posix(),
                    variant.group(1) if variant else "default",
                )
            )
    return found


@pytest.mark.parametrize(
    ("classes", "expected"),
    [
        (["hover:bg-accent", "[a&]:text-primary"], ["[a&]:text-primary"]),
        (["bg-primary", "text-primary-foreground"], ["text-primary-foreground"]),
        (["bg-destructive", "text-white"], ["text-white"]),
        (["hover:text-accent-foreground", "dark:text-primary"], []),
        (["text-sm", "text-left", "font-medium"], []),
    ],
    ids=["anchor-only", "unconditional", "literal", "not-at-rest", "not-a-colour"],
)
def test_the_link_colour_reader(classes: list[str], expected: list[str]) -> None:
    assert link_colours(classes) == expected


def test_the_button_link_scan_reads_the_tree() -> None:
    found = set(button_links())
    # A back link at the foot of a page, and a header link to configuration.
    assert ("app/programme/candidates/[id]/page.tsx", "ghost") in found, found
    assert ("app/system/page.tsx", "outline") in found, found


def test_no_button_link_falls_back_to_the_text_colour() -> None:
    """A Button rendered as a link names its colour; it never inherits one.

    The ghost and outline variants set none, and a link built on them — the
    back links, the per-row "view", the header "Configuration" — took the
    link colour from the legacy ``a`` rule. Scoped to markup with no
    ``data-slot`` (K-15), that rule stopped reaching them, and they fell back
    to the body text, which read as plain words rather than a way out.
    """
    missing = sorted(
        {
            f"{file}: variant {variant!r}"
            for file, variant in button_links()
            if not link_colours(_variant(variant, "button.tsx"))
        }
    )
    assert not missing, (
        "These Buttons render as links in a variant that gives an anchor no "
        "colour, so they take the text colour of whatever holds them; the "
        "variant needs [a&]:text-primary, the link colour:\n  " + "\n  ".join(missing)
    )


@pytest.mark.parametrize("variant", ["ghost", "outline"])
def test_a_ghost_or_outline_link_is_the_link_colour(variant: str) -> None:
    classes = _variant(variant, "button.tsx")
    assert "[a&]:text-primary" in classes, classes
    # As a <button> — the sheet's trigger, a form's Cancel — it is an action,
    # not a link, and keeps the text colour.
    assert not [t for t in link_colours(classes) if not t.startswith("[a&]:")], classes
    # And text-primary is the colour a link in text has.
    css = _blank_comments(GLOBALS.read_text(encoding="utf-8"), line_comments=False)
    assert re.search(r"--color-primary:\s*var\(--accent\);", css)
    assert any(
        decl.get("color") == "var(--accent)"
        for selectors, decl in css_rules(base_layer(css))
        if "a:where(:not([data-slot]))" in selectors
    ), "the base link rule no longer colours a link with the accent"


# ---------------------------------------------------------------------------
# 8. Only a link in running text is underlined (A-5)
# ---------------------------------------------------------------------------

#: Where running text lives. A link in one of these is met inside a sentence,
#: and its colour alone does not tell it apart: the accent against body text
#: is 1.98:1 in dark (axe ``link-in-text-block``).
RUNNING_TEXT = ("p", "li", "td", "dd", ".banner")


def _draws_underline(declarations: dict[str, str]) -> bool:
    line = f"{declarations.get('text-decoration-line', '')} " + declarations.get(
        "text-decoration", ""
    )
    return "underline" in line.split()


def underlined_links(css: str) -> list[tuple[str, str]]:
    """(selector, container) for every base-layer rule that underlines a link.

    The container is the compound the link sits in (``p`` in ``p > a``), or
    ``""`` when the rule names none.
    """
    found = []
    for selectors, declarations in css_rules(base_layer(css)):
        if not _draws_underline(declarations):
            continue
        for selector in selectors:
            for plain in _expand(selector):
                subject = _subject(plain)
                if not re.match(r"a(?![\w-])", subject):
                    continue
                before = plain[: len(plain) - len(subject)].rstrip(" >+~")
                found.append((plain, _subject(before) if before else ""))
    return found


def _in_running_text(container: str) -> bool:
    element = re.match(r"[a-z][a-z0-9]*", container)
    if element and element.group(0) in RUNNING_TEXT:
        return True
    return any(
        re.search(rf"{re.escape(c)}(?![\w-])", container)
        for c in RUNNING_TEXT
        if c.startswith(".")
    )


def links_underlined_outside_running_text(css: str) -> list[str]:
    return [
        plain for plain, where in underlined_links(css) if not _in_running_text(where)
    ]


@pytest.mark.parametrize(
    ("css", "outside"),
    [
        # What the adopting change shipped: every link on the site.
        ("a:where(:not([data-slot])) { text-decoration-line: underline; }", 1),
        ("a { text-decoration: underline 1px; }", 1),
        ("nav a:where(:not([data-slot])) { text-decoration-line: underline; }", 1),
        ("h2 > a { text-decoration-line: underline; }", 1),
        (
            ":where(p, li, td, dd, .banner) a:where(:not([data-slot]))"
            " { text-decoration-line: underline; }",
            0,
        ),
        ("p > a:where(:not([data-slot])) { text-decoration: underline; }", 0),
        ("div.banner a { text-decoration-line: underline; }", 0),
        # Not an underline, so not this check's business.
        ("a:where(:not([data-slot])) { color: blue; text-underline-offset: 2px; }", 0),
        ("a:where(:not([data-slot])):hover { text-decoration-thickness: 2px; }", 0),
    ],
    ids=[
        "every-link",
        "shorthand",
        "navigation",
        "card-title",
        "running-text",
        "paragraph",
        "banner",
        "colour-only",
        "thickness-only",
    ],
)
def test_the_underline_check(css: str, outside: int) -> None:
    assert len(links_underlined_outside_running_text(_sheet(css))) == outside


def test_only_a_link_in_running_text_is_underlined() -> None:
    css = GLOBALS.read_text(encoding="utf-8")
    assert underlined_links(css), (
        "No rule underlines a link at all, and axe's link-in-text-block fails "
        "every link inside a sentence (web/DESIGN.md A-5)"
    )
    outside = links_underlined_outside_running_text(css)
    assert not outside, (
        "A-5 underlines a link inside running text. Navigation, the sidebar, "
        "a card's title and a Button rendered as a link are drawn by their own "
        "components, and this rule reaches them:\n  " + "\n  ".join(outside)
    )


def test_a_link_in_running_text_is_underlined() -> None:
    # The other half, and it held before the rule was narrowed: a rule that
    # names no container underlines running text along with everything else.
    covered = {
        where for _, where in underlined_links(GLOBALS.read_text(encoding="utf-8"))
    }
    missing = [] if "" in covered else [c for c in RUNNING_TEXT if c not in covered]
    assert not missing, (
        "A link inside running text is told apart by more than its colour "
        "(web/DESIGN.md A-5; axe link-in-text-block); nothing underlines one "
        f"in {missing}"
    )


def test_the_sidebar_says_no_underline_for_itself() -> None:
    # Its rows sit in list items, which are running text to the rule above.
    source = APP_NAV.read_text(encoding="utf-8")
    assert "<li" in _blank_comments(source)
    assert "no-underline" in class_tokens(source), (
        "AppNav's rows are links in list items; without no-underline the "
        "running-text rule underlines the whole sidebar"
    )


# ---------------------------------------------------------------------------
# 9. An unmet gate is amber, not red (OD-2, Q-33)
# ---------------------------------------------------------------------------

GATE_CHECKLIST = SRC / "components" / "GateChecklist.tsx"


def _glyph(variant: str) -> str | None:
    """The chip glyph for a variant, as written in globals.css (``\\25B2``)."""
    css = _blank_comments(GLOBALS.read_text(encoding="utf-8"), line_comments=False)
    m = re.search(
        rf'\[data-slot="badge"\]\[data-variant="{variant}"\]::before\s*\{{\s*'
        r'content:\s*"([^"]+)"\s*/\s*""',
        css,
    )
    return m.group(1) if m else None


def _string_mapper(source: str, name: str) -> Callable[[str], str]:
    """A ``(status: string): Status`` mapper, read as its ``if … return`` chain."""
    text = _blank_comments(source)
    m = re.search(rf"export function {name}\((\w+): string\): Status \{{", text)
    assert m, f"StatusBadge.tsx has no string mapper {name}()"
    body = text[m.end() - 1 : _balanced(text, m.end() - 1, "{", "}")]
    rules = [
        (set(re.findall(rf'\b{m.group(1)} === "(\w+)"', cond)), result)
        for cond, result in re.findall(r'if \(([^)]*)\) return "(\w+)";', body)
    ]
    fallback = re.findall(r'^\s*return "(\w+)";', body, re.M)
    assert rules and fallback, f"{name}() is no longer an if/return chain"

    def run(value: str) -> str:
        return next((r for values, r in rules if value in values), fallback[-1])

    return run


def test_caution_is_a_state_of_its_own() -> None:
    union = re.search(
        r"export type Status =\s*([^;]+);", STATUS_BADGE.read_text(encoding="utf-8")
    )
    assert union and '"caution"' in union.group(1), (
        "StatusBadge has no caution state, so a gate that has not passed must "
        "borrow `blocked` (a failure) or `unknown` (not measured)"
    )


def test_an_unmet_gate_is_caution_and_never_blocked() -> None:
    passed, unmet = _mapper(
        STATUS_BADGE.read_text(encoding="utf-8"), "promotionGateStatus"
    )
    assert (passed, unmet) == ("settled", "caution"), (
        f"A gate reads {passed!r} passed and {unmet!r} unmet. It shipped as the "
        "amber '▲ N unmet' (.pill-warn): a research gate that has not passed yet "
        "is not an alarm, and red is the owner's to extend (web/DESIGN.md Q-33)"
    )


def test_the_gate_asks_for_its_state() -> None:
    source = " ".join(
        _blank_comments(GATE_CHECKLIST.read_text(encoding="utf-8")).split()
    )
    assert "status={promotionGateStatus(gate.passed)}" in source, (
        "GateChecklist's summary chip asks StatusBadge for the gate's state "
        "(web/DESIGN.md K-2)"
    )
    assert not re.search(r'gate\.passed \? "settled" : "blocked"', source)
    # Each criterion keeps its own red: it was measured, and refused.
    assert re.search(r'criterion\.met \? "settled" : "blocked"', source)


def test_caution_is_the_amber_and_its_glyph_says_so_without_colour() -> None:
    caution, unknown = set(_variant("caution")), set(_variant("unknown"))
    # The amber text on the neutral chip that .pill-warn shared with
    # .pill-unknown: it asks to be read, and it is not a plate.
    assert {"text-unknown", "bg-panel-2"} <= caution, caution
    assert "bg-stopped" not in caution
    assert caution == unknown, (caution, unknown)
    # So the glyph carries the difference (A-6): ▲ "not yet", ? "not measured".
    assert _glyph("caution") == "\\25B2", _glyph("caution")
    assert _glyph("unknown") == "?"


def test_failures_stay_red() -> None:
    """The amber is for a gate, not for everything that is not green.

    A failed or expired job and a dead worker stay `blocked`. Whether the
    owner's reservation of red reaches them is open (web/DESIGN.md C-5,
    Q-33), and moving them to amber would render "failed" in the colour of
    "not measured".
    """
    source = STATUS_BADGE.read_text(encoding="utf-8")
    job = _string_mapper(source, "jobStatus")
    assert [job(s) for s in ("failed", "expired", "succeeded", "queued")] == [
        "blocked",
        "blocked",
        "settled",
        "mute",
    ]
    assert _mapper(source, "livenessStatus") == ("blocked", "settled")


# ---------------------------------------------------------------------------
# 10. The contract names every state the chip draws (C-5, §5.1)
# ---------------------------------------------------------------------------

DESIGN_MD = WEB / "DESIGN.md"


def _statuses(source: str) -> list[str]:
    """The states of ``StatusBadge``'s ``Status`` union, in order."""
    union = re.search(r"export type Status =\s*([^;]+);", _blank_comments(source))
    assert union, "StatusBadge.tsx exports no Status union"
    return re.findall(r'"(\w+)"', union.group(1))


def _status_mappers(source: str) -> list[str]:
    """Every exported function that answers with a ``Status``: the mappers."""
    return re.findall(
        r"export function (\w+)\([^)]*\)\s*:\s*Status\b", _blank_comments(source)
    )


def _rule_text(contract: str, rule: str) -> str:
    """One bullet rule of the contract, up to the next bullet or heading."""
    m = re.search(
        rf"^- \*\*{re.escape(rule)}\*\* · .*?(?=^- \*\*|^#|\Z)", contract, re.M | re.S
    )
    assert m, f"DESIGN.md defines no {rule}"
    return m.group(0)


def _heading_section(contract: str, heading: str) -> str:
    """A section of the contract, from its heading to the next heading."""
    m = re.search(rf"^{re.escape(heading)}.*?(?=^#{{1,4}} |\Z)", contract, re.M | re.S)
    assert m, f"DESIGN.md has no {heading!r}"
    return m.group(0)


_A_BADGE = """
/** Not a state: export type Status = "ghost"; */
export type Status =
  | "settled"
  | "caution";

export function jobStatus(status: string): Status {
  return "settled";
}
export function gateStatus(passed: boolean): Status {
  return passed ? "settled" : "caution";
}
function localStatus(x: boolean): Status {
  return "settled";
}
export function label(status: Status): string {
  return status;
}
"""

_A_CONTRACT = """## 1. Colour

- **C-5** · INFERRED · `settled`: met.
  `blocked`: refused.
- **C-6** · INFERRED · `caution` is named here, in another rule.

### 5.1 Who owns which job

- **Canonical:** `StatusBadge` and its mappers (`jobStatus`).

### 5.2 Rules

- `gateStatus` is named here, under another heading.
"""


def test_the_state_reader_reads_the_union_and_not_a_comment() -> None:
    assert _statuses(_A_BADGE) == ["settled", "caution"]


def test_the_mapper_reader_reads_exported_status_functions_only() -> None:
    assert _status_mappers(_A_BADGE) == ["jobStatus", "gateStatus"]


def test_the_contract_readers_stop_where_the_rule_and_section_end() -> None:
    rule = _rule_text(_A_CONTRACT, "C-5")
    assert "`blocked`" in rule and "`caution`" not in rule, rule
    owners = _heading_section(_A_CONTRACT, "### 5.1 ")
    assert "`jobStatus`" in owners and "`gateStatus`" not in owners, owners


def test_the_contract_gives_every_state_its_meaning() -> None:
    """
    C-5 is where a state's meaning is fixed, and a page picks a state by it.

    A state the chip draws and C-5 does not name can only be learned from the
    component's source, which the contract exists so an agent need not read.
    """
    states = _statuses(STATUS_BADGE.read_text(encoding="utf-8"))
    assert {"settled", "blocked", "unknown", "mute"} <= set(states), states
    meanings = _rule_text(DESIGN_MD.read_text(encoding="utf-8"), "C-5")
    missing = [s for s in states if f"`{s}`" not in meanings]
    assert not missing, (
        f"StatusBadge draws {missing} and web/DESIGN.md C-5 gives no meaning for "
        "it; say what it means and what keeps it apart from its neighbours, "
        "marked as the owner has or has not approved it"
    )


def test_the_contract_names_every_mapper_a_page_asks() -> None:
    """A page asks a mapper for its state (K-2); §5.1 is where it finds one."""
    mappers = _status_mappers(STATUS_BADGE.read_text(encoding="utf-8"))
    assert {"jobStatus", "livenessStatus", "killSwitchStatus"} <= set(mappers), mappers
    owners = _heading_section(DESIGN_MD.read_text(encoding="utf-8"), "### 5.1 ")
    missing = [m for m in mappers if f"`{m}`" not in owners]
    assert not missing, (
        f"StatusBadge exports {missing}, which web/DESIGN.md §5.1 does not list "
        "among its mappers, so a page that needs one will write a ternary instead"
    )

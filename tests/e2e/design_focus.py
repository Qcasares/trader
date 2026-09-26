"""
design_focus.py
---------------
The keyboard half of the focus rule (web/DESIGN.md A-4, owner decision OD-3):
every control shows the one focus indicator — a 2px accent outline at 2px
offset — and the outline clears 3:1 against what it is drawn on, in both
colour schemes.

Tabs through each page below from the top, the way an operator would, and at
every stop reads what the browser actually paints: the outline's style, width,
offset and colour on the focused element, and the colour behind it (the
parent's background, composited through every translucent layer down to the
page). Chromium serialises OKLCH colours as OKLCH, so each one is converted to
sRGB through a canvas, the way it is painted.

A stop fails when it has no solid 2px outline in the accent, or when that
outline measures under 3:1 against its backdrop. shadcn's own ring, which
this replaced, measured 1.50-2.94:1, and the date input's calendar button
showed nothing at all: on that stop the input matches neither ``:focus`` nor
``:focus-visible``, so it is checked here by name.

Not part of the pytest suites and not in CI, for the same reason as
design_capture.py: it needs the stack running.

    E2E_BASE_URL=http://localhost:3000 .venv/bin/python tests/e2e/design_focus.py

Settings: those of design_capture.py (E2E_BASE_URL, E2E_PASSWORD,
E2E_CHROMIUM, E2E_SHOTS, and E2E_IDS for the detail page below). The report is
written to E2E_SHOTS/focus_report.json.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from design_capture import BASE, CHROMIUM, IDS, SHOTS, log, sign_in, wait_ready
from playwright.sync_api import Page, sync_playwright

#: The most stops walked on one page. The dashboard's run form is the longest.
MAX_STOPS = 80

MINIMUM = 3.0

#: (slug, path, what to do first so the controls worth walking are on screen)
PAGES: list[tuple[str, str, str | None]] = [
    # "Configure & run" opens the run form, with its date inputs.
    ("dashboard", "/", "button:has-text('Configure & run')"),
    ("system", "/system", None),
    ("system-configuration", "/system/configuration", None),
    ("programme", "/programme", None),
    ("programme-findings", "/programme/findings", None),
    ("backtests", "/backtests", None),
]

#: (slug, path, E2E_IDS key). A detail page carries the back link, a ghost
#: Button rendered as a link (web/DESIGN.md K-12), which none of the pages
#: above has; the candidate page adds the gate, a link-variant Button and the
#: scorecard's scroll region. Walked when E2E_IDS names the page, as
#: design_capture.py pins it, and said to be skipped when it does not.
DETAIL_PAGES: list[tuple[str, str, str]] = [
    ("programme-candidates-id", "/programme/candidates/{}", "cand_stage1"),
]

STOP_JS = """() => {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 1;
  const ctx = canvas.getContext('2d', {willReadFrequently: true});
  const rgba = (css) => {
    ctx.clearRect(0, 0, 1, 1);
    ctx.fillStyle = '#000';
    ctx.fillStyle = css;
    ctx.fillRect(0, 0, 1, 1);
    const d = ctx.getImageData(0, 0, 1, 1).data;
    return [d[0] / 255, d[1] / 255, d[2] / 255, d[3] / 255];
  };
  const el = document.activeElement;
  if (!el || el === document.body) return null;
  const layers = [];
  for (let p = el.parentElement; p; p = p.parentElement) {
    const c = rgba(getComputedStyle(p).backgroundColor);
    if (c[3] > 0) layers.push(c);
    if (c[3] >= 1) break;
  }
  const root = getComputedStyle(document.documentElement);
  let under = [1, 1, 1];
  if (!layers.length || layers[layers.length - 1][3] < 1) {
    under = rgba(root.backgroundColor).slice(0, 3);
  }
  for (const c of layers.reverse()) {
    under = under.map((u, i) => c[3] * c[i] + (1 - c[3]) * u);
  }
  const cs = getComputedStyle(el);
  const accent = rgba(root.getPropertyValue('--accent'));
  const label = (el.getAttribute('aria-label') || el.innerText || el.value ||
                 el.getAttribute('placeholder') || '').trim().replace(/\\s+/g, ' ');
  return {
    tag: el.tagName.toLowerCase(),
    type: el.getAttribute('type') || '',
    slot: el.getAttribute('data-slot') || '',
    label: label.slice(0, 48),
    focusVisible: el.matches(':focus-visible'),
    outlineStyle: cs.outlineStyle,
    outlineWidth: cs.outlineWidth,
    outlineOffset: cs.outlineOffset,
    outline: rgba(cs.outlineColor).slice(0, 3),
    accent: accent.slice(0, 3),
    backdrop: under,
  };
}"""


def _luminance(rgb: list[float]) -> float:
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: list[float], b: list[float]) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def walk(page: Page, first: str | None) -> list[dict]:
    if first:
        page.locator(first).first.click()
        page.wait_for_timeout(400)
        # Clicked, so focus is on the button; start again from the top.
    page.evaluate("() => { document.activeElement && document.activeElement.blur(); }")
    page.evaluate("() => window.scrollTo(0, 0)")
    page.mouse.click(1, 1)  # a click that lands on nothing, so Tab starts at the top
    stops, seen = [], 0
    for n in range(1, MAX_STOPS + 1):
        page.keyboard.press("Tab")
        # Longer than the 140-150ms colour transitions: a stop is judged once it
        # has settled, and A-4r's "at once" is checked by the colour, not a race.
        page.wait_for_timeout(220)
        stop = page.evaluate(STOP_JS)
        if stop is None:
            break
        stop["n"] = n
        ratio = contrast(stop["outline"], stop["backdrop"])
        stop["ratio"] = round(ratio, 2)
        is_accent = all(
            abs(a - b) < 0.02 for a, b in zip(stop["outline"], stop["accent"])
        )
        stop["ok"] = (
            stop["outlineStyle"] == "solid"
            and stop["outlineWidth"] == "2px"
            and stop["outlineOffset"] == "2px"
            and is_accent
            and ratio >= MINIMUM
        )
        stops.append(stop)
        seen += 1
        if n > 3 and stop["tag"] == "a" and stop["label"] == "Skip to content":
            break  # wrapped round to the top
    return stops


def main() -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)
    report: dict[str, list[dict]] = {}
    failures: list[str] = []
    pages = list(PAGES)
    for slug, path, key in DETAIL_PAGES:
        if key in IDS:
            pages.append((slug, path.format(IDS[key]), None))
        else:
            log(f"skip {slug}: E2E_IDS names no {key}")
    with sync_playwright() as p, tempfile.TemporaryDirectory() as tmp:
        browser = p.chromium.launch(headless=True, executable_path=CHROMIUM)
        state = Path(tmp) / "auth.json"
        sign_in(browser, state)
        for slug, path, first in pages:
            for scheme in ("dark", "light"):
                ctx = browser.new_context(
                    viewport={"width": 1440, "height": 900},
                    color_scheme=scheme,
                    storage_state=str(state),
                )
                page = ctx.new_page()
                page.emulate_media(color_scheme=scheme)
                page.goto(BASE + path)
                wait_ready(page)
                page.add_style_tag(
                    content="nextjs-portal { display: none !important; }"
                )
                stops = walk(page, first)
                ctx.close()
                name = f"{slug}__{scheme}"
                report[name] = stops
                bad = [s for s in stops if not s["ok"]]
                dates = [s for s in stops if s["type"] == "date"]
                low = min((s["ratio"] for s in stops), default=0)
                log(
                    f"{name:36s} {len(stops):3d} stops, {len(bad)} without the "
                    f"outline, lowest {low:.2f}:1, {len(dates)} date-input stops"
                )
                failures += [
                    f"{name} stop {s['n']}: {s['tag']}"
                    f"{'[' + s['slot'] + ']' if s['slot'] else ''} {s['label']!r} — "
                    f"{s['outlineStyle']} {s['outlineWidth']}"
                    f" offset {s['outlineOffset']}, {s['ratio']}:1"
                    for s in bad
                ]
        browser.close()
    (SHOTS / "focus_report.json").write_text(json.dumps(report, indent=1))
    if failures:
        log(
            "stops without the one focus indicator (DESIGN.md A-4):\n  "
            + "\n  ".join(failures)
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

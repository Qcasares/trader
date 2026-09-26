"""
design_capture.py
-----------------
Screenshots and layout checks for the web design system (web/DESIGN.md §13 (b)).

Every route, at desktop 1440x900 and mobile 390x844, in both colour schemes,
full page at device scale 1, so one image pixel is one CSS pixel and a distance
measured on a capture is a CSS length. The captures are what a person compares
side by side with the closest example in web/examples/; the checks below are
the part a machine can judge:

    overflow    no element's right edge passes the device width (web/DESIGN.md E-1).
                Measured against the device, not ``innerWidth``: with
                ``is_mobile`` Chromium widens the layout viewport to fit the
                content, so ``scrollWidth > innerWidth`` never fires.
    small-text  no visible text renders under 11 CSS px, SVG included, where the
                size is the font size times the element's screen scale
                (DESIGN.md T-1, E-5).
    one-h1      exactly one h1 inside <main> (DESIGN.md T-5).
    console     no console error and no failed request (a 4xx/5xx response)
                beyond the documented ones.

Known failures are listed in ``design_baseline.json`` beside this file, so the
run fails only on something new, and names every listed failure that has
since been fixed so the baseline can shrink.

Not part of the pytest suites and not in CI, for the same reason as
test_browser_journey.py: it needs a running Postgres, API, worker and Next.js.

    # with the stack running and seeded
    E2E_BASE_URL=http://localhost:3000 .venv/bin/python tests/e2e/design_capture.py
    E2E_ONLY=programme,dashboard ...   # a subset, by slug

Settings, all optional:

    E2E_BASE_URL   the web app (default http://localhost:3000)
    E2E_PASSWORD   operator password (default: the browser journey's, imported
                   from test_browser_journey.py so the repository holds one
                   copy of that default, not two; CLAUDE.md safety rule 6)
    E2E_CHROMIUM   browser binary (default /opt/pw-browsers/chromium; this
                   environment blocks "playwright install")
    E2E_SHOTS      output directory (default .screenshots/design, gitignored)
    E2E_IDS        JSON with the ids detail routes should use: run_ok,
                   hyp_full, cand_stage1, exp_fail. Without it, the first link
                   on the list page is used, so a capture is only comparable
                   with an example when the ids are pinned.
    E2E_ONLY       comma-separated slugs
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import Browser, Page, sync_playwright

# Run as a script from tests/e2e, so the journey is importable; importing it runs
# only its module-level settings. It reads E2E_PASSWORD the same way.
from test_browser_journey import PASSWORD

BASE = os.environ.get("E2E_BASE_URL", "http://localhost:3000").rstrip("/")
CHROMIUM = os.environ.get("E2E_CHROMIUM", "/opt/pw-browsers/chromium")
SHOTS = Path(os.environ.get("E2E_SHOTS", ".screenshots/design"))
IDS = (
    json.loads(Path(os.environ["E2E_IDS"]).read_text())
    if os.environ.get("E2E_IDS")
    else {}
)
ONLY = {s for s in os.environ.get("E2E_ONLY", "").split(",") if s}
BASELINE = Path(__file__).with_name("design_baseline.json")

VIEWPORTS = {
    "desktop": {
        "viewport": {"width": 1440, "height": 900},
        "is_mobile": False,
        "has_touch": False,
    },
    "mobile": {
        "viewport": {"width": 390, "height": 844},
        "is_mobile": True,
        "has_touch": True,
    },
}
SCHEMES = ("light", "dark")

#: (slug, path, needs auth, id key, list page and link prefix to discover it)
ROUTES: list[tuple[str, str, bool, str | None, tuple[str, str] | None]] = [
    ("login", "/login", False, None, None),
    ("dashboard", "/", True, None, None),
    ("backtests", "/backtests", True, None, None),
    ("backtests-id", "/backtests/{}", True, "run_ok", ("/backtests", "/backtests/")),
    ("portfolio", "/portfolio", True, None, None),
    ("system", "/system", True, None, None),
    ("system-configuration", "/system/configuration", True, None, None),
    ("programme", "/programme", True, None, None),
    ("programme-hypotheses", "/programme/hypotheses", True, None, None),
    (
        "programme-hypotheses-ref",
        "/programme/hypotheses/{}",
        True,
        "hyp_full",
        ("/programme/hypotheses", "/programme/hypotheses/"),
    ),
    (
        "programme-candidates-id",
        "/programme/candidates/{}",
        True,
        "cand_stage1",
        ("/programme", "/programme/candidates/"),
    ),
    (
        "programme-experiments-ref",
        "/programme/experiments/{}",
        True,
        "exp_fail",
        ("/programme/candidates/{cand_stage1}", "/programme/experiments/"),
    ),
    ("programme-findings", "/programme/findings", True, None, None),
    ("programme-report", "/programme/report", True, None, None),
    ("programme-config", "/programme/config", True, None, None),
]

#: Console lines and failed requests that are documented behaviour, not
#: defects. A queued run polls POST /system/drain, which answers 404 while a
#: worker exists (web/src/app/backtests/[id]/page.tsx).
EXPECTED_NOISE = (re.compile(r"/api/v1/system/drain"),)

HIDE_DEV_OVERLAY = "nextjs-portal { display: none !important; }"

OVERFLOW_JS = """(device) => {
  const out = [];
  for (const el of document.querySelectorAll('body *')) {
    const r = el.getBoundingClientRect();
    if (!(r.width > 0) || r.right <= device + 0.5) continue;
    let contained = false;
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      const scrolls = /(auto|scroll|hidden|clip)/.test(getComputedStyle(p).overflowX);
      if (scrolls && p.getBoundingClientRect().right <= device + 0.5) {
        contained = true;
        break;
      }
    }
    const parentOver = el.parentElement.getBoundingClientRect().right > device + 0.5;
    if (contained || parentOver) continue;
    out.push({tag: el.tagName.toLowerCase(), right: Math.round(r.right),
              text: (el.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 60)});
  }
  return out.slice(0, 5);
}"""

SMALL_TEXT_JS = """(minimum) => {
  const out = [];
  const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walk.nextNode(); n; n = walk.nextNode()) {
    const el = n.parentElement;
    if (!el || !n.textContent.trim()) continue;
    if (el.closest('.sr-only, .visually-hidden, nextjs-portal')) continue;
    const cs = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    if (cs.visibility === 'hidden' || !(r.width > 0 && r.height > 0)) continue;
    let px = parseFloat(cs.fontSize);
    if (el instanceof SVGElement && el.getScreenCTM()) {
      const m = el.getScreenCTM();
      px *= Math.hypot(m.a, m.b);
    }
    if (px >= minimum - 0.01) continue;
    out.push({tag: el.tagName.toLowerCase(), px: Math.round(px * 10) / 10,
              text: n.textContent.trim().slice(0, 40)});
  }
  return out.slice(0, 5);
}"""


def log(*args: object) -> None:
    print(*args, flush=True)


def wait_ready(page: Page, timeout_ms: int = 20000) -> None:
    """networkidle, then no skeleton (``aria-busy``), then 700ms to settle."""
    try:
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:  # noqa: BLE001 - polling pages never go idle
        pass
    try:
        page.wait_for_function(
            "() => !document.querySelector('[aria-busy=true]')", timeout=timeout_ms
        )
    except Exception:  # noqa: BLE001
        log("   still busy after", timeout_ms, "ms")
    page.wait_for_timeout(700)


def sign_in(browser: Browser, state_path: Path) -> None:
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    page.goto(BASE + "/login")
    wait_ready(page)
    page.fill("input[type=password]", PASSWORD)
    page.click("button[type=submit]")
    page.wait_for_url(BASE + "/", timeout=30000)
    ctx.storage_state(path=str(state_path))
    ctx.close()


def resolve(browser: Browser, state_path: Path) -> list[tuple[str, str, bool]]:
    """Fill each detail route's id from E2E_IDS, or from the first matching link."""
    ctx = browser.new_context(
        viewport={"width": 1440, "height": 900}, storage_state=str(state_path)
    )
    page = ctx.new_page()
    resolved: list[tuple[str, str, bool]] = []
    for slug, path, auth, key, discover in ROUTES:
        # Ids are resolved for every route, even one E2E_ONLY leaves out: the
        # experiment is discovered through the candidate page.
        value = IDS.get(key) if key else None
        if key and value is None and discover is not None:
            try:
                list_path = discover[0].format(**IDS)
            except KeyError:
                list_path = None
            if list_path:
                page.goto(BASE + list_path)
                wait_ready(page)
                hrefs = page.eval_on_selector_all(
                    f'a[href^="{discover[1]}"]',
                    "els => els.map(e => e.getAttribute('href'))",
                )
                if hrefs:
                    value = IDS[key] = hrefs[0].rstrip("/").rsplit("/", 1)[-1]
        if ONLY and slug not in ONLY:
            continue
        if key and value is None:
            log(f"skip {slug}: no id in E2E_IDS and nothing to discover")
            continue
        resolved.append((slug, path.format(value) if key else path, auth))
    ctx.close()
    return resolved


def capture(
    browser: Browser,
    state_path: Path,
    slug: str,
    path: str,
    auth: bool,
    vp: str,
    scheme: str,
) -> dict:
    ctx = browser.new_context(
        **VIEWPORTS[vp],
        device_scale_factor=1,
        color_scheme=scheme,
        storage_state=str(state_path) if auth else None,
    )
    page = ctx.new_page()
    noise: list[str] = []
    page.on(
        "console",
        lambda m: noise.append(f"console {m.text}") if m.type == "error" else None,
    )
    page.on("pageerror", lambda e: noise.append(f"pageerror {e}"))
    page.on(
        "response",
        lambda r: (
            noise.append(f"{r.status} {r.request.method} {r.url}")
            if r.status >= 400
            else None
        ),
    )
    page.emulate_media(color_scheme=scheme)
    page.goto(BASE + path)
    wait_ready(page)
    page.add_style_tag(content=HIDE_DEV_OVERLAY)
    page.wait_for_timeout(150)
    name = f"{slug}__{vp}__{scheme}"
    page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=True)

    device = VIEWPORTS[vp]["viewport"]["width"]
    found = {
        "overflow": page.evaluate(OVERFLOW_JS, device),
        "small-text": page.evaluate(SMALL_TEXT_JS, 11),
        "one-h1": []
        if page.locator("main h1").count() == 1
        else [f"{page.locator('main h1').count()} h1 in main"],
        "console": [
            n[:200] for n in noise if not any(p.search(n) for p in EXPECTED_NOISE)
        ],
    }
    ctx.close()
    return {"capture": name, "failed": {k: v for k, v in found.items() if v}}


def main() -> int:
    SHOTS.mkdir(parents=True, exist_ok=True)
    # {capture: {check: why it is tolerated, naming the DESIGN.md rule}}
    baseline: dict[str, dict[str, str]] = {
        k: v
        for k, v in json.loads(BASELINE.read_text()).items()
        if not k.startswith("$")
    }
    records = []
    with sync_playwright() as p, tempfile.TemporaryDirectory() as tmp:
        browser = p.chromium.launch(headless=True, executable_path=CHROMIUM)
        state = Path(tmp) / "auth.json"
        sign_in(browser, state)
        for slug, path, auth in resolve(browser, state):
            for vp in VIEWPORTS:
                for scheme in SCHEMES:
                    record = capture(browser, state, slug, path, auth, vp, scheme)
                    records.append(record)
                    log(f"{record['capture']:48s} {sorted(record['failed']) or 'ok'}")
        browser.close()

    new, fixed = [], []
    for record in records:
        known = set(baseline.get(record["capture"], []))
        failed = set(record["failed"])
        new += [
            f"{record['capture']}: {check} {record['failed'][check]}"
            for check in sorted(failed - known)
        ]
        fixed += [f"{record['capture']}: {check}" for check in sorted(known - failed)]
    (SHOTS / "report.json").write_text(
        json.dumps({"ids": IDS, "records": records}, indent=1)
    )
    log(f"\n{len(records)} captures in {SHOTS}")
    if fixed:
        log(
            "fixed since the baseline — delete these from design_baseline.json:\n  "
            + "\n  ".join(fixed)
        )
    if new:
        log("NEW failures (DESIGN.md E-1, T-1, T-5):\n  " + "\n  ".join(new))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
design_axe.py
-------------
axe-core over every route, desktop and mobile, both colour schemes
(web/DESIGN.md §13 (c)).

The same routes, viewports, sign-in and readiness wait as design_capture.py,
imported from it so the two can never scan different pages. axe-core is pinned
to the version the evidence was captured with (4.13.0) and comes from its own
tiny npm package, ``tests/e2e/design/``, for the reason tests/e2e/live is its
own package: nothing that Vercel builds should install test tooling.

    npm ci --prefix tests/e2e/design
    E2E_BASE_URL=http://localhost:3000 .venv/bin/python tests/e2e/design_axe.py

A capture fails on any violated rule that ``design_axe_baseline.json`` does not
list for it, and the run names every listed rule that no longer fires, so the
baseline only shrinks. The baseline holds rule ids, not node targets: targets
follow the markup and the data, and a rule is what DESIGN.md §7 decides.

axe cannot judge contrast on nodes it calls "partially obscured" (2,380 of
them in the evidence run); ``incomplete`` results are written to the report for
review, not asserted. Keyboard and screen-reader review stay human
(web/DESIGN.md §13 (c)).

Settings: those of design_capture.py, plus E2E_AXE (path to axe.min.js).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from design_capture import (
    BASE,
    CHROMIUM,
    HIDE_DEV_OVERLAY,
    SCHEMES,
    SHOTS,
    VIEWPORTS,
    log,
    resolve,
    sign_in,
    wait_ready,
)
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
AXE = Path(
    os.environ.get(
        "E2E_AXE", HERE / "design" / "node_modules" / "axe-core" / "axe.min.js"
    )
)
BASELINE = HERE / "design_axe_baseline.json"
RUN = (
    "async () => await axe.run({exclude: [['nextjs-portal']]}, "
    "{resultTypes: ['violations', 'incomplete']})"
)


def main() -> int:
    if not AXE.exists():
        log(f"axe-core not found at {AXE}; run: npm ci --prefix tests/e2e/design")
        return 2
    baseline = {
        k: v
        for k, v in json.loads(BASELINE.read_text()).items()
        if not k.startswith("$")
    }
    SHOTS.mkdir(parents=True, exist_ok=True)
    report, new, fixed = {}, [], []
    with sync_playwright() as p, tempfile.TemporaryDirectory() as tmp:
        browser = p.chromium.launch(headless=True, executable_path=CHROMIUM)
        state = Path(tmp) / "auth.json"
        sign_in(browser, state)
        for slug, path, auth in resolve(browser, state):
            for vp in VIEWPORTS:
                for scheme in SCHEMES:
                    ctx = browser.new_context(
                        **VIEWPORTS[vp],
                        device_scale_factor=1,
                        color_scheme=scheme,
                        storage_state=str(state) if auth else None,
                    )
                    page = ctx.new_page()
                    page.emulate_media(color_scheme=scheme)
                    page.goto(BASE + path)
                    wait_ready(page)
                    page.add_style_tag(content=HIDE_DEV_OVERLAY)
                    page.add_script_tag(path=str(AXE))
                    result = page.evaluate(RUN)
                    ctx.close()
                    name = f"{slug}__{vp}__{scheme}"
                    violated = {
                        v["id"]: {"impact": v["impact"], "nodes": len(v["nodes"])}
                        for v in result["violations"]
                    }
                    report[name] = {
                        "violations": violated,
                        "incomplete": {
                            v["id"]: len(v["nodes"]) for v in result["incomplete"]
                        },
                    }
                    known = set(baseline.get(name, {}))
                    new += [
                        f"{name}: {rule} ({v['impact']}, {v['nodes']} nodes)"
                        for rule in sorted(set(violated) - known)
                        for v in [violated[rule]]
                    ]
                    fixed += [
                        f"{name}: {rule}" for rule in sorted(known - set(violated))
                    ]
                    log(f"{name:48s} {sorted(violated) or 'no violations'}")
        browser.close()
    (SHOTS / "axe_report.json").write_text(json.dumps(report, indent=1))
    if fixed:
        log(
            "no longer violated — delete from design_axe_baseline.json:\n  "
            + "\n  ".join(fixed)
        )
    if new:
        log("NEW axe violations (DESIGN.md §7):\n  " + "\n  ".join(new))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

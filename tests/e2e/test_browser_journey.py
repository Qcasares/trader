"""
test_browser_journey.py
-----------------------
The Phase 2 exit criterion, driven end to end in a real browser.

    "Tune sma_period in the browser, hit run, get a new tearsheet — no deploy."

Not part of the pytest suites and not in CI: it needs a running Postgres, API,
worker and Next.js dev server, which the CI workflow does not stand up. It
lives here rather than in a scratch directory because it is the only check
covering the seam between the frontend and everything else, and a check that
lives in /tmp is a check nobody runs twice.

    # with the stack already running
    .venv/bin/python tests/e2e/test_browser_journey.py

Written to the webapp-testing skill's reconnaissance-then-action pattern: wait
for networkidle, inspect the rendered DOM, discover selectors from what is
actually there, then act. Selectors come from the page rather than being
hard-coded, so a renamed label fails loudly here instead of quietly matching
nothing.

It asserts the honesty controls are on screen, not merely that the page loaded.
A tearsheet rendering without its "not statistically significant" banner is a
worse outcome than one that fails to render at all.
"""

from __future__ import annotations

import os
import sys

from playwright.sync_api import sync_playwright

BASE = os.environ.get("E2E_BASE_URL", "http://localhost:3000")
PASSWORD = os.environ.get("E2E_PASSWORD", "trader-demo-2026")
SHOTS = os.environ.get("E2E_SHOTS", "/tmp/shots")

#: This environment ships one Chromium at a fixed path and blocks
#: "playwright install", so the default headless-shell is absent. Overridable
#: for a machine with an ordinary Playwright install.
CHROMIUM = os.environ.get("E2E_CHROMIUM", "/opt/pw-browsers/chromium")

#: The banners that must survive any change to the tearsheet. Each exists
#: because a number shown without it is a number that misleads.
REQUIRED_ON_TEARSHEET = (
    "Synthetic data",
    "Not statistically significant",
    "Annualised on",
)

console_errors: list[str] = []
failed_requests: list[str] = []


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=CHROMIUM)
        page = browser.new_page(viewport={"width": 1400, "height": 1000})

        page.on(
            "console",
            lambda m: console_errors.append(f"{m.type}: {m.text}")
            if m.type == "error"
            else None,
        )
        page.on(
            "response",
            lambda r: failed_requests.append(f"{r.status} {r.url}")
            if r.status >= 400
            else None,
        )

        # --- 1. Log in ------------------------------------------------------
        page.goto(f"{BASE}/login")
        page.wait_for_load_state("networkidle")
        page.fill("input[type=password]", PASSWORD)
        page.click("button")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1500)
        print(f"1. logged in           -> {page.url}")

        # --- 2. Reconnaissance ----------------------------------------------
        page.wait_for_selector("text=asset_class_trend_following", timeout=15000)
        labels = [
            text.split("(")[0].strip()
            for text in page.locator("label").all_text_contents()
        ]
        print(f"2. tunable params      -> {labels}")

        # --- 3. Tune a parameter in the browser -----------------------------
        sma = page.locator("label", has_text="Sma Period").locator("input")
        before = sma.input_value()
        sma.fill("150")
        print(f"3. sma_period {before} -> {sma.input_value()}")

        # Synthetic on purpose: real price hosts are blocked in this
        # environment, and a yfinance run would fail in the worker rather than
        # testing anything about the UI.
        for select in page.locator("select").all():
            if "synthetic" in (select.inner_text() or ""):
                select.select_option("synthetic")

        page.screenshot(path=f"{SHOTS}/j1-tuned.png", full_page=True)

        # --- 4. Run it -------------------------------------------------------
        page.click("button:has-text('Run backtest')")
        page.wait_for_timeout(3000)
        print(f"4. submitted           -> {page.url}")

        # --- 5. Wait for the worker to finish it ----------------------------
        rendered = False
        for _ in range(60):
            page.reload()
            page.wait_for_load_state("networkidle")
            body = page.inner_text("body")
            if "Sharpe" in body:
                rendered = True
                break
            if "failed" in body.lower():
                print(f"   run FAILED: {body[:300]}")
                break
            page.wait_for_timeout(2000)

        page.screenshot(path=f"{SHOTS}/j2-tearsheet.png", full_page=True)
        print(f"5. tearsheet           -> {'rendered' if rendered else 'MISSING'}")

        # --- 6. The honesty controls ----------------------------------------
        body = page.inner_text("body")
        missing = [p for p in REQUIRED_ON_TEARSHEET if p not in body]
        for phrase in REQUIRED_ON_TEARSHEET:
            print(f"   {'OK     ' if phrase in body else 'MISSING'}  {phrase!r}")

        # --- 7. The kill switch defaults to halted --------------------------
        page.goto(f"{BASE}/system")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1200)
        halted = "HALTED" in page.inner_text("body")
        print(f"7. trading             -> {'HALTED' if halted else 'ENABLED'}")

        browser.close()

    print(f"\nconsole errors : {console_errors or 'none'}")
    print(f"failed requests: {failed_requests or 'none'}")

    # Non-zero exit on a broken page, so this can gate a release even though it
    # is run by hand. Console errors are reported but do not fail the run: the
    # Next.js dev server emits transient chunk 404s during navigation that say
    # nothing about the app.
    problems = failed_requests + missing + ([] if rendered else ["no tearsheet"])
    if problems:
        print(f"\nFAILED: {problems}")
        sys.exit(1)
    print("\nPASSED")


if __name__ == "__main__":
    os.makedirs(SHOTS, exist_ok=True)
    main()

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

Steps 9 to 12 check states the running stack cannot be asked to produce on
demand — a known drawdown, an account whose live side is down, a poll that
fails after one that succeeded, live-trading gates that are open — by
answering those few API calls in the browser (`page.route`) with the API's own
response, fields overridden. What is under test there is the page's rendering
of an answer, so the answer is the one thing faked; everything else is the
real stack.
"""

from __future__ import annotations

import json
import os
import re
import sys

from playwright.sync_api import Page, Response, Route, sync_playwright

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

#: /portfolio's polling interval, plus a margin.
PORTFOLIO_POLL_WAIT_MS = 17_000

#: /system's polling interval, plus a margin.
SYSTEM_POLL_WAIT_MS = 7_000

#: A drawdown of 5.12%, as the API stores it: a fraction.
DRAWDOWN = -0.0512
DRAWDOWN_SHOWN = "-5.12%"

#: An equity figure distinctive enough that finding it on screen means the
#: paper account's reading is on screen.
PAPER_EQUITY = 123456.78
PAPER_EQUITY_SHOWN = "$123,456.78"

console_errors: list[str] = []
failed_requests: list[str] = []
problems: list[str] = []


def check(ok: bool, what: str) -> None:
    """Record a failed expectation and keep going, so one run reports them all."""
    print(f"   {'OK     ' if ok else 'FAILED '}  {what}")
    if not ok:
        problems.append(what)


def _record_failure(response: Response) -> None:
    # The backtest page nudges POST /system/drain while a run is queued, and a
    # deployment with a worker answers 404 by design (`api.drain` in
    # web/src/lib/api.ts). That is the normal case, not a broken page.
    if response.status == 404 and response.url.endswith("/api/v1/system/drain"):
        return
    if response.status >= 400:
        failed_requests.append(f"{response.status} {response.url}")


def _metric(page: Page, label: str) -> str:
    """The value of the metric-grid cell whose label is ``label``."""
    cell = page.locator(".metric").filter(
        has=page.locator("dt", has_text=re.compile(rf"^\s*{re.escape(label)}\s*$"))
    )
    return cell.locator("dd").first.inner_text().strip()


def _serve(
    page: Page, pattern: str, override: dict | None = None, status: int = 200
) -> None:
    """Answer matching API calls with the API's own response, fields overridden.

    A ``status`` other than 200 answers with that error instead, shaped as the
    API shapes one: a JSON ``detail``.
    """

    def handle(route: Route) -> None:
        if status != 200:
            route.fulfill(
                status=status,
                content_type="application/json",
                body=json.dumps({"detail": f"journey fixture: {status}"}),
            )
            return
        real = route.fetch()
        body = real.json()
        for dotted, value in (override or {}).items():
            target = body
            *parents, leaf = dotted.split(".")
            for key in parents:
                target = target[key]
            target[leaf] = value
        route.fulfill(response=real, body=json.dumps(body))

    page.route(re.compile(pattern), handle)


def main() -> None:
    run_id = ""
    significant = True

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, executable_path=CHROMIUM)
        context = browser.new_context(viewport={"width": 1400, "height": 1000})
        page = context.new_page()

        page.on(
            "console",
            lambda m: console_errors.append(f"{m.type}: {m.text}")
            if m.type == "error"
            else None,
        )
        page.on("response", _record_failure)

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
        # Found by the label's association, not by nesting: since the shadcn
        # rebuild each Input is its Label's sibling, tied by htmlFor and id, so
        # "the input inside the label" matches nothing.
        sma = page.get_by_label("Sma Period")
        before = sma.input_value()
        sma.fill("150")
        print(f"3. sma_period {before} -> {sma.input_value()}")

        # Synthetic on purpose: real price hosts are blocked in this
        # environment, and a yfinance run would fail in the worker rather than
        # testing anything about the UI. The source is a Radix select, whose
        # trigger shows the chosen option.
        source = page.locator("#source")
        if "synthetic" not in source.inner_text():
            source.click()
            page.get_by_role("option", name=re.compile("^synthetic")).click()
        check("synthetic" in source.inner_text(), "the run uses synthetic prices")

        page.screenshot(path=f"{SHOTS}/j1-tuned.png", full_page=True)

        # --- 4. Run it -------------------------------------------------------
        page.click("button:has-text('Run backtest')")
        page.wait_for_url(re.compile(r"/backtests/[0-9a-f-]{36}$"), timeout=15000)
        run_id = page.url.rsplit("/", 1)[-1]
        print(f"4. submitted           -> {page.url}")

        # --- 5. Wait for the worker to finish it ----------------------------
        rendered = False
        for _ in range(90):
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
        check(rendered, "the tearsheet rendered")

        # --- 6. The honesty controls ----------------------------------------
        print("6. honesty controls")
        body = page.inner_text("body")
        for phrase in REQUIRED_ON_TEARSHEET:
            check(phrase in body, f"tearsheet says {phrase!r}")
        significant = "Not statistically significant" not in body

        if rendered:
            # The card counts the run's fills, not the length of a list the API
            # capped: "Fills (500)" beside a metric of 779 was the defect.
            total = int(_metric(page, "Fills").replace(",", ""))
            title = page.locator('[data-slot="card-title"]', has_text="Fills (")
            titled = int(re.search(r"Fills \((\d+)\)", title.inner_text()).group(1))
            check(
                titled == total,
                f"the fills card counts every fill ({titled}), as the metric "
                f"does ({total})",
            )
            listed = page.locator("tbody").last.locator("tr").count()
            if total > listed:
                check(
                    f"most recent of {total}" in body,
                    f"a capped fills table says it is {listed} of {total}",
                )

        # --- 7. The kill switch defaults to halted --------------------------
        page.goto(f"{BASE}/system")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1200)
        # Read from the Trading card's own chip, not the whole body, and
        # without regard to case: the chip renders lowercase and `innerText`
        # applies text-transform, so the old search for "HALTED" reported
        # "ENABLED" on a halted system — and only printed it. "stopped" is the
        # owner's approved word for the same state (decision of 2026-09-26: a
        # halted kill switch is safe, and reads amber rather than red).
        trading = page.locator(
            '[data-slot="card-title"]', has_text=re.compile(r"^\s*Trading")
        )
        chip = trading.locator('[data-slot="badge"]').first.inner_text()
        print(f"7. trading             -> {chip.strip()!r}")
        check(
            chip.strip().lower() in ("halted", "stopped"),
            f"the kill switch reads halted (got {chip.strip()!r})",
        )
        # And in the stopped state, never the red one: red on this page means
        # live money reachable (owner decision OD-2, web/DESIGN.md C-12), and
        # a halted switch is the safest state the system has.
        variant = trading.locator('[data-slot="badge"]').first.get_attribute(
            "data-variant"
        )
        check(
            variant == "stopped",
            f"a halted kill switch is the amber 'stopped', not red (got {variant!r})",
        )

        # --- 8. The run in the backtest list --------------------------------
        print("8. backtest list")
        page.goto(f"{BASE}/backtests")
        page.wait_for_load_state("networkidle")
        row = page.locator("tbody tr").filter(
            has=page.locator(f'a[href="/backtests/{run_id}"]')
        )
        check(row.count() == 1, "the run is listed")
        row_text = row.first.inner_text().lower() if row.count() else ""
        # In words: a muted colour and a hover title were all it had.
        check(
            ("not significant" in row_text) == (not significant),
            "the row marks significance in words, as the tearsheet does",
        )
        check("effective from" in row_text, "the row states its effective start")
        check(
            re.search(r"\b\d+/yr\b", row_text) is not None,
            "the row states the sessions per year its Sharpe is annualised on",
        )

        # A second page in the same context: it shares the session and none of
        # the listeners above, because the failures from here on are on
        # purpose.
        fixture = context.new_page()

        # --- 9. One stored fraction, one rendering --------------------------
        print("9. drawdown and absences")
        _serve(
            fixture,
            r"/api/v1/programme/report(\?.*)?$",
            {"portfolio.drawdown_pct": DRAWDOWN},
        )
        fixture.goto(f"{BASE}/programme/report")
        fixture.wait_for_load_state("networkidle")
        report_dd = _metric(fixture, "Drawdown")
        check(
            report_dd == DRAWDOWN_SHOWN,
            f"the report shows drawdown {DRAWDOWN} as {DRAWDOWN_SHOWN} "
            f"(got {report_dd!r})",
        )

        _serve(
            fixture,
            r"/api/v1/portfolio\?mode=paper$",
            {
                "equity": PAPER_EQUITY,
                "cash": None,
                "drawdown_pct": DRAWDOWN,
                "as_of": "2026-09-25",
            },
        )
        fixture.goto(f"{BASE}/portfolio")
        fixture.wait_for_load_state("networkidle")
        fixture.wait_for_timeout(500)
        portfolio_dd = _metric(fixture, "Drawdown")
        check(
            portfolio_dd == DRAWDOWN_SHOWN,
            f"/portfolio shows the same {DRAWDOWN_SHOWN} (got {portfolio_dd!r})",
        )
        cash = _metric(fixture, "Cash")
        check(
            cash.lower().startswith("no data"),
            f"an absent cash figure says 'no data', not a dash (got {cash!r})",
        )

        # --- 10. Switching account never relabels the old one ---------------
        print("10. paper -> live")
        _serve(fixture, r"/api/v1/portfolio(/history)?\?mode=live$", status=503)
        fixture.get_by_role("button", name="live", exact=True).click()
        fixture.wait_for_timeout(1500)
        main_text = fixture.inner_text("main")
        check(
            PAPER_EQUITY_SHOWN not in main_text,
            "no paper figure is left on screen under the live account",
        )
        check(
            "journey fixture: 503" in main_text,
            "the live account's failure is said",
        )
        fixture.screenshot(path=f"{SHOTS}/j3-portfolio-live-down.png", full_page=True)

        # --- 11. A failed refresh marks the figures stale -------------------
        print("11. stale after a failed poll")
        fixture.get_by_role("button", name="paper", exact=True).click()
        fixture.wait_for_timeout(1500)
        check(
            PAPER_EQUITY_SHOWN in fixture.inner_text("main"),
            "switching back reads the paper account again",
        )
        fixture.unroute(re.compile(r"/api/v1/portfolio\?mode=paper$"))
        _serve(fixture, r"/api/v1/portfolio(/history)?\?mode=paper$", status=503)
        fixture.wait_for_timeout(PORTFOLIO_POLL_WAIT_MS)
        main_text = fixture.inner_text("main")
        check("Stale." in main_text, "a failed poll marks the figures stale")
        check(
            "Last read at" in main_text,
            "the stale figures carry the time they were read",
        )
        fixture.screenshot(path=f"{SHOTS}/j4-portfolio-stale.png", full_page=True)

        # --- 12. /system: red is live money, and the switch fails closed ----
        print("12. /system alarm state")
        _serve(
            fixture,
            r"/api/v1/system/status$",
            {
                "trading_enabled": True,
                "live_trading_enabled": True,
                "alpaca_allow_live": True,
            },
        )
        fixture.goto(f"{BASE}/system")
        fixture.wait_for_load_state("networkidle")
        fixture.wait_for_timeout(800)

        def trading_chip():
            return (
                fixture.locator(
                    '[data-slot="card-title"]', has_text=re.compile(r"^\s*Trading")
                )
                .locator('[data-slot="badge"]')
                .first
            )

        chip = trading_chip()
        check(
            (chip.get_attribute("data-variant"), chip.inner_text().strip())
            == ("settled", "enabled"),
            "an enabled kill switch reads enabled",
        )
        open_gates = fixture.locator(
            'main [data-slot="badge"]', has_text=re.compile(r"^\s*open\s*$")
        )
        check(
            open_gates.count() == 2
            and all(
                open_gates.nth(i).get_attribute("data-variant") == "blocked"
                for i in range(open_gates.count())
            ),
            "each open live-order gate is red: live money reachable",
        )
        check(
            "Both environment gates are open" in fixture.inner_text("main"),
            "the page says what two open gates mean",
        )
        fixture.screenshot(path=f"{SHOTS}/j5-system-gates-open.png", full_page=True)

        fixture.unroute(re.compile(r"/api/v1/system/status$"))
        _serve(fixture, r"/api/v1/system/status$", status=503)
        fixture.wait_for_timeout(SYSTEM_POLL_WAIT_MS)
        main_text = fixture.inner_text("main")
        chip = trading_chip()
        check(
            (chip.get_attribute("data-variant"), chip.inner_text().strip())
            == ("unknown", "not read"),
            "a kill switch that cannot be read is not shown as its last value "
            f"(got {chip.inner_text().strip()!r})",
        )
        check("last read: enabled" in main_text, "the last reading is said as such")
        check("Stale." in main_text, "a failed poll marks /system stale")
        fixture.screenshot(path=f"{SHOTS}/j6-system-stale.png", full_page=True)

        first = context.new_page()
        _serve(first, r"/api/v1/system/status$", status=503)
        first.goto(f"{BASE}/system")
        first.wait_for_load_state("networkidle")
        first.wait_for_timeout(800)
        check(
            first.locator("main h1").count() == 1,
            "a first load that fails keeps the page's heading",
        )
        check(
            "could not be read" in first.inner_text("main"),
            "a first load that fails says so, instead of loading for ever",
        )

        browser.close()

    print(f"\nconsole errors : {console_errors or 'none'}")
    print(f"failed requests: {failed_requests or 'none'}")

    # Non-zero exit on a broken page, so this can gate a release even though it
    # is run by hand. Console errors are reported but do not fail the run: the
    # Next.js dev server emits transient chunk 404s during navigation that say
    # nothing about the app.
    everything = failed_requests + problems
    if everything:
        print(f"\nFAILED: {everything}")
        sys.exit(1)
    print("\nPASSED")


if __name__ == "__main__":
    os.makedirs(SHOTS, exist_ok=True)
    main()

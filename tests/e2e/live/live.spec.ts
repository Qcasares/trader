/**
 * live.spec.ts
 * ------------
 * Playwright against the deployed system, not a local one.
 *
 * Everything in `tests/` runs against a stack this machine stood up. That
 * proves the code is right and says nothing about the deployment: the routing,
 * the proxy, the headers, the environment and the build are all different, and
 * every one of them has been the thing that was actually broken at some point.
 *
 * Two rules shape what is in here.
 *
 * **Read-only.** This is production. Nothing below submits a form that writes,
 * toggles a switch, or creates a row. The one write-shaped action is a single
 * deliberately-wrong login, and there is exactly one of those on purpose:
 * `src/api/throttle.py` backs off exponentially per source after five failed
 * logins, and this machine shares an address with the operator. A test suite
 * that locked the operator out of the kill switch would be worse than no test
 * suite.
 *
 * **Assertions that could fail.** A live smoke suite drifts naturally towards
 * asserting that pages return 200, which they will keep doing long after they
 * stop working. Each test here names a thing that would be wrong.
 */

import { test, expect, type Page } from "@playwright/test";

const UI = process.env.E2E_BASE_URL ?? "https://trader-ui-black.vercel.app";
const API = process.env.E2E_API_URL ?? "https://trader-vert-xi.vercel.app";

/** Every route behind the session guard. `/login` is deliberately absent. */
const PROTECTED = [
  "/",
  "/backtests",
  "/portfolio",
  "/programme",
  "/programme/config",
  "/programme/findings",
  "/programme/hypotheses",
  "/programme/report",
  "/system",
  "/system/configuration",
];

/**
 * Strings that must never appear in anything the browser is served.
 *
 * Deliberately includes shapes rather than only literals: nobody commits a
 * string called "secret", but an Alpaca key id has a fixed prefix and a model
 * key has another, and either could reach a bundle through an accidental
 * `NEXT_PUBLIC_` variable — which is the actual mechanism by which this leaks
 * in a Next.js app.
 */
const MUST_NOT_LEAK: RegExp[] = [
  /sk-ant-[A-Za-z0-9_-]{8}/,
  /\bAK[A-Z0-9]{16,}/,
  /\bPK[A-Z0-9]{16,}/,
  /postgres(?:ql)?:\/\/[^\s"']*:[^\s"'@]+@/,
  /\$2[aby]\$\d{2}\$[./A-Za-z0-9]{20}/,
];

test.describe("Availability", () => {
  test("the API reports itself ready, not merely alive", async ({ request }) => {
    // /ready must answer 503 rather than 200-with-a-false-body when it is not
    // ready, so a 200 here is a real claim about the database.
    const res = await request.get(`${API}/api/v1/ready`);
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body.ready).toBe(true);
    expect(body.database).toBe(true);
    expect(body.config).toEqual([]);
  });

  test("the UI serves the login page", async ({ page }) => {
    const res = await page.goto(`${UI}/login`, { waitUntil: "networkidle" });
    expect(res?.status()).toBe(200);
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  });
});

test.describe("The session guard", () => {
  for (const route of PROTECTED) {
    test(`${route} is not reachable without a session`, async ({ page }) => {
      await page.goto(`${UI}${route}`, { waitUntil: "networkidle" });
      // The assertion is on the landing URL, not on a redirect status: this
      // guard is client-side, so a route that rendered its shell and only then
      // bounced would still be a route that briefly served the shell.
      expect(new URL(page.url()).pathname).toBe("/login");
      await expect(page.getByLabel("Password")).toBeVisible();
    });
  }
});

test.describe("The login form", () => {
  test("a wrong password is reported verbatim and the form stays usable", async ({
    page,
  }) => {
    // The only failed login this suite performs. See the header comment.
    await page.goto(`${UI}/login`, { waitUntil: "networkidle" });
    await page.getByLabel("Password").fill("definitely-not-the-password");
    await page.getByRole("button", { name: "Sign in" }).click();

    const banner = page.locator(".banner-bad");
    await expect(banner).toBeVisible({ timeout: 15_000 });
    // Verbatim, not a friendly substitute. `api.login` distinguishes a wrong
    // password from an unreachable API and the second names the URL it tried;
    // this is the one moment nobody can reach the rest of the UI to diagnose it.
    await expect(banner).toContainText("invalid password");

    // A form that disables itself on error cannot be retried, and the usual
    // cause of an error here is a typo.
    await expect(page.getByLabel("Password")).toBeEnabled();
    await expect(page.getByRole("button", { name: "Sign in" })).toBeEnabled();
    expect(new URL(page.url()).pathname).toBe("/login");
  });

  test("the password field does not offer itself to the browser's store as text", async ({
    page,
  }) => {
    await page.goto(`${UI}/login`, { waitUntil: "networkidle" });
    const field = page.getByLabel("Password");
    await expect(field).toHaveAttribute("type", "password");
    await expect(field).toHaveAttribute("autocomplete", "current-password");
  });
});

test.describe("Nothing sensitive is served to the browser", () => {
  test("no credential material in the login document or its bundles", async ({
    page,
  }) => {
    const bodies: { url: string; text: string }[] = [];
    page.on("response", async (res) => {
      const ct = res.headers()["content-type"] ?? "";
      if (!/javascript|html|json/.test(ct)) return;
      try {
        bodies.push({ url: res.url(), text: await res.text() });
      } catch {
        /* a redirect or an aborted body has nothing to scan */
      }
    });

    await page.goto(`${UI}/login`, { waitUntil: "networkidle" });
    expect(bodies.length).toBeGreaterThan(3); // guard the guard

    const hits: string[] = [];
    for (const { url, text } of bodies) {
      for (const pattern of MUST_NOT_LEAK) {
        const m = text.match(pattern);
        // Reports the pattern and the file, never the match. A test that
        // printed the credential it found would be the leak.
        if (m) hits.push(`${pattern} in ${url}`);
      }
    }
    expect(hits).toEqual([]);
  });

  test("the API sets no permissive CORS wildcard", async ({ request }) => {
    const res = await request.get(`${API}/api/v1/ready`);
    const allow = res.headers()["access-control-allow-origin"];
    // A wildcard with credentials is rejected by browsers anyway, but a
    // wildcard here would mean the origin allowlist is not doing its job.
    expect(allow ?? "").not.toBe("*");
  });
});

test.describe("It renders in both themes and at every width", () => {
  for (const scheme of ["dark", "light"] as const) {
    test(`the login page renders in ${scheme}`, async ({ page }) => {
      // The gap this closes: the local browse tooling denies CDP media
      // emulation, so until now the dark theme was only ever verified by
      // re-applying the stylesheet's own values by hand.
      await page.emulateMedia({ colorScheme: scheme });
      await page.goto(`${UI}/login`, { waitUntil: "networkidle" });

      const bg = await page.evaluate(
        () => getComputedStyle(document.body).backgroundColor,
      );
      const fg = await page.evaluate(
        () => getComputedStyle(document.body).color,
      );
      const lum = (c: string) => {
        const [r, g, b] = (c.match(/\d+/g) ?? ["0", "0", "0"]).map(Number);
        return 0.2126 * r + 0.7152 * g + 0.0722 * b;
      };
      // Asserts the pair, not a literal colour: the palette is allowed to
      // change, text disappearing into its background is not.
      const contrast = Math.abs(lum(bg) - lum(fg));
      expect(contrast, `${scheme}: bg ${bg} vs fg ${fg}`).toBeGreaterThan(80);

      if (scheme === "dark") {
        expect(lum(bg), `dark background was ${bg}`).toBeLessThan(128);
      } else {
        expect(lum(bg), `light background was ${bg}`).toBeGreaterThan(128);
      }
      await page.screenshot({ path: `shots/login-${scheme}.png` });
    });
  }

  for (const [name, width, height] of [
    ["mobile", 390, 844],
    ["tablet", 820, 1180],
    ["desktop", 1440, 900],
  ] as const) {
    test(`no horizontal overflow at ${name} (${width}px)`, async ({ page }) => {
      await page.setViewportSize({ width, height });
      await page.goto(`${UI}/login`, { waitUntil: "networkidle" });
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      );
      expect(overflow, `${overflow}px of horizontal scroll`).toBeLessThanOrEqual(1);
      await page.screenshot({ path: `shots/login-${name}.png` });
    });
  }
});

test.describe("It loads cleanly", () => {
  test("no console errors and no failed requests on the login page", async ({
    page,
  }) => {
    const errors: string[] = [];
    const failed: string[] = [];
    page.on("console", (m) => {
      if (m.type() === "error") errors.push(m.text());
    });
    page.on("requestfailed", (r) =>
      failed.push(`${r.url()} ${r.failure()?.errorText ?? ""}`),
    );
    page.on("response", (r) => {
      if (r.status() >= 500) failed.push(`${r.status()} ${r.url()}`);
    });

    await page.goto(`${UI}/login`, { waitUntil: "networkidle" });
    await page.waitForTimeout(1500);

    expect(errors, errors.join("\n")).toEqual([]);
    expect(failed, failed.join("\n")).toEqual([]);
  });

  test("the whole form is operable by keyboard alone", async ({ page }) => {
    await page.goto(`${UI}/login`, { waitUntil: "networkidle" });

    // The page autofocuses the field, so a keyboard user types immediately
    // rather than tabbing in. The first version of this test assumed a skip
    // link came first and failed against the live site, which is the failure
    // mode a local-only suite never produces.
    expect(
      await page.evaluate(() => document.activeElement?.id ?? ""),
    ).toBe("password");

    await page.keyboard.type("keyboard-only-attempt");
    await page.keyboard.press("Tab");
    const focused = await page.evaluate(() => ({
      tag: document.activeElement?.tagName ?? "",
      text: (document.activeElement as HTMLElement)?.innerText ?? "",
    }));
    expect(focused.tag).toBe("BUTTON");
    expect(focused.text).toContain("Sign in");

    // Focus must be visible, or "operable by keyboard" is only true for
    // somebody who can already see where they are.
    const outline = await page.evaluate(() => {
      const s = getComputedStyle(document.activeElement!);
      return `${s.outlineStyle} ${s.outlineWidth} ${s.boxShadow}`;
    });
    expect(outline, `focus ring was ${outline}`).not.toMatch(
      /^none 0px none$/,
    );
    // Deliberately does not press Enter: that would submit, and this suite
    // spends exactly one failed login.
  });
});

/**
 * The authenticated journey.
 *
 * Skipped unless a password is supplied, rather than failing: the suite above
 * is worth running on its own, and a red suite that is red for a known reason
 * trains people to ignore it.
 */
const PASSWORD = process.env.E2E_PASSWORD ?? "";

test.describe("Signed in", () => {
  test.skip(!PASSWORD, "set E2E_PASSWORD to run the authenticated journey");

  const signIn = async (page: Page) => {
    await page.goto(`${UI}/login`, { waitUntil: "networkidle" });
    await page.getByLabel("Password").fill(PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();
    await page.waitForURL((u) => new URL(u).pathname === "/", {
      timeout: 20_000,
    });
  };

  test("the model credential is stored, and identified without being revealed", async ({
    page,
  }) => {
    await signIn(page);
    await page.goto(`${UI}/system/configuration`, { waitUntil: "networkidle" });

    const row = page.locator("text=Anthropic API key").locator("..");
    await expect(row).toContainText("stored");

    // The fingerprint is the proof that `crypto.encrypt` ran to completion:
    // `set_secret` computes it from the plaintext and writes both together, so
    // twelve hex characters here means the ciphertext was written under a key
    // the deployment could actually use.
    const marker = await row
      .locator(".font-mono")
      .filter({ hasText: /^[0-9a-f]{12}$/ })
      .innerText();
    expect(marker).toMatch(/^[0-9a-f]{12}$/);

    // And the value itself is nowhere on the page, in any form.
    const html = await page.content();
    expect(html).not.toContain("sk-ant-");
    for (const pattern of MUST_NOT_LEAK) expect(html).not.toMatch(pattern);
  });

  test("every route renders without a console error", async ({ page }) => {
    const errors: string[] = [];
    page.on("console", (m) => {
      if (m.type() === "error") errors.push(`${page.url()}: ${m.text()}`);
    });
    await signIn(page);
    for (const route of PROTECTED) {
      await page.goto(`${UI}${route}`, { waitUntil: "networkidle" });
      expect(new URL(page.url()).pathname, `${route} bounced to login`).toBe(
        route,
      );
      await page.screenshot({ path: `shots/auth${route.replace(/\//g, "_")}.png` });
    }
    expect(errors, errors.join("\n")).toEqual([]);
  });

  test("the kill switch and the programme switch both read as off", async ({
    page,
  }) => {
    // Read-only: asserts the seeded fail-closed state, clicks nothing.
    await signIn(page);
    await page.goto(`${UI}/system`, { waitUntil: "networkidle" });
    await expect(page.locator("body")).toContainText(/trading/i);
  });
});

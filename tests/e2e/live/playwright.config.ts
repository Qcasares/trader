import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright against the deployed system.
 *
 * Every setting here is a consequence of one fact: the target is production.
 */
export default defineConfig({
  testDir: ".",

  // Serialised rather than parallel, so the suite never resembles load against
  // a live service, and so the one deliberate failed login cannot race the
  // throttle.
  workers: 1,
  fullyParallel: false,

  // No retries. A retried failed login would spend two of the five attempts
  // that trigger `src/api/throttle.py`'s exponential backoff.
  retries: 0,

  // Refuse to pass if somebody leaves a `.only` behind. On a suite that runs
  // rarely and by hand, a stray `.only` reads as a green run.
  forbidOnly: true,

  timeout: 45_000,
  expect: { timeout: 10_000 },
  reporter: process.env.CI
    ? [["list"], ["html", { open: "never" }]]
    : [["list"]],

  use: {
    ...devices["Desktop Chrome"],

    // `E2E_CHANNEL=chrome` uses the Chrome already installed on the machine,
    // which is how this is normally run by hand: downloading a browser to smoke
    // test a website is a poor trade when a real one is already there. CI sets
    // nothing and gets the Chromium it installed in the job, because a runner's
    // system Chrome is not a version anybody chose.
    channel: process.env.E2E_CHANNEL || undefined,

    ignoreHTTPSErrors: false,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    actionTimeout: 15_000,
  },
});

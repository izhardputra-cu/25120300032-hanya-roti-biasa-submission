import { defineConfig, devices } from '@playwright/test'

// Real HTTPS checks against the deployed Cloud Run service. The base URL and
// the shared demo seller password come from the operator environment; neither
// is stored in this repository. No webServer is started: the remote service is
// the system under test.
//
// Measured limits of the reporting setup (see docs/testing/t2-remediation.md):
// - Playwright's HTML reporter embeds a full run payload (steps, params,
//   attachments) as a ZIP inside index.html, and that payload leaked a
//   submitted password during T2. Credential-bearing runs therefore use only
//   the `list` reporter plus `support/clean-reporter.js`, which writes status,
//   duration, and attachment counts.
// - `trace: 'off'` and `video: 'off'` only mean those channels are absent. They
//   do not make a run secret-free: Playwright still writes `error-context.md`,
//   whose "Error details" can quote action parameters and whose page snapshot
//   shows current password field values. `support/secrets.js` avoids
//   logged fill parameters via a probe-tested evaluate call and closes pages
//   during teardown.
// - Nothing here is a global non-disclosure guarantee. It covers artifacts and
//   stdout/stderr of this configuration, proven by
//   `scripts/check-e2e-artifacts.sh` with a synthetic canary, including
//   negative controls.
//
// `process.umask(0o077)` makes runner-created artifacts private (0600 files in
// 0700 directories) even before any later chmod.
process.umask(0o077)

export default defineConfig({
  testDir: './e2e-cloud',
  testMatch: 'auth.spec.js',
  outputDir: '../.local/t2-deploy/playwright-cloud-results',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [
    ['list'],
    ['./e2e-cloud/support/clean-reporter.js', { outputFile: '../.local/t2-deploy/cloud-summary.json' }],
  ],
  use: {
    baseURL: process.env.T2_BASE_URL,
    channel: 'chromium',
    launchOptions: { args: ['--disable-gpu'] },
    trace: 'off',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  projects: [
    {
      name: 'cloud-desktop',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1280, height: 900 } },
    },
  ],
})

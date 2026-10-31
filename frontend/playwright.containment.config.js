import cloudConfig from './playwright.cloud.config.js'

// Containment harness configuration. It *imports the cloud config* instead of
// copying its settings, so the canary gate exercises the same reporter,
// browser channel, screenshot policy, and trace/video switches that a
// credential-bearing run uses. Only the paths, test directory, and the
// per-scenario budgets are overridden here.
//
// No web server and no network: the inline page is the system under test.

const out = process.env.CONTAINMENT_OUT

if (!out) {
  throw new Error('Set CONTAINMENT_OUT to an output directory for this run')
}

const spec = process.env.CONTAINMENT_SPEC || 'credential-artifacts.spec.js'

export default {
  ...cloudConfig,
  testDir: './e2e-containment',
  testMatch: [spec],
  outputDir: `${out}/results`,
  // Shorter than the cloud budget so a fill-level timeout and an in-flight
  // timeout are cheap; the failure shapes are the same.
  timeout: 20_000,
  expect: { timeout: 3_000 },
  reporter: [
    ['list'],
    ['./e2e-cloud/support/clean-reporter.js', { outputFile: `${out}/summary.json` }],
  ],
}

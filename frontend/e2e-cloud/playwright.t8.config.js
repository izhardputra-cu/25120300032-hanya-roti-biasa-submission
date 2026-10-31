import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { devices } from '@playwright/test'
import base from '../playwright.cloud.config.js'

// T8 release run against the final public service. It imports the gated cloud
// configuration so the reporter, umask, trace/video switches and screenshot
// policy stay identical; only output locations, test selection and the mobile
// project are overridden. T2 evidence is never overwritten.
const here = dirname(fileURLToPath(import.meta.url))
const root = resolve(here, '../..')
process.env.CLOUD_RUN_OUT ||= resolve(
  root, '.local/t8-evidence', `run-${Date.now()}-${process.pid}`,
)
const out = resolve(process.env.CLOUD_RUN_OUT)
process.env.CLOUD_EVIDENCE_DIR ||= resolve(out, 'screenshots')

export default {
  ...base,
  testDir: './',
  timeout: 120_000,
  outputDir: resolve(out, 'results'),
  reporter: [
    ['list'],
    [
      resolve(here, 'support/clean-reporter.js'),
      { outputFile: resolve(out, 'summary.json') },
    ],
  ],
  projects: [
    {
      name: 'cloud-desktop',
      use: { ...base.projects[0].use },
      testMatch: /(auth|t8-flows)\.spec\.js/,
    },
    {
      name: 'cloud-mobile',
      use: { ...devices['Pixel 5'] },
      testMatch: /t8-mobile\.spec\.js/,
    },
  ],
}

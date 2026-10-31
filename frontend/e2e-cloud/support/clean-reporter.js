// Minimal reporter for runs that touch real credentials.
//
// Playwright's bundled HTML reporter embeds the full run payload (steps,
// params, attachments) in a ZIP inside index.html. One such payload leaked a
// shared demo password in T2, so credential-bearing runs no longer use it.
// This reporter keeps only what an evidence log needs: identity, status,
// duration, and attachment counts. No params, page text, or error messages
// are written, because any of those can carry a submitted value.

import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'

export default class CleanReporter {
  constructor(options = {}) {
    this.outputFile = resolve(
      options.outputFile || '../.local/t2-deploy/cloud-summary.json',
    )
    this.startedAt = null
    this.tests = []
  }

  onBegin(config, suite) {
    this.startedAt = new Date().toISOString()
    this.expected = suite.allTests().length
  }

  onTestEnd(test, result) {
    this.tests.push({
      file: test.location.file.split('/').pop(),
      title: test.title,
      project: test.parent.project()?.name ?? 'default',
      status: result.status,
      expectedStatus: test.expectedStatus,
      durationMs: result.duration,
      attachments: result.attachments.length,
    })
  }

  onEnd(result) {
    const summary = {
      startedAt: this.startedAt,
      finishedAt: new Date().toISOString(),
      status: result.status,
      expectedTests: this.expected,
      tests: this.tests,
      note: 'Status only. Step parameters, page text, and error messages are never recorded.',
    }
    mkdirSync(dirname(this.outputFile), { recursive: true })
    writeFileSync(this.outputFile, `${JSON.stringify(summary, null, 2)}\n`, {
      mode: 0o600,
    })
  }
}

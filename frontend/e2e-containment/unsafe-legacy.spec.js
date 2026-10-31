import { expect, test } from '@playwright/test'
import { releaseCredentialPages, requireSecret, setPasswordField } from '../e2e-cloud/support/secrets.js'

// NEGATIVE CONTROL for the T2 credential-leak gate. Purpose: prove the gate's
// scanner really detects a leak in *this* configuration, instead of only
// proving that clean runs look clean.
//
// Historical fill/scrub failures and unsafe post-entry assertions run only
// when the operator sets CANARY_RED=1:
//
//   * `unsafe-fill`: `legacyFill` passes the secret to `locator.fill()`, so a
//     fill-level failure writes `fill("<canary>")` into the action call log ->
//     stdout via the `list` reporter and the "Error details" section of
//     error-context.md.
//   * `unsafe-snapshot`: no teardown (no scrub, no page close), which is the
//     pre-70c07b3 behaviour and also what the old scrubbing `catch {}`
//     degenerated to, so the value is still in the DOM when Playwright writes
//     its page snapshot.
//   * `unsafe-rerender`: the F2 timing shape (DOM-only scrub defeated by a
//     1 ms model re-apply). Kept for reproduction only: it reproduced in 3 of
//     4 gate runs, so it is too timing-dependent to be a gate control.
//
// The gate also requires unsafe-element-snapshot: a post-fill assertion can
// capture a password-bearing element before teardown. Synthetic canaries only.

const CANARY_RED = process.env.CANARY_RED === '1'
const CONTROL = process.env.CONTROL || ''

test.skip(() => !CANARY_RED, 'Negative control runs only with CANARY_RED=1')
test.skip(() => !CONTROL, 'CONTROL selects one unsafe control')

async function legacyFill(locator, secret, timeout) {
  const type = await locator.getAttribute('type')
  if (type !== 'password') {
    throw new Error('unsafe control: expected a password field')
  }
  await locator.fill(secret, { timeout })
}

async function legacyScrub(context) {
  for (const page of context.pages()) {
    if (page.isClosed()) {
      continue
    }
    try {
      await page.evaluate(() => {
        for (const input of document.querySelectorAll('input[type="password"]')) {
          input.value = ''
        }
      })
    } catch {
      // The old helper swallowed every scrub failure.
    }
  }
}

test.afterEach(async ({ context }, testInfo) => {
  if (CONTROL === 'unsafe-element-snapshot') {
    await releaseCredentialPages(context, testInfo)
    return
  }
  if (CONTROL !== 'unsafe-rerender') {
    // The other controls deliberately run without teardown.
    return
  }
  await legacyScrub(context)
})

const SNAPSHOT_ONLY = `<form id="f">
  <input id="p" type="password" aria-label="Password">
  <button type="submit">Masuk</button></form>
  <p id="status" role="status"></p>
  <script>
    window.__model = ''
    const input = document.getElementById('p')
    input.addEventListener('input', () => { window.__model = input.value })
    document.getElementById('f').addEventListener('submit', (event) => {
      event.preventDefault()
      document.getElementById('status').textContent = 'Permintaan diterima'
    })
  </script>`

const LOOP = `<form id="f">
  <input id="p" type="password" aria-label="Password">
  <button type="submit">Masuk</button></form>
  <p id="status" role="status"></p>
  <script>
    window.__model = ''
    const input = document.getElementById('p')
    input.addEventListener('input', () => { window.__model = input.value })
    document.getElementById('f').addEventListener('submit', (event) => {
      event.preventDefault()
      document.getElementById('status').textContent = 'Permintaan diterima'
    })
    setInterval(() => {
      if (input.value !== window.__model) input.value = window.__model
    }, 1)
  </script>`

test('unsafe fill: the call log carries the canary', async ({ page }) => {
  test.skip(CONTROL !== 'unsafe-fill', 'CONTROL selects one unsafe control')
  const canary = requireSecret('CANARY_VALUE')
  await page.setContent('<input type="password" readonly aria-label="Password">')
  // A per-action timeout keeps the control deterministic: the action fails
  // with its call log (`fill("<canary>")`) instead of racing a test timeout.
  await legacyFill(page.getByLabel('Password'), canary, 1_000)
})

test('unsafe snapshot: no teardown leaves the canary in the page snapshot', async ({
  page,
}) => {
  test.skip(CONTROL !== 'unsafe-snapshot', 'CONTROL selects one unsafe control')
  const canary = requireSecret('CANARY_VALUE')
  await page.setContent(SNAPSHOT_ONLY)
  await legacyFill(page.getByLabel('Password'), canary, 1_000)
  await page.getByRole('button', { name: 'Masuk' }).click()
  await expect(page.getByRole('status')).toContainText('Permintaan diterima')
  expect(1).toBe(2)
})

for (const target of ['password', 'ancestor', 'missing-heading']) {
  test(`unsafe element snapshot: ${target} assertion captures the canary before teardown`, async ({ page }) => {
    test.skip(CONTROL !== 'unsafe-element-snapshot', 'CONTROL selects one unsafe control')
    await page.setContent(`<main>${SNAPSHOT_ONLY}</main>`)
    await setPasswordField(page.getByLabel('Password'), requireSecret('CANARY_VALUE'))
    const synced = await page.evaluate(() =>
      window.__model.length > 0 && window.__model === document.getElementById('p').value,
    )
    expect(synced).toBe(true)
    if (target === 'password') {
      await expect(page.getByLabel('Password')).not.toBeEditable()
    } else if (target === 'ancestor') {
      await expect(page.locator('main')).toBeHidden()
    } else {
      await page.getByRole('button', { name: 'Masuk' }).click()
      await expect(page.getByRole('heading', { name: 'Kelola katalog' })).toBeVisible()
    }
  })
}

test('unsafe rerender: DOM-only scrub is defeated by a 1 ms re-apply (timing)', async ({
  page,
}) => {
  test.skip(CONTROL !== 'unsafe-rerender', 'CONTROL selects one unsafe control')
  const canary = requireSecret('CANARY_VALUE')
  await page.setContent(LOOP)
  await legacyFill(page.getByLabel('Password'), canary, 1_000)
  await page.getByRole('button', { name: 'Masuk' }).click()
  await expect(page.getByRole('status')).toContainText('Permintaan diterima')
  expect(1).toBe(2)
})

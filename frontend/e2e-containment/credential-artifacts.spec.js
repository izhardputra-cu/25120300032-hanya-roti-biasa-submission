import { expect, test } from '@playwright/test'
import {
  clearPasswordFields,
  releaseCredentialPages,
  requireSecret,
  setPasswordField,
  waitForCredentialFormExit,
} from '../e2e-cloud/support/secrets.js'

// Regression harness for the T2 credential-leak channels, run entirely
// locally against an inline page. It uses the shipped config (see
// `playwright.containment.config.js`, which imports the cloud config) and a
// synthetic canary from the environment instead of a real credential.
//
// Scenarios are selected with CONTAINMENT_SCENARIO; `scripts/check-e2e-artifacts.sh`
// runs each one and scans every produced file plus stdout/stderr afterwards.
//
// The inline form is a faithful analogue of the Vue views: `v-model` on
// `input[type=password]`, an `input` listener that stores the value, and a
// submit handler that only renders a status message (no application logic and
// no database is mocked).

const SCENARIO = process.env.CONTAINMENT_SCENARIO || 'happy'

test.afterEach(async ({ context }, testInfo) => {
  // The shipped teardown: scrub, then close every page deterministically.
  await releaseCredentialPages(context, testInfo)
})

function formPage({ rerender = 0, raf = false, readonly = false } = {}) {
  return `<!doctype html>
<html lang="id">
  <head><meta charset="utf-8"><title>Formulir uji</title></head>
  <body>
    <main>
      <h1>Masuk ke akun</h1>
      <form id="form">
        <label for="email">Email</label>
        <input id="email" name="email" type="email" autocomplete="username">
        <label for="password">Password</label>
        <input id="password" name="password" type="password" autocomplete="current-password"${
          readonly ? ' readonly' : ''
        }>
        <button type="submit">Masuk</button>
      </form>
      <p id="status" role="status"></p>
    </main>
    <script>
      window.__model = { email: '', password: '' }
      const email = document.getElementById('email')
      const password = document.getElementById('password')
      email.addEventListener('input', () => { window.__model.email = email.value })
      password.addEventListener('input', () => { window.__model.password = password.value })
      document.getElementById('form').addEventListener('submit', (event) => {
        event.preventDefault()
        document.getElementById('status').textContent =
          window.__model.password ? 'Permintaan diterima' : 'Password kosong'
      })
      ${
        rerender > 0
          ? `setInterval(() => {
        if (password.value !== window.__model.password) password.value = window.__model.password
        if (email.value !== window.__model.email) email.value = window.__model.email
      }, ${rerender})`
          : ''
      }
      ${
        raf
          ? `const tick = () => {
        if (password.value !== window.__model.password) password.value = window.__model.password
        if (email.value !== window.__model.email) email.value = window.__model.email
        requestAnimationFrame(tick)
      }
      requestAnimationFrame(tick)`
          : ''
      }
    </script>
  </body>
</html>`
}

// Compares the component model with the DOM inside the page so the canary is
// never passed to `expect()` or any reporter-facing call.
function modelMatchesDom(page) {
  return page.evaluate(
    () =>
      window.__model.password === document.getElementById('password').value &&
      window.__model.password.length > 0,
  )
}

async function submitCanary(page, options) {
  const canary = requireSecret('CANARY_VALUE')
  await page.setContent(formPage(options))
  await page.getByLabel('Email').fill('canary@example.com')
  await setPasswordField(page.getByLabel('Password'), canary)
  const synced = await modelMatchesDom(page)
  if (!synced) {
    throw new Error('The page model did not follow the native input event')
  }
  await page.getByRole('button', { name: 'Masuk' }).click()
  await expect(page.getByRole('status')).toContainText('Permintaan diterima')
}

test('happy path: canary submitted through a real form leaves no trace', async ({
  page,
}) => {
  test.skip(SCENARIO !== 'happy', 'CONTAINMENT_SCENARIO selects one scenario')
  await submitCanary(page)
  await page.evaluate(() => document.querySelector('input[type="password"]').remove())
  await waitForCredentialFormExit(page)
})

test('failed login: wait for form exit without a failure-time DOM snapshot', async ({ page }) => {
  test.skip(SCENARIO !== 'form-exit-failure', 'CONTAINMENT_SCENARIO selects one scenario')
  await submitCanary(page)
  await waitForCredentialFormExit(page, 500)
})

test('failure path: value-free assertion after a submitted canary', async ({
  page,
}) => {
  test.skip(SCENARIO !== 'assertion-failure', 'CONTAINMENT_SCENARIO selects one scenario')
  await submitCanary(page)
  expect(1).toBe(2)
})

test('fill-level failure: the password field never becomes editable', async ({ page }) => {
  test.skip(SCENARIO !== 'not-editable', 'CONTAINMENT_SCENARIO selects one scenario')
  const canary = requireSecret('CANARY_VALUE')
  await page.setContent(formPage({ readonly: true }))
  // The secret is not an argument here, so the timeout can only report the
  // locator, never the value.
  await setPasswordField(page.getByLabel('Password'), canary)
})

test('test timeout with the canary already in the DOM', async ({ page }) => {
  test.skip(SCENARIO !== 'test-timeout', 'CONTAINMENT_SCENARIO selects one scenario')
  test.setTimeout(1_500)
  await submitCanary(page)
  await page.evaluate(() => new Promise(() => {}))
})

test('test timeout while the value-setting call is still in flight', async ({ page }) => {
  test.skip(SCENARIO !== 'test-timeout', 'CONTAINMENT_SCENARIO selects one scenario')
  test.setTimeout(1_500)
  const canary = requireSecret('CANARY_VALUE')
  await page.setContent(formPage())
  // Direct shape probe: the same native-setter call as `setPasswordField`, but
  // it never returns, so the timeout lands mid-call.
  await page.getByLabel('Password').evaluate((element, value) => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set
    setter.call(element, value)
    element.dispatchEvent(new Event('input', { bubbles: true }))
    return new Promise(() => {})
  }, canary)
})

test('pending model re-render (interval) cannot resurrect the canary', async ({ page }) => {
  test.skip(SCENARIO !== 'rerender', 'CONTAINMENT_SCENARIO selects one scenario')
  await submitCanary(page, { rerender: 1 })
  expect(1).toBe(2)
})

test('pending model re-render (requestAnimationFrame) cannot resurrect the canary', async ({
  page,
}) => {
  test.skip(SCENARIO !== 'rerender', 'CONTAINMENT_SCENARIO selects one scenario')
  await submitCanary(page, { raf: true })
  expect(1).toBe(2)
})

test('a blocked scrub still ends with no page snapshot', async ({ page }) => {
  test.skip(SCENARIO !== 'scrub-blocked', 'CONTAINMENT_SCENARIO selects one scenario')
  await submitCanary(page, { rerender: 1 })
  // Block the main thread so the teardown scrub cannot run inside its budget.
  // Closing the page is what removes the snapshot; the degradation is reported
  // as an annotation instead of being treated as a clean scrub.
  await page.evaluate(() => {
    setTimeout(() => {
      const end = Date.now() + 3_000
      while (Date.now() < end) {
        // busy loop
      }
    }, 0)
  })
  throw new Error('probe: failing with a blocked main thread')
})

test('a context destroyed mid-teardown is classified, not swallowed as success', async ({
  page,
}) => {
  test.skip(SCENARIO !== 'context-lost', 'CONTAINMENT_SCENARIO selects one scenario')
  await submitCanary(page)
  await page.context().close()
  throw new Error('probe: context destroyed while a canary was in the DOM')
})

test('teardown contract: an unknown scrub error fails the run', async () => {
  test.skip(SCENARIO !== 'contract', 'CONTAINMENT_SCENARIO selects one scenario')
  const fakePage = {
    isClosed: () => false,
    evaluate: async () => {
      throw new Error('unexpected evaluate failure')
    },
    close: async () => {},
  }
  await expect(
    releaseCredentialPages({ pages: () => [fakePage] }, undefined),
  ).rejects.toThrow(/scrub failed/)
})

test('teardown contract: an unknown close error fails the run', async () => {
  test.skip(SCENARIO !== 'contract', 'CONTAINMENT_SCENARIO selects one scenario')
  const fakePage = {
    isClosed: () => false,
    evaluate: async () => {},
    close: async () => {
      throw new Error('unexpected close failure')
    },
  }
  await expect(
    releaseCredentialPages({ pages: () => [fakePage] }, undefined),
  ).rejects.toThrow(/could not close/)
})

test('teardown contract: context loss does not prove a page was closed', async () => {
  test.skip(SCENARIO !== 'contract', 'CONTAINMENT_SCENARIO selects one scenario')
  const fakePage = {
    isClosed: () => false,
    evaluate: async () => {},
    close: async () => {
      throw new Error('Execution context was destroyed')
    },
  }
  await expect(
    releaseCredentialPages({ pages: () => [fakePage] }, undefined),
  ).rejects.toThrow(/could not close/)
})

test('teardown contract: a page lost during the scrub is benign', async () => {
  test.skip(SCENARIO !== 'contract', 'CONTAINMENT_SCENARIO selects one scenario')
  let closed = false
  const fakePage = {
    isClosed: () => false,
    evaluate: async () => {
      throw new Error('Execution context was destroyed')
    },
    close: async () => {
      closed = true
    },
  }
  const result = await releaseCredentialPages({ pages: () => [fakePage] }, undefined)
  expect(result.closed).toBe(1)
  expect(closed).toBe(true)
})

test('teardown contract: an already closed page is skipped', async () => {
  test.skip(SCENARIO !== 'contract', 'CONTAINMENT_SCENARIO selects one scenario')
  const result = await releaseCredentialPages(
    { pages: () => [{ isClosed: () => true }] },
    undefined,
  )
  expect(result.pages).toBe(0)
})

test('teardown contract: the scrub syncs component state, not only the DOM', async ({
  page,
}) => {
  test.skip(SCENARIO !== 'contract', 'CONTAINMENT_SCENARIO selects one scenario')
  await submitCanary(page, { rerender: 1 })
  const outcome = await clearPasswordFields(page)
  expect(outcome).toBe('scrubbed')
  // Give the 1 ms re-render loop time to re-apply the component model.
  await page.waitForTimeout(50)
  const remainsEmpty = await page.evaluate(
    () =>
      document.getElementById('password').value === '' &&
      window.__model.password === '',
  )
  expect(remainsEmpty).toBe(true)
})

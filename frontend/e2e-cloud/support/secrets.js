// Credential handling for cloud browser tests.
//
// Measured facts about Playwright 1.64.1 (probes in
// `.local/t2-second-remediation/probe-evaluate/`, results in
// `docs/testing/t2-remediation.md`):
//
// 1. `locator.fill(value)` writes `fill("<value>")` into the action call log.
//    That log reaches captured stdout via the `list` reporter and the
//    "Error details" section of `error-context.md`. `type=password` does NOT
//    mask action parameters.
// 2. `locator.evaluate(fn, value)` does NOT write the argument to the call log,
//    the error details, or the reporter output. Its page-snapshot section can
//    still show a value that is *in the DOM* at failure time.
// 3. Playwright's `error-context.md` page snapshot renders the current value of
//    an `input[type=password]` in clear text.
//
// Secrets travel as evaluate arguments, not as parameters to form-filling
// actions such as fill/type. Their absence from reports is probe-specific,
// not a promise about arbitrary page errors or future Playwright versions.
//
// A. Editability is waited for and asserted BEFORE the secret exists in the
//    browser, so a readonly/locked form fails without the value anywhere.
// B. The value is written inside the page with the native input value setter
//    plus bubbling `input`/`change` events, which is what Vue's `v-model`
//    listens for. The tested reports omit its argument; errors can still log.
// C. Teardown clears password inputs (syncing framework state via the same
//    input event) and then closes every page, so Playwright's teardown has no
//    page to snapshot at teardown. Failure-time element snapshots already
//    captured by assertions survive closing: never assert on a password-bearing
//    locator or ancestor after entry. A MISSING locator can snapshot the whole
//    credential form too. Wait for the form to disappear before post-submit
//    locator assertions; an existing safe status or a value-free boolean is narrower.
//
// `scripts/check-e2e-artifacts.sh` proves A, B and C with a synthetic canary on
// passing runs, failure runs, fill-level failures, in-flight timeouts, a
// re-rendering form, a blocked scrub, and three detected unsafe controls,
// including failure-time element snapshots that teardown cannot erase.

import { expect } from '@playwright/test'

// A scrub that cannot finish (busy page) must not block teardown.
const SCRUB_TIMEOUT_MS = 750

// Playwright messages that mean "this page/context is already gone". Anything
// else during teardown is a real failure and is re-thrown, never swallowed.
const PAGE_GONE =
  /(Target page, context or browser has been closed|Target closed|Browser has been closed|Protocol error[^:]*: Target closed|Execution context was destroyed|Cannot find context with specified id|Target crashed|Page crashed|Session closed)/i

// Navigation/login or registration success removes the password form. Unlike a
// locator assertion, this timeout does not embed a DOM snapshot in Error details.
export async function waitForCredentialFormExit(page, timeout = 10_000) {
  await page.waitForFunction(
    () => document.querySelector('input[type="password"]') === null,
    null,
    { timeout },
  )
}

export function requireSecret(name) {
  const value = process.env[name]
  if (!value) {
    throw new Error(`${name} is not set`)
  }
  return value
}

// Runs inside the page. `input` is the event Vue's v-model uses, so the
// component state follows the DOM instead of overwriting it on the next
// render.
function writeValue(element, value) {
  const setter = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    'value',
  )?.set
  if (!setter) {
    return false
  }
  setter.call(element, value)
  element.dispatchEvent(new Event('input', { bubbles: true }))
  element.dispatchEvent(new Event('change', { bubbles: true }))
  return element.value === value
}

function clearPasswordInputs() {
  const setter = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    'value',
  )?.set
  const inputs = document.querySelectorAll('input[type="password"]')
  for (const input of inputs) {
    if (setter) {
      setter.call(input, '')
    } else {
      input.value = ''
    }
    // Sync framework state too; otherwise a pending re-render restores the
    // value from the component model.
    input.dispatchEvent(new Event('input', { bubbles: true }))
    input.dispatchEvent(new Event('change', { bubbles: true }))
  }
  return inputs.length
}

/**
 * Put a secret into a password field without ever handing it to a logged
 * Playwright action.
 */
export async function setPasswordField(locator, secret) {
  if (typeof secret !== 'string' || secret.length === 0) {
    throw new Error('Refusing to set an empty secret')
  }
  const type = await locator.getAttribute('type')
  if (type !== 'password') {
    throw new Error('Refusing to set a secret on a field that is not type=password')
  }
  // Rule A: wait for a real, editable field before the secret enters the page.
  await expect(locator).toBeEditable()
  await locator.focus()
  // The evaluate argument is absent from the tested call-log/error channels.
  const landed = await locator.evaluate(writeValue, secret)
  if (landed !== true) {
    throw new Error('The password field did not accept the value')
  }
}

/** Clear every password input on one page and sync framework state. */
export async function clearPasswordFields(page) {
  if (page.isClosed()) {
    return 'already-closed'
  }
  const work = page.evaluate(clearPasswordInputs)
  let timer
  const budget = new Promise((resolve) => {
    timer = setTimeout(() => resolve('scrub-timeout'), SCRUB_TIMEOUT_MS)
  })
  const outcome = await Promise.race([
    work.then(
      () => 'scrubbed',
      (error) => (PAGE_GONE.test(String(error?.message ?? error)) ? 'page-gone' : { error }),
    ),
    budget,
  ])
  clearTimeout(timer)
  // A timed-out evaluate is still running; keep its rejection from surfacing
  // as an unhandled rejection once the page closes below.
  work.catch(() => {})
  return outcome
}

async function closePage(page) {
  if (page.isClosed()) {
    return 'already-closed'
  }
  try {
    await page.close({ runBeforeUnload: false })
    return 'closed'
  } catch (error) {
    // Losing a JavaScript context during navigation does not prove page closure.
    if (page.isClosed()) {
      return 'closed-during-teardown'
    }
    throw error
  }
}

/**
 * Deterministic credential teardown. Runs in `afterEach`.
 *
 * Closes every page even when the scrub could not run (mid-navigation, busy
 * main thread, crashed renderer), because a closed page cannot carry a
 * password into the teardown-time page snapshot. Previously captured element
 * snapshots in assertion error details are not erased. Failures that are
 * not "page already gone" are re-thrown: a broken teardown must fail the run
 * rather than be reported as safe.
 */
export async function releaseCredentialPages(context, testInfo) {
  const pages = context.pages().filter((page) => !page.isClosed())
  let scrubbed = 0
  let closed = 0
  let degraded = 0
  const problems = []

  for (const page of pages) {
    let outcome
    try {
      outcome = await clearPasswordFields(page)
    } catch (error) {
      outcome = { error }
    }
    if (outcome === 'scrubbed') {
      scrubbed += 1
    } else if (outcome === 'page-gone' || outcome === 'already-closed') {
      degraded += 1
    } else if (outcome === 'scrub-timeout') {
      degraded += 1
      problems.push('scrub-timeout')
    } else {
      degraded += 1
      problems.push(`scrub-error:${outcome?.error?.name ?? 'unknown'}`)
    }

    try {
      const closedAs = await closePage(page)
      if (closedAs !== 'already-closed') {
        closed += 1
      }
    } catch (error) {
      // Closing failed for a reason that is not "already gone": surface it.
      throw new Error(
        `Credential teardown could not close a page (${error?.name ?? 'unknown'})`,
        { cause: error },
      )
    }
  }

  const description = `pages=${pages.length} scrubbed=${scrubbed} closed=${closed} degraded=${degraded}`
  testInfo?.annotations?.push({ type: 'credential-teardown', description })

  const scrubError = problems.find((problem) => problem.startsWith('scrub-error:'))
  if (scrubError) {
    // The page is closed, so nothing leaked; still fail loudly so a new
    // teardown failure mode is not mistaken for a clean run.
    throw new Error(`Credential teardown scrub failed (${scrubError}); pages were closed`)
  }

  return { pages: pages.length, scrubbed, closed, degraded }
}

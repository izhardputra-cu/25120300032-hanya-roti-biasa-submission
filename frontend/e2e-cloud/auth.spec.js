import { randomUUID } from 'node:crypto'
import { expect, test } from '@playwright/test'
import {
  releaseCredentialPages,
  requireSecret,
  setPasswordField,
  waitForCredentialFormExit,
} from './support/secrets.js'

// Remote HTTPS smoke test. The seller password is supplied through the
// operator environment only, never committed. Buyer accounts are synthetic
// and get a random password per run.
//
// Credential-safety rules for this file: passwords go in only through
// `setPasswordField`, which waits for an editable field and then writes the
// value with a native setter plus an `input` event inside the page. The value
// travels through evaluate, whose argument was absent from the tested reports;
// fill(secret) instead logs its argument even on password inputs. Tests never
// deliberately pass passwords to expect(), console.log(), or errors. The
// `afterEach` scrub plus page close keeps the value out of Playwright's
// teardown-time page snapshot. Never assert on a password field or its ancestor
// after entry: failure-time element snapshots would survive that cleanup.
const SELLER_EMAIL = 'seller@example.com'
const EVIDENCE = process.env.CLOUD_EVIDENCE_DIR || '../.local/t2-deploy/evidence'

test.skip(
  () => !process.env.T2_BASE_URL || !process.env.T2_SELLER_PASSWORD,
  'Set T2_BASE_URL and T2_SELLER_PASSWORD to run the cloud smoke test.',
)

test.afterEach(async ({ context }, testInfo) => {
  await releaseCredentialPages(context, testInfo)
})

function buyerCredentials() {
  return {
    email: `cloud-${randomUUID()}@example.com`,
    password: `Cloud-buyer-${randomUUID()}`,
  }
}

async function screenshot(page, name) {
  await page.screenshot({ path: `${EVIDENCE}/${name}.png`, fullPage: true })
}

async function login(page, { email, password }) {
  await page.getByLabel('Email').fill(email)
  await setPasswordField(page.getByLabel('Password'), password)
  await page.getByRole('button', { name: 'Masuk' }).click()
  await waitForCredentialFormExit(page)
}

test('deep links serve the built Vue app and anonymous guards redirect to login', async ({
  page,
}) => {
  await page.goto('/masuk')
  await expect(page.getByRole('heading', { name: 'Masuk ke akun' })).toBeVisible()
  await expect
    .poll(() => page.evaluate(() => getComputedStyle(document.body).backgroundColor))
    .toBe('rgb(251, 246, 236)')

  await page.goto('/daftar')
  await expect(page.getByRole('heading', { name: 'Buat akun pembeli' })).toBeVisible()

  for (const path of ['/akun', '/penjual']) {
    await page.goto(path)
    await expect(page).toHaveURL(/\/masuk(\?|$)/)
    await expect(page.getByRole('status')).toContainText(
      'Masuk untuk melanjutkan. Isi keranjang tetap tersimpan.',
    )
  }
  await screenshot(page, 'deep-link-login-guard')
})

test('buyer registers, logs in, is denied the seller page, and logs out', async ({
  page,
}, testInfo) => {
  const buyer = buyerCredentials()
  await page.goto('/daftar')
  await page.getByLabel('Nama').fill('Cloud Buyer')
  await page.getByLabel('Email').fill(buyer.email)
  await setPasswordField(page.getByLabel('Password'), buyer.password)
  await page.getByRole('button', { name: 'Buat akun pembeli' }).click()
  await waitForCredentialFormExit(page)
  await expect(page.getByRole('status')).toContainText('Akun pembeli berhasil dibuat')

  await page.getByRole('link', { name: 'Masuk ke akun' }).click()
  await login(page, buyer)

  await expect(page).toHaveURL(/\/akun$/)
  await expect(page.getByRole('heading', { name: 'Akun Anda' })).toBeVisible()
  await expect(page.getByText(buyer.email)).toBeVisible()
  await expect(page.getByText('Pembeli', { exact: true })).toBeVisible()
  await screenshot(page, 'buyer-account-https')

  await page.goto('/penjual')
  await expect(page.getByRole('heading', { name: 'Akses ditolak' })).toBeVisible()
  await expect(page.getByText('Akun ini terdaftar sebagai pembeli.')).toBeVisible()
  await screenshot(page, `buyer-denied-${testInfo.project.name}`)

  await page.goto('/akun')
  await page.getByRole('button', { name: 'Keluar' }).click()
  await expect(page).toHaveURL(/\/masuk/)
  await expect(page.getByRole('status')).toContainText('Anda sudah keluar dari akun ini.')
})

test('seeded seller opens the seller room over HTTPS and keeps the session on reload', async ({
  page,
  context,
}) => {
  await page.goto('/masuk')
  await login(page, { email: SELLER_EMAIL, password: requireSecret('T2_SELLER_PASSWORD') })

  await expect(page).toHaveURL(/\/penjual$/)
  await expect(page.getByRole('heading', { name: 'Kelola katalog' })).toBeVisible()
  await expect(page.getByText('Masuk sebagai penjual')).toBeVisible()
  await screenshot(page, 'seller-room-https')

  const cookies = await context.cookies()
  const session = cookies.find((cookie) => cookie.name === 'wad05_session')
  expect(session).toBeDefined()
  expect(session.httpOnly).toBe(true)
  expect(session.secure).toBe(true)
  expect(session.sameSite).toBe('Lax')
  // Report attribute flags only; never print the cookie value. This records
  // that the session cookie exists and is flag-protected, not that anything
  // is withheld from the logs.
  console.log('session cookie flags:', {
    name: session.name,
    domain: session.domain,
    path: session.path,
    httpOnly: session.httpOnly,
    secure: session.secure,
    sameSite: session.sameSite,
  })

  await page.reload()
  await expect(page.getByRole('heading', { name: 'Kelola katalog' })).toBeVisible()
  await expect(page.getByText('seller@example.com')).toBeVisible()
})

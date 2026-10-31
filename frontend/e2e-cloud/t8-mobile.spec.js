import { randomUUID } from 'node:crypto'
import { expect, test } from '@playwright/test'
import {
  releaseCredentialPages,
  requireSecret,
  setPasswordField,
  waitForCredentialFormExit,
} from './support/secrets.js'

// Selected T8 flows at a phone viewport against the real deployment. Same
// credential rules as the desktop spec: passwords only through
// setPasswordField, pages scrubbed and closed in afterEach.
const SELLER_EMAIL = 'seller@example.com'
const EVIDENCE = process.env.CLOUD_EVIDENCE_DIR || '../.local/t8-evidence'

test.skip(
  () => !process.env.T2_BASE_URL || !process.env.T2_SELLER_PASSWORD,
  'Set T2_BASE_URL and T2_SELLER_PASSWORD to run the cloud flows.',
)

test.afterEach(async ({ context }, testInfo) => {
  await releaseCredentialPages(context, testInfo)
})

async function noOverflow(page) {
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
  ).toBe(true)
}

test('mobile: demo catalog, open schedule, seller recap and buyer account render on a phone', async ({
  page,
}) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Katalog roti sourdough' })).toBeVisible()
  const cards = page.locator('li.product-card')
  await expect(cards.first()).toBeVisible()
  expect(await cards.count()).toBeGreaterThan(0)
  await noOverflow(page)

  await page.goto('/jadwal')
  await expect(page.getByRole('heading', { name: 'Jadwal pre-order' })).toBeVisible()
  await expect(
    page.locator('li.schedule-panel', { hasText: 'Dibuka' }).first(),
  ).toBeVisible()
  await noOverflow(page)
  await page.screenshot({ path: `${EVIDENCE}/mobile-public-jadwal.png`, fullPage: true })

  await page.goto('/masuk')
  await page.getByLabel('Email').fill(SELLER_EMAIL)
  await setPasswordField(page.getByLabel('Password'), requireSecret('T2_SELLER_PASSWORD'))
  await page.getByRole('button', { name: 'Masuk' }).click()
  await waitForCredentialFormExit(page)
  await expect(page.getByRole('heading', { name: 'Kelola katalog' })).toBeVisible()
  await page.goto('/penjual/rekap')
  await expect(page.getByRole('heading', { name: 'Rekap produksi' })).toBeVisible()
  await noOverflow(page)
  await page.screenshot({ path: `${EVIDENCE}/mobile-seller-recap.png`, fullPage: true })

  await page.context().clearCookies()
  const email = `t8-mobile-${randomUUID()}@example.com`
  const password = `Cloud-buyer-${randomUUID()}`
  await page.goto('/daftar')
  await page.getByLabel('Nama').fill('Pembeli Demo Mobile')
  await page.getByLabel('Email').fill(email)
  await setPasswordField(page.getByLabel('Password'), password)
  await page.getByRole('button', { name: 'Buat akun pembeli' }).click()
  await waitForCredentialFormExit(page)
  await expect(page.getByRole('status')).toContainText('Akun pembeli berhasil dibuat')
  await page.getByRole('link', { name: 'Masuk ke akun' }).click()
  await page.getByLabel('Email').fill(email)
  await setPasswordField(page.getByLabel('Password'), password)
  await page.getByRole('button', { name: 'Masuk' }).click()
  await waitForCredentialFormExit(page)
  await expect(page.getByRole('heading', { name: 'Akun Anda' })).toBeVisible()
  await noOverflow(page)
})

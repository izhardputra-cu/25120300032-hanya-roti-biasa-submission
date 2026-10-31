import { randomUUID } from 'node:crypto'
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { expect, test } from '@playwright/test'
import {
  releaseCredentialPages,
  requireSecret,
  setPasswordField,
  waitForCredentialFormExit,
} from './support/secrets.js'

// Genuine cloud end-to-end flows for the T8 release: real HTTPS UI, real MySQL
// behind Cloud Run, no mocks and no local database helpers. Credentials go in
// only through setPasswordField (see support/secrets.js); synthetic buyers get
// a random password per run.
//
// Cleanup contract for this file:
// - Every product and schedule created here is recorded from the actual create
//   response (id + exact per-run name token). Nothing is selected by a broad
//   name prefix, so an unrelated row can never be archived or deleted.
// - Cleanup runs in `finally`, before the credential pages are released. It
//   closes the owned schedule cutoff through the normal seller API, archives
//   only owned closed schedules whose orders are all `selesai`/`batal`, then
//   archives the owned products. An unfinished order is reported as a cleanup
//   failure with the IDs preserved, never refunded, cancelled, or deleted.
// - A per-run manifest (ids and cleanup outcomes only, no cookies, passwords,
//   or page text) is written under a private directory for the parent.
// - Mutations require T8_ALLOW_MUTATIONS=1 so the standard cloud smoke cannot
//   silently add catalog rows.
const SELLER_EMAIL = 'seller@example.com'
const EVIDENCE = process.env.CLOUD_EVIDENCE_DIR || '../.local/t8-evidence'
const CLEANUP_DIR = process.env.CLOUD_CLEANUP_DIR || resolve(dirname(EVIDENCE), 'cleanup')
const ORIGIN = process.env.T2_BASE_URL ? new URL(process.env.T2_BASE_URL).origin : ''
const MUTATIONS_ENABLED = process.env.T8_ALLOW_MUTATIONS === '1'

test.skip(
  () => !process.env.T2_BASE_URL || !process.env.T2_SELLER_PASSWORD,
  'Set T2_BASE_URL and T2_SELLER_PASSWORD to run the cloud flows.',
)

const extraContexts = []

test.afterEach(async ({ context }, testInfo) => {
  for (const extra of extraContexts.splice(0)) {
    await releaseCredentialPages(extra, testInfo)
    await extra.close()
  }
  await releaseCredentialPages(context, testInfo)
})

async function newCredentialContext(browser) {
  const extra = await browser.newContext()
  extraContexts.push(extra)
  return extra
}

function buyerCredentials() {
  return {
    email: `t8-${randomUUID()}@example.com`,
    password: `Cloud-buyer-${randomUUID()}`,
  }
}

/**
 * One run's exact ownership record. The random token makes every created name
 * unique per run without relying on a timestamp shared by parallel workers.
 */
function createRun(testInfo) {
  const runId = randomUUID()
  return {
    runId,
    token: runId.slice(0, 8),
    test: testInfo.title,
    project: testInfo.project.name,
    startedAt: new Date().toISOString(),
    products: [],
    schedules: [],
    orders: [],
    cleanup: null,
  }
}

function uniqueName(run, label) {
  return `T8 ${label} ${run.token}`
}

function manifestPath(run) {
  return resolve(CLEANUP_DIR, `run-${run.token}-${run.runId}.json`)
}

function writeManifest(run) {
  mkdirSync(CLEANUP_DIR, { recursive: true, mode: 0o700 })
  const payload = {
    runId: run.runId,
    test: run.test,
    project: run.project,
    startedAt: run.startedAt,
    finishedAt: new Date().toISOString(),
    bodyOutcome: run.bodyOutcome,
    products: run.products,
    schedules: run.schedules,
    orders: run.orders,
    cleanup: run.cleanup,
    note: 'IDs and cleanup outcomes only; no cookies, passwords, headers, or page text.',
  }
  writeFileSync(manifestPath(run), `${JSON.stringify(payload, null, 2)}\n`, {
    mode: 0o600,
  })
}

async function csrfHeaders(page) {
  const response = await page.request.get('/api/auth/session')
  expect(response.status()).toBe(200)
  const { csrf_token: csrf } = await response.json()
  return { Origin: ORIGIN, 'X-CSRF-Token': csrf }
}

async function sellerApi(page, method, path, data) {
  const headers = await csrfHeaders(page)
  return page.request.fetch(`${ORIGIN}${path}`, {
    method,
    headers,
    ...(data === undefined ? {} : { data }),
  })
}

async function hasSellerSession(page) {
  const response = await page.request.get('/api/auth/session')
  if (response.status() !== 200) {
    return false
  }
  const body = await response.json()
  return body.user?.role === 'seller'
}

/**
 * Archive only what this run created. Each step is recorded in the manifest so
 * a refusal stays visible instead of being reported as a clean run.
 */
async function cleanupRun(page, run) {
  const result = { ok: true, startedAt: new Date().toISOString(), steps: [] }
  const record = (step, ok, detail = {}) => {
    result.steps.push({ step, ok, ...detail })
    if (!ok) {
      result.ok = false
    }
  }
  try {
    if (!(await hasSellerSession(page))) {
      await page.context().clearCookies()
      await loginSeller(page)
    }
    for (const schedule of [...run.schedules].reverse()) {
      const closed = await sellerApi(page, 'PATCH', `/api/seller/schedules/${schedule.id}`, {
        order_cutoff_at: new Date(Date.now() - 60_000).toISOString(),
      })
      record('close-cutoff', closed.status() === 200, {
        scheduleId: schedule.id,
        status: closed.status(),
      })
      if (closed.status() !== 200) {
        continue
      }
      const archived = await sellerApi(
        page,
        'POST',
        `/api/seller/schedules/${schedule.id}/archive`,
      )
      const detail =
        archived.status() === 200 ? {} : { body: await archived.json().catch(() => null) }
      record('archive-schedule', archived.status() === 200, {
        scheduleId: schedule.id,
        status: archived.status(),
        ...detail,
      })
    }
    for (const product of [...run.products].reverse()) {
      const archived = await sellerApi(
        page,
        'POST',
        `/api/seller/products/${product.id}/archive`,
      )
      record('archive-product', archived.status() === 200, {
        productId: product.id,
        status: archived.status(),
      })
    }
  } catch (error) {
    record('cleanup-error', false, { name: error?.name ?? 'Error' })
  }
  result.finishedAt = new Date().toISOString()
  return result
}

/**
 * Run a mutating flow with cleanup that cannot hide the original failure.
 * When the flow passed but cleanup refused an archive (for example because an
 * order was left unfinished), the test fails and the manifest keeps the IDs.
 */
async function withCloudCleanup(page, testInfo, body) {
  const run = createRun(testInfo)
  let thrown = null
  try {
    await body(run)
    run.bodyOutcome = 'passed'
  } catch (error) {
    run.bodyOutcome = 'failed'
    thrown = error
    throw error
  } finally {
    run.cleanup = await cleanupRun(page, run)
    try {
      writeManifest(run)
    } catch (manifestError) {
      // Keep the original test failure; report only non-secret ownership IDs.
      console.error(JSON.stringify({
        type: 'cloud-manifest-write-failed', runId: run.runId,
        productIds: run.products.map((product) => product.id),
        scheduleIds: run.schedules.map((schedule) => schedule.id),
        cleanupOk: run.cleanup.ok,
      }))
      if (thrown === null) throw manifestError
    }
    testInfo.annotations.push({
      type: 't8-cleanup',
      description: `ok=${run.cleanup.ok} products=${run.products.length} schedules=${run.schedules.length}`,
    })
    if (run.cleanup.ok !== true && thrown === null) {
      throw new Error(
        `Cloud cleanup failed for run ${run.token}; ids preserved in ${manifestPath(run)}`,
      )
    }
  }
}

function wibInput(daysFromNow, hour) {
  const day = new Date(Date.now() + 7 * 3600 * 1000 + daysFromNow * 86_400_000)
  const y = day.getUTCFullYear()
  const m = String(day.getUTCMonth() + 1).padStart(2, '0')
  const d = String(day.getUTCDate()).padStart(2, '0')
  return `${y}-${m}-${d}T${String(hour).padStart(2, '0')}:00`
}

async function screenshot(page, name) {
  mkdirSync(EVIDENCE, { recursive: true })
  await page.screenshot({ path: `${EVIDENCE}/${name}.png`, fullPage: true })
}

async function waitSellerPage(page) {
  await expect(page.getByText('Memeriksa akses penjual...')).toHaveCount(0)
}

async function loginSeller(page) {
  await page.goto('/masuk')
  await page.getByLabel('Email').fill(SELLER_EMAIL)
  await setPasswordField(page.getByLabel('Password'), requireSecret('T2_SELLER_PASSWORD'))
  await page.getByRole('button', { name: 'Masuk' }).click()
  await waitForCredentialFormExit(page)
  await expect(page.getByRole('heading', { name: 'Kelola katalog' })).toBeVisible()
  await waitSellerPage(page)
}

async function loginBuyer(page, { email, password }) {
  await page.goto('/masuk')
  await page.getByLabel('Email').fill(email)
  await setPasswordField(page.getByLabel('Password'), password)
  await page.getByRole('button', { name: 'Masuk' }).click()
  await waitForCredentialFormExit(page)
  await expect(page.getByRole('heading', { name: 'Akun Anda' })).toBeVisible()
}

async function registerBuyer(page, { email, password }) {
  await page.goto('/daftar')
  await page.getByLabel('Nama').fill('Pembeli Demo T8')
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
}

async function createProduct(page, run, { name, unit, price }) {
  await page.goto('/penjual')
  await waitSellerPage(page)
  await page.getByLabel('Nama produk').fill(name)
  await page.getByLabel('Unit jual').fill(unit)
  await page.getByLabel('Harga (Rupiah)').fill(String(price))
  const [response] = await Promise.all([
    page.waitForResponse(
      (candidate) =>
        new URL(candidate.url()).pathname === '/api/seller/products' &&
        candidate.request().method() === 'POST',
    ),
    page.getByRole('button', { name: 'Tambah produk' }).click(),
  ])
  expect(response.status()).toBe(201)
  const created = await response.json()
  expect(created.name).toBe(name)
  run.products.push({ id: created.id, name: created.name })
  await expect(page.getByRole('status')).toContainText('Produk baru ditambahkan')
}

async function openSchedule(page, run, products, { pickup, cutoff }) {
  await page.goto('/penjual/jadwal')
  await expect(page.getByRole('heading', { name: 'Kelola jadwal pre-order' })).toBeVisible()
  await waitSellerPage(page)
  const openButton = page.getByRole('button', { name: 'Buat jadwal baru' })
  if (await openButton.isVisible()) {
    await openButton.click()
  }
  await page.getByLabel('Waktu pengambilan (WIB)').fill(pickup)
  await page.getByLabel('Batas PO bersama (WIB)').fill(cutoff)
  for (const product of products) {
    await page.getByRole('checkbox', { name: product.name }).check()
    await page.getByLabel(`Kuota ${product.name}`).fill(String(product.quota))
  }
  const [response] = await Promise.all([
    page.waitForResponse(
      (candidate) =>
        new URL(candidate.url()).pathname === '/api/seller/schedules' &&
        candidate.request().method() === 'POST',
    ),
    page.getByRole('button', { name: 'Buka jadwal' }).click(),
  ])
  expect(response.status()).toBe(201)
  const created = await response.json()
  run.schedules.push({ id: created.id, pickupAt: created.pickup_at })
  await expect(page.getByRole('status')).toContainText('Jadwal pre-order baru dibuka')
}

async function addToCart(page, productName, quantity) {
  const panel = page.locator('li.schedule-panel', { hasText: productName })
  await panel.getByLabel(`Jumlah ${productName}`).fill(String(quantity))
  await panel.getByRole('button', { name: `Tambahkan ${productName} ke keranjang` }).click()
  await expect(page.getByRole('status')).toContainText(`${productName} masuk keranjang`)
}

async function checkout(page, run) {
  await page.locator('.site-nav').getByRole('link', { name: /Keranjang/ }).click()
  await expect(page.getByRole('heading', { name: 'Tinjauan pesanan' })).toBeVisible()
  await page.getByRole('button', { name: 'Buat pesanan' }).click()
  await expect(page).toHaveURL(/\/pesanan\/\d+(\?|$)/)
  const orderId = Number(new URL(page.url()).pathname.split('/').pop())
  const orderNumber = await page.locator('.order-number').first().innerText()
  expect(orderNumber).toMatch(/^PO-\d{8}-\d{6}$/)
  run.orders.push({ id: orderId, orderNumber })
  return { orderId, orderNumber }
}

async function openSellerOrder(page, orderNumber) {
  await page.locator('.site-nav').getByRole('link', { name: 'Pesanan', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Pesanan masuk' })).toBeVisible()
  const card = page.locator('li.order-card', { hasText: orderNumber })
  await card.getByRole('link', { name: 'Buka tindakan pesanan' }).click()
  await expect(
    page.getByRole('heading', { name: `Tindakan pesanan ${orderNumber}` }),
  ).toBeVisible()
}

async function verifyPayment(sellerPage, amount) {
  await sellerPage
    .getByLabel('Jumlah dana yang benar-benar diterima (Rupiah)')
    .fill(String(amount))
  await sellerPage.getByRole('button', { name: 'Verifikasi pembayaran' }).click()
  await expect(sellerPage.getByRole('status')).toContainText('tercatat terkonfirmasi')
  await expect(sellerPage.locator('.status-tag')).toContainText('Terkonfirmasi')
}

async function noOverflow(page) {
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
  ).toBe(true)
}

test.describe('mutating cloud flows', () => {
  test.skip(!MUTATIONS_ENABLED, 'Set T8_ALLOW_MUTATIONS=1 to run mutating cloud flows.')

  test('T3-T7 demo catalog, schedule, checkout, payment verification, pickup and recap over HTTPS', async ({
    page,
    browser,
  }, testInfo) => {
    await withCloudCleanup(page, testInfo, async (run) => {
      const classic = uniqueName(run, 'Klasik')
      const whole = uniqueName(run, 'Gandum')
      const buyer = buyerCredentials()
      const pickup = wibInput(12, 9)
      const cutoff = wibInput(10, 20)

      await loginSeller(page)
      await createProduct(page, run, { name: classic, unit: '1 loaf 500 gram', price: 65000 })
      await createProduct(page, run, { name: whole, unit: '1 loaf 650 gram', price: 72000 })
      await openSchedule(
        page,
        run,
        [
          { name: classic, quota: 12 },
          { name: whole, quota: 8 },
        ],
        { pickup, cutoff },
      )
      const schedulePanel = page.locator('li.schedule-panel', { hasText: classic })
      await expect(schedulePanel).toContainText('Dibuka')
      await screenshot(page, 'seller-demo-schedule-created')

      // The created catalog and open schedule are visible to anonymous visitors.
      const visitorContext = await newCredentialContext(browser)
      const visitorPage = await visitorContext.newPage()
      await visitorPage.goto('/')
      await expect(
        visitorPage.getByRole('heading', { name: 'Katalog roti sourdough' }),
      ).toBeVisible()
      await expect(visitorPage.getByText(classic)).toBeVisible()
      await expect(visitorPage.getByText(whole)).toBeVisible()
      await noOverflow(visitorPage)
      await screenshot(visitorPage, 'public-catalog-demo')
      await visitorPage.goto('/jadwal')
      const publicPanel = visitorPage.locator('li.schedule-panel', { hasText: classic })
      await expect(publicPanel).toContainText('Dibuka')
      await expect(publicPanel).toContainText('Sisa 12 dari kuota 12')
      await noOverflow(visitorPage)
      await screenshot(visitorPage, 'public-schedule-open')

      await page.context().clearCookies()
      await registerBuyer(page, buyer)
      await page.goto('/jadwal')
      await addToCart(page, classic, 2)
      await addToCart(page, whole, 1)
      const { orderId, orderNumber } = await checkout(page, run)
      await expect(page.getByText('202.000').first()).toBeVisible()
      await expect(page.getByText('Menunggu pembayaran')).toBeVisible()

      // Buyer reports a transfer; it stays unpaid until a human checks it.
      await expect(
        page.getByRole('heading', { name: 'Pembayaran transfer' }),
      ).toBeVisible()
      await page.locator('#transfer-note').fill('Transfer T8, nominal pas, pengirim A***.')
      await page.getByRole('button', { name: 'Kirim konfirmasi transfer' }).click()
      await expect(page.locator('.status-tag')).toContainText('Menunggu pemeriksaan')
      await screenshot(page, 'buyer-transfer-reported')

      // A different buyer never sees this order and cannot act as the seller.
      const otherBuyer = buyerCredentials()
      const otherContext = await newCredentialContext(browser)
      const otherPage = await otherContext.newPage()
      await registerBuyer(otherPage, otherBuyer)
      const otherOrder = await otherPage.request.get(`/api/orders/${orderId}`)
      expect([403, 404]).toContain(otherOrder.status())
      const otherSeller = await otherPage.request.get('/api/seller/orders')
      expect(otherSeller.status()).toBe(403)
      await otherPage.goto(`/pesanan/${orderId}`)
      await expect(
        otherPage.getByRole('heading', { name: 'Pesanan tidak ditemukan' }),
      ).toHaveCount(1)
      await otherPage.goto('/penjual')
      await expect(otherPage.getByRole('heading', { name: 'Akses ditolak' })).toBeVisible()

      // Mutations without Origin/CSRF are rejected on the real deployment.
      const noCsrf = await otherPage.request.post('/api/orders', { data: {} })
      expect(noCsrf.status()).toBe(403)
      const foreignOrigin = await otherPage.request.post('/api/orders', {
        data: {},
        headers: { Origin: 'https://evil.example' },
      })
      expect(foreignOrigin.status()).toBe(403)

      // Seller verifies the payment: wrong amount first, then the exact total.
      await page.context().clearCookies()
      await loginSeller(page)
      await openSellerOrder(page, orderNumber)
      await page
        .getByLabel('Jumlah dana yang benar-benar diterima (Rupiah)')
        .fill('202001')
      await page.getByRole('button', { name: 'Verifikasi pembayaran' }).click()
      const mismatch = page
        .getByRole('alert')
        .filter({ hasText: 'tidak sama dengan total pesanan' })
      await expect(mismatch).toBeVisible()
      await expect(page.locator('.status-tag')).toContainText('Menunggu pemeriksaan')
      await screenshot(page, 'seller-verify-mismatch')
      await verifyPayment(page, 202000)

      // Pickup lifecycle: ready keeps the recap, complete keeps it as well.
      await page.getByRole('button', { name: 'Tandai siap diambil' }).click()
      await expect(page.getByRole('status')).toContainText('ditandai siap diambil')
      await expect(page.locator('.status-tag')).toContainText('Siap diambil')
      await page.goto('/penjual/rekap')
      await expect(page.getByRole('heading', { name: 'Rekap produksi' })).toBeVisible()
      const recap = page.locator('li.recap-schedule', { hasText: classic })
      await expect(recap).toContainText('2 unit jual')
      await expect(recap).toContainText('1 unit jual')
      await expect(recap).toContainText('Total 3 unit jual untuk jadwal ini.')
      await noOverflow(page)
      await screenshot(page, 'seller-recap-ready')

      await openSellerOrder(page, orderNumber)
      await page.getByRole('button', { name: 'Tandai selesai' }).click()
      const confirm = page.getByRole('group', { name: 'Konfirmasi pesanan selesai' })
      await confirm.getByRole('button', { name: 'Ya, tandai selesai' }).click()
      await expect(page.getByRole('status')).toContainText('ditandai selesai')
      await expect(page.locator('.status-tag')).toContainText('Selesai')
      await page.goto('/penjual/rekap')
      await expect(
        page.locator('li.recap-schedule', { hasText: classic }),
      ).toContainText('Total 3 unit jual untuk jadwal ini.')

      await page.context().clearCookies()
      await loginBuyer(page, buyer)
      await page.goto(`/pesanan/${orderId}`)
      await expect(page.getByRole('heading', { name: 'Pesanan selesai' })).toBeVisible()
      await expect(page.locator('.status-tag')).toContainText('Selesai')
      await expect(page.getByText('202.000').first()).toBeVisible()
      await screenshot(page, 'buyer-order-completed')
      await page.goto('/penjual/rekap')
      await expect(page.getByRole('heading', { name: 'Akses ditolak' })).toBeVisible()
    })
  })

  test('T7 ready cancellation requires a manual refund and releases quota and recap', async ({
    page,
  }, testInfo) => {
    await withCloudCleanup(page, testInfo, async (run) => {
      const productName = uniqueName(run, 'Batal Siap')
      const buyer = buyerCredentials()
      const reason = 'Pesanan tidak dapat diserahkan; dana sudah dikembalikan manual.'

      await loginSeller(page)
      await createProduct(page, run, {
        name: productName,
        unit: '1 loaf 500 gram',
        price: 55000,
      })
      await openSchedule(page, run, [{ name: productName, quota: 4 }], {
        pickup: wibInput(18, 9),
        cutoff: wibInput(16, 20),
      })

      await page.context().clearCookies()
      await registerBuyer(page, buyer)
      await page.goto('/jadwal')
      await addToCart(page, productName, 2)
      const { orderId, orderNumber } = await checkout(page, run)
      await expect(page.getByText('110.000').first()).toBeVisible()

      await page.context().clearCookies()
      await loginSeller(page)
      await openSellerOrder(page, orderNumber)
      await verifyPayment(page, 110000)
      await page.getByRole('button', { name: 'Tandai siap diambil' }).click()
      await expect(page.getByRole('status')).toContainText('ditandai siap diambil')
      await expect(page.getByRole('button', { name: 'Batalkan pesanan' })).toBeVisible()

      const refundOptions = await page.locator('#refund-outcome option').allTextContents()
      expect(refundOptions).not.toContain('Dana belum atau tidak saya terima')
      await page.getByRole('button', { name: 'Batalkan pesanan' }).click()
      await page.locator('#cancel-reason').fill(reason)
      await page.locator('#refund-outcome').selectOption('refunded_manually')
      await page.getByRole('button', { name: 'Batalkan pesanan' }).click()
      const confirm = page.getByRole('group', { name: 'Konfirmasi pembatalan pesanan' })
      await confirm.getByRole('button', { name: 'Ya, catat pembatalan' }).click()
      await expect(page.getByRole('status')).toContainText('Pembatalan tercatat')
      await expect(page.locator('.status-tag')).toContainText('Batal')
      await expect(
        page.getByText('Dana sudah dikembalikan manual di luar aplikasi.'),
      ).toBeVisible()
      await expect(page.getByRole('button', { name: 'Tandai selesai' })).toHaveCount(0)
      await screenshot(page, 'seller-ready-cancelled-refund')

      await page.goto('/penjual/jadwal')
      await waitSellerPage(page)
      const panel = page.locator('li.schedule-panel', { hasText: productName })
      await expect(panel).toContainText('Teralokasi 0')
      await expect(panel).toContainText('sisa 4 dari 4')
      await page.goto('/penjual/rekap')
      await expect(page.locator('li.recap-schedule', { hasText: productName })).toHaveCount(0)
      await expect(
        page.getByText('Belum ada pesanan terbayar pada jadwal ini.', { exact: false }).first(),
      ).toBeVisible()

      await page.goto(`/pesanan/${orderId}`)
      await expect(page.getByRole('heading', { name: 'Pesanan batal' })).toBeVisible()
      await expect(page.getByText(reason)).toBeVisible()
      await expect(page.locator('.status-tag')).toContainText('Batal')
      await screenshot(page, 'buyer-ready-cancelled')
    })
  })
})

test('anonymous guards and own-history boundaries hold on the public origin', async ({
  page,
  browser,
}) => {
  const anonymous = await newCredentialContext(browser)
  const anonymousPage = await anonymous.newPage()
  await anonymousPage.goto('/pesanan')
  await expect(anonymousPage).toHaveURL(/\/masuk(\?|$)/)
  await expect(anonymousPage.getByRole('status')).toContainText(
    'Masuk untuk melanjutkan. Isi keranjang tetap tersimpan.',
  )
  const health = await anonymousPage.request.get('/api/health')
  expect(health.status()).toBe(200)

  const buyer = buyerCredentials()
  await registerBuyer(page, buyer)
  await page.goto('/pesanan')
  await expect(page.getByRole('heading', { name: 'Pesanan saya' })).toBeVisible()
  await expect(page.getByText('Belum ada pesanan.')).toBeVisible()
  await page.goto('/penjual')
  await expect(page.getByRole('heading', { name: 'Akses ditolak' })).toBeVisible()
})

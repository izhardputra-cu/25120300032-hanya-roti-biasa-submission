import { mkdirSync } from 'node:fs'
import { expect, test } from '@playwright/test'
import { purgeOrders } from './support/orders-db.js'

const BASE_URL = 'http://127.0.0.1:5173'
const SELLER = { email: 'seller@example.com', password: 'Demo-seller-2026!' }
const EVIDENCE = '../.local/t4-evidence'
const PREFIX = 'Jadwal Uji'
const OPEN_PICKUP = '2035-11-08T18:00'
const OPEN_CUTOFF = '2035-11-06T20:00'

function uniqueName(label) {
  return `${PREFIX} ${label} ${Date.now().toString(36)}`
}

async function screenshot(page, testInfo, name) {
  mkdirSync(EVIDENCE, { recursive: true })
  await page.screenshot({
    path: `${EVIDENCE}/${testInfo.project.name}-${name}.png`,
    fullPage: true,
  })
}

async function loginSeller(page) {
  await page.goto('/masuk')
  await page.getByLabel('Email').fill(SELLER.email)
  await page.getByLabel('Password').fill(SELLER.password)
  await page.getByRole('button', { name: 'Masuk' }).click()
  await expect(page.getByRole('heading', { name: 'Kelola katalog' })).toBeVisible()
}

async function cleanupSchedules(page) {
  await page.goto('/penjual/jadwal')
  await expect(page.getByRole('heading', { name: 'Kelola jadwal pre-order' })).toBeVisible()
  await expect(page.getByText('Memeriksa akses penjual...')).toHaveCount(0)
  // Archived rows are hidden by default; cleanup must see them to restore first.
  if (!(await page.getByLabel('Sertakan arsip').isChecked())) {
    const reload = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === '/api/seller/schedules' &&
        response.request().method() === 'GET',
    )
    await page.getByLabel('Sertakan arsip').check()
    await reload
  }
  const panels = page.locator('li.schedule-panel')
  while ((await panels.count()) > 0) {
    const before = await panels.count()
    const restore = panels.first().getByRole('button', { name: 'Pulihkan', exact: true })
    if ((await restore.count()) > 0) {
      await restore.click()
      await expect(page.getByRole('status')).toContainText('dipulihkan')
      await expect.poll(() => restore.count()).toBe(0)
    }
    await panels.first().getByRole('button', { name: 'Hapus jadwal' }).click()
    await panels.first().getByRole('button', { name: 'Ya, hapus jadwal' }).click()
    await expect(page.getByRole('status')).toContainText('dihapus')
    await expect.poll(() => panels.count()).toBe(before - 1)
  }
}

async function cleanupProducts(page) {
  await page.goto('/penjual')
  await expect(page.getByRole('heading', { name: 'Kelola katalog' })).toBeVisible()
  await expect(page.getByText('Memeriksa akses penjual...')).toHaveCount(0)
  // Archived products can still be deleted once no offer references them.
  if (!(await page.getByLabel('Sertakan arsip').isChecked())) {
    await page.getByLabel('Sertakan arsip').check()
  }
  const rows = page.locator('li.seller-product', { hasText: PREFIX })
  while ((await rows.count()) > 0) {
    const before = await rows.count()
    await rows.first().getByRole('button', { name: 'Hapus', exact: true }).click()
    await rows.first().getByRole('button', { name: 'Ya, hapus permanen' }).click()
    await expect(page.getByRole('status')).toContainText('dihapus permanen')
    await expect.poll(() => rows.count()).toBe(before - 1)
  }
}

async function createProduct(page, { name, unit = '1 loaf 500 gram', price, description }) {
  await page.getByLabel('Nama produk').fill(name)
  await page.getByLabel('Unit jual').fill(unit)
  await page.getByLabel('Harga (Rupiah)').fill(String(price))
  if (description) {
    await page.getByLabel('Deskripsi (opsional)').fill(description)
  }
  await page.getByRole('button', { name: 'Tambah produk' }).click()
  await expect(page.getByRole('status')).toContainText('Produk baru ditambahkan')
}

async function resetSyntheticData(page) {
  await loginSeller(page)
  // Orders reference schedules/products, so clear synthetic orders first.
  purgeOrders()
  await cleanupSchedules(page)
  await cleanupProducts(page)
}

async function fillScheduleForm(page, { pickup = OPEN_PICKUP, cutoff = OPEN_CUTOFF } = {}) {
  await page.getByLabel('Waktu pengambilan (WIB)').fill(pickup)
  await page.getByLabel('Batas PO bersama (WIB)').fill(cutoff)
}

async function selectProduct(page, name, quota) {
  await page.getByRole('checkbox', { name }).check()
  await page.getByLabel(`Kuota ${name}`).fill(String(quota))
}

test('seller opens a schedule and a visitor sees open and closed states in WIB', async ({
  page,
}, testInfo) => {
  const productName = uniqueName('Terbuka')
  await resetSyntheticData(page)
  await createProduct(page, { name: productName, price: 65000 })
  await page.goto('/penjual/jadwal')
  await expect(
    page.getByRole('heading', { name: 'Kelola jadwal pre-order' }),
  ).toBeVisible()
  await screenshot(page, testInfo, 'seller-schedule-empty')

  try {
    await fillScheduleForm(page)
    await selectProduct(page, productName, 6)
    await page.getByRole('button', { name: 'Buka jadwal' }).click()
    await expect(page.getByRole('status')).toContainText('Jadwal pre-order baru dibuka')

    const panel = page.locator('li.schedule-panel', { hasText: productName })
    await expect(panel).toContainText('Pengambilan 8 November 2035, 18.00 WIB')
    await expect(panel).toContainText('Batas PO 6 November 2035, 20.00 WIB')
    await expect(panel).toContainText('Dibuka')
    await expect(panel.getByLabel(`Kuota ${productName}`)).toHaveValue('6')
    await expect(panel).toContainText(productName)
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true)
    await screenshot(page, testInfo, 'seller-schedule-created')

    const visitor = await page.context().browser().newContext()
    const visitorPage = await visitor.newPage()
    await visitorPage.goto(`${BASE_URL}/jadwal`)
    await expect(
      visitorPage.getByRole('heading', { name: 'Jadwal pre-order' }),
    ).toBeVisible()
    const publicPanel = visitorPage.locator('li.schedule-panel', { hasText: productName })
    await expect(publicPanel).toContainText('Dibuka')
    await expect(publicPanel).toContainText('Sisa 6 dari kuota 6')
    await expect(publicPanel).toContainText('Pengambilan 8 November 2035, 18.00 WIB')
    await expect(publicPanel).toContainText('Batas PO 6 November 2035, 20.00 WIB')
    expect(
      await visitorPage.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true)
    await screenshot(visitorPage, testInfo, 'public-schedule-open')

    await page.goto('/penjual')
    await page.locator('.seller-product', { hasText: productName })
      .getByRole('button', { name: 'Arsipkan' }).click()
    await expect(page.getByRole('status')).toContainText('diarsipkan')
    await visitorPage.goto(`${BASE_URL}/`)
    await expect(visitorPage.getByText('Memuat katalog...')).toHaveCount(0)
    await expect(visitorPage.locator('.product-card', { hasText: productName })).toHaveCount(0)
    await visitorPage.goto(`${BASE_URL}/jadwal`)
    await expect(publicPanel).toContainText(productName)
    await expect(publicPanel).toContainText('Sisa 6 dari kuota 6')
    await screenshot(visitorPage, testInfo, 'public-schedule-archived-product')
    await page.goto('/penjual/jadwal')

    // A past cutoff is a valid schedule, but the server must report it closed.
    await panel.getByRole('button', { name: 'Ubah waktu' }).click()
    await panel.getByLabel('Batas PO bersama (WIB)').fill('2020-01-01T20:00')
    await page.getByRole('button', { name: 'Simpan waktu' }).click()
    await expect(page.getByRole('status')).toContainText('Waktu jadwal disimpan')
    await expect(panel).toContainText('Ditutup')

    await visitorPage.goto(`${BASE_URL}/jadwal`)
    const closedPanel = visitorPage.locator('li.schedule-panel', { hasText: productName })
    await expect(closedPanel).toContainText('Ditutup')
    await expect(closedPanel).toContainText('Batas PO 1 Januari 2020, 20.00 WIB')
    await screenshot(visitorPage, testInfo, 'public-schedule-closed')
    await visitor.close()
  } finally {
    await cleanupSchedules(page)
    await cleanupProducts(page)
  }
})

test('seller form validates, recovers from a network error, and manages offers', async ({
  page,
}, testInfo) => {
  const firstProduct = uniqueName('Pertama')
  const secondProduct = uniqueName('Kedua')
  await resetSyntheticData(page)
  await createProduct(page, { name: firstProduct, price: 65000 })
  await createProduct(page, { name: secondProduct, price: 72000, unit: '1 loaf 650 gram' })
  await page.goto('/penjual/jadwal')

  try {
    await page.getByRole('button', { name: 'Buka jadwal' }).click()
    await expect(page.getByText('Isi tanggal dan waktu pengambilan dalam WIB.')).toBeVisible()
    await expect(page.getByText('Isi batas PO dalam WIB.')).toBeVisible()
    await expect(page.getByText('Pilih minimal satu produk dari katalog.')).toBeVisible()
    await expect(page.getByLabel('Waktu pengambilan (WIB)')).toBeFocused()
    await screenshot(page, testInfo, 'seller-schedule-validation')

    await fillScheduleForm(page)
    await page.getByRole('button', { name: 'Buka jadwal' }).click()
    await expect(page.getByText('Pilih minimal satu produk dari katalog.')).toBeVisible()
    await expect(page.locator('.product-picker input[type="checkbox"]').first()).toBeFocused()

    await expect(page.getByRole('group', { name: 'Produk yang ditawarkan' }))
      .toHaveAttribute('aria-describedby', 'schedule-offers-error')
    await expect(page.getByRole('checkbox', { name: firstProduct })).toHaveCSS('cursor', 'pointer')
    await expect(page.locator('.picker-check', { hasText: firstProduct }))
      .toHaveCSS('cursor', 'pointer')
    await page.getByRole('checkbox', { name: firstProduct }).check()
    await page.getByLabel(`Kuota ${firstProduct}`).fill('0')
    await page.getByRole('button', { name: 'Buka jadwal' }).click()
    await expect(page.getByText('Kuota harus bilangan bulat 1 sampai 999.')).toBeVisible()
    await expect(page.getByLabel(`Kuota ${firstProduct}`)).toBeFocused()

    await page.getByLabel(`Kuota ${firstProduct}`).fill('6')
    await page.route('**/api/seller/schedules', (route) => route.abort('connectionfailed'), {
      times: 1,
    })
    await page.getByRole('button', { name: 'Buka jadwal' }).click()
    await expect(page.getByRole('alert')).toContainText('Jaringan tidak tersedia')
    await expect(page.getByLabel('Waktu pengambilan (WIB)')).toHaveValue(OPEN_PICKUP)
    await screenshot(page, testInfo, 'seller-schedule-network-error')

    await page.route(
      '**/api/seller/schedules',
      async (route) => {
        await new Promise((resolve) => setTimeout(resolve, 700))
        await route.continue()
      },
      { times: 1 },
    )
    await page.getByRole('button', { name: 'Buka jadwal' }).click()
    await expect(page.getByRole('button', { name: 'Menyimpan jadwal...' })).toBeVisible()
    await expect(page.getByRole('status')).toContainText('Jadwal pre-order baru dibuka')

    const panel = page.locator('li.schedule-panel', { hasText: firstProduct })
    await panel.getByRole('button', { name: 'Tambah penawaran' }).click()
    await panel.getByLabel('Produk dari katalog').selectOption({ index: 1 })
    await panel.getByLabel('Kuota', { exact: true }).fill('2')
    await panel.locator('.inline-form').getByRole('button', { name: 'Tambah penawaran' }).click()
    await expect(page.getByRole('status')).toContainText('Penawaran baru ditambahkan')
    await expect(panel).toContainText(secondProduct)
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true)
    await screenshot(page, testInfo, 'seller-schedule-offers')

    const secondRow = panel.locator('li.offer-row', { hasText: secondProduct })
    await secondRow.getByLabel(`Kuota ${secondProduct}`).fill('4')
    await secondRow.getByRole('button', { name: 'Simpan penawaran' }).click()
    await expect(page.getByRole('status')).toContainText(`Penawaran "${secondProduct}" disimpan`)
    await expect(secondRow.getByLabel(`Kuota ${secondProduct}`)).toHaveValue('4')

    const removeTrigger = secondRow.getByRole('button', { name: 'Hapus penawaran' })
    await removeTrigger.click()
    await panel.locator('.confirm-panel').getByRole('button', { name: 'Batal' }).click()
    await expect(panel.locator('.confirm-panel')).toHaveCount(0)
    await expect(removeTrigger).toBeFocused()

    await removeTrigger.click()
    await panel.locator('.confirm-panel').getByRole('button', { name: 'Ya, hapus penawaran' }).click()
    await expect(page.getByRole('status')).toContainText('dihapus dari jadwal')
    await expect(panel).not.toContainText(secondProduct)

    const deleteTrigger = panel.getByRole('button', { name: 'Hapus jadwal' })
    await deleteTrigger.click()
    await panel.getByRole('button', { name: 'Batal' }).click()
    await expect(panel.getByRole('group')).toHaveCount(0)
    await expect(deleteTrigger).toBeFocused()

    await deleteTrigger.click()
    await panel.getByRole('button', { name: 'Ya, hapus jadwal' }).click()
    await expect(page.getByRole('status')).toContainText('dihapus')
    await expect(page.locator('li.schedule-panel')).toHaveCount(0)
    await screenshot(page, testInfo, 'seller-schedule-after-delete')
  } finally {
    await cleanupSchedules(page)
    await cleanupProducts(page)
  }
})

test('public schedule page shows an empty state and a recoverable error', async ({
  page,
}, testInfo) => {
  await page.goto('/jadwal')
  await expect(page.getByText('Belum ada jadwal pre-order.', { exact: true })).toBeVisible()
  await screenshot(page, testInfo, 'public-schedule-empty')

  await page.route('**/api/schedules', (route) => route.abort('connectionfailed'), {
    times: 1,
  })
  await page.reload()
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page.locator('.schedule-footnote')).toHaveCount(0)
  await screenshot(page, testInfo, 'public-schedule-network-error')

  const responsePromise = page.waitForResponse(
    (response) => new URL(response.url()).pathname === '/api/schedules',
  )
  await page.getByRole('button', { name: 'Coba lagi' }).click()
  const response = await responsePromise
  expect(response.status()).toBe(200)
  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect(page.getByText('Belum ada jadwal pre-order.', { exact: true })).toBeVisible()
})

test('buyer and anonymous visitors cannot open the seller schedule page', async ({
  page,
}, testInfo) => {
  await page.goto('/penjual/jadwal')
  await expect(page).toHaveURL(/\/masuk(\?|$)/)
  await expect(page.getByRole('status')).toContainText('Masuk untuk melanjutkan. Isi keranjang tetap tersimpan.')

  const email = `schedule-buyer-${Date.now()}-${Math.random().toString(16).slice(2, 8)}@example.com`
  await page.goto('/daftar')
  await page.getByLabel('Nama').fill('Schedule Buyer')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill('Synthetic-buyer-2026!')
  await page.getByRole('button', { name: 'Buat akun pembeli' }).click()
  await expect(page.getByRole('status')).toContainText('Akun pembeli berhasil dibuat')
  await page.getByRole('link', { name: 'Masuk ke akun' }).click()
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill('Synthetic-buyer-2026!')
  await page.getByRole('button', { name: 'Masuk' }).click()
  await expect(page).toHaveURL(/\/akun$/)

  await page.goto('/penjual/jadwal')
  await expect(page.getByRole('heading', { name: 'Akses ditolak' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Kembali ke kelola katalog' })).toHaveCount(0)
  await expect(page.getByRole('link', { name: 'Kembali ke akun' })).toBeVisible()
  await screenshot(page, testInfo, 'seller-schedule-denied')
})

test('seller archives a closed schedule, sees it only on request, and restores it', async ({
  page,
}, testInfo) => {
  const productName = uniqueName('Arsip')
  const snap = (name) => screenshot(page, testInfo, name)

  await resetSyntheticData(page)
  await createProduct(page, { name: productName, price: 65000 })
  await page.goto('/penjual/jadwal')
  await expect(
    page.getByRole('heading', { name: 'Kelola jadwal pre-order' }),
  ).toBeVisible()

  try {
    // A past cutoff is a normal closed schedule; no order is needed to archive it.
    await fillScheduleForm(page, { pickup: OPEN_PICKUP, cutoff: '2020-01-01T20:00' })
    await selectProduct(page, productName, 6)
    await page.getByRole('button', { name: 'Buka jadwal' }).click()
    await expect(page.getByRole('status')).toContainText('Jadwal pre-order baru dibuka')
    const panel = page.locator('li.schedule-panel', { hasText: productName })
    await expect(panel).toContainText('Ditutup')
    await expect(panel.getByRole('button', { name: 'Arsipkan' })).toBeVisible()

    // Archive asks for an explicit confirmation and returns focus on cancel.
    const archiveTrigger = panel.getByRole('button', { name: 'Arsipkan' })
    await archiveTrigger.click()
    const confirm = panel.getByRole('group', { name: /Konfirmasi arsip jadwal/ })
    await expect(confirm).toBeVisible()
    await confirm.getByRole('button', { name: 'Batal', exact: true }).click()
    await expect(confirm).toHaveCount(0)
    await expect(archiveTrigger).toBeFocused()

    await archiveTrigger.click()
    await panel
      .getByRole('group', { name: /Konfirmasi arsip jadwal/ })
      .getByRole('button', { name: 'Ya, arsipkan jadwal' })
      .click()
    await expect(page.getByRole('status')).toContainText('diarsipkan')
    await expect(page.getByRole('status')).toBeFocused()
    await expect(panel).toHaveCount(0)
    await expect(page.getByText('Tidak ada jadwal pada tampilan ini.', { exact: true })).toBeVisible()
    await snap('seller-schedule-archived-default')

    // Filtering keeps keyboard focus through loading, including empty lists.
    for (const [path, endpoint] of [
      ['/penjual/pesanan', '/api/seller/orders'],
      ['/penjual/rekap', '/api/seller/production-recap'],
    ]) {
      await page.goto(path)
      const filter = page.getByLabel('Sertakan arsip')
      await expect(filter).toBeVisible()
      for (const checked of [true, false]) {
        await Promise.all([
          page.waitForResponse((response) => new URL(response.url()).pathname === endpoint),
          filter.setChecked(checked),
        ])
        await expect(filter).toBeVisible()
        await expect.soft(filter).toBeFocused()
      }
      await page.route(`**${endpoint}*`, (route) => route.abort('connectionfailed'), { times: 1 })
      await filter.check()
      await expect(page.getByRole('alert')).toBeFocused()
      await page.getByRole('button', { name: 'Coba lagi' }).click()
      await expect(page.getByRole('alert')).toHaveCount(0)
      await expect(filter).toBeVisible()
    }
    await page.goto('/penjual/jadwal')

    // The public schedule list drops it, and no new order can be placed.
    const visitor = await page.context().browser().newContext()
    const visitorPage = await visitor.newPage()
    await visitorPage.goto(`${BASE_URL}/jadwal`)
    await expect(visitorPage.getByRole('heading', { name: 'Jadwal pre-order' })).toBeVisible()
    await expect(visitorPage.locator('li.schedule-panel', { hasText: productName })).toHaveCount(0)
    expect(
      await visitorPage.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true)
    await visitor.close()

    // Opting in shows the archived schedule read-only, with history intact.
    const reload = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === '/api/seller/schedules' &&
        response.request().method() === 'GET',
    )
    await page.getByLabel('Sertakan arsip').check()
    await reload
    const archivedPanel = page.locator('li.schedule-panel', { hasText: productName })
    await expect(archivedPanel).toContainText('Diarsipkan')
    await expect(archivedPanel).toContainText('sisa 6 dari 6')
    await expect(archivedPanel).not.toContainText('Ubah waktu')
    await expect(archivedPanel).not.toContainText('Hapus jadwal')
    await expect(archivedPanel.getByRole('button', { name: 'Pulihkan' })).toBeVisible()
    await snap('seller-schedule-archived-opt-in')

    await archivedPanel.getByRole('button', { name: 'Pulihkan' }).click()
    await expect(page.getByRole('status')).toContainText('dipulihkan')
    await expect(
      page.locator('li.schedule-panel', { hasText: productName }),
    ).not.toContainText('Diarsipkan')
    await expect(
      page.locator('li.schedule-panel', { hasText: productName }),
    ).toContainText('sisa 6 dari 6')
    await snap('seller-schedule-restored')

    const publicAgain = await page.context().browser().newContext()
    const publicAgainPage = await publicAgain.newPage()
    await publicAgainPage.goto(`${BASE_URL}/jadwal`)
    await expect(
      publicAgainPage.locator('li.schedule-panel', { hasText: productName }),
    ).toContainText('Ditutup')
    await publicAgain.close()
  } finally {
    await cleanupSchedules(page)
    await cleanupProducts(page)
  }
})

import { mkdirSync } from 'node:fs'
import { expect, test } from '@playwright/test'
import { purgeOrders } from './support/orders-db.js'

const SELLER = { email: 'seller@example.com', password: 'Demo-seller-2026!' }
const BUYER_PASSWORD = 'Synthetic-buyer-2026!'
const EVIDENCE = '../.local/t5-evidence'
const EVIDENCE_T6 = '../.local/t6-evidence'
const PREFIX = 'Pesanan Uji'
const OPEN_PICKUP = '2035-11-08T18:00'
const OPEN_CUTOFF = '2035-11-06T20:00'

function uniqueName(label) {
  return `${PREFIX} ${label} ${Date.now().toString(36)}`
}

function uniqueEmail(label) {
  return `${label}-${Date.now()}-${Math.random().toString(16).slice(2, 8)}@example.com`
}

async function screenshot(page, testInfo, name) {
  mkdirSync(EVIDENCE, { recursive: true })
  await page.screenshot({
    path: `${EVIDENCE}/${testInfo.project.name}-${name}.png`,
    fullPage: true,
  })
}

async function screenshotT6(page, testInfo, name) {
  mkdirSync(EVIDENCE_T6, { recursive: true })
  await page.screenshot({
    path: `${EVIDENCE_T6}/${testInfo.project.name}-${name}.png`,
    fullPage: true,
  })
}

async function waitSellerPage(page) {
  await expect(page.getByText('Memeriksa akses penjual...')).toHaveCount(0)
}

async function loginSeller(page) {
  await page.goto('/masuk')
  await page.getByLabel('Email').fill(SELLER.email)
  await page.getByLabel('Password').fill(SELLER.password)
  await page.getByRole('button', { name: 'Masuk' }).click()
  await expect(page.getByRole('heading', { name: 'Kelola katalog' })).toBeVisible()
}

async function loginBuyer(page, email) {
  await page.goto('/masuk')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(BUYER_PASSWORD)
  await page.getByRole('button', { name: 'Masuk' }).click()
}

async function registerBuyer(page, email, { keepLoggedIn = false } = {}) {
  await page.context().clearCookies()
  await page.goto('/daftar')
  await page.getByLabel('Nama').fill('Pembeli Uji')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(BUYER_PASSWORD)
  await page.getByRole('button', { name: 'Buat akun pembeli' }).click()
  await expect(page.getByRole('status')).toContainText('Akun pembeli berhasil dibuat')
  await page.getByRole('link', { name: 'Masuk ke akun' }).click()
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(BUYER_PASSWORD)
  await page.getByRole('button', { name: 'Masuk' }).click()
  await expect(page.getByRole('heading', { name: 'Akun Anda' })).toBeVisible()
  if (!keepLoggedIn) {
    await page.getByRole('button', { name: 'Keluar' }).click()
    await expect(page).toHaveURL(/\/masuk/)
  }
}

async function cleanupSchedules(page) {
  await page.goto('/penjual/jadwal')
  await expect(page.getByRole('heading', { name: 'Kelola jadwal pre-order' })).toBeVisible()
  await waitSellerPage(page)
  // Archived rows are hidden by default; cleanup must restore them before deleting.
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
  await waitSellerPage(page)
  // Archived products are hidden until the seller opts in; delete those too.
  if (!(await page.getByLabel('Sertakan arsip').isChecked())) {
    await page.getByLabel('Sertakan arsip').check()
  }
  // This spec resets all synthetic catalog rows in the local test database.
  const rows = page.locator('li.seller-product')
  while ((await rows.count()) > 0) {
    const before = await rows.count()
    await rows.first().getByRole('button', { name: 'Hapus', exact: true }).click()
    await rows.first().getByRole('button', { name: 'Ya, hapus permanen' }).click()
    await expect(page.getByRole('status')).toContainText('dihapus permanen')
    await expect.poll(() => rows.count()).toBe(before - 1)
  }
}

async function resetSyntheticData(page) {
  // The current session may be a buyer; the cleanup needs the seller account.
  await page.context().clearCookies()
  await loginSeller(page)
  purgeOrders()
  await cleanupSchedules(page)
  await cleanupProducts(page)
}

async function createProduct(page, { name, unit = '1 loaf 500 gram', price = 65000, description }) {
  await page.goto('/penjual')
  await waitSellerPage(page)
  await page.getByLabel('Nama produk').fill(name)
  await page.getByLabel('Unit jual').fill(unit)
  await page.getByLabel('Harga (Rupiah)').fill(String(price))
  if (description) {
    await page.getByLabel('Deskripsi (opsional)').fill(description)
  }
  await page.getByRole('button', { name: 'Tambah produk' }).click()
  await expect(page.getByRole('status')).toContainText('Produk baru ditambahkan')
}

async function createSchedule(page, products, { pickup = OPEN_PICKUP, cutoff = OPEN_CUTOFF } = {}) {
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
  await page.getByRole('button', { name: 'Buka jadwal' }).click()
  await expect(page.getByRole('status')).toContainText('Jadwal pre-order baru dibuka')
}

async function addToCart(page, productName, quantity = 1) {
  const panel = page.locator('li.schedule-panel', { hasText: productName })
  await panel.getByLabel(`Jumlah ${productName}`).fill(String(quantity))
  await panel.getByRole('button', { name: `Tambahkan ${productName} ke keranjang` }).click()
  await expect(page.getByRole('status')).toContainText(`${productName} masuk keranjang`)
}

function cartLink(page) {
  return page.locator('.site-nav').getByRole('link', { name: /Keranjang/ })
}

async function openCart(page) {
  await cartLink(page).click()
}

test('buyer keeps a drafted cart through login, reviews prices, checks out, and reads history', async ({
  page,
}, testInfo) => {
  const classic = uniqueName('Klasik')
  const longName = uniqueName('Gandum Utuh dengan Biji Bunga Matahari dan Dedak Halus')
  const buyer = uniqueEmail('buyer-cart')
  await resetSyntheticData(page)
  await createProduct(page, { name: classic, price: 65000 })
  await createProduct(page, {
    name: longName,
    unit: '1 loaf 650 gram',
    price: 72000,
    description: 'Deskripsi panjang untuk memeriksa teks yang membungkus.',
  })
  await createSchedule(page, [
    { name: classic, quota: 6 },
    { name: longName, quota: 6 },
  ])
  await registerBuyer(page, buyer)

  try {
    await page.goto('/jadwal')
    await expect(page.getByRole('heading', { name: 'Jadwal pre-order' })).toBeVisible()
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true)
    await screenshot(page, testInfo, 'public-jadwal-order-controls')

    await addToCart(page, classic, 2)
    await addToCart(page, longName, 1)
    await expect(cartLink(page)).toContainText('2')

    await openCart(page)
    // The guarded route keeps the draft and asks the buyer to sign in.
    await expect(page).toHaveURL(/\/masuk\?/)
    await expect(page.getByRole('status')).toContainText(
      'Masuk untuk melanjutkan. Isi keranjang tetap tersimpan.',
    )
    await page.getByLabel('Email').fill(buyer)
    await page.getByLabel('Password').fill(BUYER_PASSWORD)
    await page.getByRole('button', { name: 'Masuk' }).click()
    await expect(page).toHaveURL((url) => url.pathname === '/keranjang')

    await expect(page.getByRole('heading', { name: 'Tinjauan pesanan' })).toBeVisible()
    await expect(page.getByText(classic, { exact: false })).toBeVisible()
    await expect(page.getByText(longName, { exact: false })).toBeVisible()
    await expect(page.getByText('202.000')).toBeVisible()
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true)

    await page.goto('/pesanan')
    await expect(page.getByText('Belum ada pesanan.')).toBeVisible()
    await page.goto('/keranjang')
    await expect(page.getByRole('heading', { name: 'Tinjauan pesanan' })).toBeVisible()
    await expect(page.getByText(classic, { exact: false })).toBeVisible()
    await screenshot(page, testInfo, 'cart-review')

    await page.getByRole('button', { name: 'Kosongkan keranjang' }).click()
    const clearConfirm = page.getByRole('group', { name: 'Konfirmasi kosongkan keranjang' })
    await expect(clearConfirm).toBeVisible()
    await clearConfirm.getByRole('button', { name: 'Batal' }).click()
    await expect(page.getByRole('button', { name: 'Kosongkan keranjang' })).toBeFocused()

    const quantity = page.getByLabel(`Jumlah ${classic}`)
    await quantity.fill('0')
    await page.getByRole('button', { name: 'Buat pesanan' }).click()
    await expect(page.getByText('Jumlah harus bilangan bulat 1 sampai 999.')).toBeVisible()
    await expect(quantity).toBeFocused()
    await quantity.fill('3')
    await quantity.blur()
    await expect(page.getByText('267.000')).toBeVisible()

    // The seller changes one price after the buyer drafted the cart.
    const sellerContext = await page.context().browser().newContext()
    const sellerPage = await sellerContext.newPage()
    await loginSeller(sellerPage)
    await sellerPage.goto('/penjual/jadwal')
    await waitSellerPage(sellerPage)
    const offerRow = sellerPage.locator('li.offer-row', { hasText: longName })
    await offerRow.getByLabel(`Harga ${longName}`).fill('80000')
    await offerRow.getByRole('button', { name: 'Simpan penawaran' }).click()
    await expect(sellerPage.getByRole('status')).toContainText(
      `Penawaran "${longName}" disimpan`,
    )
    await sellerPage.close()
    await sellerContext.close()

    await page.reload()
    await expect(page.getByText('Harga berubah sejak produk dimasukkan ke keranjang:')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Buat pesanan' })).toBeDisabled()
    await screenshot(page, testInfo, 'cart-review-price-change')
    await page.getByRole('button', { name: 'Perbarui harga tinjauan' }).click()
    await expect(page.getByText('Harga berubah sejak produk dimasukkan ke keranjang:')).toHaveCount(0)
    await expect(page.getByText('275.000')).toBeVisible()

    await page.route(
      '**/api/orders',
      async (route) => {
        await new Promise((resolve) => setTimeout(resolve, 700))
        await route.continue()
      },
      { times: 1 },
    )
    await page.getByRole('button', { name: 'Buat pesanan' }).click()
    await expect(page.getByRole('button', { name: 'Mengirim pesanan...' })).toBeVisible()
    await expect(page).toHaveURL(/\/pesanan\/\d+\?baru=1$/)
    await expect(page.getByRole('status')).toContainText('berhasil dibuat')
    const orderNumber = await page.locator('.order-number').first().innerText()
    expect(orderNumber).toMatch(/^PO-\d{8}-\d{6}$/)
    await expect(page.getByText('Menunggu pembayaran')).toBeVisible()
    // The T6 payment panel repeats the order total, so this assertion targets
    // presence rather than requiring a single match on the whole page.
    await expect(page.getByText('275.000').first()).toBeVisible()
    await expect(page.getByText(longName, { exact: false })).toBeVisible()
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true)
    await screenshot(page, testInfo, 'order-success')

    await page.goto('/pesanan')
    await expect(page.getByRole('heading', { name: 'Pesanan saya' })).toBeVisible()
    await expect(page.getByText(orderNumber)).toBeVisible()
    await screenshot(page, testInfo, 'orders-history')
    await page.getByRole('link', { name: 'Lihat detail pesanan' }).first().click()
    await expect(page.getByRole('heading', { name: `Pesanan ${orderNumber}` })).toBeVisible()
    await screenshot(page, testInfo, 'order-detail')

    await page.goto('/keranjang')
    await expect(page.getByText('Keranjang masih kosong.')).toBeVisible()
  } finally {
    await resetSyntheticData(page)
  }
})

test('a lost checkout response retries with the same key and creates one order', async ({
  page,
}, testInfo) => {
  const productName = uniqueName('Retry')
  const buyer = uniqueEmail('buyer-retry')
  await resetSyntheticData(page)
  await createProduct(page, { name: productName, price: 65000 })
  await createSchedule(page, [{ name: productName, quota: 6 }])
  await registerBuyer(page, buyer, { keepLoggedIn: true })

  try {
    await page.goto('/jadwal')
    await addToCart(page, productName, 1)
    await openCart(page)
    await expect(page).toHaveURL((url) => url.pathname === '/keranjang')

    await page.route(
      '**/api/orders',
      async (route) => {
        if (route.request().method() !== 'POST') {
          await route.continue()
          return
        }
        // Let MySQL commit the order, then lose the response on the way back.
        await route.fetch()
        await route.abort('failed')
      },
      { times: 1 },
    )
    await page.getByRole('button', { name: 'Buat pesanan' }).click()
    await expect(page.getByRole('alert')).toContainText('Jaringan tidak tersedia')
    await expect(page).toHaveURL((url) => url.pathname === '/keranjang')
    await screenshot(page, testInfo, 'cart-network-error')

    await page.getByRole('button', { name: 'Buat pesanan' }).click()
    await expect(page).toHaveURL(/\/pesanan\/\d+/)
    await expect(page.getByRole('status')).toContainText('berhasil dibuat')
    await page.goto('/pesanan')
    await expect(page.locator('.order-card')).toHaveCount(1)
    await screenshot(page, testInfo, 'retry-single-order')
  } finally {
    await resetSyntheticData(page)
  }
})

test('quota conflict and a closed cutoff block checkout with actionable states', async ({
  page,
  browser,
}, testInfo) => {
  const productName = uniqueName('Terbatas')
  const buyerA = uniqueEmail('buyer-a')
  const buyerB = uniqueEmail('buyer-b')
  await resetSyntheticData(page)
  await createProduct(page, { name: productName, price: 65000 })
  await createSchedule(page, [{ name: productName, quota: 1 }])

  const buyerBContext = await browser.newContext()
  const buyerBPage = await buyerBContext.newPage()
  try {
    await registerBuyer(page, buyerA, { keepLoggedIn: true })
    await page.goto('/jadwal')
    await addToCart(page, productName, 1)
    await openCart(page)
    await expect(page).toHaveURL((url) => url.pathname === '/keranjang')
    await expect(page.getByText('Sisa kuota 1 dari 1')).toBeVisible()

    // The second buyer takes the last unit while buyer A reviews the old quote.
    await registerBuyer(buyerBPage, buyerB, { keepLoggedIn: true })
    await buyerBPage.goto('/jadwal')
    await addToCart(buyerBPage, productName, 1)
    await buyerBPage.locator('.site-nav').getByRole('link', { name: /Keranjang/ }).click()
    await buyerBPage.getByRole('button', { name: 'Buat pesanan' }).click()
    await expect(buyerBPage).toHaveURL(/\/pesanan\/\d+/)

    await page.getByRole('button', { name: 'Buat pesanan' }).click()
    await expect(page.getByRole('alert')).toContainText('Kuota')
    await expect(page.getByText('Sisa kuota 0 dari 1')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Buat pesanan' })).toBeDisabled()
    await screenshot(page, testInfo, 'cart-quota-conflict')

    // Closing the schedule after a draft is also visible and blocks submission.
    const sellerContext = await page.context().browser().newContext()
    const sellerPage = await sellerContext.newPage()
    await loginSeller(sellerPage)
    await sellerPage.goto('/penjual/jadwal')
    await waitSellerPage(sellerPage)
    const panel = sellerPage.locator('li.schedule-panel', { hasText: productName })
    await panel.getByRole('button', { name: 'Ubah waktu' }).click()
    await panel.getByLabel('Batas PO bersama (WIB)').fill('2020-01-01T20:00')
    await sellerPage.getByRole('button', { name: 'Simpan waktu' }).click()
    await expect(sellerPage.getByRole('status')).toContainText('Waktu jadwal disimpan')
    await sellerPage.close()
    await sellerContext.close()

    await page.reload()
    await expect(page.getByText('Sudah ditutup')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Buat pesanan' })).toBeDisabled()
    await screenshot(page, testInfo, 'cart-schedule-closed')
  } finally {
    await buyerBContext.close()
    await resetSyntheticData(page)
  }
})

test('seller edits price and quota while orders keep their snapshots and guards hold', async ({
  page,
}, testInfo) => {
  const productName = uniqueName('Editor')
  const buyer = uniqueEmail('buyer-editor')
  await resetSyntheticData(page)
  await createProduct(page, { name: productName, price: 65000 })
  await createSchedule(page, [{ name: productName, quota: 3 }])

  const buyerContext = await page.context().browser().newContext()
  const buyerPage = await buyerContext.newPage()
  try {
    await registerBuyer(buyerPage, buyer, { keepLoggedIn: true })
    await buyerPage.goto('/jadwal')
    await addToCart(buyerPage, productName, 2)
    await buyerPage.locator('.site-nav').getByRole('link', { name: /Keranjang/ }).click()
    await buyerPage.getByRole('button', { name: 'Buat pesanan' }).click()
    await expect(buyerPage).toHaveURL(/\/pesanan\/\d+/)
    const orderNumber = await buyerPage.locator('.order-number').first().innerText()

    await page.goto('/penjual/jadwal')
    const panel = page.locator('li.schedule-panel', { hasText: productName })
    const row = panel.locator('li.offer-row', { hasText: productName })
    await expect(row).toContainText('Teralokasi 2')
    await expect(row).toContainText('sisa 1 dari 3')
    const infoBeforeError = await row.locator('.offer-info').boundingBox()

    await row.getByLabel(`Kuota ${productName}`).fill('1')
    await row.getByRole('button', { name: 'Simpan penawaran' }).click()
    const offerError = row.getByRole('alert')
    await expect(offerError).toContainText('Kuota tidak boleh di bawah 2')
    await expect(offerError).toBeFocused()
    await expect(offerError).toBeInViewport({ ratio: 1 })
    const infoBox = await row.locator('.offer-info').boundingBox()
    expect(infoBox.width).toBeGreaterThanOrEqual(infoBeforeError.width - 1)
    await expect(row.getByLabel(`Kuota ${productName}`)).toHaveValue('1')
    await screenshot(page, testInfo, 'seller-offer-quota-guard')

    await row.getByLabel(`Kuota ${productName}`).fill('2')
    await row.getByLabel(`Harga ${productName}`).fill('70000')
    await page.route(
      '**/api/seller/schedules/*/offers/*',
      async (route) => {
        await new Promise((resolve) => setTimeout(resolve, 600))
        await route.continue()
      },
      { times: 1 },
    )
    await row.getByRole('button', { name: 'Simpan penawaran' }).click()
    await expect(page.getByRole('button', { name: 'Menyimpan penawaran...' })).toBeVisible()
    await expect(page.getByRole('status')).toContainText(`Penawaran "${productName}" disimpan`)
    await expect(row).toContainText('Teralokasi 2')
    await expect(row).toContainText('sisa 0 dari 2')
    await expect(row.getByRole('alert')).toHaveCount(0)
    await screenshot(page, testInfo, 'seller-offer-editor')

    await buyerPage.goto('/pesanan')
    await buyerPage.getByRole('link', { name: 'Lihat detail pesanan' }).first().click()
    await expect(buyerPage.getByRole('heading', { name: `Pesanan ${orderNumber}` })).toBeVisible()
    await expect(buyerPage.getByText('65.000')).toBeVisible()
    await screenshot(buyerPage, testInfo, 'order-snapshot-after-price-edit')

    await panel.getByRole('button', { name: 'Hapus jadwal' }).click()
    await panel.getByRole('button', { name: 'Ya, hapus jadwal' }).click()
    await expect(page.getByRole('alert')).toContainText('sudah memiliki pesanan')
    await screenshot(page, testInfo, 'seller-schedule-delete-guard')
  } finally {
    await buyerContext.close()
    await resetSyntheticData(page)
  }
})


async function openSellerWorklist(page) {
  await page.locator('.site-nav').getByRole('link', { name: 'Pesanan', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Pesanan masuk' })).toBeVisible()
}

async function openSellerOrder(page, orderNumber) {
  const card = page.locator('li.order-card', { hasText: orderNumber })
  await card.getByRole('link', { name: 'Buka tindakan pesanan' }).click()
  await expect(
    page.getByRole('heading', { name: `Tindakan pesanan ${orderNumber}` }),
  ).toBeVisible()
}

test('buyer reports a simulated transfer and seller verifies only a matching amount', async ({
  page,
}, testInfo) => {
  const productName = uniqueName('Bayar')
  const buyer = uniqueEmail('buyer-bayar')
  const note = 'Transfer 31 Okt, pengirim A***, nominal pas.'
  await resetSyntheticData(page)
  await createProduct(page, { name: productName, price: 65000 })
  await createSchedule(page, [{ name: productName, quota: 6 }])
  await registerBuyer(page, buyer, { keepLoggedIn: true })

  const sellerContext = await page.context().browser().newContext()
  const sellerPage = await sellerContext.newPage()
  try {
    await page.goto('/jadwal')
    await addToCart(page, productName, 2)
    await openCart(page)
    await expect(page).toHaveURL((url) => url.pathname === '/keranjang')
    await page.getByRole('button', { name: 'Buat pesanan' }).click()
    await expect(page).toHaveURL(/\/pesanan\/\d+\?baru=1$/)
    const orderNumber = await page.locator('.order-number').first().innerText()

    await expect(page.getByRole('heading', { name: 'Pembayaran transfer' })).toBeVisible()
    const paymentPanel = page.locator('.payment-panel')
    await expect(paymentPanel).toContainText('belum lunas')
    await expect(paymentPanel).toContainText('belum diverifikasi')
    await expect(paymentPanel).not.toContainText(/simulasi|sintetis/i)
    await expect(page.locator('.demo-tag')).toHaveCount(0)
    await expect(page.locator('.site-header').getByText('Hanya Roti Biasa')).toBeVisible()
    await expect(page.getByText('130.000').first()).toBeVisible()
    await expect(page.locator('.payment-panel')).toContainText('6 November 2035, 20.00 WIB')
    await screenshotT6(page, testInfo, 'buyer-payment-simulation')

    const noteInput = page.locator('#transfer-note')
    await expect(noteInput).toHaveAttribute('aria-describedby', 'transfer-note-help')
    await noteInput.fill('ab')
    await page.getByRole('button', { name: 'Kirim konfirmasi transfer' }).click()
    await expect(page.getByText('Keterangan harus 3 sampai 200 karakter.')).toBeVisible()
    await expect(noteInput).toBeFocused()
    await expect(noteInput).toHaveAttribute('aria-describedby', 'transfer-note-help transfer-note-error')

    await noteInput.fill(note)
    await page.getByRole('button', { name: 'Kirim konfirmasi transfer' }).click()
    await expect(page.locator('.status-tag')).toContainText('Menunggu pemeriksaan')
    await expect(page.getByRole('status')).toContainText('belum lunas')
    await expect(page.getByRole('status')).toBeFocused()
    await expect(page.getByRole('button', { name: 'Batalkan pesanan' })).toHaveCount(0)
    await screenshotT6(page, testInfo, 'buyer-transfer-reported')

    await loginSeller(sellerPage)
    await openSellerWorklist(sellerPage)
    const worklistCard = sellerPage.locator('li.order-card', { hasText: orderNumber })
    await expect(worklistCard).toContainText(buyer)
    await expect(worklistCard).toContainText('Menunggu pemeriksaan')
    await expect(worklistCard).toContainText(note)
    await screenshotT6(sellerPage, testInfo, 'seller-worklist')

    await openSellerOrder(sellerPage, orderNumber)
    await expect(sellerPage.locator('#received-total')).toHaveAttribute('aria-describedby', 'received-total-help')
    await expect(sellerPage.locator('#cancel-reason')).toHaveAttribute('aria-describedby', 'cancel-reason-help')
    await expect(sellerPage.locator('#refund-outcome')).toHaveAttribute('aria-describedby', 'refund-outcome-help')
    await expect(sellerPage.getByText(note)).toBeVisible()
    await sellerPage.route(
      '**/api/seller/orders/*/verify',
      async (route) => {
        await new Promise((resolve) => setTimeout(resolve, 600))
        await route.continue()
      },
      { times: 1 },
    )
    await sellerPage.getByLabel('Jumlah dana yang benar-benar diterima (Rupiah)').fill('129999')
    await sellerPage.getByRole('button', { name: 'Verifikasi pembayaran' }).click()
    await expect(sellerPage.getByRole('button', { name: 'Memverifikasi...' })).toBeVisible()
    const mismatch = sellerPage.getByRole('alert').filter({ hasText: 'tidak sama dengan total pesanan' })
    await expect(mismatch).toBeVisible()
    await expect(mismatch).toBeFocused()
    await expect(sellerPage.locator('.status-tag')).toContainText('Menunggu pemeriksaan')
    await screenshotT6(sellerPage, testInfo, 'seller-verify-mismatch')

    await sellerPage
      .getByLabel('Jumlah dana yang benar-benar diterima (Rupiah)')
      .fill('130000')
    await sellerPage.getByRole('button', { name: 'Verifikasi pembayaran' }).click()
    await expect(sellerPage.getByRole('status')).toContainText('tercatat terkonfirmasi')
    await expect(sellerPage.getByRole('status')).toBeFocused()
    await expect(sellerPage.locator('.status-tag')).toContainText('Terkonfirmasi')
    await expect(sellerPage.getByRole('button', { name: 'Verifikasi pembayaran' })).toHaveCount(0)
    await screenshotT6(sellerPage, testInfo, 'seller-verified')

    await page.reload()
    await expect(page.getByRole('heading', { name: 'Pembayaran terverifikasi penjual' })).toBeVisible()
    await expect(page.getByText('130.000').first()).toBeVisible()
    await expect(page.getByRole('button', { name: 'Batalkan pesanan' })).toHaveCount(0)
    await screenshotT6(page, testInfo, 'buyer-verified')
  } finally {
    await sellerPage.close()
    await sellerContext.close()
    await resetSyntheticData(page)
  }
})

test('buyer cancels before confirmation, returns quota once, and the order stays final', async ({
  page,
}, testInfo) => {
  const productName = uniqueName('Batal')
  const buyer = uniqueEmail('buyer-batal')
  await resetSyntheticData(page)
  await createProduct(page, { name: productName, price: 65000 })
  await createSchedule(page, [{ name: productName, quota: 2 }])
  await registerBuyer(page, buyer, { keepLoggedIn: true })

  await page.goto('/jadwal')
  await addToCart(page, productName, 1)
  await openCart(page)
  await expect(page).toHaveURL((url) => url.pathname === '/keranjang')
  await page.getByRole('button', { name: 'Buat pesanan' }).click()
  await expect(page).toHaveURL(/\/pesanan\/\d+/)
  const orderNumber = await page.locator('.order-number').first().innerText()

  try {
    const cancelTrigger = page.getByRole('button', { name: 'Batalkan pesanan' })
    await cancelTrigger.click()
    const confirm = page.getByRole('group', { name: 'Konfirmasi pembatalan pesanan' })
    await expect(confirm.getByRole('button', { name: 'Ya, batalkan pesanan' })).toBeFocused()
    await screenshotT6(page, testInfo, 'buyer-cancel-confirm')
    await confirm.getByRole('button', { name: 'Tidak, kembali' }).click()
    await expect(cancelTrigger).toBeFocused()

    await cancelTrigger.click()
    await confirm.getByRole('button', { name: 'Ya, batalkan pesanan' }).click()
    await expect(page.getByRole('status')).toContainText('dibatalkan sebelum konfirmasi transfer')
    await expect(page.getByRole('status')).toBeFocused()
    await expect(page.locator('.status-tag')).toContainText('Batal')
    await expect(page.getByRole('heading', { name: 'Pesanan batal' })).toBeVisible()
    await expect(page.getByText('Dibatalkan oleh')).toBeVisible()
    await expect(page.getByText('Pembeli', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Batalkan pesanan' })).toHaveCount(0)
    await screenshotT6(page, testInfo, 'buyer-cancelled')

    await page.context().clearCookies()
    await loginSeller(page)
    await page.goto('/penjual/jadwal')
    await waitSellerPage(page)
    const panel = page.locator('li.schedule-panel', { hasText: productName })
    await expect(panel).toContainText('Teralokasi 0')
    await expect(panel).toContainText('sisa 2 dari 2')
    await openSellerWorklist(page)
    await expect(
      page.locator('li.order-card', { hasText: orderNumber }).getByText('Batal', { exact: true }),
    ).toBeVisible()
    const cancelledCard = page.locator('li.order-card', { hasText: orderNumber })
    await expect(cancelledCard.getByRole('link', { name: 'Buka detail pesanan' })).toBeVisible()
    await expect(cancelledCard.getByRole('link', { name: 'Buka tindakan pesanan' })).toHaveCount(0)
    await screenshotT6(page, testInfo, 'seller-worklist-cancelled')
  } finally {
    await resetSyntheticData(page)
  }
})

test('seller cancellation after verification requires a settled manual refund', async ({
  page,
}, testInfo) => {
  const productName = uniqueName('Refund')
  const buyer = uniqueEmail('buyer-refund')
  const reason = 'Pesanan tidak dapat dipenuhi; dana sudah dikembalikan manual.'
  await resetSyntheticData(page)
  await createProduct(page, { name: productName, price: 65000 })
  await createSchedule(page, [{ name: productName, quota: 6 }])
  await registerBuyer(page, buyer, { keepLoggedIn: true })

  const sellerContext = await page.context().browser().newContext()
  const sellerPage = await sellerContext.newPage()
  try {
    await page.goto('/jadwal')
    await addToCart(page, productName, 2)
    await openCart(page)
    await expect(page).toHaveURL((url) => url.pathname === '/keranjang')
    await page.getByRole('button', { name: 'Buat pesanan' }).click()
    await expect(page).toHaveURL(/\/pesanan\/\d+/)
    const orderNumber = await page.locator('.order-number').first().innerText()

    await loginSeller(sellerPage)
    await sellerPage.goto(new URL(page.url()).pathname)
    await expect(sellerPage.getByText('Gunakan detail penjual untuk memeriksa pembayaran dan menangani pesanan ini.')).toBeVisible()
    await expect(sellerPage.getByText('Tahap pemenuhan pesanan dikerjakan pada tiket berikutnya.', { exact: false })).toHaveCount(0)
    await openSellerWorklist(sellerPage)
    await openSellerOrder(sellerPage, orderNumber)
    await sellerPage
      .getByLabel('Jumlah dana yang benar-benar diterima (Rupiah)')
      .fill('130000')
    await sellerPage.getByRole('button', { name: 'Verifikasi pembayaran' }).click()
    await expect(sellerPage.getByRole('status')).toContainText('tercatat terkonfirmasi')

    const refundOptions = await sellerPage.locator('#refund-outcome option').allTextContents()
    expect(refundOptions).not.toContain('Dana belum atau tidak saya terima')
    await sellerPage.getByRole('button', { name: 'Batalkan pesanan' }).click()
    await expect(sellerPage.getByText('Alasan harus 3 sampai 300 karakter.')).toBeVisible()
    await expect(sellerPage.locator('#cancel-reason')).toBeFocused()
    await expect(sellerPage.locator('#cancel-reason')).toHaveAttribute('aria-describedby', 'cancel-reason-help cancel-reason-error')
    await expect(sellerPage.locator('#refund-outcome')).toHaveAttribute('aria-describedby', 'refund-outcome-help refund-outcome-error')

    await sellerPage.locator('#cancel-reason').fill(reason)
    await sellerPage
      .locator('#refund-outcome')
      .selectOption('refunded_manually')
    await sellerPage.getByRole('button', { name: 'Batalkan pesanan' }).click()
    const confirm = sellerPage.getByRole('group', { name: 'Konfirmasi pembatalan pesanan' })
    await expect(confirm.getByRole('button', { name: 'Ya, catat pembatalan' })).toBeFocused()
    await confirm.getByRole('button', { name: 'Ya, catat pembatalan' }).click()
    await expect(sellerPage.getByRole('status')).toContainText('Pembatalan tercatat')
    await expect(sellerPage.getByRole('status')).toBeFocused()
    await expect(sellerPage.getByRole('heading', { name: `Detail pesanan ${orderNumber}` })).toBeVisible()
    await expect(sellerPage.getByText('Pembatalan tidak boleh menyatakan dana belum diterima', { exact: false })).toHaveCount(0)
    await expect(sellerPage.locator('.status-tag')).toContainText('Batal')
    await expect(sellerPage.getByText('Dana sudah dikembalikan manual di luar aplikasi.')).toBeVisible()
    await expect(sellerPage.getByText('Pembayaran terverifikasi')).toBeVisible()
    await screenshotT6(sellerPage, testInfo, 'seller-cancelled-refund')

    await page.reload()
    await expect(page.getByRole('heading', { name: 'Pesanan batal' })).toBeVisible()
    await expect(page.getByText(reason)).toBeVisible()
    await expect(page.getByText('Dana sudah dikembalikan manual di luar aplikasi.')).toBeVisible()
    await expect(page.getByText('Pembayaran terverifikasi')).toBeVisible()
    await screenshotT6(page, testInfo, 'buyer-cancelled-refund')
  } finally {
    await sellerPage.close()
    await sellerContext.close()
    await resetSyntheticData(page)
  }
})

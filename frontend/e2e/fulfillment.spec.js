import { mkdirSync } from 'node:fs'
import { expect, test } from '@playwright/test'
import { purgeOrders } from './support/orders-db.js'

const SELLER = { email: 'seller@example.com', password: 'Demo-seller-2026!' }
const BUYER_PASSWORD = 'Synthetic-buyer-2026!'
const EVIDENCE = '../.local/t7-evidence'
const PREFIX = 'Pemenuhan Uji'
const PICKUP = '2035-11-08T18:00'
const CUTOFF = '2035-11-06T20:00'

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

async function noHorizontalOverflow(page) {
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
  ).toBe(true)
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

async function registerBuyer(page, email) {
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
  await page.context().clearCookies()
  await loginSeller(page)
  purgeOrders()
  await cleanupSchedules(page)
  await cleanupProducts(page)
}

async function createProduct(page, { name, unit = '1 loaf 500 gram', price = 65000 }) {
  await page.goto('/penjual')
  await waitSellerPage(page)
  await page.getByLabel('Nama produk').fill(name)
  await page.getByLabel('Unit jual').fill(unit)
  await page.getByLabel('Harga (Rupiah)').fill(String(price))
  await page.getByRole('button', { name: 'Tambah produk' }).click()
  await expect(page.getByRole('status')).toContainText('Produk baru ditambahkan')
}

async function createSchedule(page, products) {
  await page.goto('/penjual/jadwal')
  await expect(page.getByRole('heading', { name: 'Kelola jadwal pre-order' })).toBeVisible()
  await waitSellerPage(page)
  const openButton = page.getByRole('button', { name: 'Buat jadwal baru' })
  if (await openButton.isVisible()) {
    await openButton.click()
  }
  await page.getByLabel('Waktu pengambilan (WIB)').fill(PICKUP)
  await page.getByLabel('Batas PO bersama (WIB)').fill(CUTOFF)
  for (const product of products) {
    await page.getByRole('checkbox', { name: product.name }).check()
    await page.getByLabel(`Kuota ${product.name}`).fill(String(product.quota))
  }
  await page.getByRole('button', { name: 'Buka jadwal' }).click()
  await expect(page.getByRole('status')).toContainText('Jadwal pre-order baru dibuka')
}

async function addToCart(page, productName, quantity) {
  const panel = page.locator('li.schedule-panel', { hasText: productName })
  await panel.getByLabel(`Jumlah ${productName}`).fill(String(quantity))
  await panel.getByRole('button', { name: `Tambahkan ${productName} ke keranjang` }).click()
  await expect(page.getByRole('status')).toContainText(`${productName} masuk keranjang`)
}

async function checkout(page) {
  await page.locator('.site-nav').getByRole('link', { name: /Keranjang/ }).click()
  await expect(page.getByRole('heading', { name: 'Tinjauan pesanan' })).toBeVisible()
  await page.getByRole('button', { name: 'Buat pesanan' }).click()
  await expect(page).toHaveURL(/\/pesanan\/\d+(\?|$)/)
  const orderId = Number(new URL(page.url()).pathname.split('/').pop())
  const orderNumber = await page.locator('.order-number').first().innerText()
  return { orderId, orderNumber }
}

async function openSellerWorklist(page) {
  await page.locator('.site-nav').getByRole('link', { name: 'Pesanan', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Pesanan masuk' })).toBeVisible()
}

async function openSellerOrder(page, orderNumber) {
  const card = page.locator('li.order-card', { hasText: orderNumber })
  await card.getByRole('link', { name: 'Buka tindakan pesanan' }).click()
  await expect(
    page.getByRole('heading', { name: /Tindakan pesanan|Detail pesanan/ }),
  ).toBeVisible()
}

async function verifyPayment(sellerPage, amount) {
  await sellerPage
    .getByLabel('Jumlah dana yang benar-benar diterima (Rupiah)')
    .fill(String(amount))
  await sellerPage.getByRole('button', { name: 'Verifikasi pembayaran' }).click()
  await expect(sellerPage.getByRole('status')).toContainText('tercatat terkonfirmasi')
}

test('seller marks ready then complete while the recap keeps counting and buyer monitors', async ({
  page,
}, testInfo) => {
  const classic = uniqueName('Klasik')
  const whole = uniqueName('Gandum')
  const buyer = uniqueEmail('buyer-pemenuhan')
  await resetSyntheticData(page)
  await createProduct(page, { name: classic, price: 65000 })
  await createProduct(page, { name: whole, unit: '1 pak 4 irisan', price: 72000 })
  await createSchedule(page, [
    { name: classic, quota: 6 },
    { name: whole, quota: 6 },
  ])
  await registerBuyer(page, buyer)

  const sellerContext = await page.context().browser().newContext()
  const sellerPage = await sellerContext.newPage()
  try {
    await page.goto('/jadwal')
    await addToCart(page, classic, 2)
    await addToCart(page, whole, 1)
    const { orderId, orderNumber } = await checkout(page)
    expect(orderNumber).toMatch(/^PO-\d{8}-\d{6}$/)
    // 2 x 65.000 + 1 x 72.000
    await expect(page.getByText('202.000').first()).toBeVisible()

    await loginSeller(sellerPage)
    await sellerPage.goto('/penjual/rekap')
    await expect(sellerPage.getByRole('heading', { name: 'Rekap produksi' })).toBeVisible()
    // An unpaid order is excluded until the seller verifies the funds.
    await expect(
      sellerPage.getByText('Belum ada pesanan terbayar pada jadwal ini.'),
    ).toBeVisible()
    await noHorizontalOverflow(sellerPage)

    await openSellerWorklist(sellerPage)
    await openSellerOrder(sellerPage, orderNumber)
    await verifyPayment(sellerPage, 202000)
    await expect(sellerPage.locator('.status-tag')).toContainText('Terkonfirmasi')
    await expect(sellerPage.getByRole('button', { name: 'Tandai selesai' })).toHaveCount(0)
    await screenshot(sellerPage, testInfo, 'seller-fulfillment-ready-control')

    await sellerPage.getByRole('button', { name: 'Tandai siap diambil' }).click()
    await expect(sellerPage.getByRole('status')).toContainText('ditandai siap diambil')
    await expect(sellerPage.getByRole('status')).toBeFocused()
    await expect(sellerPage.locator('.status-tag')).toContainText('Siap diambil')
    await expect(sellerPage.getByRole('button', { name: 'Tandai siap diambil' })).toHaveCount(0)
    await expect(sellerPage.getByRole('button', { name: 'Tandai selesai' })).toBeVisible()

    await sellerPage.goto('/penjual/rekap')
    const scheduleCard = sellerPage.locator('li.recap-schedule')
    await expect(scheduleCard).toHaveCount(1)
    await expect(scheduleCard).toContainText(classic)
    await expect(scheduleCard).toContainText('2 unit jual')
    await expect(scheduleCard).toContainText(whole)
    await expect(scheduleCard).toContainText('1 unit jual')
    await expect(scheduleCard).toContainText('Total 3 unit jual untuk jadwal ini.')
    await noHorizontalOverflow(sellerPage)
    await screenshot(sellerPage, testInfo, 'seller-production-recap-ready')

    await page.reload()
    await expect(page.getByRole('heading', { name: 'Pesanan siap diambil' })).toBeVisible()
    await expect(page.locator('.status-tag')).toContainText('Siap diambil')
    await expect(page.getByRole('button', { name: 'Batalkan pesanan' })).toHaveCount(0)
    await screenshot(page, testInfo, 'buyer-order-ready')

    await openSellerWorklist(sellerPage)
    await openSellerOrder(sellerPage, orderNumber)
    await sellerPage.getByRole('button', { name: 'Tandai selesai' }).click()
    const confirm = sellerPage.getByRole('group', { name: 'Konfirmasi pesanan selesai' })
    await expect(confirm.getByRole('button', { name: 'Ya, tandai selesai' })).toBeFocused()
    await confirm.getByRole('button', { name: 'Ya, tandai selesai' }).click()
    await expect(sellerPage.getByRole('status')).toContainText('ditandai selesai')
    await expect(sellerPage.getByRole('status')).toBeFocused()
    await expect(sellerPage.locator('.status-tag')).toContainText('Selesai')
    await expect(sellerPage.getByRole('heading', { name: 'Pesanan selesai' })).toBeVisible()
    await expect(sellerPage.getByRole('button', { name: 'Batalkan pesanan' })).toHaveCount(0)
    await expect(sellerPage.getByRole('button', { name: 'Tandai selesai' })).toHaveCount(0)
    await screenshot(sellerPage, testInfo, 'seller-order-completed')

    // Completion never removes the quantity from the recap.
    await sellerPage.goto('/penjual/rekap')
    await expect(sellerPage.locator('li.recap-schedule')).toContainText(
      'Total 3 unit jual untuk jadwal ini.',
    )
    await screenshot(sellerPage, testInfo, 'seller-production-recap-completed')

    await page.reload()
    await expect(page.getByRole('heading', { name: 'Pesanan selesai' })).toBeVisible()
    await expect(page.locator('.payment-panel').getByRole('status')).toContainText(
      'Penjual mencatat pesanan ini sudah diserahkan kepada pembeli.',
    )
    await expect(page.locator('.status-tag')).toContainText('Selesai')
    await expect(page.getByRole('button', { name: 'Batalkan pesanan' })).toHaveCount(0)
    await expect(page.getByText('202.000').first()).toBeVisible()
    await screenshot(page, testInfo, 'buyer-order-completed')

    // The buyer can monitor but never open seller surfaces or transitions.
    await page.goto('/penjual/rekap')
    await expect(page.getByRole('heading', { name: 'Akses ditolak' })).toBeVisible()
    await page.goto(`/penjual/pesanan/${orderId}`)
    await expect(page.getByRole('heading', { name: 'Akses ditolak' })).toBeVisible()
  } finally {
    await sellerPage.close()
    await sellerContext.close()
    await resetSyntheticData(page)
  }
})

test('a ready order is cancelled only with a manual refund and leaves the recap', async ({
  page,
}, testInfo) => {
  const productName = uniqueName('Batal Siap')
  const buyer = uniqueEmail('buyer-batal-siap')
  const reason = 'Pesanan tidak dapat diserahkan; dana sudah dikembalikan manual.'
  await resetSyntheticData(page)
  await createProduct(page, { name: productName, price: 65000 })
  await createSchedule(page, [{ name: productName, quota: 4 }])
  await registerBuyer(page, buyer)

  const sellerContext = await page.context().browser().newContext()
  const sellerPage = await sellerContext.newPage()
  try {
    await page.goto('/jadwal')
    await addToCart(page, productName, 2)
    const { orderNumber } = await checkout(page)

    await loginSeller(sellerPage)
    await openSellerWorklist(sellerPage)
    await openSellerOrder(sellerPage, orderNumber)
    await verifyPayment(sellerPage, 130000)
    await sellerPage.getByRole('button', { name: 'Tandai siap diambil' }).click()
    await expect(sellerPage.getByRole('status')).toContainText('ditandai siap diambil')
    await expect(sellerPage.getByRole('button', { name: 'Tandai selesai' })).toBeVisible()
    await expect(sellerPage.getByRole('button', { name: 'Batalkan pesanan' })).toBeVisible()
    await screenshot(sellerPage, testInfo, 'seller-ready-cancel-control')

    // A verified payment can only be cancelled after a settled manual refund.
    const refundOptions = await sellerPage.locator('#refund-outcome option').allTextContents()
    expect(refundOptions).not.toContain('Dana belum atau tidak saya terima')

    await sellerPage.getByRole('button', { name: 'Batalkan pesanan' }).click()
    await expect(sellerPage.getByText('Alasan harus 3 sampai 300 karakter.')).toBeVisible()
    await expect(sellerPage.locator('#cancel-reason')).toBeFocused()
    await sellerPage.locator('#cancel-reason').fill(reason)
    await sellerPage.locator('#refund-outcome').selectOption('refunded_manually')
    await sellerPage.getByRole('button', { name: 'Batalkan pesanan' }).click()
    const confirm = sellerPage.getByRole('group', { name: 'Konfirmasi pembatalan pesanan' })
    await confirm.getByRole('button', { name: 'Ya, catat pembatalan' }).click()
    await expect(sellerPage.getByRole('status')).toContainText('Pembatalan tercatat')
    await expect(sellerPage.getByRole('status')).toBeFocused()
    await expect(sellerPage.locator('.status-tag')).toContainText('Batal')
    await expect(sellerPage.getByText('Dana sudah dikembalikan manual di luar aplikasi.')).toBeVisible()
    await expect(sellerPage.getByRole('button', { name: 'Tandai selesai' })).toHaveCount(0)
    await screenshot(sellerPage, testInfo, 'seller-ready-cancelled')

    // Cancellation releases the allocation and removes the quantity from the recap.
    await sellerPage.goto('/penjual/jadwal')
    await waitSellerPage(sellerPage)
    const panel = sellerPage.locator('li.schedule-panel', { hasText: productName })
    await expect(panel).toContainText('Teralokasi 0')
    await expect(panel).toContainText('sisa 4 dari 4')
    await sellerPage.goto('/penjual/rekap')
    await expect(
      sellerPage.getByText('Belum ada pesanan terbayar pada jadwal ini.'),
    ).toBeVisible()
    await screenshot(sellerPage, testInfo, 'seller-production-recap-cancelled')

    await page.reload()
    await expect(page.getByRole('heading', { name: 'Pesanan batal' })).toBeVisible()
    await expect(page.locator('.status-tag')).toContainText('Batal')
    await expect(page.getByText(reason)).toBeVisible()
    await expect(page.getByText('Dana sudah dikembalikan manual di luar aplikasi.')).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Pesanan siap diambil' })).toHaveCount(0)
    await expect(page.getByRole('button', { name: 'Batalkan pesanan' })).toHaveCount(0)
    await screenshot(page, testInfo, 'buyer-ready-cancelled')
  } finally {
    await sellerPage.close()
    await sellerContext.close()
    await resetSyntheticData(page)
  }
})

import { mkdirSync } from 'node:fs'
import { expect, test } from '@playwright/test'

const SELLER = { email: 'seller@example.com', password: 'Demo-seller-2026!' }
const EVIDENCE = '../.local/t3-evidence'

function uniqueName(label) {
  return `${label} ${Date.now().toString(36)}`
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

async function createProduct(page, { name, unit, price, description }) {
  await page.getByLabel('Nama produk').fill(name)
  await page.getByLabel('Unit jual').fill(unit)
  await page.getByLabel('Harga (Rupiah)').fill(String(price))
  if (description) {
    await page.getByLabel('Deskripsi (opsional)').fill(description)
  }
  await page.getByRole('button', { name: 'Tambah produk' }).click()
  await expect(page.getByRole('status')).toContainText('Produk baru ditambahkan')
}

async function deleteAllMatching(page, text) {
  // Archived leftovers are hidden until the seller opts in; permanently delete
  // them too so a repeated run does not inherit stale rows.
  if (!(await page.getByLabel('Sertakan arsip').isChecked())) {
    await page.getByLabel('Sertakan arsip').check()
  }
  const rows = page.locator('li.seller-product', { hasText: text })
  for (let remaining = await rows.count(); remaining > 0; remaining = await rows.count()) {
    await rows.first().getByRole('button', { name: 'Hapus' }).click()
    await rows.first().getByRole('button', { name: 'Ya, hapus permanen' }).click()
    await expect(page.getByRole('status')).toContainText('dihapus permanen')
  }
}

async function deleteProductByName(page, name, testInfo) {
  if (!(await page.getByLabel('Sertakan arsip').isChecked())) {
    await page.getByLabel('Sertakan arsip').check()
  }
  const row = page.locator('li.seller-product', { hasText: name })
  const trigger = row.getByRole('button', { name: 'Hapus', exact: true })
  await trigger.click()
  await row.getByRole('button', { name: 'Batal', exact: true }).click()
  await expect(row.getByRole('group')).toHaveCount(0)
  await expect(trigger).toBeFocused()

  await trigger.press('Enter')
  await page.keyboard.press('Tab')
  const confirm = row.getByRole('button', { name: 'Ya, hapus permanen' })
  await expect(confirm).toBeFocused()
  if (testInfo) {
    await screenshot(page, testInfo, 'seller-delete-confirmation')
  }
  await confirm.press('Enter')
  await expect(page.getByRole('status')).toContainText('dihapus permanen')
  await expect(page.getByRole('status')).toBeFocused()
}

async function expectPublicCopyWithoutDemoLabels(page) {
  await expect(page.locator('.site-header').getByText('Hanya Roti Biasa')).toBeVisible()
  await expect(page.locator('.demo-tag')).toHaveCount(0)
  await expect(page.locator('.catalog-hero-copy')).not.toContainText(
    /demo|sintetis|belum beroperasi/i,
  )
  await expect(page.locator('.site-footer')).not.toContainText(
    /demo|sintetis|belum beroperasi/i,
  )
  await expect(page.locator('.catalog-hero-figure figcaption')).toHaveCount(0)
  await expect(page.locator('.catalog-hero-figure img')).toHaveAttribute(
    'alt',
    'Roti sourdough bulat di dalam panci besi',
  )
}

test('seller manages one product and visitors see the catalog change', async ({
  page,
}, testInfo) => {
  const name = uniqueName('Sourdough Uji')
  await loginSeller(page)
  await screenshot(page, testInfo, 'seller-catalog-empty-or-list')

  await createProduct(page, {
    name,
    unit: '1 loaf 500 gram',
    price: 65000,
    description: 'Roti asam dengan tepung, air, dan garam.',
  })
  const row = page.locator('li.seller-product', { hasText: name })
  await expect(row).toContainText('Rp 65.000')
  await expect(row).toContainText('1 loaf 500 gram')
  await expect(row.locator('.demo-tag')).toHaveCount(0)
  await screenshot(page, testInfo, 'seller-catalog-created')

  // Edit through the same form.
  await row.getByRole('button', { name: 'Ubah' }).click()
  await expect(page.getByRole('button', { name: 'Simpan perubahan' })).toBeVisible()
  await page.getByLabel('Harga (Rupiah)').fill('73000')
  await page.getByRole('button', { name: 'Batal ubah' }).click()
  await expect(page.getByRole('button', { name: 'Tambah produk' })).toBeVisible()
  await expect(row).toContainText('Rp 65.000')
  await row.getByRole('button', { name: 'Ubah' }).click()
  await page.getByLabel('Harga (Rupiah)').fill('72000')
  await page.getByRole('button', { name: 'Simpan perubahan' }).click()
  await expect(page.getByRole('status')).toContainText('Perubahan produk disimpan')
  await expect(page.locator('li.seller-product', { hasText: name })).toContainText('Rp 72.000')

  // A visitor reads the catalog without logging in.
  const visitor = await page.context().browser().newContext()
  const visitorPage = await visitor.newPage()
  await visitorPage.goto('/')
  await expect(visitorPage.getByRole('heading', { name: 'Katalog roti sourdough' })).toBeVisible()
  await expect(visitorPage.getByText(name)).toBeVisible()
  await expect(visitorPage.getByText('Rp 72.000')).toBeVisible()
  await expect(visitorPage.locator('li.product-card', { hasText: name }).locator('.demo-tag')).toHaveCount(0)
  await expectPublicCopyWithoutDemoLabels(visitorPage)
  await screenshot(visitorPage, testInfo, 'catalog-public')
  await visitor.close()

  // Archive hides it from visitors and from the seller's default list.
  await row.getByRole('button', { name: 'Arsipkan' }).click()
  await expect(page.getByRole('status')).toContainText('diarsipkan')
  await expect(page.locator('li.seller-product', { hasText: name })).toHaveCount(0)
  await screenshot(page, testInfo, 'seller-catalog-archived-default')

  const archiveCheck = await page.context().browser().newContext()
  const archivePage = await archiveCheck.newPage()
  await archivePage.goto('/')
  await expect(archivePage.getByText(name)).toHaveCount(0)
  await archiveCheck.close()

  // An explicit opt-in reveals the archived row and permits restoration.
  await page.getByLabel('Sertakan arsip').check()
  const archivedRow = page.locator('li.seller-product', { hasText: name })
  await expect(archivedRow).toContainText('Diarsipkan')
  await screenshot(page, testInfo, 'seller-catalog-archived')

  // Restore and delete permanently.
  await archivedRow.getByRole('button', { name: 'Pulihkan' }).click()
  await expect(page.getByRole('status')).toContainText('kembali tampil')
  await deleteProductByName(page, name, testInfo)
  await expect(page.locator('li.seller-product', { hasText: name })).toHaveCount(0)
})

test('product text with HTML is shown literally and never executed', async ({
  page,
}, testInfo) => {
  const markup = '<img src=x onerror="window.__catalogXss=1">'
  const suffix = Date.now().toString(36)
  const name = `${markup} ${suffix}`
  await loginSeller(page)
  // Remove rows left behind by earlier failed runs so the count is exact.
  await deleteAllMatching(page, 'onerror')
  await createProduct(page, { name, unit: '1 loaf 500 gram', price: 55000 })
  await screenshot(page, testInfo, 'seller-catalog-markup')

  await page.goto('/')
  const card = page.locator('li.product-card', { hasText: suffix })
  await expect(card).toHaveCount(1)
  await expect(card.getByRole('heading', { level: 3 })).toHaveText(name)
  expect(await page.evaluate(() => window.__catalogXss)).toBeUndefined()
  expect(await page.locator('li.product-card img').count()).toBe(0)
  await screenshot(page, testInfo, 'catalog-escaped-text')

  await page.goto('/penjual')
  await expect(page.getByRole('heading', { name: 'Kelola katalog' })).toBeVisible()
  await deleteProductByName(page, suffix)
})

test('seller form validates bounds and keeps keyboard focus', async ({ page }, testInfo) => {
  await loginSeller(page)
  await page.getByLabel('Nama produk').fill('a')
  await page.getByLabel('Unit jual').fill('x')
  await page.getByLabel('Harga (Rupiah)').fill('500')
  await page.getByRole('button', { name: 'Tambah produk' }).click()

  await expect(page.getByText('Nama harus 2 sampai 80 karakter.')).toBeVisible()
  await expect(page.getByText('Unit jual harus 2 sampai 40 karakter.')).toBeVisible()
  await expect(
    page.getByText('Harga harus bilangan bulat Rp1.000 sampai Rp1.000.000.'),
  ).toBeVisible()
  await expect(page.getByLabel('Nama produk')).toBeFocused()

  const focusStyle = await page.getByLabel('Nama produk').evaluate((element) => {
    const style = getComputedStyle(element)
    return { outlineStyle: style.outlineStyle, outlineWidth: style.outlineWidth }
  })
  expect(focusStyle.outlineStyle).not.toBe('none')
  expect(Number.parseFloat(focusStyle.outlineWidth)).toBeGreaterThan(0)
  await screenshot(page, testInfo, 'seller-form-validation')
})

test('public catalog has no horizontal overflow and a readable empty state', async ({
  page,
}, testInfo) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Katalog roti sourdough' })).toBeVisible()
  await expectPublicCopyWithoutDemoLabels(page)
  const noOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth,
  )
  expect(noOverflow).toBe(true)
  await expect(page.getByRole('heading', { name: 'Produk' })).toBeVisible()
  await expect(page.getByText('Belum ada produk di katalog.', { exact: true })).toBeVisible()
  await screenshot(page, testInfo, 'catalog-layout')
})

test('catalog shows a network error and retry loads the real API', async ({ page }, testInfo) => {
  await page.route('**/api/products', (route) => route.abort('connectionfailed'), { times: 1 })
  await page.goto('/')
  await expect(page.getByRole('alert')).toBeVisible()
  const retry = page.getByRole('button', { name: 'Coba lagi' })
  await expect(retry).toBeVisible()
  await screenshot(page, testInfo, 'catalog-network-error')

  const responsePromise = page.waitForResponse(
    (response) => new URL(response.url()).pathname === '/api/products',
  )
  await retry.click()
  const response = await responsePromise
  expect(response.status()).toBe(200)
  expect(Array.isArray((await response.json()).items)).toBe(true)
  await expect(page.getByRole('alert')).toHaveCount(0)
  await expect(page.getByText('Belum ada produk di katalog.', { exact: true })).toBeVisible()
  await screenshot(page, testInfo, 'catalog-network-recovered')
})

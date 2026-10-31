import { expect, test } from '@playwright/test'

const SELLER = { email: 'seller@example.com', password: 'Demo-seller-2026!' }
const BUYER_PASSWORD = 'Synthetic-buyer-2026!'

function uniqueBuyerEmail() {
  return `buyer-${Date.now()}-${Math.random().toString(16).slice(2, 8)}@example.com`
}

async function screenshot(page, testInfo, name) {
  const path = testInfo.outputPath(`${testInfo.project.name}-${name}.png`)
  await page.screenshot({ path, fullPage: true })
  return path
}

async function fillAndSubmitRegister(page, { name, email, password }) {
  await page.goto('/daftar')
  await page.getByLabel('Nama').fill(name)
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Buat akun pembeli' }).click()
}

async function registerBuyer(page, testInfo) {
  const email = uniqueBuyerEmail()
  await fillAndSubmitRegister(page, {
    name: 'Demo Buyer',
    email,
    password: BUYER_PASSWORD,
  })
  await expect(page.getByRole('status')).toContainText('Akun pembeli berhasil dibuat')
  await screenshot(page, testInfo, 'registration-success')
  await page.getByRole('link', { name: 'Masuk ke akun' }).click()
  return { email, password: BUYER_PASSWORD }
}

async function login(page, email, password) {
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Masuk' }).click()
}

test('buyer registers, logs in, reads account from the API, and logs out', async ({
  page,
}, testInfo) => {
  const buyer = await registerBuyer(page, testInfo)
  await login(page, buyer.email, buyer.password)

  await expect(page).toHaveURL(/\/akun$/)
  await expect(page.getByRole('heading', { name: 'Akun Anda' })).toBeVisible()
  await expect(page.getByText(buyer.email)).toBeVisible()
  await expect(page.getByText('Pembeli', { exact: true })).toBeVisible()
  await screenshot(page, testInfo, 'account-buyer')

  await page.getByRole('button', { name: 'Keluar' }).click()
  await expect(page).toHaveURL(/\/masuk/)
  await expect(page.getByRole('status')).toContainText('Anda sudah keluar dari akun ini.')

  await page.goto('/akun')
  await expect(page).toHaveURL(/\/masuk/)
  await expect(page.getByRole('status')).toContainText('Masuk untuk melanjutkan. Isi keranjang tetap tersimpan.')
})

test('buyer is denied the seller page and anonymous visitors are sent to login', async ({
  page,
}, testInfo) => {
  const buyer = await registerBuyer(page, testInfo)
  await login(page, buyer.email, buyer.password)
  await expect(page).toHaveURL(/\/akun$/)

  await page.goto('/penjual')
  await expect(page.getByRole('heading', { name: 'Akses ditolak' })).toBeVisible()
  await expect(page.getByText('Akun ini terdaftar sebagai pembeli.')).toBeVisible()
  await screenshot(page, testInfo, 'seller-denied')

  await page.goto('/akun')
  await page.getByRole('button', { name: 'Keluar' }).click()
  await expect(page).toHaveURL(/\/masuk/)
  await page.goto('/penjual')
  await expect(page).toHaveURL(/\/masuk/)
  await expect(page.getByRole('status')).toContainText('Masuk untuk melanjutkan. Isi keranjang tetap tersimpan.')
})

test('seeded seller can open the seller-only page', async ({ page }, testInfo) => {
  await page.goto('/masuk')
  await login(page, SELLER.email, SELLER.password)

  await expect(page).toHaveURL(/\/penjual$/)
  await expect(page.getByRole('heading', { name: 'Kelola katalog' })).toBeVisible()
  await expect(page.getByText('Masuk sebagai penjual')).toBeVisible()
  await expect(page.getByText('seller@example.com')).toBeVisible()
  await screenshot(page, testInfo, 'seller-profile')
})

test('registration validates fields, preserves drafts, and exposes keyboard focus', async ({
  page,
}, testInfo) => {
  await page.goto('/daftar')
  const noOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth,
  )
  expect(noOverflow).toBe(true)

  await page.getByRole('button', { name: 'Buat akun pembeli' }).click()
  await expect(page.getByText('Nama harus 2 sampai 100 karakter.')).toBeVisible()
  await expect(page.getByText('Masukkan email.')).toBeVisible()
  await expect(page.getByText('Password minimal 12 karakter.')).toBeVisible()
  await expect(page.getByLabel('Password')).toHaveAttribute(
    'aria-describedby',
    /register-password-error/,
  )
  await expect(page.getByLabel('Nama')).toBeFocused()

  await page.getByLabel('Nama').fill('Demo Buyer')
  await page.getByLabel('Email').fill('not-an-email')
  await page.getByLabel('Password').fill('short-pass')
  await page.getByRole('button', { name: 'Buat akun pembeli' }).click()
  await expect(page.getByText('Masukkan alamat email yang valid.')).toBeVisible()
  await expect(page.getByLabel('Email')).toHaveValue('not-an-email')
  await expect(page.getByLabel('Password')).toHaveValue('short-pass')
  await expect(page.getByLabel('Email')).toBeFocused()

  const focusStyle = await page.getByLabel('Email').evaluate((element) => {
    const style = getComputedStyle(element)
    return {
      outlineStyle: style.outlineStyle,
      outlineWidth: style.outlineWidth,
      outlineColor: style.outlineColor,
    }
  })
  expect(focusStyle.outlineStyle).not.toBe('none')
  expect(Number.parseFloat(focusStyle.outlineWidth)).toBeGreaterThan(0)
  expect(focusStyle.outlineColor).not.toBe('transparent')

  await page.getByLabel('Nama').focus()
  await page.keyboard.press('Tab')
  await expect(page.getByLabel('Email')).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(page.getByLabel('Password')).toBeFocused()

  await screenshot(page, testInfo, 'register-validation')
})

test('login shows a loading state and a recoverable network error', async ({ page }, testInfo) => {
  await page.goto('/masuk')
  await page.getByLabel('Email').fill(SELLER.email)
  await page.getByLabel('Password').fill(SELLER.password)

  await page.route('**/api/auth/login', async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 600))
    await route.continue()
  })
  await page.getByRole('button', { name: 'Masuk' }).click()
  await expect(page.getByRole('button', { name: 'Memproses...' })).toBeVisible()
  await expect(page).toHaveURL(/\/penjual$/)
  await page.unroute('**/api/auth/login')

  await page.goto('/akun')
  await page.getByRole('button', { name: 'Keluar' }).click()
  await expect(page).toHaveURL(/\/masuk/)

  await page.getByLabel('Email').fill(SELLER.email)
  await page.getByLabel('Password').fill(SELLER.password)
  await page.route('**/api/auth/login', (route) => route.abort())
  await page.getByRole('button', { name: 'Masuk' }).click()

  await expect(page.getByRole('alert')).toContainText('Jaringan tidak tersedia')
  await expect(page.getByLabel('Email')).toHaveValue(SELLER.email)
  await expect(page.getByLabel('Password')).toHaveValue(SELLER.password)
  await screenshot(page, testInfo, 'login-network-error')
})

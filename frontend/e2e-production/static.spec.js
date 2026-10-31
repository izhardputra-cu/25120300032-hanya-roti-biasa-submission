import { mkdirSync } from 'node:fs'
import { expect, test } from '@playwright/test'

const SELLER = { email: 'seller@example.com', password: 'Demo-seller-2026!' }

// Raw HTTP checks that must not be fooled by a browser-like Accept header.
test('API and missing assets stay JSON 404 on the single origin', async ({ request }) => {
  const unknownApi = await request.get('/api/missing', { headers: { Accept: 'text/html' } })
  expect(unknownApi.status()).toBe(404)
  expect(unknownApi.headers()['content-type']).toContain('application/json')

  const missingAsset = await request.get('/assets/missing.js', {
    headers: { Accept: 'text/html' },
  })
  expect(missingAsset.status()).toBe(404)
  expect(missingAsset.headers()['content-type']).toContain('application/json')

  const health = await request.get('/api/health', { headers: { Accept: 'text/html' } })
  expect(health.status()).toBe(200)
  expect(health.headers()['content-type']).toContain('application/json')

  const fontLicense = await request.get('/plus-jakarta-sans-OFL.txt')
  expect(fontLicense.status()).toBe(200)
  expect(await fontLicense.text()).toContain('SIL OPEN FONT LICENSE Version 1.1')

  // The public catalog is a JSON API on the same origin and needs no session.
  const catalog = await request.get('/api/products', { headers: { Accept: 'text/html' } })
  expect(catalog.status()).toBe(200)
  expect(catalog.headers()['content-type']).toContain('application/json')
  expect(await catalog.json()).toHaveProperty('items')

  // Schedule reads and SPA deep links belong to the same built origin.
  const schedules = await request.get('/api/schedules', { headers: { Accept: 'text/html' } })
  expect(schedules.status()).toBe(200)
  expect(schedules.headers()['content-type']).toContain('application/json')
  expect(await schedules.json()).toHaveProperty('items')
  for (const path of ['/jadwal', '/penjual/jadwal', '/keranjang', '/pesanan']) {
    const page = await request.get(path, { headers: { Accept: 'text/html' } })
    expect(page.status()).toBe(200)
    expect(page.headers()['content-type']).toContain('text/html')
  }
})

test('built Vue app serves deep links and keeps the seller session across refresh', async ({
  page,
}, testInfo) => {
  await page.goto('/masuk')
  await expect(page.getByRole('heading', { name: 'Masuk ke akun' })).toBeVisible()
  // A warm ground colour proves the built stylesheet loaded, not just HTML.
  await expect
    .poll(() => page.evaluate(() => getComputedStyle(document.body).backgroundColor))
    .toBe('rgb(251, 246, 236)')

  // Public presentation carries the shop name, not demo meta-disclaimers.
  await expect(page.locator('.site-header').getByText('Hanya Roti Biasa')).toBeVisible()
  await expect(page.locator('.demo-tag')).toHaveCount(0)
  await expect(page.locator('.site-footer')).not.toContainText(
    /demo|sintetis|belum beroperasi/i,
  )

  // The built stylesheet and hashed font asset must resolve on this origin,
  // not only under the Vite dev server. A loaded FontFace plus the Latin WOFF2
  // resource proves the file actually downloaded; document.fonts.check alone
  // can report true for a family the page never fetched.
  const font = await page.evaluate(async () => {
    await document.fonts.ready
    const faces = [...document.fonts]
      .filter((face) => face.family.includes('Plus Jakarta Sans'))
      .map((face) => ({
        family: face.family,
        style: face.style,
        weight: face.weight,
        status: face.status,
      }))
    const input = document.querySelector('#login-email')
    const select = document.createElement('select')
    document.body.append(select)
    const selectFamily = getComputedStyle(select).fontFamily
    select.remove()
    return {
      faces,
      bodyFamily: getComputedStyle(document.body).fontFamily,
      inputFamily: input ? getComputedStyle(input).fontFamily : null,
      selectFamily,
      fontResources: performance
        .getEntriesByType('resource')
        .map((entry) => entry.name)
        .filter(
          (name) => /\.woff2?($|\?)/i.test(name) || /fonts\.(googleapis|gstatic)\.com/.test(name),
        ),
    }
  })
  const firstFamily = (value) => value.split(',')[0].trim().replace(/^["']|["']$/g, '')
  expect(
    font.faces.find(
      (face) =>
        face.family === 'Plus Jakarta Sans Variable' &&
        face.status === 'loaded' &&
        face.style === 'normal',
    ),
  ).toMatchObject({ weight: '200 800' })
  expect(firstFamily(font.bodyFamily)).toBe('Plus Jakarta Sans Variable')
  expect(firstFamily(font.inputFamily)).toBe('Plus Jakarta Sans Variable')
  expect(firstFamily(font.selectFamily)).toBe('Plus Jakarta Sans Variable')
  expect(
    font.fontResources.some((name) => /plus-jakarta-sans-latin-wght-normal/.test(name)),
  ).toBe(true)
  expect(
    font.fontResources.filter((name) => /fonts\.(googleapis|gstatic)\.com/.test(name)),
  ).toEqual([])
  const fontUrl = new URL(
    font.fontResources.find((name) => /plus-jakarta-sans-latin-wght-normal/.test(name)),
    page.url(),
  )
  expect(fontUrl.origin).toBe(new URL(page.url()).origin)
  const fontResponse = await page.request.get(fontUrl.toString())
  expect(fontResponse.status()).toBe(200)
  expect((await fontResponse.body()).length).toBeGreaterThan(1000)

  mkdirSync('../.local/font-jakarta-evidence', { recursive: true })
  await page.screenshot({
    path: `../.local/font-jakarta-evidence/production-${testInfo.project.name}-login-form.png`,
    fullPage: true,
  })

  await page.goto('/daftar')
  await expect(page.getByRole('heading', { name: 'Buat akun pembeli' })).toBeVisible()

  await page.goto('/akun')
  await expect(page).toHaveURL(/\/masuk(\?|$)/)
  await expect(page.getByRole('status')).toContainText('Masuk untuk melanjutkan. Isi keranjang tetap tersimpan.')

  await page.goto('/penjual')
  await expect(page).toHaveURL(/\/masuk(\?|$)/)

  await page.getByLabel('Email').fill(SELLER.email)
  await page.getByLabel('Password').fill(SELLER.password)
  await page.getByRole('button', { name: 'Masuk' }).click()
  await expect(page).toHaveURL(/\/penjual$/)
  await expect(page.getByRole('heading', { name: 'Kelola katalog' })).toBeVisible()
  await expect(page.getByText('Masuk sebagai penjual')).toBeVisible()

  // Deep-link reload keeps the same server-side session cookie.
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Kelola katalog' })).toBeVisible()
  await expect(page.getByText('seller@example.com')).toBeVisible()

  // The built app also renders the T4 schedule routes, not just HTML fallbacks.
  await page.goto('/jadwal')
  await expect(page.getByRole('heading', { name: 'Jadwal pre-order' })).toBeVisible()
  await page.goto('/penjual/jadwal')
  await expect(
    page.getByRole('heading', { name: 'Kelola jadwal pre-order' }),
  ).toBeVisible()
  await expect(page.getByText('Masuk sebagai penjual')).toBeVisible()
})

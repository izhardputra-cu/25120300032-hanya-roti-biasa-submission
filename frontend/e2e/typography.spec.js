import { mkdirSync } from 'node:fs'
import { expect, test } from '@playwright/test'

const EVIDENCE = '../.local/font-jakarta-evidence'
const FONT_FAMILY = 'Plus Jakarta Sans Variable'
const SELLER = { email: 'seller@example.com', password: 'Demo-seller-2026!' }

function firstFamily(value) {
  return value.split(',')[0].trim().replace(/^["']|["']$/g, '')
}

function expectJakartaFamily(value) {
  expect(value).toBeTruthy()
  expect(firstFamily(value)).toBe(FONT_FAMILY)
}

async function readFontState(page) {
  return page.evaluate(async () => {
    await document.fonts.ready
    const faces = [...document.fonts]
      .filter((face) => face.family.includes('Plus Jakarta Sans'))
      .map((face) => ({
        family: face.family,
        style: face.style,
        weight: face.weight,
        status: face.status,
        unicodeRange: face.unicodeRange,
      }))
    const probe = (tag) => {
      const element = document.createElement(tag)
      document.body.append(element)
      const family = getComputedStyle(element).fontFamily
      element.remove()
      return family
    }
    const h1 = document.querySelector('h1')
    const input = document.querySelector('input')
    const textarea = document.querySelector('textarea')
    return {
      bodyFamily: getComputedStyle(document.body).fontFamily,
      headingFamily: h1 ? getComputedStyle(h1).fontFamily : null,
      inputFamily: input ? getComputedStyle(input).fontFamily : null,
      textareaFamily: textarea ? getComputedStyle(textarea).fontFamily : null,
      selectFamily: probe('select'),
      textareaProbeFamily: probe('textarea'),
      faces,
      fontResources: performance
        .getEntriesByType('resource')
        .map((entry) => entry.name)
        .filter((name) => /\.woff2?($|\?)/i.test(name) || /fonts\.(googleapis|gstatic)\.com/.test(name)),
    }
  })
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

function expectLoadedLatinFace(state) {
  const loaded = state.faces.find(
    (face) => face.family === FONT_FAMILY && face.status === 'loaded' && face.style === 'normal',
  )
  expect(loaded).toBeTruthy()
  expect(loaded.weight).toMatch(/^200 800$/)
  expect(loaded.unicodeRange.length).toBeGreaterThan(0)
  expect(
    state.fontResources.some((name) => /plus-jakarta-sans-latin-wght-normal/.test(name)),
  ).toBe(true)
  expect(
    state.fontResources.filter((name) => /fonts\.(googleapis|gstatic)\.com/.test(name)),
  ).toEqual([])
}

test('self-hosted Plus Jakarta Sans renders text and form controls', async ({
  page,
}, testInfo) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Katalog roti sourdough' })).toBeVisible()

  const catalog = await readFontState(page)
  expectLoadedLatinFace(catalog)
  expectJakartaFamily(catalog.bodyFamily)
  expectJakartaFamily(catalog.headingFamily)
  await noHorizontalOverflow(page)
  await screenshot(page, testInfo, 'catalog-navigation')

  await page.goto('/masuk')
  await expect(page.getByRole('heading', { name: 'Masuk ke akun' })).toBeVisible()
  const form = await readFontState(page)
  expectLoadedLatinFace(form)
  expectJakartaFamily(form.inputFamily)
  expectJakartaFamily(form.selectFamily)
  expectJakartaFamily(form.textareaProbeFamily)
  await noHorizontalOverflow(page)
  await screenshot(page, testInfo, 'login-form')

  await page.getByLabel('Email').fill(SELLER.email)
  await page.getByLabel('Password').fill(SELLER.password)
  await page.getByRole('button', { name: 'Masuk' }).click()
  await expect(page.getByRole('heading', { name: 'Kelola katalog' })).toBeVisible()

  const seller = await readFontState(page)
  expectLoadedLatinFace(seller)
  expectJakartaFamily(seller.textareaFamily)
  await noHorizontalOverflow(page)

  await page.goto('/penjual/rekap')
  await expect(page.getByRole('heading', { name: 'Rekap produksi' })).toBeVisible()
  await expect(page.getByText('Memeriksa akses penjual...')).toHaveCount(0)
  await noHorizontalOverflow(page)
  await screenshot(page, testInfo, 'production-recap')
})

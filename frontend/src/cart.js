// The cart is one schedule, kept in localStorage so signing in or returning from
// a guard does not throw away a drafted order. The server remains the authority
// for price, quota, and totals; this module only remembers what to review.
import { computed, reactive } from 'vue'

const STORAGE_KEY = 'wad05_cart_v1'
const MAX_QUANTITY = 999

function freshCart() {
  return {
    scheduleId: null,
    pickupAt: null,
    items: [],
    checkoutKey: null,
    checkoutSignature: null,
  }
}

function isItem(value) {
  return (
    value &&
    Number.isInteger(value.offerId) &&
    typeof value.productName === 'string' &&
    typeof value.sellingUnit === 'string' &&
    Number.isInteger(value.priceRupiah) &&
    Number.isInteger(value.quantity) &&
    value.quantity >= 1 &&
    value.quantity <= MAX_QUANTITY
  )
}

function readStored() {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (!raw) {
      return freshCart()
    }
    const parsed = JSON.parse(raw)
    if (
      !parsed ||
      !Number.isInteger(parsed.scheduleId) ||
      !Array.isArray(parsed.items) ||
      !parsed.items.every(isItem)
    ) {
      return freshCart()
    }
    return {
      scheduleId: parsed.scheduleId,
      pickupAt: typeof parsed.pickupAt === 'string' ? parsed.pickupAt : null,
      items: parsed.items.map((item) => ({ ...item })),
      checkoutKey: typeof parsed.checkoutKey === 'string' ? parsed.checkoutKey : null,
      checkoutSignature:
        typeof parsed.checkoutSignature === 'string' ? parsed.checkoutSignature : null,
    }
  } catch {
    return freshCart()
  }
}

export const cart = reactive(readStored())

export const cartLineCount = computed(() => cart.items.length)

export const cartQuoteTotal = computed(() =>
  cart.items.reduce((total, item) => total + item.priceRupiah * item.quantity, 0),
)

function persist() {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...cart }))
  } catch {
    // A browser that refuses storage still gets a working in-memory cart.
  }
}

function invalidateKey() {
  cart.checkoutKey = null
  cart.checkoutSignature = null
}

export function payloadForCheckout() {
  return {
    schedule_id: cart.scheduleId,
    items: [...cart.items]
      .sort((a, b) => a.offerId - b.offerId)
      .map((item) => ({
        offer_id: item.offerId,
        quantity: item.quantity,
        quoted_price_rupiah: item.priceRupiah,
      })),
  }
}

export function payloadSignature() {
  return JSON.stringify(payloadForCheckout())
}

export function cartIsFor(scheduleId) {
  return cart.scheduleId === scheduleId
}

export function addItem(schedule, offer, quantity, { replace = false } = {}) {
  if (!Number.isInteger(quantity) || quantity < 1 || quantity > MAX_QUANTITY) {
    return 'invalid'
  }
  if (cart.items.length > 0 && !cartIsFor(schedule.id)) {
    if (!replace) {
      return 'other-schedule'
    }
    cart.items = []
  }
  cart.scheduleId = schedule.id
  cart.pickupAt = schedule.pickup_at
  const existing = cart.items.find((item) => item.offerId === offer.id)
  if (existing) {
    const combined = existing.quantity + quantity
    if (combined > MAX_QUANTITY) {
      return 'invalid'
    }
    existing.quantity = combined
    existing.priceRupiah = offer.price_rupiah
  } else {
    cart.items.push({
      offerId: offer.id,
      productName: offer.product_name,
      sellingUnit: offer.selling_unit,
      priceRupiah: offer.price_rupiah,
      quantity,
    })
  }
  invalidateKey()
  persist()
  return 'ok'
}

export function setQuantity(offerId, quantity) {
  if (!Number.isInteger(quantity) || quantity < 1 || quantity > MAX_QUANTITY) {
    return false
  }
  const item = cart.items.find((entry) => entry.offerId === offerId)
  if (!item) {
    return false
  }
  item.quantity = quantity
  invalidateKey()
  persist()
  return true
}

export function refreshPrices(offersById) {
  for (const item of cart.items) {
    const offer = offersById.get(item.offerId)
    if (offer) {
      item.priceRupiah = offer.price_rupiah
      item.productName = offer.product_name
      item.sellingUnit = offer.selling_unit
    }
  }
  invalidateKey()
  persist()
}

export function removeItem(offerId) {
  cart.items = cart.items.filter((item) => item.offerId !== offerId)
  if (cart.items.length === 0) {
    cart.scheduleId = null
    cart.pickupAt = null
  }
  invalidateKey()
  persist()
}

export function clearCart() {
  Object.assign(cart, freshCart())
  persist()
}

export function checkoutKeyForCurrentPayload() {
  const signature = payloadSignature()
  if (cart.checkoutKey && cart.checkoutSignature === signature) {
    return cart.checkoutKey
  }
  cart.checkoutKey = crypto.randomUUID()
  cart.checkoutSignature = signature
  persist()
  return cart.checkoutKey
}

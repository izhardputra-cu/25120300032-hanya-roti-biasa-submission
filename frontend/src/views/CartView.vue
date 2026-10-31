<script setup>
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { ApiError, apiRequest } from '../api'
import {
  cart,
  cartQuoteTotal,
  checkoutKeyForCurrentPayload,
  clearCart,
  payloadForCheckout,
  refreshPrices,
  removeItem,
  setQuantity,
} from '../cart'
import { formatWib } from '../datetime'
import { formatRupiah } from '../money'
import { session } from '../session'

const router = useRouter()
const loading = ref(true)
const loadError = ref('')
const schedule = ref(null)
const offersById = ref(new Map())
const quantityDrafts = reactive({})
const itemErrors = reactive({})
const formError = ref('')
const submitting = ref(false)
const statusMessage = ref('')
const statusRef = ref(null)
const confirmingClear = ref(false)

const priceChanges = computed(() =>
  cart.items.filter((item) => {
    const offer = offersById.value.get(item.offerId)
    return offer && offer.price_rupiah !== item.priceRupiah
  }),
)

const missingItems = computed(() =>
  cart.items.filter((item) => !offersById.value.has(item.offerId)),
)

const availabilityProblems = computed(() =>
  cart.items.filter((item) => {
    const offer = offersById.value.get(item.offerId)
    return offer && offer.remaining_quota < item.quantity
  }),
)

const scheduleClosed = computed(() => Boolean(schedule.value && !schedule.value.orders_open))

const canSubmit = computed(
  () =>
    cart.items.length > 0 &&
    Boolean(schedule.value) &&
    !scheduleClosed.value &&
    missingItems.value.length === 0 &&
    availabilityProblems.value.length === 0 &&
    priceChanges.value.length === 0 &&
    !submitting.value,
)

function offerFor(item) {
  return offersById.value.get(item.offerId)
}

function syncDrafts() {
  for (const item of cart.items) {
    if (quantityDrafts[item.offerId] === undefined) {
      quantityDrafts[item.offerId] = String(item.quantity)
    }
  }
}

async function loadSchedule() {
  loading.value = true
  loadError.value = ''
  try {
    const data = await apiRequest('/api/schedules')
    const found = data.items.find((entry) => entry.id === cart.scheduleId) || null
    schedule.value = found
    offersById.value = new Map(
      (found?.offers || []).map((offer) => [offer.id, offer]),
    )
    syncDrafts()
  } catch (caught) {
    loadError.value =
      caught instanceof ApiError ? caught.message : 'Tinjauan pesanan tidak dapat dimuat.'
  } finally {
    loading.value = false
  }
}

async function focusStatus() {
  await nextTick()
  statusRef.value?.focus()
}

async function focusFirstInvalid() {
  await nextTick()
  const invalid = document.querySelector('[aria-invalid="true"]')
  if (invalid instanceof HTMLElement) {
    invalid.focus()
  }
}

function saveQuantity(item) {
  delete itemErrors[item.offerId]
  const value = quantityDrafts[item.offerId]
  const quantity = Number(value)
  if (value === '' || !Number.isInteger(quantity) || quantity < 1 || quantity > 999) {
    itemErrors[item.offerId] = 'Jumlah harus bilangan bulat 1 sampai 999.'
    focusFirstInvalid()
    return
  }
  setQuantity(item.offerId, quantity)
  formError.value = ''
}

function setStatus(message) {
  statusMessage.value = message
  nextTick(() => statusRef.value?.focus())
}

function discardItem(item) {
  removeItem(item.offerId)
  delete quantityDrafts[item.offerId]
  delete itemErrors[item.offerId]
  formError.value = ''
  setStatus(`${item.productName} dihapus dari keranjang.`)
}

function updateQuotes() {
  refreshPrices(offersById.value)
  formError.value = ''
  setStatus('Harga tinjauan diperbarui. Periksa kembali total sebelum memesan.')
}

function askClearCart() {
  confirmingClear.value = true
  formError.value = ''
}

async function cancelClearCart(event) {
  const trigger = event.currentTarget.closest('.cart-summary')?.querySelector('[data-clear-cart]')
  confirmingClear.value = false
  await nextTick()
  trigger?.focus()
}

function confirmClearCart() {
  clearCart()
  confirmingClear.value = false
  setStatus('Keranjang dikosongkan.')
}

function mapServerErrors(caught, items) {
  const locations = caught instanceof ApiError ? caught.locations : []
  for (const location of locations) {
    const match = /^items\.(\d+)\.(\w+)$/.exec(location.path)
    if (match) {
      const item = items[Number(match[1])]
      if (item) {
        itemErrors[item.offerId] = location.message
      }
    }
  }
}

async function submit() {
  if (!canSubmit.value) {
    return
  }
  formError.value = ''
  for (const key of Object.keys(itemErrors)) {
    delete itemErrors[key]
  }
  for (const item of cart.items) {
    const value = quantityDrafts[item.offerId]
    const quantity = Number(value)
    if (value === '' || !Number.isInteger(quantity) || quantity < 1 || quantity > 999) {
      itemErrors[item.offerId] = 'Jumlah harus bilangan bulat 1 sampai 999.'
      await focusFirstInvalid()
      return
    }
    if (quantity !== item.quantity) {
      // Only a real payload change rotates the idempotency key; an unchanged
      // retry must reuse it so a lost response cannot create a duplicate order.
      setQuantity(item.offerId, quantity)
    }
  }
  const items = [...cart.items].sort((a, b) => a.offerId - b.offerId)
  const payload = {
    checkout_key: checkoutKeyForCurrentPayload(),
    ...payloadForCheckout(),
  }
  submitting.value = true
  try {
    const order = await apiRequest('/api/orders', { method: 'POST', body: payload })
    clearCart()
    await router.push({
      name: 'order-detail',
      params: { id: order.id },
      query: { baru: '1' },
    })
  } catch (caught) {
    if (caught instanceof ApiError && caught.status === 401) {
      await router.replace({
        name: 'login',
        query: { masuk: '1', redirect: '/keranjang' },
      })
      return
    }
    if (caught instanceof ApiError) {
      mapServerErrors(caught, items)
      if (caught.status === 0) {
        // Network failures keep the cart, quantities, and checkout key intact so
        // pressing the button again is an idempotent retry.
        formError.value = caught.message
      } else if (caught.status === 409) {
        formError.value = caught.message
      } else {
        formError.value = 'Pesanan tidak dapat dibuat. Periksa kembali isian lalu coba lagi.'
      }
      if (caught.status === 409) {
        // A business conflict means the review is stale; reloading prices and
        // remaining quota is the next step, never a silent new total.
        await loadSchedule()
      }
    } else {
      formError.value = 'Pesanan tidak dapat dibuat. Periksa jaringan lalu coba lagi.'
    }
    await focusFirstInvalid()
  } finally {
    submitting.value = false
  }
}

onMounted(loadSchedule)
</script>

<template>
  <section class="cart-page" aria-labelledby="cart-title">
    <div class="schedule-heading">
      <h1 id="cart-title">Tinjauan pesanan</h1>
      <p>
        Satu pesanan berisi produk dari satu jadwal panggang. Harga, sisa kuota, dan total
        akhir dihitung ulang oleh server saat pesanan dibuat.
      </p>
    </div>

    <div v-if="loading" class="form-card state-panel" role="status" aria-busy="true">
      <p>Memuat tinjauan pesanan...</p>
    </div>

    <div v-else-if="loadError" class="alert alert-error" role="alert">
      <p>{{ loadError }}</p>
      <button class="button button-secondary" type="button" @click="loadSchedule">
        Coba lagi
      </button>
    </div>

    <div v-else-if="session.user?.role === 'seller'" class="form-card state-panel">
      <p>Akun penjual tidak dapat membuat pesanan pembeli.</p>
      <p class="state-note">
        <RouterLink to="/penjual/jadwal">Kembali ke kelola jadwal</RouterLink>
      </p>
    </div>

    <div v-else-if="cart.items.length === 0" class="form-card state-panel">
      <p>Keranjang masih kosong.</p>
      <p class="state-note">
        Pilih produk dari <RouterLink to="/jadwal">jadwal pre-order</RouterLink> yang masih
        dibuka.
      </p>
    </div>

    <template v-else>
      <p
        v-if="statusMessage"
        ref="statusRef"
        class="alert alert-success"
        role="status"
        tabindex="-1"
      >
        {{ statusMessage }}
      </p>

      <p v-if="formError" class="alert alert-error" role="alert">{{ formError }}</p>

      <div v-if="!schedule" class="alert alert-warning" role="alert">
        <p>Jadwal pada keranjang tidak tersedia lagi.</p>
        <button class="button button-secondary" type="button" @click="confirmClearCart">
          Kosongkan keranjang
        </button>
      </div>

      <template v-else>
        <div class="form-card cart-schedule">
          <h2>Pengambilan {{ formatWib(schedule.pickup_at) }}</h2>
          <p class="schedule-meta">
            Batas PO {{ formatWib(schedule.order_cutoff_at) }} &middot;
            {{ schedule.orders_open ? 'Masih dibuka' : 'Sudah ditutup' }}
          </p>
          <p v-if="scheduleClosed" class="alert alert-warning" role="alert">
            Batas PO sudah lewat. Pesanan baru untuk jadwal ini tidak dapat dibuat.
          </p>
        </div>

        <div v-if="missingItems.length > 0" class="alert alert-warning" role="alert">
          <p>Satu atau lebih penawaran sudah tidak tersedia pada jadwal ini.</p>
          <p class="state-note">Hapus produk tersebut dari keranjang lalu pilih lagi.</p>
        </div>

        <div v-if="priceChanges.length > 0" class="alert alert-warning" role="alert">
          <p>Harga berubah sejak produk dimasukkan ke keranjang:</p>
          <ul class="price-change-list">
            <li v-for="item in priceChanges" :key="item.offerId">
              {{ item.productName }}: {{ formatRupiah(item.priceRupiah) }} menjadi
              {{ formatRupiah(offerFor(item).price_rupiah) }}.
            </li>
          </ul>
          <button class="button button-secondary" type="button" @click="updateQuotes">
            Perbarui harga tinjauan
          </button>
        </div>

        <ul v-if="cart.items.length > 0" class="cart-list">
          <li v-for="item in cart.items" :key="item.offerId" class="cart-row">
            <div class="cart-item-info">
              <h3>{{ item.productName }}</h3>
              <p class="product-unit">{{ item.sellingUnit }}</p>
              <p class="product-price">{{ formatRupiah(item.priceRupiah) }}</p>
              <p v-if="priceChanges.includes(item)" class="field-help">
                Harga saat ini {{ formatRupiah(offerFor(item).price_rupiah) }}; perbarui
                tinjauan sebelum memesan.
              </p>
              <p v-if="offerFor(item)" class="offer-quota">
                Sisa kuota {{ offerFor(item).remaining_quota }} dari
                {{ offerFor(item).quota }}
              </p>
            </div>
            <div class="cart-controls">
              <div class="field cart-quantity">
                <label :for="`cart-qty-${item.offerId}`">Jumlah</label>
                <input
                  :id="`cart-qty-${item.offerId}`"
                  v-model="quantityDrafts[item.offerId]"
                  type="number"
                  min="1"
                  max="999"
                  step="1"
                  inputmode="numeric"
                  :aria-label="`Jumlah ${item.productName}`"
                  :aria-invalid="Boolean(itemErrors[item.offerId])"
                  :aria-describedby="
                    itemErrors[item.offerId]
                      ? `cart-qty-${item.offerId}-error`
                      : undefined
                  "
                  @change="saveQuantity(item)"
                />
                <p
                  v-if="itemErrors[item.offerId]"
                  :id="`cart-qty-${item.offerId}-error`"
                  class="field-error"
                >
                  {{ itemErrors[item.offerId] }}
                </p>
                <p
                  v-else-if="availabilityProblems.includes(item)"
                  class="field-error"
                >
                  Sisa kuota hanya {{ offerFor(item).remaining_quota }}. Turunkan jumlah.
                </p>
              </div>
              <p class="cart-subtotal">
                Subtotal {{ formatRupiah(item.priceRupiah * item.quantity) }}
              </p>
              <button
                class="button button-secondary"
                type="button"
                :aria-label="`Hapus ${item.productName} dari keranjang`"
                @click="discardItem(item)"
              >
                Hapus
              </button>
            </div>
          </li>
        </ul>

        <div class="form-card cart-summary">
          <p class="cart-total-label">Total perkiraan</p>
          <p class="cart-total">{{ formatRupiah(cartQuoteTotal) }}</p>
          <p class="field-help">
            Total akhir dihitung ulang server dari harga dan jumlah saat pesanan dibuat.
          </p>

          <div class="actions">
            <button
              class="button button-primary"
              type="button"
              :disabled="!canSubmit"
              @click="submit"
            >
              {{ submitting ? 'Mengirim pesanan...' : 'Buat pesanan' }}
            </button>
            <button
              class="button button-secondary"
              type="button"
              :disabled="submitting"
              data-clear-cart
              @click="askClearCart"
            >
              Kosongkan keranjang
            </button>
          </div>

          <div
            v-if="confirmingClear"
            class="confirm-panel"
            role="group"
            aria-label="Konfirmasi kosongkan keranjang"
          >
            <p>Kosongkan seluruh isi keranjang? Tindakan ini tidak dapat dibatalkan.</p>
            <div class="actions">
              <button class="button button-danger" type="button" @click="confirmClearCart">
                Ya, kosongkan
              </button>
              <button class="button button-secondary" type="button" @click="cancelClearCart">
                Batal
              </button>
            </div>
          </div>

          <p class="form-switch">
            <RouterLink to="/jadwal">Kembali melihat jadwal</RouterLink>
          </p>
        </div>
      </template>
    </template>
  </section>
</template>

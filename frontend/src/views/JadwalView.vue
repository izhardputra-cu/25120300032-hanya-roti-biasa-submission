<script setup>
import { onMounted, reactive, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { ApiError, apiRequest } from '../api'
import { addItem, cart } from '../cart'
import { formatWib } from '../datetime'
import { formatRupiah } from '../money'

const loading = ref(true)
const error = ref('')
const schedules = ref([])
const quantities = reactive({})
const quantityErrors = reactive({})
const statusMessage = ref('')
const pendingReplace = ref(null)

function quantityFor(offer) {
  return quantities[offer.id] ?? '1'
}

function rememberResult(message) {
  statusMessage.value = message
}

function addToCart(schedule, offer) {
  delete quantityErrors[offer.id]
  statusMessage.value = ''
  const value = quantityFor(offer)
  const quantity = Number(value)
  if (value === '' || !Number.isInteger(quantity) || quantity < 1 || quantity > 999) {
    quantityErrors[offer.id] = 'Jumlah harus bilangan bulat 1 sampai 999.'
    return
  }
  const result = addItem(schedule, offer, quantity)
  if (result === 'other-schedule') {
    pendingReplace.value = { schedule, offer, quantity }
    return
  }
  if (result === 'invalid') {
    quantityErrors[offer.id] = 'Jumlah melebihi batas 999 unit.'
    return
  }
  pendingReplace.value = null
  rememberResult(`${offer.product_name} masuk keranjang.`)
}

function confirmReplace() {
  const pending = pendingReplace.value
  if (!pending) {
    return
  }
  addItem(pending.schedule, pending.offer, pending.quantity, { replace: true })
  rememberResult(`Keranjang diganti dengan jadwal ${formatWib(pending.schedule.pickup_at)}.`)
  pendingReplace.value = null
}

function cancelReplace() {
  pendingReplace.value = null
  rememberResult('')
}

async function loadSchedules() {
  loading.value = true
  error.value = ''
  try {
    const data = await apiRequest('/api/schedules')
    schedules.value = data.items
    for (const schedule of data.items) {
      for (const offer of schedule.offers) {
        if (quantities[offer.id] === undefined) {
          quantities[offer.id] = '1'
        }
      }
    }
  } catch (caught) {
    error.value =
      caught instanceof ApiError ? caught.message : 'Jadwal tidak dapat dimuat.'
  } finally {
    loading.value = false
  }
}

onMounted(loadSchedules)
</script>

<template>
  <div class="schedule-page">
    <section class="schedule-heading" aria-labelledby="schedule-title">
      <h1 id="schedule-title">Jadwal pre-order</h1>
      <p>
        Jadwal panggang beserta produk dan kuotanya. Semua waktu ditampilkan dalam
        WIB (UTC+7). Jam server menentukan apakah pemesanan masih dibuka. Keranjang hanya
        berisi produk dari satu jadwal; masuk saat checkout untuk menyimpan pesanan.
      </p>
    </section>

    <p v-if="statusMessage" class="alert alert-success" role="status">
      {{ statusMessage }}
      <RouterLink to="/keranjang">Lihat keranjang ({{ cart.items.length }})</RouterLink>
    </p>

    <div v-if="loading" class="form-card state-panel" role="status" aria-busy="true">
      <p>Memuat jadwal...</p>
    </div>

    <div v-else-if="error" class="alert alert-error" role="alert">
      <p>{{ error }}</p>
      <button class="button button-secondary" type="button" @click="loadSchedules">
        Coba lagi
      </button>
    </div>

    <div v-else-if="schedules.length === 0" class="form-card state-panel">
      <p>Belum ada jadwal pre-order.</p>
      <p class="state-note">
        Penjual dapat membuka jadwal dari ruang penjual. Pengunjung tidak perlu masuk
        untuk melihat jadwal.
      </p>
    </div>

    <ul v-else class="schedule-list">
      <li v-for="schedule in schedules" :key="schedule.id" class="schedule-panel">
        <div class="schedule-head">
          <div>
            <h2>Pengambilan {{ formatWib(schedule.pickup_at) }}</h2>
            <p class="schedule-meta">
              Batas PO {{ formatWib(schedule.order_cutoff_at) }}
            </p>
          </div>
          <span
            class="status-tag"
            :class="schedule.orders_open ? 'status-tag-open' : 'status-tag-closed'"
          >
            {{ schedule.orders_open ? 'Dibuka' : 'Ditutup' }}
          </span>
        </div>

        <p v-if="schedule.orders_open" class="schedule-note">
          Pemesanan masih dibuka sampai batas PO. Waktu mengikuti jam server.
        </p>
        <p v-else class="schedule-note">
          Batas PO sudah lewat. Jadwal ini ditutup untuk pesanan baru.
        </p>

        <section class="schedule-offers" :aria-labelledby="`offers-${schedule.id}`">
          <h3 :id="`offers-${schedule.id}`">Penawaran</h3>
          <p v-if="schedule.offers.length === 0" class="state-note">
            Belum ada penawaran pada jadwal ini.
          </p>
          <ul v-else class="offer-list">
            <li v-for="offer in schedule.offers" :key="offer.id" class="offer-row">
              <div class="offer-info">
                <h4>{{ offer.product_name }}</h4>
                <p class="product-price">{{ formatRupiah(offer.price_rupiah) }}</p>
                <p class="product-unit">{{ offer.selling_unit }}</p>
                <p class="offer-quota">
                  Sisa {{ offer.remaining_quota }} dari kuota {{ offer.quota }}
                </p>
              </div>

              <div v-if="schedule.orders_open" class="offer-buy">
                <template v-if="offer.remaining_quota > 0">
                  <div class="field offer-quantity">
                    <label :for="`offer-qty-${offer.id}`">Jumlah</label>
                    <input
                      :id="`offer-qty-${offer.id}`"
                      v-model="quantities[offer.id]"
                      type="number"
                      min="1"
                      max="999"
                      step="1"
                      inputmode="numeric"
                      :aria-label="`Jumlah ${offer.product_name}`"
                      :aria-invalid="Boolean(quantityErrors[offer.id])"
                      :aria-describedby="
                        quantityErrors[offer.id]
                          ? `offer-qty-${offer.id}-error`
                          : undefined
                      "
                      @input="delete quantityErrors[offer.id]"
                    />
                    <p
                      v-if="quantityErrors[offer.id]"
                      :id="`offer-qty-${offer.id}-error`"
                      class="field-error"
                    >
                      {{ quantityErrors[offer.id] }}
                    </p>
                  </div>
                  <button
                    class="button button-primary"
                    type="button"
                    :aria-label="`Tambahkan ${offer.product_name} ke keranjang`"
                    @click="addToCart(schedule, offer)"
                  >
                    Tambah
                  </button>
                </template>
                <p v-else class="offer-quota">Kuota habis</p>
              </div>
              <p v-else class="offer-quota">Ditutup</p>
            </li>
          </ul>
        </section>
      </li>
    </ul>

    <div v-if="pendingReplace" class="confirm-panel" role="group" aria-label="Konfirmasi ganti jadwal">
      <p>
        Keranjang hanya boleh berisi satu jadwal. Ganti isi keranjang dengan jadwal
        {{ formatWib(pendingReplace.schedule.pickup_at) }}?
      </p>
      <div class="actions">
        <button class="button button-danger" type="button" @click="confirmReplace">
          Ya, ganti jadwal
        </button>
        <button class="button button-secondary" type="button" @click="cancelReplace">
          Batal
        </button>
      </div>
    </div>

    <p v-if="!loading && !error" class="schedule-footnote">
      Checkout memakai keranjang satu jadwal. Pesanan yang sudah dibuat menyimpan harga
      dan jumlah saat checkout.
    </p>
  </div>
</template>

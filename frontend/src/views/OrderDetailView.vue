<script setup>
import { nextTick, onMounted, reactive, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { ApiError, apiRequest } from '../api'
import { formatWib } from '../datetime'
import { formatRupiah } from '../money'
import { orderStatusClass, orderStatusLabel } from '../orderStatus'
import { session } from '../session'

const route = useRoute()
const loading = ref(true)
const error = ref('')
const notFound = ref(false)
const order = ref(null)
const notice = ref('')
const actionError = ref('')
const saving = ref(false)
const confirmingCancel = ref(false)
const note = ref('')
const fieldErrors = reactive({})
const successRef = ref(null)
const errorRef = ref(null)
const noteInput = ref(null)
const cancelTrigger = ref(null)
const cancelConfirmButton = ref(null)

function clearActionState() {
  notice.value = ''
  actionError.value = ''
  for (const key of Object.keys(fieldErrors)) {
    delete fieldErrors[key]
  }
}

async function focusStatus() {
  await nextTick()
  successRef.value?.focus()
}

function clearField(field) {
  delete fieldErrors[field]
}

async function focusError() {
  await nextTick()
  errorRef.value?.focus()
}

async function loadOrder() {
  loading.value = true
  error.value = ''
  notFound.value = false
  clearActionState()
  try {
    order.value = await apiRequest(`/api/orders/${route.params.id}`)
    if (route.query.baru) {
      await focusStatus()
    }
  } catch (caught) {
    if (caught instanceof ApiError && caught.status === 404) {
      notFound.value = true
    } else {
      error.value =
        caught instanceof ApiError ? caught.message : 'Pesanan tidak dapat dimuat.'
    }
  } finally {
    loading.value = false
  }
}

function readNote() {
  const value = note.value.trim()
  if (value.length < 3 || value.length > 200) {
    fieldErrors.note = 'Keterangan harus 3 sampai 200 karakter.'
    return null
  }
  return value
}

async function reportTransfer() {
  if (saving.value) {
    return
  }
  clearActionState()
  const value = readNote()
  if (value === null) {
    await nextTick()
    noteInput.value?.focus()
    return
  }
  saving.value = true
  try {
    const updated = await apiRequest(`/api/orders/${order.value.id}/transfer-report`, {
      method: 'POST',
      body: { note: value },
    })
    order.value = { ...order.value, ...updated }
    note.value = ''
    notice.value =
      'Konfirmasi transfer terkirim. Pesanan menunggu pemeriksaan penjual dan belum lunas.'
    await focusStatus()
  } catch (caught) {
    if (caught instanceof ApiError) {
      Object.assign(fieldErrors, caught.fields)
      if (caught.status === 422 && caught.fields.note) {
        await nextTick()
        noteInput.value?.focus()
      } else {
        actionError.value = caught.message
        await focusError()
      }
    } else {
      actionError.value = 'Konfirmasi transfer tidak dapat dikirim. Coba lagi.'
      await focusError()
    }
  } finally {
    saving.value = false
  }
}

async function startCancel() {
  actionError.value = ''
  confirmingCancel.value = true
  await nextTick()
  cancelConfirmButton.value?.focus()
}

async function abortCancel() {
  confirmingCancel.value = false
  await nextTick()
  cancelTrigger.value?.focus()
}

async function cancelOrder() {
  if (saving.value) {
    return
  }
  actionError.value = ''
  saving.value = true
  try {
    const updated = await apiRequest(`/api/orders/${order.value.id}/cancel`, {
      method: 'POST',
      body: {},
    })
    order.value = { ...order.value, ...updated }
    confirmingCancel.value = false
    notice.value =
      'Pesanan dibatalkan sebelum konfirmasi transfer. Status batal bersifat final dan kuota dikembalikan satu kali.'
    await focusStatus()
  } catch (caught) {
    confirmingCancel.value = false
    actionError.value =
      caught instanceof ApiError ? caught.message : 'Pesanan tidak dapat dibatalkan.'
    await focusError()
  } finally {
    saving.value = false
  }
}

function cancellationActor(role) {
  if (role === 'buyer') {
    return 'Pembeli'
  }
  if (role === 'seller') {
    return 'Penjual'
  }
  return 'Tidak tercatat'
}

function refundLabel(outcome) {
  if (outcome === 'refunded_manually') {
    return 'Dana sudah dikembalikan manual di luar aplikasi.'
  }
  if (outcome === 'no_funds_received') {
    return 'Penjual menyatakan dana belum atau tidak diterima.'
  }
  return 'Tidak ada pernyataan refund penjual.'
}

onMounted(loadOrder)
</script>

<template>
  <section class="order-detail-page" aria-labelledby="order-detail-title">
    <div v-if="loading" class="form-card state-panel" role="status" aria-busy="true">
      <p>Memuat pesanan...</p>
    </div>

    <div v-else-if="notFound" class="form-card state-panel">
      <h1 id="order-detail-title">Pesanan tidak ditemukan</h1>
      <p>Pesanan ini tidak ada, atau bukan milik akun yang sedang masuk.</p>
      <p class="state-note">
        <RouterLink to="/pesanan">Kembali ke riwayat pesanan</RouterLink>
      </p>
    </div>

    <div v-else-if="error" class="alert alert-error" role="alert">
      <p>{{ error }}</p>
      <button class="button button-secondary" type="button" @click="loadOrder">
        Coba lagi
      </button>
    </div>

    <template v-else-if="order">
      <p
        v-if="notice || (route.query.baru && order.status === 'menunggu_pembayaran')"
        ref="successRef"
        class="alert alert-success"
        role="status"
        tabindex="-1"
      >
        <template v-if="notice">{{ notice }}</template>
        <template v-else>Pesanan {{ order.order_number }} berhasil dibuat.</template>
      </p>

      <div class="schedule-heading">
        <h1 id="order-detail-title">Pesanan {{ order.order_number }}</h1>
        <p>
          Simpan nomor ini. Harga dan jumlah di bawah adalah yang disepakati saat checkout.
        </p>
      </div>

      <div class="form-card order-detail">
        <div class="order-detail-head">
          <p class="order-number">{{ order.order_number }}</p>
          <span class="status-tag" :class="orderStatusClass(order.status)">
            {{ orderStatusLabel(order.status) }}
          </span>
        </div>

        <dl class="account-details">
          <div>
            <dt>Dibuat</dt>
            <dd>{{ formatWib(order.created_at) }}</dd>
          </div>
          <div>
            <dt>Pengambilan</dt>
            <dd>{{ formatWib(order.pickup_at) }}</dd>
          </div>
          <div>
            <dt>Batas PO bersama</dt>
            <dd>{{ formatWib(order.order_cutoff_at) }}</dd>
          </div>
          <div>
            <dt>Total pesanan</dt>
            <dd><strong>{{ formatRupiah(order.total_rupiah) }}</strong></dd>
          </div>
        </dl>

        <p v-if="session.user?.role === 'seller'" class="alert alert-info" role="status">
          Anda melihat pesanan pembeli sebagai penjual.
          <RouterLink :to="{ name: 'seller-order-detail', params: { id: order.id } }">
            Buka tindakan penjual
          </RouterLink>
        </p>

        <section class="order-items" aria-labelledby="order-items-title">
          <h2 id="order-items-title">Rincian produk</h2>
          <ul class="order-item-list">
            <li v-for="item in order.items" :key="item.id" class="order-item">
              <div>
                <h3>{{ item.product_name }}</h3>
                <p class="product-unit">{{ item.selling_unit }}</p>
                <p class="schedule-meta">
                  {{ item.quantity }} &times; {{ formatRupiah(item.unit_price_rupiah) }}
                </p>
              </div>
              <p class="order-line-total">{{ formatRupiah(item.line_total_rupiah) }}</p>
            </li>
          </ul>
        </section>

        <section
          v-if="session.user?.role === 'buyer' && order.status === 'menunggu_pembayaran'"
          class="payment-panel"
          aria-labelledby="payment-title"
        >
          <h2 id="payment-title">Pembayaran transfer</h2>
          <p class="alert alert-warning" role="note">
            Pesanan ini belum lunas. Laporan transfer di bawah belum diverifikasi; penjual
            mencocokkan dana secara manual sebelum mengonfirmasi pesanan.
          </p>
          <p>
            Total yang harus dicocokkan adalah
            <strong>{{ formatRupiah(order.total_rupiah) }}</strong>. Transfer sesuai
            petunjuk penjual, lalu kirim konfirmasi setelahnya. Batas PO bersama jadwal ini
            adalah <strong>{{ formatWib(order.order_cutoff_at) }}</strong>. Batas PO hanya
            menutup pesanan baru. Pesanan yang sudah dibuat tidak otomatis dibatalkan dan
            tidak punya timer pembayaran.
          </p>
          <p v-if="actionError" ref="errorRef" class="alert alert-error" role="alert" tabindex="-1">
            {{ actionError }}
          </p>

          <form class="payment-form" novalidate :aria-busy="saving" @submit.prevent="reportTransfer">
            <div class="field">
              <label for="transfer-note">Keterangan singkat untuk pencocokan</label>
              <textarea
                id="transfer-note"
                ref="noteInput"
                v-model="note"
                rows="3"
                maxlength="200"
                :aria-invalid="fieldErrors.note ? 'true' : 'false'"
                :aria-describedby="fieldErrors.note ? 'transfer-note-help transfer-note-error' : 'transfer-note-help'"
                @input="clearField('note')"
              ></textarea>
              <p id="transfer-note-help" class="field-help">
                Sebutkan tanggal transfer dan inisial pengirim agar penjual mudah
                mencocokkan dana. Jangan tulis nomor rekening atau data pribadi. Bukti
                transfer tidak diunggah di sini.
              </p>
              <p v-if="fieldErrors.note" id="transfer-note-error" class="field-error">
                {{ fieldErrors.note }}
              </p>
            </div>
            <button class="button button-primary" type="submit" :disabled="saving">
              {{ saving ? 'Mengirim konfirmasi...' : 'Kirim konfirmasi transfer' }}
            </button>
          </form>

          <div class="cancel-zone">
            <h3>Batalkan pesanan</h3>
            <p>
              Pembatalan sendiri hanya tersedia sebelum konfirmasi transfer. Setelah
              konfirmasi dikirim, penjual yang memeriksa dana dan menangani pembatalan
              serta refund manual di luar aplikasi.
            </p>
            <div v-if="!confirmingCancel" class="actions">
              <button
                ref="cancelTrigger"
                class="button button-danger"
                type="button"
                :disabled="saving"
                @click="startCancel"
              >
                Batalkan pesanan
              </button>
            </div>
            <div
              v-else
              class="confirm-panel"
              role="group"
              aria-label="Konfirmasi pembatalan pesanan"
            >
              <p>
                Batalkan pesanan {{ order.order_number }}? Status batal bersifat final dan
                kuota dikembalikan satu kali.
              </p>
              <div class="actions">
                <button
                  ref="cancelConfirmButton"
                  class="button button-danger"
                  type="button"
                  :disabled="saving"
                  @click="cancelOrder"
                >
                  {{ saving ? 'Membatalkan...' : 'Ya, batalkan pesanan' }}
                </button>
                <button
                  class="button button-secondary"
                  type="button"
                  :disabled="saving"
                  @click="abortCancel"
                >
                  Tidak, kembali
                </button>
              </div>
            </div>
          </div>
        </section>

        <section
          v-else-if="order.status === 'menunggu_pemeriksaan'"
          class="payment-panel"
          aria-labelledby="review-title"
        >
          <h2 id="review-title">Menunggu pemeriksaan penjual</h2>
          <p class="alert alert-info" role="note">
            Konfirmasi transfer dikirim {{ formatWib(order.transfer_reported_at) }}.
            Pesanan ini belum lunas sampai penjual mencocokkan dana secara manual.
          </p>
          <dl class="account-details">
            <div>
              <dt>Keterangan pembeli</dt>
              <dd>{{ order.transfer_note }}</dd>
            </div>
            <div>
              <dt>Total pesanan</dt>
              <dd><strong>{{ formatRupiah(order.total_rupiah) }}</strong></dd>
            </div>
            <div>
              <dt>Batas PO bersama</dt>
              <dd>{{ formatWib(order.order_cutoff_at) }}</dd>
            </div>
          </dl>
          <p>
            Pembeli tidak dapat membatalkan setelah konfirmasi transfer. Pembatalan dan
            refund manual ditangani penjual di luar aplikasi.
          </p>
        </section>

        <section
          v-else-if="order.status === 'terkonfirmasi'"
          class="payment-panel"
          aria-labelledby="verified-title"
        >
          <h2 id="verified-title">Pembayaran terverifikasi penjual</h2>
          <p class="alert alert-success" role="status">
            Penjual mencatat dana diterima
            <strong>{{ formatRupiah(order.payment_received_rupiah) }}</strong> pada
            {{ formatWib(order.verified_at) }}.
          </p>
          <p>
            Pencocokan dana dilakukan manual oleh penjual. Aplikasi tidak memeriksa mutasi
            bank dan tidak menjalankan refund. Pengembalian dana, bila diperlukan,
            diselesaikan penjual di luar aplikasi.
          </p>
          <p>
            Penjual akan menandai pesanan siap diambil setelah roti disiapkan, lalu
            menandainya selesai setelah penyerahan.
          </p>
        </section>

        <section
          v-else-if="order.status === 'siap_diambil'"
          class="payment-panel"
          aria-labelledby="ready-title"
        >
          <h2 id="ready-title">Pesanan siap diambil</h2>
          <p class="alert alert-success" role="status">
            Penjual sudah menyiapkan pesanan ini. Ambil sesuai waktu pengambilan pada
            jadwal, yaitu <strong>{{ formatWib(order.pickup_at) }}</strong>.
          </p>
          <dl class="account-details">
            <div>
              <dt>Pengambilan</dt>
              <dd>{{ formatWib(order.pickup_at) }}</dd>
            </div>
            <div v-if="order.verified_at">
              <dt>Pembayaran terverifikasi</dt>
              <dd>
                {{ formatRupiah(order.payment_received_rupiah) }} pada
                {{ formatWib(order.verified_at) }}
              </dd>
            </div>
            <div>
              <dt>Total pesanan</dt>
              <dd><strong>{{ formatRupiah(order.total_rupiah) }}</strong></dd>
            </div>
          </dl>
          <p>
            Status ini adalah tanda kesiapan dari penjual, bukan penjadwalan otomatis.
            Setelah pesanan diserahkan, penjual menandainya selesai.
          </p>
        </section>

        <section
          v-else-if="order.status === 'selesai'"
          class="payment-panel"
          aria-labelledby="completed-title"
        >
          <h2 id="completed-title">Pesanan selesai</h2>
          <p class="alert alert-success" role="status">
            Penjual mencatat pesanan ini sudah diserahkan kepada pembeli.
            Status selesai bersifat final.
          </p>
          <dl class="account-details">
            <div v-if="order.verified_at">
              <dt>Pembayaran terverifikasi</dt>
              <dd>
                {{ formatRupiah(order.payment_received_rupiah) }} pada
                {{ formatWib(order.verified_at) }}
              </dd>
            </div>
            <div>
              <dt>Total pesanan</dt>
              <dd><strong>{{ formatRupiah(order.total_rupiah) }}</strong></dd>
            </div>
          </dl>
          <p>
            Status selesai bersifat final dan tidak dapat dibatalkan atau dibuka kembali.
          </p>
        </section>

        <section
          v-else-if="order.status === 'batal'"
          class="payment-panel"
          aria-labelledby="cancelled-title"
        >
          <h2 id="cancelled-title">Pesanan batal</h2>
          <dl class="account-details">
            <div>
              <dt>Dibatalkan oleh</dt>
              <dd>{{ cancellationActor(order.cancelled_by_role) }}</dd>
            </div>
            <div>
              <dt>Waktu pembatalan</dt>
              <dd>{{ formatWib(order.cancelled_at) }}</dd>
            </div>
            <div>
              <dt>Alasan</dt>
              <dd>{{ order.cancellation_reason }}</dd>
            </div>
            <div>
              <dt>Penyelesaian dana</dt>
              <dd>{{ refundLabel(order.refund_outcome) }}</dd>
            </div>
            <div v-if="order.verified_at">
              <dt>Pembayaran terverifikasi</dt>
              <dd>
                {{ formatRupiah(order.payment_received_rupiah) }} pada
                {{ formatWib(order.verified_at) }}
              </dd>
            </div>
          </dl>
          <p>
            Status batal bersifat final dan tidak dapat dibuka kembali. Kuota pesanan ini
            dikembalikan satu kali. Riwayat pembayaran yang pernah diverifikasi tetap
            tercatat.
          </p>
        </section>

        <p v-else class="alert alert-info" role="note">
          Gunakan detail penjual untuk memeriksa pembayaran dan menangani pesanan ini.
        </p>

        <p class="form-switch">
          <RouterLink v-if="session.user?.role !== 'seller'" to="/pesanan">
            Kembali ke riwayat pesanan
          </RouterLink>
          <RouterLink v-else to="/penjual/pesanan">Kembali ke pesanan masuk</RouterLink>
        </p>
      </div>
    </template>
  </section>
</template>

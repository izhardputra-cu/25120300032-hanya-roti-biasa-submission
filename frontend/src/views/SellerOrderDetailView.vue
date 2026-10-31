<script setup>
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { ApiError, apiRequest } from '../api'
import { formatWib } from '../datetime'
import { formatRupiah } from '../money'
import { orderStatusClass, orderStatusLabel } from '../orderStatus'

const route = useRoute()
const router = useRouter()
const loading = ref(true)
const denied = ref(false)
const notFound = ref(false)
const error = ref('')
const order = ref(null)
const notice = ref('')
const verifyError = ref('')
const cancelError = ref('')
const fulfillError = ref('')
const verifyAmount = ref('')
const cancelReason = ref('')
const refundOutcome = ref('')
const verifyErrors = reactive({})
const cancelErrors = reactive({})
const savingVerify = ref(false)
const savingCancel = ref(false)
const savingFulfill = ref(false)
const confirmingCancel = ref(false)
const confirmingComplete = ref(false)
const successRef = ref(null)
const verifyErrorRef = ref(null)
const cancelErrorRef = ref(null)
const fulfillErrorRef = ref(null)
const verifyInput = ref(null)
const cancelReasonInput = ref(null)
const refundSelect = ref(null)
const cancelTrigger = ref(null)
const cancelConfirmButton = ref(null)
const completeTrigger = ref(null)
const completeConfirmButton = ref(null)

const canVerify = computed(
  () =>
    order.value !== null &&
    (order.value.status === 'menunggu_pembayaran' ||
      order.value.status === 'menunggu_pemeriksaan'),
)
const canMarkReady = computed(
  () => order.value !== null && order.value.status === 'terkonfirmasi',
)
const canComplete = computed(
  () => order.value !== null && order.value.status === 'siap_diambil',
)
const canCancel = computed(
  () =>
    order.value !== null &&
    ['menunggu_pembayaran', 'menunggu_pemeriksaan', 'terkonfirmasi', 'siap_diambil'].includes(
      order.value.status,
    ),
)

async function focusSuccess() {
  await nextTick()
  successRef.value?.focus()
}

function clearVerifyField() {
  delete verifyErrors.received_total_rupiah
}

function clearCancelField(field) {
  delete cancelErrors[field]
}

async function loadOrder() {
  loading.value = true
  denied.value = false
  notFound.value = false
  error.value = ''
  notice.value = ''
  try {
    order.value = await apiRequest(`/api/seller/orders/${route.params.id}`)
  } catch (caught) {
    if (caught instanceof ApiError && caught.status === 401) {
      await router.replace({ name: 'login', query: { expired: '1' } })
      return
    }
    if (caught instanceof ApiError && caught.status === 403) {
      denied.value = true
      return
    }
    if (caught instanceof ApiError && caught.status === 404) {
      notFound.value = true
      return
    }
    error.value =
      caught instanceof ApiError ? caught.message : 'Pesanan tidak dapat dimuat.'
  } finally {
    loading.value = false
  }
}

function readVerifiedAmount() {
  const raw = verifyAmount.value.trim()
  const amount = Number(raw)
  if (
    raw === '' ||
    !Number.isInteger(amount) ||
    amount < 1000 ||
    amount > 49950000000
  ) {
    verifyErrors.received_total_rupiah =
      'Jumlah dana harus bilangan bulat Rp1.000 sampai Rp49.950.000.000.'
    return null
  }
  return amount
}

async function verifyPayment() {
  if (savingVerify.value) {
    return
  }
  verifyError.value = ''
  delete verifyErrors.received_total_rupiah
  const amount = readVerifiedAmount()
  if (amount === null) {
    await nextTick()
    verifyInput.value?.focus()
    return
  }
  savingVerify.value = true
  try {
    const updated = await apiRequest(`/api/seller/orders/${order.value.id}/verify`, {
      method: 'POST',
      body: { received_total_rupiah: amount },
    })
    order.value = { ...order.value, ...updated }
    verifyAmount.value = ''
    notice.value = `Pembayaran ${order.value.order_number} tercatat terkonfirmasi. Dana yang dicatat sama dengan total pesanan.`
    await focusSuccess()
  } catch (caught) {
    if (caught instanceof ApiError) {
      Object.assign(verifyErrors, caught.fields)
      if (caught.status === 422 && caught.fields.received_total_rupiah) {
        await nextTick()
        verifyInput.value?.focus()
      } else {
        verifyError.value = caught.message
        await nextTick()
        verifyErrorRef.value?.focus()
      }
    } else {
      verifyError.value = 'Verifikasi tidak dapat disimpan. Coba lagi.'
      await nextTick()
      verifyErrorRef.value?.focus()
    }
  } finally {
    savingVerify.value = false
  }
}

function readCancellation() {
  const reason = cancelReason.value.trim()
  if (reason.length < 3 || reason.length > 300) {
    cancelErrors.reason = 'Alasan harus 3 sampai 300 karakter.'
  }
  if (!refundOutcome.value) {
    cancelErrors.refund_outcome = 'Pilih penyelesaian dana.'
  }
  if (Object.keys(cancelErrors).length > 0) {
    return null
  }
  return { reason, refund_outcome: refundOutcome.value }
}

async function startCancelConfirm() {
  cancelError.value = ''
  for (const key of Object.keys(cancelErrors)) {
    delete cancelErrors[key]
  }
  const payload = readCancellation()
  if (payload === null) {
    await nextTick()
    if (cancelErrors.reason) {
      cancelReasonInput.value?.focus()
    } else {
      refundSelect.value?.focus()
    }
    return
  }
  confirmingCancel.value = true
  await nextTick()
  cancelConfirmButton.value?.focus()
}

async function abortCancel() {
  confirmingCancel.value = false
  await nextTick()
  cancelTrigger.value?.focus()
}

async function submitCancel() {
  if (savingCancel.value) {
    return
  }
  const payload = readCancellation()
  if (payload === null) {
    confirmingCancel.value = false
    return
  }
  savingCancel.value = true
  cancelError.value = ''
  try {
    const updated = await apiRequest(`/api/seller/orders/${order.value.id}/cancel`, {
      method: 'POST',
      body: payload,
    })
    order.value = { ...order.value, ...updated }
    confirmingCancel.value = false
    notice.value =
      'Pembatalan tercatat sebagai pernyataan penjual. Status batal bersifat final dan kuota dikembalikan satu kali.'
    await focusSuccess()
  } catch (caught) {
    confirmingCancel.value = false
    cancelError.value =
      caught instanceof ApiError ? caught.message : 'Pembatalan tidak dapat disimpan.'
    await nextTick()
    cancelErrorRef.value?.focus()
  } finally {
    savingCancel.value = false
  }
}

async function refreshFacts() {
  try {
    order.value = await apiRequest(`/api/seller/orders/${order.value.id}`)
  } catch {
    // Keep the last known facts; the visible action error explains the refusal.
  }
}

async function showFulfillError(message) {
  fulfillError.value = message
  await refreshFacts()
  await nextTick()
  fulfillErrorRef.value?.focus()
}

async function markReady() {
  if (savingFulfill.value) {
    return
  }
  fulfillError.value = ''
  notice.value = ''
  savingFulfill.value = true
  try {
    const updated = await apiRequest(`/api/seller/orders/${order.value.id}/ready`, {
      method: 'POST',
      body: {},
    })
    order.value = { ...order.value, ...updated }
    notice.value =
      `Pesanan ${order.value.order_number} ditandai siap diambil. ` +
      'Rekap produksi tetap menghitung jumlahnya sampai pesanan selesai.'
    await focusSuccess()
  } catch (caught) {
    await showFulfillError(
      caught instanceof ApiError ? caught.message : 'Status siap diambil tidak dapat dicatat.',
    )
  } finally {
    savingFulfill.value = false
  }
}

async function startCompleteConfirm() {
  fulfillError.value = ''
  confirmingComplete.value = true
  await nextTick()
  completeConfirmButton.value?.focus()
}

async function abortComplete() {
  confirmingComplete.value = false
  await nextTick()
  completeTrigger.value?.focus()
}

async function completeOrder() {
  if (savingFulfill.value) {
    return
  }
  fulfillError.value = ''
  notice.value = ''
  savingFulfill.value = true
  try {
    const updated = await apiRequest(`/api/seller/orders/${order.value.id}/complete`, {
      method: 'POST',
      body: {},
    })
    order.value = { ...order.value, ...updated }
    confirmingComplete.value = false
    notice.value =
      `Pesanan ${order.value.order_number} ditandai selesai. ` +
      'Status ini final dan rekap produksi tetap menghitung jumlahnya.'
    await focusSuccess()
  } catch (caught) {
    confirmingComplete.value = false
    await showFulfillError(
      caught instanceof ApiError ? caught.message : 'Pesanan tidak dapat ditandai selesai.',
    )
  } finally {
    savingFulfill.value = false
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
  <section class="order-detail-page" aria-labelledby="seller-order-title">
    <div v-if="loading" class="form-card state-panel" role="status" aria-busy="true">
      <p>Memuat pesanan...</p>
    </div>

    <div v-else-if="denied" class="alert alert-warning" role="alert">
      <h2>Akses ditolak</h2>
      <p>Tindakan pesanan hanya tersedia untuk akun penjual.</p>
      <RouterLink class="button button-secondary" to="/akun">Kembali ke akun</RouterLink>
    </div>

    <div v-else-if="notFound" class="form-card state-panel">
      <h1 id="seller-order-title">Pesanan tidak ditemukan</h1>
      <p>Nomor pesanan ini tidak ada.</p>
      <p class="state-note">
        <RouterLink to="/penjual/pesanan">Kembali ke pesanan masuk</RouterLink>
      </p>
    </div>

    <div v-else-if="error" class="alert alert-error" role="alert">
      <p>{{ error }}</p>
      <button class="button button-secondary" type="button" @click="loadOrder">
        Coba lagi
      </button>
    </div>

    <template v-else-if="order">
      <p ref="successRef" v-if="notice" class="alert alert-success" role="status" tabindex="-1">
        {{ notice }}
      </p>

      <div class="schedule-heading">
        <h1 id="seller-order-title">
          {{ canVerify || canCancel ? 'Tindakan pesanan' : 'Detail pesanan' }} {{ order.order_number }}
        </h1>
        <p v-if="canVerify || canCancel">
          Cocokkan dana secara manual, lalu catat verifikasi, kesiapan diambil, atau
          pembatalan. Aplikasi ini tidak memeriksa mutasi bank dan tidak memindahkan uang.
        </p>
        <p v-else>Rincian dan riwayat pesanan. Tidak ada tindakan pada halaman ini.</p>
      </div>

      <div class="form-card order-detail">
        <div class="order-detail-head">
          <p class="order-number">{{ order.order_number }}</p>
          <span class="status-tag" :class="orderStatusClass(order.status)">
            {{ orderStatusLabel(order.status) }}
          </span>
        </div>

        <p class="seller-order-buyer">
          Pembeli: <strong>{{ order.buyer.name }}</strong> &middot; {{ order.buyer.email }}
        </p>

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

        <section class="order-items" aria-labelledby="seller-order-items-title">
          <h2 id="seller-order-items-title">Rincian produk</h2>
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

        <section class="payment-panel" aria-labelledby="transfer-facts-title">
          <h2 id="transfer-facts-title">Konfirmasi pembeli</h2>
          <p v-if="order.transfer_note" class="alert alert-info">
            Dikirim {{ formatWib(order.transfer_reported_at) }}.<br />
            Keterangan: {{ order.transfer_note }}
          </p>
          <p v-else-if="canVerify" class="state-note">
            Pembeli belum mengirim konfirmasi transfer. Verifikasi langsung tetap bisa
            dilakukan setelah dana benar-benar diperiksa.
          </p>
          <p v-else class="state-note">
            Tidak ada konfirmasi transfer pembeli yang tercatat.
          </p>
        </section>

        <section v-if="order.verified_at" class="payment-panel" aria-labelledby="verified-facts-title">
          <h2 id="verified-facts-title">Pembayaran tercatat</h2>
          <dl class="account-details">
            <div>
              <dt>Dana diterima</dt>
              <dd>{{ formatRupiah(order.payment_received_rupiah) }}</dd>
            </div>
            <div>
              <dt>Diverifikasi</dt>
              <dd>{{ formatWib(order.verified_at) }}</dd>
            </div>
          </dl>
          <p v-if="canCancel">
            Pembayaran ini pernah diverifikasi. Pembatalan tidak boleh menyatakan dana
            belum diterima, dan refund harus diselesaikan manual di luar aplikasi.
          </p>
        </section>

        <section v-if="canVerify" class="payment-panel" aria-labelledby="verify-title">
          <h2 id="verify-title">Verifikasi pembayaran</h2>
          <p>
            Masukkan jumlah dana yang benar-benar diterima. Nominal harus sama dengan total
            pesanan <strong>{{ formatRupiah(order.total_rupiah) }}</strong>. Nominal
            berbeda tidak akan menandai pesanan lunas.
          </p>
          <p
            v-if="verifyError"
            ref="verifyErrorRef"
            class="alert alert-error"
            role="alert"
            tabindex="-1"
          >
            {{ verifyError }}
          </p>
          <form class="payment-form" novalidate :aria-busy="savingVerify" @submit.prevent="verifyPayment">
            <div class="field">
              <label for="received-total">Jumlah dana yang benar-benar diterima (Rupiah)</label>
              <input
                id="received-total"
                ref="verifyInput"
                v-model="verifyAmount"
                type="text"
                inputmode="numeric"
                autocomplete="off"
                :aria-invalid="verifyErrors.received_total_rupiah ? 'true' : 'false'"
                :aria-describedby="verifyErrors.received_total_rupiah ? 'received-total-help received-total-error' : 'received-total-help'"
                @input="clearVerifyField"
              />
              <p id="received-total-help" class="field-help">
                Cocokkan dengan catatan penerimaan dana sebenarnya. Aplikasi tidak
                memeriksa mutasi bank.
              </p>
              <p v-if="verifyErrors.received_total_rupiah" id="received-total-error" class="field-error">
                {{ verifyErrors.received_total_rupiah }}
              </p>
            </div>
            <button class="button button-primary" type="submit" :disabled="savingVerify">
              {{ savingVerify ? 'Memverifikasi...' : 'Verifikasi pembayaran' }}
            </button>
          </form>
        </section>

        <section v-if="canCancel" class="payment-panel" aria-labelledby="cancel-title">
          <h2 id="cancel-title">Batalkan pesanan</h2>
          <p>
            Pembatalan mencatat alasan dan pernyataan penyelesaian dana. Aplikasi tidak
            menjalankan refund; selesaikan pengembalian dana manual terlebih dahulu.
          </p>
          <p v-if="canComplete" class="alert alert-warning" role="note">
            Pesanan sudah siap diambil. Membatalkan berarti pesanan tidak diserahkan:
            kuota dikembalikan satu kali dan jumlahnya keluar dari rekap produksi.
          </p>
          <p v-if="order.verified_at" class="alert alert-warning" role="note">
            Pembayaran sudah diverifikasi. Pilihan yang tersedia hanya pernyataan bahwa
            dana sudah dikembalikan manual.
          </p>
          <p
            v-if="cancelError"
            ref="cancelErrorRef"
            class="alert alert-error"
            role="alert"
            tabindex="-1"
          >
            {{ cancelError }}
          </p>
          <form class="payment-form" novalidate :aria-busy="savingCancel" @submit.prevent="startCancelConfirm">
            <div class="field">
              <label for="cancel-reason">Alasan pembatalan</label>
              <textarea
                id="cancel-reason"
                ref="cancelReasonInput"
                v-model="cancelReason"
                rows="3"
                maxlength="300"
                :aria-invalid="cancelErrors.reason ? 'true' : 'false'"
                :aria-describedby="cancelErrors.reason ? 'cancel-reason-help cancel-reason-error' : 'cancel-reason-help'"
                @input="clearCancelField('reason')"
              ></textarea>
              <p id="cancel-reason-help" class="field-help">
                3 sampai 300 karakter. Jelaskan alasan operasional yang sebenarnya.
              </p>
              <p v-if="cancelErrors.reason" id="cancel-reason-error" class="field-error">
                {{ cancelErrors.reason }}
              </p>
            </div>
            <div class="field">
              <label for="refund-outcome">Penyelesaian dana</label>
              <select
                id="refund-outcome"
                ref="refundSelect"
                v-model="refundOutcome"
                :aria-invalid="cancelErrors.refund_outcome ? 'true' : 'false'"
                :aria-describedby="cancelErrors.refund_outcome ? 'refund-outcome-help refund-outcome-error' : 'refund-outcome-help'"
                @change="clearCancelField('refund_outcome')"
              >
                <option value="">Pilih penyelesaian dana</option>
                <option value="refunded_manually">
                  Dana sudah saya kembalikan manual di luar aplikasi
                </option>
                <option v-if="!order.verified_at" value="no_funds_received">
                  Dana belum atau tidak saya terima
                </option>
              </select>
              <p id="refund-outcome-help" class="field-help">
                Pernyataan ini dicatat sebagai pernyataan penjual, bukan verifikasi bank.
              </p>
              <p v-if="cancelErrors.refund_outcome" id="refund-outcome-error" class="field-error">
                {{ cancelErrors.refund_outcome }}
              </p>
            </div>
            <div v-if="!confirmingCancel" class="actions">
              <button
                ref="cancelTrigger"
                class="button button-danger"
                type="submit"
                :disabled="savingCancel"
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
                Catat pembatalan {{ order.order_number }}? Status batal bersifat final,
                riwayat tidak dapat ditimpa, dan kuota dikembalikan satu kali.
              </p>
              <div class="actions">
                <button
                  ref="cancelConfirmButton"
                  class="button button-danger"
                  type="button"
                  :disabled="savingCancel"
                  @click="submitCancel"
                >
                  {{ savingCancel ? 'Menyimpan pembatalan...' : 'Ya, catat pembatalan' }}
                </button>
                <button
                  class="button button-secondary"
                  type="button"
                  :disabled="savingCancel"
                  @click="abortCancel"
                >
                  Tidak, kembali
                </button>
              </div>
            </div>
          </form>
        </section>

        <section v-if="order.status === 'batal'" class="payment-panel" aria-labelledby="final-cancel-title">
          <h2 id="final-cancel-title">Pembatalan tercatat</h2>
          <dl class="account-details">
            <div>
              <dt>Dibatalkan oleh</dt>
              <dd>{{ cancellationActor(order.cancelled_by_role) }}</dd>
            </div>
            <div>
              <dt>Waktu</dt>
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
            Status batal tidak dapat dibuka kembali. Kuota pesanan ini dikembalikan satu
            kali. Riwayat pembayaran yang pernah diverifikasi tetap tercatat.
          </p>
        </section>

        <p
          v-if="fulfillError"
          ref="fulfillErrorRef"
          class="alert alert-error"
          role="alert"
          tabindex="-1"
        >
          {{ fulfillError }}
        </p>

        <section
          v-if="canMarkReady || canComplete"
          class="payment-panel"
          aria-labelledby="fulfillment-title"
        >
          <h2 id="fulfillment-title">Pengambilan pesanan</h2>
          <p v-if="canMarkReady">
            Tandai siap diambil setelah roti benar-benar disiapkan untuk pembeli. Status
            ini menjadi tanda kesiapan penjual, bukan penjadwalan otomatis.
          </p>
          <p v-if="canComplete">
            Tandai selesai setelah pesanan benar-benar diserahkan kepada pembeli. Status
            selesai bersifat final, tidak dapat dibatalkan atau dibuka kembali, dan
            jumlahnya tetap dihitung pada rekap produksi.
          </p>
          <div v-if="canMarkReady" class="actions">
            <button
              class="button button-primary"
              type="button"
              :disabled="savingFulfill"
              @click="markReady"
            >
              {{ savingFulfill ? 'Menyimpan status...' : 'Tandai siap diambil' }}
            </button>
          </div>
          <div v-else-if="canComplete">
            <div v-if="!confirmingComplete" class="actions">
              <button
                ref="completeTrigger"
                class="button button-primary"
                type="button"
                :disabled="savingFulfill"
                @click="startCompleteConfirm"
              >
                Tandai selesai
              </button>
            </div>
            <div
              v-else
              class="confirm-panel"
              role="group"
              aria-label="Konfirmasi pesanan selesai"
            >
              <p>
                Catat {{ order.order_number }} sebagai selesai? Status ini final dan
                tidak dapat dibatalkan atau dibuka kembali. Rekap produksi tetap
                menghitung jumlahnya.
              </p>
              <div class="actions">
                <button
                  ref="completeConfirmButton"
                  class="button button-primary"
                  type="button"
                  :disabled="savingFulfill"
                  @click="completeOrder"
                >
                  {{ savingFulfill ? 'Menyimpan status...' : 'Ya, tandai selesai' }}
                </button>
                <button
                  class="button button-secondary"
                  type="button"
                  :disabled="savingFulfill"
                  @click="abortComplete"
                >
                  Tidak, kembali
                </button>
              </div>
            </div>
          </div>
        </section>

        <section
          v-if="order.status === 'selesai'"
          class="payment-panel"
          aria-labelledby="completed-title"
        >
          <h2 id="completed-title">Pesanan selesai</h2>
          <p>
            Penjual mencatat pesanan ini sudah diserahkan kepada pembeli. Status selesai
            tidak dapat dibatalkan atau dibuka kembali.
          </p>
          <p class="state-note">
            Jumlah pesanan ini tetap dihitung pada
            <RouterLink to="/penjual/rekap">rekap produksi</RouterLink>.
          </p>
        </section>

        <p class="form-switch">
          <RouterLink to="/penjual/pesanan">Kembali ke pesanan masuk</RouterLink>
        </p>
      </div>
    </template>
  </section>
</template>

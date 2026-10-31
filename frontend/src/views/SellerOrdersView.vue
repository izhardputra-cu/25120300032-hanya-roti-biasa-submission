<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { ApiError, apiRequest } from '../api'
import { formatWib } from '../datetime'
import { formatRupiah } from '../money'
import { orderStatusClass, orderStatusLabel } from '../orderStatus'

const router = useRouter()
const loading = ref(true)
const denied = ref(false)
const error = ref('')
const errorRef = ref(null)
const orders = ref([])
const includeArchived = ref(false)
const hasLoaded = ref(false)

const attentionCount = computed(
  () =>
    orders.value.filter(
      (order) => order.status === 'menunggu_pemeriksaan' || order.status === 'menunggu_pembayaran',
    ).length,
)

async function loadOrders() {
  loading.value = true
  denied.value = false
  error.value = ''
  try {
    const query = includeArchived.value ? '?include_archived=true' : ''
    const data = await apiRequest(`/api/seller/orders${query}`)
    orders.value = data.items
    hasLoaded.value = true
  } catch (caught) {
    if (caught instanceof ApiError && caught.status === 401) {
      await router.replace({ name: 'login', query: { expired: '1' } })
      return
    }
    if (caught instanceof ApiError && caught.status === 403) {
      denied.value = true
      return
    }
    error.value =
      caught instanceof ApiError ? caught.message : 'Pesanan masuk tidak dapat dimuat.'
  } finally {
    loading.value = false
    if (error.value) {
      await nextTick()
      errorRef.value?.focus()
    }
  }
}

onMounted(loadOrders)
</script>

<template>
  <section class="seller-orders-page" aria-labelledby="seller-orders-title">
    <div class="seller-heading">
      <h1 id="seller-orders-title">Pesanan masuk</h1>
      <p>
        Daftar kerja sederhana untuk mencocokkan pembayaran dan menangani pembatalan.
        Verifikasi hanya setelah dana benar-benar diperiksa.
      </p>
      <p class="seller-heading-link">
        <RouterLink to="/penjual/jadwal">Kembali ke kelola jadwal</RouterLink>
        <span aria-hidden="true"> &middot; </span>
        <RouterLink to="/penjual/rekap">Rekap produksi</RouterLink>
      </p>
    </div>

    <p v-if="hasLoaded && !denied" class="list-filter">
      <label class="picker-check">
        <input v-model="includeArchived" type="checkbox" @change="loadOrders" />
        <span>Sertakan arsip</span>
      </label>
    </p>

    <div v-if="loading" class="form-card state-panel" role="status" aria-busy="true">
      <p>Memuat pesanan masuk...</p>
    </div>

    <div v-else-if="denied" class="alert alert-warning" role="alert">
      <h2>Akses ditolak</h2>
      <p>Halaman ini hanya tersedia untuk akun penjual.</p>
      <RouterLink class="button button-secondary" to="/akun">Kembali ke akun</RouterLink>
    </div>

    <div v-else-if="error" ref="errorRef" class="alert alert-error" role="alert" tabindex="-1">
      <p>{{ error }}</p>
      <button class="button button-secondary" type="button" @click="loadOrders">
        Coba lagi
      </button>
    </div>

    <div v-else-if="orders.length === 0" class="form-card state-panel">
      <p>Belum ada pesanan masuk.</p>
      <p class="state-note">
        Pesanan muncul setelah pembeli checkout dari
        <RouterLink to="/penjual/jadwal">jadwal pre-order</RouterLink>.
      </p>
      <p v-if="!includeArchived" class="state-note">
        Centang “Sertakan arsip” untuk melihat riwayat pesanan pada jadwal yang sudah
        diarsipkan.
      </p>
    </div>

    <template v-else>
      <p class="field-help">
        Pesanan pada jadwal yang diarsipkan tetap tersimpan tetapi tidak tampil di
        daftar kerja bawaan.
      </p>

      <p v-if="attentionCount > 0" class="worklist-summary" role="status">
        {{ attentionCount }} pesanan menunggu pemeriksaan atau verifikasi pembayaran.
      </p>

      <ul class="order-list">
        <li v-for="order in orders" :key="order.id" class="order-card seller-order-card">
          <div class="order-card-head">
            <h2>
              <RouterLink :to="{ name: 'seller-order-detail', params: { id: order.id } }">
                {{ order.order_number }}
              </RouterLink>
            </h2>
            <span class="status-tag" :class="orderStatusClass(order.status)">
              {{ orderStatusLabel(order.status) }}
            </span>
          </div>
          <p class="seller-order-buyer">
            Pembeli: <strong>{{ order.buyer.name }}</strong> &middot; {{ order.buyer.email }}
          </p>
          <p class="schedule-meta">
            Dibuat {{ formatWib(order.created_at) }} &middot; Pengambilan
            {{ formatWib(order.pickup_at) }}
          </p>
          <p class="order-summary">
            {{ order.items.length }} jenis produk &middot;
            <strong>{{ formatRupiah(order.total_rupiah) }}</strong>
          </p>
          <p v-if="order.transfer_note" class="alert alert-info">
            Keterangan pembeli: {{ order.transfer_note }}
          </p>
          <p v-if="order.status === 'menunggu_pembayaran'" class="state-note">
            Pembeli belum mengirim konfirmasi transfer. Verifikasi langsung tetap bisa
            dilakukan setelah dana diperiksa.
          </p>
          <p v-else-if="order.status === 'menunggu_pemeriksaan'" class="state-note">
            Konfirmasi pembeli menunggu pemeriksaan dana. Nominal harus sama dengan total
            pesanan sebelum ditandai terkonfirmasi.
          </p>
          <p v-else-if="order.status === 'terkonfirmasi'" class="state-note">
            Pembayaran terverifikasi. Tandai siap diambil setelah roti benar-benar
            disiapkan.
          </p>
          <p v-else-if="order.status === 'siap_diambil'" class="state-note">
            Sudah ditandai siap diambil. Tandai selesai setelah pesanan diserahkan, atau
            batalkan dengan pernyataan refund manual bila tidak jadi dipenuhi.
          </p>
          <p v-else-if="order.status === 'selesai'" class="state-note">
            Pesanan selesai dan final. Jumlahnya tetap dihitung pada rekap produksi.
          </p>
          <p class="seller-heading-link">
            <RouterLink :to="{ name: 'seller-order-detail', params: { id: order.id } }">
              {{ ['batal', 'selesai'].includes(order.status) ? 'Buka detail pesanan' : 'Buka tindakan pesanan' }}
            </RouterLink>
          </p>
        </li>
      </ul>
    </template>
  </section>
</template>

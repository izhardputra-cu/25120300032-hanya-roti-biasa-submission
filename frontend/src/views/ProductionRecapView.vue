<script setup>
import { nextTick, onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { ApiError, apiRequest } from '../api'
import { formatWib } from '../datetime'

const router = useRouter()
const loading = ref(true)
const denied = ref(false)
const error = ref('')
const errorRef = ref(null)
const recap = ref(null)
const includeArchived = ref(false)
const hasLoaded = ref(false)

async function loadRecap() {
  loading.value = true
  denied.value = false
  error.value = ''
  try {
    const query = includeArchived.value ? '?include_archived=true' : ''
    recap.value = await apiRequest(`/api/seller/production-recap${query}`)
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
      caught instanceof ApiError ? caught.message : 'Rekap produksi tidak dapat dimuat.'
  } finally {
    loading.value = false
    if (error.value) {
      await nextTick()
      errorRef.value?.focus()
    }
  }
}

onMounted(loadRecap)
</script>

<template>
  <section class="seller-page" aria-labelledby="recap-title">
    <div class="seller-heading">
      <h1 id="recap-title">Rekap produksi</h1>
      <p>
        Jumlah unit jual yang perlu disiapkan pada tiap jadwal panggang, dihitung dari
        pesanan yang pembayarannya sudah diverifikasi penjual dan tidak dibatalkan.
      </p>
      <p class="state-note">
        Pesanan siap diambil dan selesai tetap dihitung, sehingga jumlah tidak hilang
        setelah penyerahan. Pesanan yang menunggu pembayaran, menunggu pemeriksaan, atau
        batal tidak dihitung. Angka di bawah adalah unit jual, bukan jumlah jenis produk
        atau jumlah pesanan.
      </p>
      <p class="seller-heading-link">
        <RouterLink to="/penjual/pesanan">Buka pesanan masuk</RouterLink>
        <span aria-hidden="true"> &middot; </span>
        <RouterLink to="/penjual/jadwal">Kelola jadwal pre-order</RouterLink>
      </p>
    </div>

    <p v-if="hasLoaded && !denied" class="list-filter">
      <label class="picker-check">
        <input v-model="includeArchived" type="checkbox" @change="loadRecap" />
        <span>Sertakan arsip</span>
      </label>
    </p>

    <div v-if="loading" class="form-card state-panel" role="status" aria-busy="true">
      <p>Menghitung rekap produksi...</p>
    </div>

    <div v-else-if="denied" class="alert alert-warning" role="alert">
      <h2>Akses ditolak</h2>
      <p>Rekap produksi hanya tersedia untuk akun penjual.</p>
      <RouterLink class="button button-secondary" to="/akun">Kembali ke akun</RouterLink>
    </div>

    <div v-else-if="error" ref="errorRef" class="alert alert-error" role="alert" tabindex="-1">
      <p>{{ error }}</p>
      <button class="button button-secondary" type="button" @click="loadRecap">
        Coba lagi
      </button>
    </div>

    <div v-else-if="recap && recap.items.length === 0" class="form-card state-panel">
      <p>Belum ada jadwal panggang.</p>
      <p class="state-note">
        Rekap muncul setelah penjual membuka jadwal dan pesanan terbayar masuk.
        <RouterLink to="/penjual/jadwal">Buka jadwal pre-order</RouterLink>.
      </p>
      <p v-if="!includeArchived" class="state-note">
        Centang “Sertakan arsip” untuk melihat rekap jadwal yang sudah diarsipkan.
      </p>
    </div>

    <div v-else-if="recap" class="form-card">
      <p class="field-help">
        Jadwal yang diarsipkan tidak tampil di rekap bawaan. Jumlah unit yang sudah
        terverifikasi tetap utuh saat arsip disertakan atau jadwal dipulihkan.
      </p>
      <ul class="recap-list">
        <li
          v-for="schedule in recap.items"
          :key="schedule.schedule_id"
          class="recap-schedule"
        >
          <div class="recap-head">
            <h2 :id="`recap-schedule-${schedule.schedule_id}`">
              Pengambilan {{ formatWib(schedule.pickup_at) }}
            </h2>
            <span v-if="schedule.archived" class="status-tag">Diarsipkan</span>
            <span
              class="status-tag"
              :class="schedule.orders_open ? 'status-tag-open' : 'status-tag-closed'"
            >
              {{ schedule.orders_open ? 'Dibuka' : 'Ditutup' }}
            </span>
          </div>
          <p class="schedule-meta">
            Batas PO {{ formatWib(schedule.order_cutoff_at) }}
          </p>

          <template v-if="schedule.lines.length > 0">
            <ul
              class="order-item-list"
              :aria-labelledby="`recap-schedule-${schedule.schedule_id}`"
            >
              <li v-for="line in schedule.lines" :key="line.offer_id" class="order-item">
                <div>
                  <h3>{{ line.product_name }}</h3>
                  <p class="product-unit">{{ line.selling_unit }}</p>
                </div>
                <p class="order-line-total">{{ line.quantity }} unit jual</p>
              </li>
            </ul>
            <p class="recap-total">
              Total {{ schedule.total_quantity }} unit jual untuk jadwal ini.
            </p>
          </template>
          <p v-else class="state-note">
            Belum ada pesanan terbayar pada jadwal ini. Pesanan yang belum terverifikasi
            atau batal tidak masuk rekap.
          </p>

          <p class="seller-heading-link">
            <RouterLink to="/penjual/pesanan">
              Buka pesanan masuk
            </RouterLink>
          </p>
        </li>
      </ul>
    </div>
  </section>
</template>

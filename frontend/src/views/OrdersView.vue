<script setup>
import { onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { ApiError, apiRequest } from '../api'
import { formatWib } from '../datetime'
import { formatRupiah } from '../money'
import { orderStatusClass, orderStatusLabel } from '../orderStatus'
import { session } from '../session'

const loading = ref(true)
const error = ref('')
const orders = ref([])

async function loadOrders() {
  loading.value = true
  error.value = ''
  try {
    const data = await apiRequest('/api/orders')
    orders.value = data.items
  } catch (caught) {
    error.value =
      caught instanceof ApiError ? caught.message : 'Riwayat pesanan tidak dapat dimuat.'
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  if (session.user?.role === 'seller') {
    loading.value = false
    return
  }
  loadOrders()
})
</script>

<template>
  <section class="orders-page" aria-labelledby="orders-title">
    <div class="schedule-heading">
      <h1 id="orders-title">Pesanan saya</h1>
      <p>
        Riwayat pesanan akun ini. Setiap pesanan hanya menampilkan produk dan harga yang
        disepakati saat checkout.
      </p>
    </div>

    <div v-if="loading" class="form-card state-panel" role="status" aria-busy="true">
      <p>Memuat pesanan...</p>
    </div>

    <div v-else-if="session.user?.role === 'seller'" class="form-card state-panel">
      <p>Riwayat ini hanya untuk akun pembeli.</p>
      <p class="state-note">
        <RouterLink to="/penjual/jadwal">Kembali ke kelola jadwal</RouterLink>
      </p>
    </div>

    <div v-else-if="error" class="alert alert-error" role="alert">
      <p>{{ error }}</p>
      <button class="button button-secondary" type="button" @click="loadOrders">
        Coba lagi
      </button>
    </div>

    <div v-else-if="orders.length === 0" class="form-card state-panel">
      <p>Belum ada pesanan.</p>
      <p class="state-note">
        Pilih produk dari <RouterLink to="/jadwal">jadwal pre-order</RouterLink> yang masih
        dibuka.
      </p>
    </div>

    <ul v-else class="order-list">
      <li v-for="order in orders" :key="order.id" class="order-card">
        <div class="order-card-head">
          <h2>
            <RouterLink :to="{ name: 'order-detail', params: { id: order.id } }">
              {{ order.order_number }}
            </RouterLink>
          </h2>
          <span class="status-tag" :class="orderStatusClass(order.status)">
            {{ orderStatusLabel(order.status) }}
          </span>
        </div>
        <p class="schedule-meta">
          Dibuat {{ formatWib(order.created_at) }} &middot; Pengambilan
          {{ formatWib(order.pickup_at) }}
        </p>
        <p class="order-summary">
          {{ order.items.length }} jenis produk &middot;
          <strong>{{ formatRupiah(order.total_rupiah) }}</strong>
        </p>
        <p class="seller-heading-link">
          <RouterLink :to="{ name: 'order-detail', params: { id: order.id } }">
            Lihat detail pesanan
          </RouterLink>
        </p>
      </li>
    </ul>
  </section>
</template>

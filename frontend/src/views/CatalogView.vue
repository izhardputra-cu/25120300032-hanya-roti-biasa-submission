<script setup>
import { onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { ApiError, apiRequest } from '../api'
import breadHero from '../assets/bread-hero.jpg'

const loading = ref(true)
const error = ref('')
const products = ref([])

const rupiah = new Intl.NumberFormat('id-ID', {
  style: 'currency',
  currency: 'IDR',
  maximumFractionDigits: 0,
})

function formatPrice(value) {
  return rupiah.format(value)
}

async function loadCatalog() {
  loading.value = true
  error.value = ''
  try {
    const data = await apiRequest('/api/products')
    products.value = data.items
  } catch (caught) {
    error.value =
      caught instanceof ApiError ? caught.message : 'Katalog tidak dapat dimuat.'
  } finally {
    loading.value = false
  }
}

onMounted(loadCatalog)
</script>

<template>
  <div class="catalog-page">
    <section class="catalog-hero" aria-labelledby="catalog-title">
      <div class="catalog-hero-copy">
        <h1 id="catalog-title">Katalog roti sourdough</h1>
        <p class="catalog-hero-text">
          Roti sourdough dipanggang per jadwal.
        </p>
        <p class="catalog-hero-note">
          Pilih roti di bawah, lalu buka
          <RouterLink to="/jadwal">jadwal dan batas PO</RouterLink>
          untuk sisa kuota serta waktu pengambilan dalam WIB.
        </p>
      </div>
      <figure class="catalog-hero-figure">
        <img
          :src="breadHero"
          alt="Roti sourdough bulat di dalam panci besi"
          width="960"
          height="996"
          fetchpriority="high"
        />
      </figure>
    </section>

    <section class="catalog-section" aria-labelledby="catalog-list-title">
      <div class="catalog-section-head">
        <h2 id="catalog-list-title">Produk</h2>
        <p v-if="!loading && !error && products.length > 0" class="catalog-count">
          {{ products.length }} produk
        </p>
      </div>

      <div v-if="loading" class="form-card state-panel" role="status" aria-busy="true">
        <p>Memuat katalog...</p>
      </div>

      <div v-else-if="error" class="alert alert-error" role="alert">
        <p>{{ error }}</p>
        <button class="button button-secondary" type="button" @click="loadCatalog">
          Coba lagi
        </button>
      </div>

      <div v-else-if="products.length === 0" class="form-card state-panel">
        <p>Belum ada produk di katalog.</p>
        <p class="state-note">
          Penjual dapat menambahkan produk dari ruang penjual. Pengunjung tidak perlu masuk
          untuk melihat katalog.
        </p>
      </div>

      <ul v-else class="product-grid">
        <li v-for="product in products" :key="product.id" class="product-card">
          <h3>{{ product.name }}</h3>
          <p class="product-price">{{ formatPrice(product.price_rupiah) }}</p>
          <p class="product-unit">{{ product.selling_unit }}</p>
          <p v-if="product.description" class="product-description">
            {{ product.description }}
          </p>
        </li>
      </ul>
    </section>
  </div>
</template>

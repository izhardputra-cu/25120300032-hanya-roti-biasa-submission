<script setup>
import { ref } from 'vue'
import { RouterLink, RouterView } from 'vue-router'
import { cart } from './cart'
import { loadSession, session } from './session'

const retrying = ref(false)

async function retry() {
  retrying.value = true
  try {
    await loadSession(true)
  } catch {
    // The shared error panel stays visible with the current message.
  } finally {
    retrying.value = false
  }
}
</script>

<template>
  <div class="app-shell">
    <a class="skip-link" href="#main">Lewati ke konten</a>
    <header class="site-header">
      <div class="shell header-row">
        <RouterLink class="brand" to="/">
          <span class="brand-name">Hanya Roti Biasa</span>
        </RouterLink>
        <nav class="site-nav" aria-label="Navigasi utama">
          <RouterLink to="/">Katalog</RouterLink>
          <RouterLink to="/jadwal">Jadwal</RouterLink>
          <RouterLink
            v-if="session.user?.role !== 'seller'"
            to="/keranjang"
            class="nav-cart"
          >
            Keranjang
            <span v-if="cart.items.length > 0" class="cart-count">
              {{ cart.items.length }}
            </span>
          </RouterLink>
          <template v-if="session.user">
            <RouterLink v-if="session.user.role === 'buyer'" to="/pesanan">
              Pesanan
            </RouterLink>
            <RouterLink to="/akun">Akun</RouterLink>
            <RouterLink v-if="session.user.role === 'seller'" to="/penjual">
              Kelola katalog
            </RouterLink>
            <RouterLink v-if="session.user.role === 'seller'" to="/penjual/jadwal">
              Kelola jadwal
            </RouterLink>
            <RouterLink v-if="session.user.role === 'seller'" to="/penjual/pesanan">
              Pesanan
            </RouterLink>
            <RouterLink v-if="session.user.role === 'seller'" to="/penjual/rekap">
              Rekap
            </RouterLink>
          </template>
          <template v-else>
            <RouterLink to="/masuk">Masuk</RouterLink>
            <RouterLink class="nav-primary" to="/daftar">Daftar</RouterLink>
          </template>
        </nav>
      </div>
    </header>

    <main id="main" class="shell page" tabindex="-1">
      <section v-if="session.error" class="alert alert-error" role="alert">
        <h1 class="error-title">Halaman belum dapat dimuat</h1>
        <p>{{ session.error.message }}</p>
        <button
          class="button button-secondary"
          type="button"
          :disabled="retrying"
          @click="retry"
        >
          {{ retrying ? 'Memuat ulang...' : 'Coba muat ulang' }}
        </button>
      </section>
      <RouterView v-else />
    </main>

    <footer class="site-footer">
      <div class="shell">
        <p>
          Pre-order roti sourdough dibuka per jadwal panggang. Pembayaran transfer dan
          pengambilan diatur langsung dengan penjual.
        </p>
      </div>
    </footer>
  </div>
</template>

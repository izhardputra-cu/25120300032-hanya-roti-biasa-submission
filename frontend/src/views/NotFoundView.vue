<script setup>
import { RouterLink } from 'vue-router'
</script>

<template>
  <section class="auth-page" aria-labelledby="not-found-title">
    <div class="auth-heading">
      <h1 id="not-found-title">Halaman tidak ditemukan</h1>
      <p>Alamat ini tidak tersedia. Kembali ke katalog untuk melanjutkan.</p>
    </div>
    <div class="form-card">
      <RouterLink class="button button-primary button-block" to="/">
        Buka katalog
      </RouterLink>
    </div>
  </section>
</template>

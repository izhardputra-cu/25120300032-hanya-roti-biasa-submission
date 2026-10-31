<script setup>
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { ApiError, apiRequest } from '../api'
import { logout, session, setUser } from '../session'

const router = useRouter()
const loading = ref(true)
const error = ref('')
const loggingOut = ref(false)
const logoutError = ref('')

const roleLabel = computed(() => (session.user?.role === 'seller' ? 'Penjual' : 'Pembeli'))

async function loadAccount() {
  loading.value = true
  error.value = ''
  try {
    const user = await apiRequest('/api/me')
    setUser(user)
  } catch (caught) {
    if (caught instanceof ApiError && caught.status === 401) {
      setUser(null)
      await router.replace({ name: 'login', query: { expired: '1' } })
      return
    }
    error.value =
      caught instanceof ApiError ? caught.message : 'Data akun tidak dapat dimuat.'
  } finally {
    loading.value = false
  }
}

async function signOut() {
  if (loggingOut.value) {
    return
  }
  loggingOut.value = true
  logoutError.value = ''
  try {
    await logout()
    await router.push({ name: 'login', query: { keluar: '1' } })
  } catch (caught) {
    logoutError.value =
      caught instanceof ApiError ? caught.message : 'Keluar dari akun gagal. Coba lagi.'
  } finally {
    loggingOut.value = false
  }
}

onMounted(loadAccount)
</script>

<template>
  <section class="auth-page" aria-labelledby="account-title">
    <div class="auth-heading">
      <h1 id="account-title">Akun Anda</h1>
      <p>Data akun dan peran di bawah ini dibaca dari server, bukan dari pilihan di browser.</p>
    </div>

    <div v-if="loading" class="form-card state-panel" role="status" aria-busy="true">
      <p>Memuat data akun...</p>
    </div>

    <div v-else-if="error" class="alert alert-error" role="alert">
      <p>{{ error }}</p>
      <button class="button button-secondary" type="button" @click="loadAccount">
        Coba lagi
      </button>
    </div>

    <div v-else-if="session.user" class="form-card">
      <dl class="account-details">
        <div>
          <dt>Nama</dt>
          <dd>{{ session.user.name }}</dd>
        </div>
        <div>
          <dt>Email</dt>
          <dd>{{ session.user.email }}</dd>
        </div>
        <div>
          <dt>Peran</dt>
          <dd>{{ roleLabel }}</dd>
        </div>
      </dl>

      <p v-if="logoutError" class="alert alert-error" role="alert">{{ logoutError }}</p>

      <div class="actions">
        <RouterLink
          v-if="session.user.role === 'buyer'"
          class="button button-secondary"
          to="/pesanan"
        >
          Pesanan saya
        </RouterLink>
        <RouterLink
          v-if="session.user.role === 'buyer'"
          class="button button-secondary"
          to="/keranjang"
        >
          Keranjang
        </RouterLink>
        <RouterLink v-if="session.user.role === 'seller'" class="button button-secondary" to="/penjual">
          Buka ruang penjual
        </RouterLink>
        <button class="button button-primary" type="button" :disabled="loggingOut" @click="signOut">
          {{ loggingOut ? 'Keluar...' : 'Keluar' }}
        </button>
      </div>
    </div>
  </section>
</template>

<script setup>
import { nextTick, onMounted, reactive, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { ApiError } from '../api'
import { safeRedirect } from '../navigation'
import { login } from '../session'

const route = useRoute()
const router = useRouter()
const form = reactive({ email: '', password: '' })
const errors = reactive({})
const formError = ref('')
const notice = ref('')
const submitting = ref(false)

onMounted(() => {
  if (route.query.expired) {
    notice.value = 'Sesi Anda sudah berakhir. Silakan masuk lagi.'
  } else if (route.query.keluar) {
    notice.value = 'Anda sudah keluar dari akun ini.'
  } else if (route.query.masuk) {
    notice.value = 'Masuk untuk melanjutkan. Isi keranjang tetap tersimpan.'
  }
})

function clearField(field) {
  delete errors[field]
  formError.value = ''
}

function validate() {
  const email = form.email.trim()
  if (!email) {
    errors.email = 'Masukkan email.'
  } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    errors.email = 'Masukkan alamat email yang valid.'
  }
  if (!form.password) {
    errors.password = 'Masukkan password.'
  }
  return Object.keys(errors).length === 0
}

async function focusFirstError() {
  await nextTick()
  const invalid = document.querySelector('[aria-invalid="true"]')
  if (invalid instanceof HTMLElement) {
    invalid.focus()
  }
}

async function submit() {
  if (submitting.value) {
    return
  }
  formError.value = ''
  for (const key of Object.keys(errors)) {
    delete errors[key]
  }
  if (!validate()) {
    await focusFirstError()
    return
  }

  submitting.value = true
  try {
    const data = await login({
      email: form.email.trim().toLowerCase(),
      password: form.password,
    })
    const destination = safeRedirect(route.query.redirect)
    await router.push(
      destination || (data.user.role === 'seller' ? '/penjual' : '/akun'),
    )
  } catch (error) {
    if (error instanceof ApiError) {
      Object.assign(errors, error.fields)
      formError.value =
        error.status === 401 ? 'Email atau password salah.' : error.message
    } else {
      formError.value = 'Terjadi kesalahan. Coba lagi.'
    }
    await focusFirstError()
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <section class="auth-page" aria-labelledby="login-title">
    <div class="auth-heading">
      <h1 id="login-title">Masuk ke akun</h1>
      <p>Gunakan akun pembeli atau penjual yang sudah terdaftar. Peran akun dibaca dari server.</p>
    </div>

    <p v-if="notice" class="alert alert-info" role="status">{{ notice }}</p>
    <p v-if="formError" class="alert alert-error" role="alert">{{ formError }}</p>

    <form class="form-card" novalidate :aria-busy="submitting" @submit.prevent="submit">
      <div class="field">
        <label for="login-email">Email</label>
        <input
          id="login-email"
          v-model="form.email"
          type="email"
          name="email"
          autocomplete="username"
          inputmode="email"
          :aria-invalid="Boolean(errors.email)"
          :aria-describedby="errors.email ? 'login-email-error' : undefined"
          @input="clearField('email')"
        />
        <p v-if="errors.email" id="login-email-error" class="field-error">
          {{ errors.email }}
        </p>
      </div>

      <div class="field">
        <label for="login-password">Password</label>
        <input
          id="login-password"
          v-model="form.password"
          type="password"
          name="password"
          autocomplete="current-password"
          :aria-invalid="Boolean(errors.password)"
          :aria-describedby="errors.password ? 'login-password-error' : undefined"
          @input="clearField('password')"
        />
        <p v-if="errors.password" id="login-password-error" class="field-error">
          {{ errors.password }}
        </p>
      </div>

      <button class="button button-primary button-block" type="submit" :disabled="submitting">
        {{ submitting ? 'Memproses...' : 'Masuk' }}
      </button>

      <p class="form-switch">
        Belum punya akun?
        <RouterLink to="/daftar">Daftar sebagai pembeli</RouterLink>
      </p>
    </form>
  </section>
</template>

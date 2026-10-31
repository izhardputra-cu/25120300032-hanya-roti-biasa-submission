<script setup>
import { computed, nextTick, reactive, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { ApiError } from '../api'
import { register } from '../session'

const route = useRoute()
const loginTarget = computed(() => {
  const target = { path: '/masuk' }
  if (typeof route.query.redirect === 'string') {
    target.query = { redirect: route.query.redirect }
  }
  return target
})

const form = reactive({ name: '', email: '', password: '' })
const errors = reactive({})
const formError = ref('')
const submitting = ref(false)
const createdUser = ref(null)

function clearField(field) {
  delete errors[field]
  formError.value = ''
}

function validate() {
  const name = form.name.trim()
  if (name.length < 2 || name.length > 100) {
    errors.name = 'Nama harus 2 sampai 100 karakter.'
  }
  const email = form.email.trim()
  if (!email) {
    errors.email = 'Masukkan email.'
  } else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    errors.email = 'Masukkan alamat email yang valid.'
  }
  if (form.password.length < 12) {
    errors.password = 'Password minimal 12 karakter.'
  } else if (form.password.length > 128) {
    errors.password = 'Password maksimal 128 karakter.'
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
    const result = await register({
      name: form.name.trim(),
      email: form.email.trim().toLowerCase(),
      password: form.password,
    })
    createdUser.value = result.user
  } catch (error) {
    if (error instanceof ApiError) {
      Object.assign(errors, error.fields)
      formError.value = error.message
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
  <section class="auth-page" aria-labelledby="register-title">
    <div class="auth-heading">
      <h1 id="register-title">Buat akun pembeli</h1>
      <p>
        Registrasi publik hanya membuat akun pembeli. Akun penjual disiapkan terpisah dan tidak
        dapat dipilih dari formulir ini.
      </p>
    </div>

    <div v-if="createdUser" class="form-card" role="status">
      <p class="alert alert-success">
        Akun pembeli berhasil dibuat untuk {{ createdUser.name }}. Akun tidak masuk otomatis.
      </p>
      <p class="form-switch">
        <RouterLink :to="loginTarget">Masuk ke akun</RouterLink>
      </p>
    </div>

    <form v-else class="form-card" novalidate :aria-busy="submitting" @submit.prevent="submit">
      <p v-if="formError" class="alert alert-error" role="alert">{{ formError }}</p>

      <div class="field">
        <label for="register-name">Nama</label>
        <input
          id="register-name"
          v-model="form.name"
          type="text"
          name="name"
          autocomplete="name"
          :aria-invalid="Boolean(errors.name)"
          :aria-describedby="errors.name ? 'register-name-error' : undefined"
          @input="clearField('name')"
        />
        <p v-if="errors.name" id="register-name-error" class="field-error">
          {{ errors.name }}
        </p>
      </div>

      <div class="field">
        <label for="register-email">Email</label>
        <input
          id="register-email"
          v-model="form.email"
          type="email"
          name="email"
          autocomplete="email"
          inputmode="email"
          :aria-invalid="Boolean(errors.email)"
          :aria-describedby="errors.email ? 'register-email-error' : undefined"
          @input="clearField('email')"
        />
        <p v-if="errors.email" id="register-email-error" class="field-error">
          {{ errors.email }}
        </p>
      </div>

      <div class="field">
        <label for="register-password">Password</label>
        <input
          id="register-password"
          v-model="form.password"
          type="password"
          name="password"
          autocomplete="new-password"
          :aria-describedby="
            errors.password
              ? 'register-password-error register-password-help'
              : 'register-password-help'
          "
          :aria-invalid="Boolean(errors.password)"
          @input="clearField('password')"
        />
        <p id="register-password-help" class="field-help">Minimal 12 karakter.</p>
        <p v-if="errors.password" id="register-password-error" class="field-error">
          {{ errors.password }}
        </p>
      </div>

      <button class="button button-primary button-block" type="submit" :disabled="submitting">
        {{ submitting ? 'Membuat akun...' : 'Buat akun pembeli' }}
      </button>

      <p class="form-switch">
        Sudah punya akun?
        <RouterLink :to="loginTarget">Masuk</RouterLink>
      </p>
    </form>
  </section>
</template>

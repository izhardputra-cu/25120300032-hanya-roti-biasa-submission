<script setup>
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { ApiError, apiRequest } from '../api'
import { setUser } from '../session'

const router = useRouter()

const loading = ref(true)
const denied = ref(false)
const error = ref('')
const profile = ref(null)
const products = ref([])
const notice = ref('')
const actionError = ref('')
const saving = ref(false)
const includeArchived = ref(false)
const editingId = ref(null)
const confirmingId = ref(null)
const formError = ref('')
const fieldErrors = reactive({})
const statusRef = ref(null)
const nameInput = ref(null)

const form = reactive({ name: '', selling_unit: '', price: '', description: '' })

// Archived rows stay in the response for the seller, but the management list
// hides them until the seller explicitly asks for archive history.
const visibleProducts = computed(() =>
  includeArchived.value
    ? products.value
    : products.value.filter((product) => !product.archived),
)

const rupiah = new Intl.NumberFormat('id-ID', {
  style: 'currency',
  currency: 'IDR',
  maximumFractionDigits: 0,
})

function formatPrice(value) {
  return rupiah.format(value)
}

function clearField(field) {
  delete fieldErrors[field]
  formError.value = ''
}

function validate() {
  const name = form.name.trim()
  if (name.length < 2 || name.length > 80) {
    fieldErrors.name = 'Nama harus 2 sampai 80 karakter.'
  }
  const unit = form.selling_unit.trim()
  if (unit.length < 2 || unit.length > 40) {
    fieldErrors.selling_unit = 'Unit jual harus 2 sampai 40 karakter.'
  }
  const price = Number(form.price)
  if (!Number.isInteger(price) || form.price === '' || price < 1000 || price > 1000000) {
    fieldErrors.price_rupiah = 'Harga harus bilangan bulat Rp1.000 sampai Rp1.000.000.'
  }
  if (form.description.trim().length > 400) {
    fieldErrors.description = 'Deskripsi maksimal 400 karakter.'
  }
  return Object.keys(fieldErrors).length === 0
}

async function focusFirstError() {
  await nextTick()
  const invalid = document.querySelector('[aria-invalid="true"]')
  if (invalid instanceof HTMLElement) {
    invalid.focus()
  }
}

async function focusStatus() {
  await nextTick()
  statusRef.value?.focus()
}

async function loadPage() {
  loading.value = true
  denied.value = false
  error.value = ''
  try {
    profile.value = await apiRequest('/api/seller/profile')
    setUser(profile.value)
    await loadProducts()
  } catch (caught) {
    if (caught instanceof ApiError && caught.status === 401) {
      setUser(null)
      await router.replace({ name: 'login', query: { expired: '1' } })
      return
    }
    if (caught instanceof ApiError && caught.status === 403) {
      denied.value = true
      return
    }
    error.value =
      caught instanceof ApiError ? caught.message : 'Data katalog tidak dapat dimuat.'
  } finally {
    loading.value = false
  }
}

async function loadProducts() {
  const data = await apiRequest('/api/seller/products')
  products.value = data.items
}

function resetForm() {
  editingId.value = null
  form.name = ''
  form.selling_unit = ''
  form.price = ''
  form.description = ''
  formError.value = ''
  for (const key of Object.keys(fieldErrors)) {
    delete fieldErrors[key]
  }
}

async function startEdit(product) {
  editingId.value = product.id
  confirmingId.value = null
  notice.value = ''
  actionError.value = ''
  formError.value = ''
  form.name = product.name
  form.selling_unit = product.selling_unit
  form.price = String(product.price_rupiah)
  form.description = product.description
  await nextTick()
  nameInput.value?.focus()
}

async function submit() {
  if (saving.value) {
    return
  }
  formError.value = ''
  actionError.value = ''
  notice.value = ''
  for (const key of Object.keys(fieldErrors)) {
    delete fieldErrors[key]
  }
  if (!validate()) {
    await focusFirstError()
    return
  }

  const payload = {
    name: form.name.trim(),
    selling_unit: form.selling_unit.trim(),
    price_rupiah: Number(form.price),
    description: form.description.trim(),
  }
  saving.value = true
  try {
    if (editingId.value === null) {
      await apiRequest('/api/seller/products', { method: 'POST', body: payload })
      notice.value = 'Produk baru ditambahkan ke katalog.'
    } else {
      await apiRequest(`/api/seller/products/${editingId.value}`, {
        method: 'PATCH',
        body: payload,
      })
      notice.value = 'Perubahan produk disimpan.'
    }
    resetForm()
    await loadProducts()
    await focusStatus()
  } catch (caught) {
    if (caught instanceof ApiError) {
      Object.assign(fieldErrors, caught.fields)
      formError.value = caught.message
    } else {
      formError.value = 'Perubahan tidak dapat disimpan. Coba lagi.'
    }
    await focusFirstError()
  } finally {
    saving.value = false
  }
}

async function setArchived(product, archived) {
  if (saving.value) {
    return
  }
  saving.value = true
  actionError.value = ''
  notice.value = ''
  try {
    await apiRequest(`/api/seller/products/${product.id}/${archived ? 'archive' : 'restore'}`, {
      method: 'POST',
    })
    notice.value = archived
      ? `"${product.name}" diarsipkan dan tidak tampil di katalog publik. Penawaran jadwal yang sudah dibuat tetap ada.`
      : `"${product.name}" kembali tampil di katalog publik.`
    if (editingId.value === product.id) {
      resetForm()
    }
    await loadProducts()
    await focusStatus()
  } catch (caught) {
    actionError.value =
      caught instanceof ApiError ? caught.message : 'Status produk tidak dapat diubah.'
  } finally {
    saving.value = false
  }
}

async function cancelDelete(event) {
  const trigger = event.currentTarget.closest('.seller-product')
    ?.querySelector('.seller-product-actions .button-danger')
  confirmingId.value = null
  await nextTick()
  trigger?.focus()
}

async function removeProduct(product) {
  if (saving.value) {
    return
  }
  saving.value = true
  actionError.value = ''
  notice.value = ''
  try {
    await apiRequest(`/api/seller/products/${product.id}`, { method: 'DELETE' })
    confirmingId.value = null
    if (editingId.value === product.id) {
      resetForm()
    }
    notice.value = `"${product.name}" dihapus permanen dari katalog.`
    await loadProducts()
    await focusStatus()
  } catch (caught) {
    actionError.value =
      caught instanceof ApiError ? caught.message : 'Produk tidak dapat dihapus.'
  } finally {
    saving.value = false
  }
}

onMounted(loadPage)
</script>

<template>
  <section class="seller-page" aria-labelledby="seller-title">
    <div class="seller-heading">
      <h1 id="seller-title">Kelola katalog</h1>
      <p>
        Tambah, ubah, arsipkan, atau hapus produk. Hanya akun penjual yang dapat
        mengubah katalog.
      </p>
      <p class="state-note">
        Arsip hanya menyembunyikan produk dari katalog publik. Penawaran jadwal dan pesanan
        yang sudah dibuat tetap ada; arsip bukan pembatalan pesanan.
      </p>
      <p class="seller-heading-link">
        <RouterLink to="/penjual/jadwal">Kelola jadwal pre-order</RouterLink>
        <span aria-hidden="true"> &middot; </span>
        <RouterLink to="/penjual/pesanan">Pesanan masuk</RouterLink>
        <span aria-hidden="true"> &middot; </span>
        <RouterLink to="/penjual/rekap">Rekap produksi</RouterLink>
      </p>
    </div>

    <div v-if="loading" class="form-card state-panel" role="status" aria-busy="true">
      <p>Memeriksa akses penjual...</p>
    </div>

    <div v-else-if="denied" class="alert alert-warning" role="alert">
      <h2>Akses ditolak</h2>
      <p>Akun ini terdaftar sebagai pembeli. Halaman penjual hanya tersedia untuk akun penjual.</p>
      <RouterLink class="button button-secondary" to="/akun">Kembali ke akun</RouterLink>
    </div>

    <div v-else-if="error" class="alert alert-error" role="alert">
      <p>{{ error }}</p>
      <button class="button button-secondary" type="button" @click="loadPage">
        Coba lagi
      </button>
    </div>

    <template v-else>
      <p class="seller-identity">
        Masuk sebagai penjual <strong>{{ profile?.email }}</strong>.
      </p>

      <p
        v-if="notice"
        ref="statusRef"
        class="alert alert-success"
        role="status"
        tabindex="-1"
      >
        {{ notice }}
      </p>
      <p v-if="actionError" class="alert alert-error" role="alert">{{ actionError }}</p>

      <form class="form-card seller-form" novalidate :aria-busy="saving" @submit.prevent="submit">
        <h2>{{ editingId === null ? 'Tambah produk' : 'Ubah produk' }}</h2>
        <p v-if="formError" class="alert alert-error" role="alert">{{ formError }}</p>

        <div class="field">
          <label for="product-name">Nama produk</label>
          <input
            id="product-name"
            ref="nameInput"
            v-model="form.name"
            type="text"
            name="name"
            maxlength="80"
            :aria-invalid="Boolean(fieldErrors.name)"
            :aria-describedby="fieldErrors.name ? 'product-name-error' : 'product-name-help'"
            @input="clearField('name')"
          />
          <p id="product-name-help" class="field-help">2 sampai 80 karakter.</p>
          <p v-if="fieldErrors.name" id="product-name-error" class="field-error">
            {{ fieldErrors.name }}
          </p>
        </div>

        <div class="field">
          <label for="product-unit">Unit jual</label>
          <input
            id="product-unit"
            v-model="form.selling_unit"
            type="text"
            name="selling_unit"
            maxlength="40"
            :aria-invalid="Boolean(fieldErrors.selling_unit)"
            :aria-describedby="
              fieldErrors.selling_unit ? 'product-unit-error' : 'product-unit-help'
            "
            @input="clearField('selling_unit')"
          />
          <p id="product-unit-help" class="field-help">
            Contoh: 1 loaf 500 gram. 2 sampai 40 karakter.
          </p>
          <p v-if="fieldErrors.selling_unit" id="product-unit-error" class="field-error">
            {{ fieldErrors.selling_unit }}
          </p>
        </div>

        <div class="field">
          <label for="product-price">Harga (Rupiah)</label>
          <input
            id="product-price"
            v-model="form.price"
            type="number"
            name="price_rupiah"
            inputmode="numeric"
            min="1000"
            max="1000000"
            step="1"
            :aria-invalid="Boolean(fieldErrors.price_rupiah)"
            :aria-describedby="
              fieldErrors.price_rupiah ? 'product-price-error' : 'product-price-help'
            "
            @input="clearField('price_rupiah')"
          />
          <p id="product-price-help" class="field-help">
            Bilangan bulat Rp1.000 sampai Rp1.000.000, tanpa titik.
          </p>
          <p v-if="fieldErrors.price_rupiah" id="product-price-error" class="field-error">
            {{ fieldErrors.price_rupiah }}
          </p>
        </div>

        <div class="field">
          <label for="product-description">Deskripsi (opsional)</label>
          <textarea
            id="product-description"
            v-model="form.description"
            name="description"
            rows="3"
            maxlength="400"
            :aria-invalid="Boolean(fieldErrors.description)"
            :aria-describedby="
              fieldErrors.description ? 'product-description-error' : 'product-description-help'
            "
            @input="clearField('description')"
          ></textarea>
          <p id="product-description-help" class="field-help">
            Maksimal 400 karakter. Teks ditampilkan sebagai teks biasa.
          </p>
          <p
            v-if="fieldErrors.description"
            id="product-description-error"
            class="field-error"
          >
            {{ fieldErrors.description }}
          </p>
        </div>

        <div class="actions">
          <button class="button button-primary" type="submit" :disabled="saving">
            {{
              saving
                ? 'Menyimpan...'
                : editingId === null
                  ? 'Tambah produk'
                  : 'Simpan perubahan'
            }}
          </button>
          <button
            v-if="editingId !== null"
            class="button button-secondary"
            type="button"
            :disabled="saving"
            @click="resetForm"
          >
            Batal ubah
          </button>
        </div>
      </form>

      <section class="seller-list" aria-labelledby="seller-list-title">
        <div class="catalog-section-head">
          <h2 id="seller-list-title">Daftar produk</h2>
          <p class="catalog-count">{{ visibleProducts.length }} produk</p>
        </div>

        <p class="list-filter">
          <label class="picker-check">
            <input v-model="includeArchived" type="checkbox" />
            <span>Sertakan arsip</span>
          </label>
        </p>
        <p class="field-help">
          Produk yang diarsipkan disembunyikan dari katalog publik dan daftar ini
          secara bawaan. Penawaran jadwal dan riwayat pesanannya tetap ada.
        </p>

        <div v-if="visibleProducts.length === 0" class="state-panel">
          <p>{{ includeArchived ? 'Belum ada produk.' : 'Belum ada produk aktif.' }}</p>
          <p class="state-note">
            <template v-if="includeArchived">
              Tambahkan produk pertama lewat formulir di atas.
            </template>
            <template v-else>
              Tambahkan produk lewat formulir di atas, atau centang “Sertakan arsip”
              untuk melihat dan memulihkan produk yang diarsipkan.
            </template>
          </p>
        </div>

        <ul v-else class="seller-products">
          <li v-for="product in visibleProducts" :key="product.id" class="seller-product">
            <div class="seller-product-info">
              <div class="seller-product-head">
                <h3>{{ product.name }}</h3>
                <span v-if="product.archived" class="status-tag">Diarsipkan</span>
              </div>
              <p class="product-price">{{ formatPrice(product.price_rupiah) }}</p>
              <p class="product-unit">{{ product.selling_unit }}</p>
              <p v-if="product.description" class="product-description">
                {{ product.description }}
              </p>
            </div>

            <div class="seller-product-actions">
              <button
                class="button button-secondary"
                type="button"
                :disabled="saving"
                @click="startEdit(product)"
              >
                Ubah
              </button>
              <button
                class="button button-secondary"
                type="button"
                :disabled="saving"
                @click="setArchived(product, !product.archived)"
              >
                {{ product.archived ? 'Pulihkan' : 'Arsipkan' }}
              </button>
              <button
                class="button button-danger"
                type="button"
                :disabled="saving"
                @click="confirmingId = confirmingId === product.id ? null : product.id"
              >
                Hapus
              </button>
            </div>

            <div
              v-if="confirmingId === product.id"
              class="confirm-panel"
              role="group"
              :aria-label="`Konfirmasi hapus ${product.name}`"
            >
              <p>Hapus permanen? Tindakan ini tidak dapat dibatalkan.</p>
              <div class="actions">
                <button
                  class="button button-danger"
                  type="button"
                  :disabled="saving"
                  @click="removeProduct(product)"
                >
                  Ya, hapus permanen
                </button>
                <button
                  class="button button-secondary"
                  type="button"
                  :disabled="saving"
                  @click="cancelDelete"
                >
                  Batal
                </button>
              </div>
            </div>
          </li>
        </ul>
      </section>
    </template>
  </section>
</template>

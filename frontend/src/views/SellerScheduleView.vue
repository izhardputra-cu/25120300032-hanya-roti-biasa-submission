<script setup>
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { ApiError, apiRequest } from '../api'
import { formatWib, fromWibInputValue, toWibInputValue, wibInputsInOrder } from '../datetime'
import { formatRupiah } from '../money'
import { setUser } from '../session'

const router = useRouter()

const loading = ref(true)
const denied = ref(false)
const error = ref('')
const profile = ref(null)
const products = ref([])
const schedules = ref([])
const notice = ref('')
const actionError = ref('')
const pending = ref('')
const busy = computed(() => pending.value !== '')
const statusRef = ref(null)
const actionErrorRef = ref(null)
const scheduleFormRef = ref(null)
const showCreateForm = ref(true)
let createFormInitialised = false

const form = reactive({ pickup_at: '', order_cutoff_at: '' })
const selections = reactive({})
const quotas = reactive({})
const formError = ref('')
const fieldErrors = reactive({})

const editingId = ref(null)
const edit = reactive({ pickup_at: '', order_cutoff_at: '' })
const editErrors = reactive({})

const addingFor = ref(null)
const addDraft = reactive({ product_id: '', quota: '1' })
const addErrors = reactive({})

const quotaDrafts = reactive({})
const quotaErrors = reactive({})
const priceDrafts = reactive({})
const priceErrors = reactive({})
const offerSaveErrors = reactive({})

const confirmingScheduleId = ref(null)
const confirmingOfferId = ref(null)
const confirmingArchiveId = ref(null)
const includeArchived = ref(false)

const activeProducts = computed(() => products.value.filter((product) => !product.archived))

function availableProducts(schedule) {
  const offered = new Set(schedule.offers.map((offer) => offer.product_id))
  return activeProducts.value.filter((product) => !offered.has(product.id))
}

function clearErrors(target) {
  for (const key of Object.keys(target)) {
    delete target[key]
  }
}

function clearError(target, key) {
  delete target[key]
}

function confirmedOffer(schedule) {
  return schedule.offers.find((item) => item.id === confirmingOfferId.value)
}

function clearAllFormErrors() {
  formError.value = ''
  clearErrors(fieldErrors)
}

function initializeProductDrafts() {
  for (const product of activeProducts.value) {
    if (selections[product.id] === undefined) {
      selections[product.id] = false
    }
    if (quotas[product.id] === undefined) {
      quotas[product.id] = '1'
    }
  }
}

async function focusCreateFormInvalid() {
  await nextTick()
  const form = scheduleFormRef.value
  if (!form) {
    return
  }
  const invalid = form.querySelector('[aria-invalid="true"]')
  if (invalid instanceof HTMLElement) {
    invalid.focus()
    return
  }
  const firstCheckbox = form.querySelector('.product-picker input[type="checkbox"]')
  if (firstCheckbox instanceof HTMLElement) {
    firstCheckbox.focus()
  }
}

async function focusOfferField(offerId, field) {
  await nextTick()
  document.getElementById(`offer-${field}-${offerId}`)?.focus()
}

async function openCreateForm() {
  showCreateForm.value = true
  await nextTick()
  scheduleFormRef.value?.querySelector('input')?.focus()
}

async function closeCreateForm() {
  showCreateForm.value = false
  resetForm()
  await nextTick()
  document.querySelector('[data-open-create]')?.focus()
}

async function focusStatus() {
  await nextTick()
  statusRef.value?.focus()
}

async function focusActionError() {
  await nextTick()
  actionErrorRef.value?.focus()
}

function initialiseOfferDrafts(items) {
  for (const schedule of items) {
    for (const offer of schedule.offers) {
      if (quotaDrafts[offer.id] === undefined) {
        quotaDrafts[offer.id] = String(offer.quota)
      }
      if (priceDrafts[offer.id] === undefined) {
        priceDrafts[offer.id] = String(offer.price_rupiah)
      }
    }
  }
}

async function loadSchedules() {
  const query = includeArchived.value ? '?include_archived=true' : ''
  const data = await apiRequest(`/api/seller/schedules${query}`)
  schedules.value = data.items
  initialiseOfferDrafts(data.items)
}

async function toggleArchived() {
  notice.value = ''
  actionError.value = ''
  confirmingArchiveId.value = null
  try {
    await loadSchedules()
  } catch (caught) {
    actionError.value =
      caught instanceof ApiError ? caught.message : 'Daftar jadwal tidak dapat dimuat.'
    await focusActionError()
  }
}

async function loadPage() {
  loading.value = true
  denied.value = false
  error.value = ''
  try {
    profile.value = await apiRequest('/api/seller/profile')
    setUser(profile.value)
    const [productData, scheduleData] = await Promise.all([
      apiRequest('/api/seller/products'),
      apiRequest('/api/seller/schedules'),
    ])
    products.value = productData.items
    schedules.value = scheduleData.items
    initializeProductDrafts()
    initialiseOfferDrafts(schedules.value)
    if (!createFormInitialised) {
      // Keep the worklist first; the create form is a disclosure once it exists.
      showCreateForm.value = schedules.value.length === 0
      createFormInitialised = true
    }
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
      caught instanceof ApiError ? caught.message : 'Jadwal tidak dapat dimuat.'
  } finally {
    loading.value = false
  }
}

function resetForm() {
  form.pickup_at = ''
  form.order_cutoff_at = ''
  for (const product of activeProducts.value) {
    selections[product.id] = false
    quotas[product.id] = '1'
  }
  clearAllFormErrors()
}

function validateMainForm() {
  clearAllFormErrors()
  const pickup = fromWibInputValue(form.pickup_at)
  const cutoff = fromWibInputValue(form.order_cutoff_at)
  if (pickup === null) {
    fieldErrors.pickup_at = 'Isi tanggal dan waktu pengambilan dalam WIB.'
  }
  if (cutoff === null) {
    fieldErrors.order_cutoff_at = 'Isi batas PO dalam WIB.'
  }
  if (pickup !== null && cutoff !== null && !wibInputsInOrder(form.pickup_at, form.order_cutoff_at)) {
    fieldErrors.order_cutoff_at = 'Batas PO harus sebelum waktu pengambilan.'
  }
  const chosen = activeProducts.value.filter((product) => selections[product.id])
  if (chosen.length === 0) {
    fieldErrors.offers = 'Pilih minimal satu produk dari katalog.'
  }
  for (const product of chosen) {
    const value = quotas[product.id]
    const quota = Number(value)
    if (value === '' || !Number.isInteger(quota) || quota < 1 || quota > 999) {
      fieldErrors[`quota_${product.id}`] = 'Kuota harus bilangan bulat 1 sampai 999.'
    }
  }
  return Object.keys(fieldErrors).length === 0
}

function mapScheduleCreateErrors(caught, chosen) {
  if (!(caught instanceof ApiError)) {
    return
  }
  Object.assign(fieldErrors, caught.fields)
  for (const location of caught.locations) {
    const match = /^offers\.(\d+)\.(\w+)$/.exec(location.path)
    const product = match ? chosen[Number(match[1])] : null
    if (product && match && match[2] === 'quota') {
      delete fieldErrors.quota
      fieldErrors[`quota_${product.id}`] = location.message
    } else if (match) {
      delete fieldErrors.quota
      fieldErrors.offers = location.message
    } else if (location.field === 'quota') {
      delete fieldErrors.quota
      if (chosen.length === 1) {
        fieldErrors[`quota_${chosen[0].id}`] = location.message
      } else {
        fieldErrors.offers = location.message
      }
    }
  }
}

async function submitSchedule() {
  if (busy.value) {
    return
  }
  notice.value = ''
  actionError.value = ''
  if (!validateMainForm()) {
    await focusCreateFormInvalid()
    return
  }
  const chosen = activeProducts.value.filter((product) => selections[product.id])
  const payload = {
    pickup_at: fromWibInputValue(form.pickup_at),
    order_cutoff_at: fromWibInputValue(form.order_cutoff_at),
    offers: chosen.map((product) => ({
      product_id: product.id,
      quota: Number(quotas[product.id]),
    })),
  }
  pending.value = 'create'
  try {
    await apiRequest('/api/seller/schedules', { method: 'POST', body: payload })
    notice.value = 'Jadwal pre-order baru dibuka.'
    resetForm()
    showCreateForm.value = false
    await loadSchedules()
    await focusStatus()
  } catch (caught) {
    if (caught instanceof ApiError) {
      mapScheduleCreateErrors(caught, chosen)
      formError.value = caught.message
    } else {
      formError.value = 'Jadwal tidak dapat disimpan. Coba lagi.'
    }
    await focusCreateFormInvalid()
  } finally {
    pending.value = ''
  }
}

async function startEditTimes(schedule) {
  editingId.value = schedule.id
  confirmingScheduleId.value = null
  confirmOffersReset()
  notice.value = ''
  actionError.value = ''
  clearErrors(editErrors)
  edit.pickup_at = toWibInputValue(schedule.pickup_at)
  edit.order_cutoff_at = toWibInputValue(schedule.order_cutoff_at)
  await nextTick()
  document.getElementById(`edit-pickup-${schedule.id}`)?.focus()
}

async function cancelEditTimes(event) {
  const trigger = event.currentTarget
    .closest('.schedule-panel')
    ?.querySelector('[data-edit-times]')
  editingId.value = null
  await nextTick()
  trigger?.focus()
}

function validateEditTimes() {
  clearErrors(editErrors)
  if (fromWibInputValue(edit.pickup_at) === null) {
    editErrors.pickup_at = 'Isi tanggal dan waktu pengambilan dalam WIB.'
  }
  if (fromWibInputValue(edit.order_cutoff_at) === null) {
    editErrors.order_cutoff_at = 'Isi batas PO dalam WIB.'
  }
  if (
    fromWibInputValue(edit.pickup_at) !== null &&
    fromWibInputValue(edit.order_cutoff_at) !== null &&
    !wibInputsInOrder(edit.pickup_at, edit.order_cutoff_at)
  ) {
    editErrors.order_cutoff_at = 'Batas PO harus sebelum waktu pengambilan.'
  }
  return Object.keys(editErrors).length === 0
}

async function saveEditTimes(schedule) {
  if (busy.value) {
    return
  }
  notice.value = ''
  actionError.value = ''
  if (!validateEditTimes()) {
    await nextTick()
    const target = editErrors.pickup_at
      ? document.getElementById(`edit-pickup-${schedule.id}`)
      : document.getElementById(`edit-cutoff-${schedule.id}`)
    target?.focus()
    return
  }
  pending.value = `edit:${schedule.id}`
  try {
    await apiRequest(`/api/seller/schedules/${schedule.id}`, {
      method: 'PATCH',
      body: {
        pickup_at: fromWibInputValue(edit.pickup_at),
        order_cutoff_at: fromWibInputValue(edit.order_cutoff_at),
      },
    })
    notice.value = 'Waktu jadwal disimpan.'
    editingId.value = null
    await loadSchedules()
    await focusStatus()
  } catch (caught) {
    actionError.value =
      caught instanceof ApiError ? caught.message : 'Waktu jadwal tidak dapat disimpan.'
  } finally {
    pending.value = ''
  }
}

function confirmOffersReset() {
  confirmingOfferId.value = null
}

function confirmDeleteSchedule(schedule) {
  confirmingScheduleId.value = schedule.id
  confirmingOfferId.value = null
  notice.value = ''
  actionError.value = ''
}

async function cancelDeleteSchedule(event) {
  const trigger = event.currentTarget
    .closest('.schedule-panel')
    ?.querySelector('[data-delete-schedule]')
  confirmingScheduleId.value = null
  await nextTick()
  trigger?.focus()
}

async function removeSchedule(schedule) {
  if (busy.value) {
    return
  }
  pending.value = `delete:${schedule.id}`
  notice.value = ''
  actionError.value = ''
  try {
    await apiRequest(`/api/seller/schedules/${schedule.id}`, { method: 'DELETE' })
    confirmingScheduleId.value = null
    if (editingId.value === schedule.id) {
      editingId.value = null
    }
    if (addingFor.value === schedule.id) {
      addingFor.value = null
    }
    notice.value = `Jadwal pengambilan ${formatWib(schedule.pickup_at)} dihapus.`
    await loadSchedules()
    await focusStatus()
  } catch (caught) {
    actionError.value =
      caught instanceof ApiError ? caught.message : 'Jadwal tidak dapat dihapus.'
  } finally {
    pending.value = ''
  }
}

function confirmArchiveSchedule(schedule) {
  confirmingArchiveId.value = schedule.id
  confirmingScheduleId.value = null
  confirmingOfferId.value = null
  notice.value = ''
  actionError.value = ''
}

async function cancelArchiveSchedule(event) {
  const trigger = event.currentTarget
    .closest('.schedule-panel')
    ?.querySelector('[data-archive-schedule]')
  confirmingArchiveId.value = null
  await nextTick()
  trigger?.focus()
}

async function archiveSchedule(schedule) {
  if (busy.value) {
    return
  }
  pending.value = `archive:${schedule.id}`
  notice.value = ''
  actionError.value = ''
  try {
    await apiRequest(`/api/seller/schedules/${schedule.id}/archive`, { method: 'POST' })
    confirmingArchiveId.value = null
    if (editingId.value === schedule.id) {
      editingId.value = null
    }
    if (addingFor.value === schedule.id) {
      addingFor.value = null
    }
    notice.value = `Jadwal pengambilan ${formatWib(schedule.pickup_at)} diarsipkan. Penawaran dan riwayat pesanannya tetap tersimpan.`
    await loadSchedules()
    await focusStatus()
  } catch (caught) {
    actionError.value =
      caught instanceof ApiError ? caught.message : 'Jadwal tidak dapat diarsipkan.'
    await focusActionError()
  } finally {
    pending.value = ''
  }
}

async function restoreSchedule(schedule) {
  if (busy.value) {
    return
  }
  pending.value = `restore:${schedule.id}`
  notice.value = ''
  actionError.value = ''
  try {
    await apiRequest(`/api/seller/schedules/${schedule.id}/restore`, { method: 'POST' })
    notice.value = `Jadwal pengambilan ${formatWib(schedule.pickup_at)} dipulihkan dengan waktu dan penawaran yang sama.`
    await loadSchedules()
    await focusStatus()
  } catch (caught) {
    actionError.value =
      caught instanceof ApiError ? caught.message : 'Jadwal tidak dapat dipulihkan.'
    await focusActionError()
  } finally {
    pending.value = ''
  }
}

async function startAddOffer(schedule) {
  addingFor.value = schedule.id
  confirmingOfferId.value = null
  confirmingScheduleId.value = null
  notice.value = ''
  actionError.value = ''
  clearErrors(addErrors)
  addDraft.product_id = ''
  addDraft.quota = '1'
  await nextTick()
  document.getElementById(`add-offer-product-${schedule.id}`)?.focus()
}

async function cancelAddOffer(event) {
  const trigger = event.currentTarget
    .closest('.schedule-panel')
    ?.querySelector('[data-add-offer]')
  addingFor.value = null
  await nextTick()
  trigger?.focus()
}

async function saveNewOffer(schedule) {
  if (busy.value) {
    return
  }
  clearErrors(addErrors)
  notice.value = ''
  actionError.value = ''
  if (addDraft.product_id === '') {
    addErrors.product_id = 'Pilih produk dari katalog.'
  }
  const quota = Number(addDraft.quota)
  if (addDraft.quota === '' || !Number.isInteger(quota) || quota < 1 || quota > 999) {
    addErrors.quota = 'Kuota harus bilangan bulat 1 sampai 999.'
  }
  if (Object.keys(addErrors).length > 0) {
    await nextTick()
    const target = addErrors.product_id
      ? document.getElementById(`add-offer-product-${schedule.id}`)
      : document.getElementById(`add-offer-quota-${schedule.id}`)
    target?.focus()
    return
  }
  pending.value = `add:${schedule.id}`
  try {
    await apiRequest(`/api/seller/schedules/${schedule.id}/offers`, {
      method: 'POST',
      body: { product_id: Number(addDraft.product_id), quota },
    })
    notice.value = 'Penawaran baru ditambahkan ke jadwal.'
    addingFor.value = null
    await loadSchedules()
    await focusStatus()
  } catch (caught) {
    actionError.value =
      caught instanceof ApiError ? caught.message : 'Penawaran tidak dapat ditambahkan.'
  } finally {
    pending.value = ''
  }
}

async function saveOffer(schedule, offer) {
  if (busy.value) {
    return
  }
  delete quotaErrors[offer.id]
  delete priceErrors[offer.id]
  delete offerSaveErrors[offer.id]
  const quotaValue = quotaDrafts[offer.id]
  const quota = Number(quotaValue)
  if (quotaValue === '' || !Number.isInteger(quota) || quota < 1 || quota > 999) {
    quotaErrors[offer.id] = 'Kuota harus bilangan bulat 1 sampai 999.'
    await focusOfferField(offer.id, 'quota')
    return
  }
  const priceValue = priceDrafts[offer.id]
  const price = Number(priceValue)
  if (priceValue === '' || !Number.isInteger(price) || price < 1000 || price > 1000000) {
    priceErrors[offer.id] = 'Harga harus bilangan bulat Rp1.000 sampai Rp1.000.000.'
    await focusOfferField(offer.id, 'price')
    return
  }
  pending.value = `offer:${offer.id}`
  notice.value = ''
  actionError.value = ''
  try {
    const updated = await apiRequest(
      `/api/seller/schedules/${schedule.id}/offers/${offer.id}`,
      { method: 'PATCH', body: { quota, price_rupiah: price } },
    )
    quotaDrafts[offer.id] = String(updated.quota)
    priceDrafts[offer.id] = String(updated.price_rupiah)
    notice.value = `Penawaran "${offer.product_name}" disimpan.`
    await loadSchedules()
    await focusStatus()
  } catch (caught) {
    if (caught instanceof ApiError) {
      if (caught.fields.quota) {
        quotaErrors[offer.id] = caught.fields.quota
      }
      if (caught.fields.price_rupiah) {
        priceErrors[offer.id] = caught.fields.price_rupiah
      }
      offerSaveErrors[offer.id] = caught.message
    } else {
      offerSaveErrors[offer.id] = 'Penawaran tidak dapat disimpan. Coba lagi.'
    }
    if (quotaErrors[offer.id]) {
      await focusOfferField(offer.id, 'quota')
    } else if (priceErrors[offer.id]) {
      await focusOfferField(offer.id, 'price')
    } else {
      await nextTick()
      document.getElementById(`offer-save-error-${offer.id}`)?.focus()
    }
  } finally {
    pending.value = ''
  }
}

function confirmRemoveOffer(offer) {
  confirmingOfferId.value = offer.id
  confirmingScheduleId.value = null
  notice.value = ''
  actionError.value = ''
}

async function cancelRemoveOffer(event, schedule) {
  const offer = confirmedOffer(schedule)
  const trigger = offer
    ? event.currentTarget
        .closest('.schedule-panel')
        ?.querySelector(`[data-remove-offer-id="${offer.id}"]`)
    : null
  confirmingOfferId.value = null
  await nextTick()
  trigger?.focus()
}

async function removeOffer(schedule, offer) {
  if (busy.value) {
    return
  }
  pending.value = `remove-offer:${offer.id}`
  notice.value = ''
  actionError.value = ''
  try {
    await apiRequest(`/api/seller/schedules/${schedule.id}/offers/${offer.id}`, {
      method: 'DELETE',
    })
    confirmingOfferId.value = null
    notice.value = `Penawaran "${offer.product_name}" dihapus dari jadwal.`
    await loadSchedules()
    await focusStatus()
  } catch (caught) {
    actionError.value =
      caught instanceof ApiError ? caught.message : 'Penawaran tidak dapat dihapus.'
  } finally {
    pending.value = ''
  }
}

onMounted(loadPage)
</script>

<template>
  <section class="seller-page" aria-labelledby="seller-schedule-title">
    <div class="seller-heading">
      <h1 id="seller-schedule-title">Kelola jadwal pre-order</h1>
      <p>
        Buka jadwal panggang, pilih produk yang sudah ada di katalog, lalu tetapkan
        kuota, batas PO, dan waktu pengambilan. Semua waktu diisi dan ditampilkan dalam
        WIB.
      </p>
      <p v-if="!loading && !denied && !error" class="seller-heading-link">
        <RouterLink to="/penjual">Kembali ke kelola katalog</RouterLink>
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
      <p v-if="actionError" ref="actionErrorRef" class="alert alert-error" role="alert" tabindex="-1">
        {{ actionError }}
      </p>

      <div v-if="!showCreateForm" class="create-form-toggle">
        <button
          class="button button-primary"
          type="button"
          data-open-create
          aria-controls="schedule-create-form"
          @click="openCreateForm"
        >
          Buat jadwal baru
        </button>
        <p class="field-help">
          Buka formulir untuk membuat jadwal panggang baru.
        </p>
      </div>

      <form
        v-if="showCreateForm"
        id="schedule-create-form"
        ref="scheduleFormRef"
        class="form-card seller-form"
        novalidate
        :aria-busy="busy"
        @submit.prevent="submitSchedule"
      >
        <div class="create-form-head">
          <h2>Buka jadwal baru</h2>
          <button
            class="button button-secondary"
            type="button"
            :disabled="busy"
            @click="closeCreateForm"
          >
            Tutup formulir
          </button>
        </div>
        <p v-if="formError" class="alert alert-error" role="alert">{{ formError }}</p>

        <div class="field">
          <label for="schedule-pickup">Waktu pengambilan (WIB)</label>
          <input
            id="schedule-pickup"
            v-model="form.pickup_at"
            type="datetime-local"
            name="pickup_at"
            step="60"
            :aria-invalid="Boolean(fieldErrors.pickup_at)"
            :aria-describedby="
              fieldErrors.pickup_at
                ? 'schedule-pickup-help schedule-pickup-error'
                : 'schedule-pickup-help'
            "
            @input="clearAllFormErrors"
          />
          <p id="schedule-pickup-help" class="field-help">
            Gunakan pemilih tanggal dan isi jam dalam WIB (UTC+7).
          </p>
          <p v-if="fieldErrors.pickup_at" id="schedule-pickup-error" class="field-error">
            {{ fieldErrors.pickup_at }}
          </p>
        </div>

        <div class="field">
          <label for="schedule-cutoff">Batas PO bersama (WIB)</label>
          <input
            id="schedule-cutoff"
            v-model="form.order_cutoff_at"
            type="datetime-local"
            name="order_cutoff_at"
            step="60"
            :aria-invalid="Boolean(fieldErrors.order_cutoff_at)"
            :aria-describedby="
              fieldErrors.order_cutoff_at
                ? 'schedule-cutoff-help schedule-cutoff-error'
                : 'schedule-cutoff-help'
            "
            @input="clearAllFormErrors"
          />
          <p id="schedule-cutoff-help" class="field-help">
            Satu batas untuk pemesanan dan pembayaran. Harus lebih awal dari waktu
            pengambilan; tepat pada waktu yang sama ditolak.
          </p>
          <p
            v-if="fieldErrors.order_cutoff_at"
            id="schedule-cutoff-error"
            class="field-error"
          >
            {{ fieldErrors.order_cutoff_at }}
          </p>
        </div>

        <fieldset
          class="product-picker"
          :aria-describedby="fieldErrors.offers ? 'schedule-offers-error' : undefined"
        >
          <legend>Produk yang ditawarkan</legend>
          <p v-if="fieldErrors.offers" id="schedule-offers-error" class="field-error">
            {{ fieldErrors.offers }}
          </p>
          <p v-if="activeProducts.length === 0" class="state-note">
            Belum ada produk aktif.
            <RouterLink to="/penjual">Tambahkan produk di kelola katalog</RouterLink>
            terlebih dahulu.
          </p>
          <ul v-else class="picker-list">
            <li v-for="product in activeProducts" :key="product.id" class="picker-row">
              <label class="picker-check">
                <input v-model="selections[product.id]" type="checkbox" />
                <span>{{ product.name }}</span>
              </label>
              <p class="picker-meta">
                {{ formatRupiah(product.price_rupiah) }} &middot; {{ product.selling_unit }}
              </p>
              <div v-if="selections[product.id]" class="field quota-field">
                <label :for="`quota-${product.id}`">Kuota</label>
                <input
                  :id="`quota-${product.id}`"
                  v-model="quotas[product.id]"
                  :aria-label="`Kuota ${product.name}`"
                  type="number"
                  min="1"
                  max="999"
                  step="1"
                  inputmode="numeric"
                  :aria-invalid="Boolean(fieldErrors[`quota_${product.id}`])"
                  :aria-describedby="
                    fieldErrors[`quota_${product.id}`]
                      ? `quota-${product.id}-help quota-${product.id}-error`
                      : `quota-${product.id}-help`
                  "
                  @input="clearAllFormErrors"
                />
                <p :id="`quota-${product.id}-help`" class="field-help">
                  Bilangan bulat 1 sampai 999 unit.
                </p>
                <p
                  v-if="fieldErrors[`quota_${product.id}`]"
                  :id="`quota-${product.id}-error`"
                  class="field-error"
                >
                  {{ fieldErrors[`quota_${product.id}`] }}
                </p>
              </div>
            </li>
          </ul>
        </fieldset>

        <div class="actions">
          <button
            class="button button-primary"
            type="submit"
            :disabled="busy || activeProducts.length === 0"
          >
            {{ pending === 'create' ? 'Menyimpan jadwal...' : 'Buka jadwal' }}
          </button>
          <button
            class="button button-secondary"
            type="button"
            :disabled="busy"
            @click="closeCreateForm"
          >
            Batal
          </button>
        </div>
      </form>

      <section class="seller-list" aria-labelledby="seller-schedule-list-title">
        <div class="catalog-section-head">
          <h2 id="seller-schedule-list-title">Daftar jadwal</h2>
          <p class="catalog-count">{{ schedules.length }} jadwal</p>
        </div>

        <p class="list-filter">
          <label class="picker-check">
            <input v-model="includeArchived" type="checkbox" @change="toggleArchived" />
            <span>Sertakan arsip</span>
          </label>
        </p>
        <p class="field-help">
          Jadwal yang diarsipkan tidak tampil di toko dan daftar ini secara bawaan.
          Riwayat pesanannya tetap tersimpan.
        </p>

        <div v-if="schedules.length === 0" class="state-panel">
          <p>Tidak ada jadwal pada tampilan ini.</p>
          <p v-if="!includeArchived" class="state-note">
            Centang “Sertakan arsip” untuk melihat jadwal yang sudah diarsipkan.
          </p>
          <p class="state-note">Gunakan “Buat jadwal baru” untuk membuka jadwal berikutnya.</p>
        </div>

        <ul v-else class="schedule-list">
          <li v-for="schedule in schedules" :key="schedule.id" class="schedule-panel">
            <div class="schedule-head">
              <div>
                <h3>Pengambilan {{ formatWib(schedule.pickup_at) }}</h3>
                <p class="schedule-meta">
                  Batas PO {{ formatWib(schedule.order_cutoff_at) }}
                </p>
              </div>
              <span v-if="schedule.archived" class="status-tag">Diarsipkan</span>
              <span
                class="status-tag"
                :class="schedule.orders_open ? 'status-tag-open' : 'status-tag-closed'"
              >
                {{ schedule.orders_open ? 'Dibuka' : 'Ditutup' }}
              </span>
            </div>

            <div v-if="!schedule.archived" class="schedule-actions">
              <button
                class="button button-secondary"
                type="button"
                data-edit-times
                :disabled="busy"
                @click="startEditTimes(schedule)"
              >
                Ubah waktu
              </button>
              <button
                class="button button-secondary"
                type="button"
                data-archive-schedule
                :disabled="busy"
                @click="confirmArchiveSchedule(schedule)"
              >
                Arsipkan
              </button>
              <button
                class="button button-danger"
                type="button"
                data-delete-schedule
                :disabled="busy"
                @click="confirmDeleteSchedule(schedule)"
              >
                Hapus jadwal
              </button>
            </div>
            <div v-else class="schedule-actions">
              <button
                class="button button-secondary"
                type="button"
                data-restore-schedule
                :disabled="busy"
                @click="restoreSchedule(schedule)"
              >
                {{ pending === `restore:${schedule.id}` ? 'Memulihkan...' : 'Pulihkan' }}
              </button>
            </div>
            <p v-if="schedule.archived" class="state-note">
              Jadwal ini diarsipkan: tidak tampil di toko, tetapi semua penawaran dan
              riwayat pesanannya tetap ada. Pulihkan untuk mengubah waktu atau penawaran.
            </p>

            <div
              v-if="editingId === schedule.id && !schedule.archived"
              class="inline-form"
              role="group"
              :aria-label="`Ubah waktu jadwal ${formatWib(schedule.pickup_at)}`"
            >
              <div class="field">
                <label :for="`edit-pickup-${schedule.id}`">Waktu pengambilan (WIB)</label>
                <input
                  :id="`edit-pickup-${schedule.id}`"
                  v-model="edit.pickup_at"
                  type="datetime-local"
                  step="60"
                  :aria-invalid="Boolean(editErrors.pickup_at)"
                  @input="clearError(editErrors, 'pickup_at')"
                />
                <p v-if="editErrors.pickup_at" class="field-error">
                  {{ editErrors.pickup_at }}
                </p>
              </div>
              <div class="field">
                <label :for="`edit-cutoff-${schedule.id}`">Batas PO bersama (WIB)</label>
                <input
                  :id="`edit-cutoff-${schedule.id}`"
                  v-model="edit.order_cutoff_at"
                  type="datetime-local"
                  step="60"
                  :aria-invalid="Boolean(editErrors.order_cutoff_at)"
                  @input="clearError(editErrors, 'order_cutoff_at')"
                />
                <p v-if="editErrors.order_cutoff_at" class="field-error">
                  {{ editErrors.order_cutoff_at }}
                </p>
              </div>
              <div class="actions">
                <button
                  class="button button-primary"
                  type="button"
                  :disabled="busy"
                  @click="saveEditTimes(schedule)"
                >
                  {{
                    pending === `edit:${schedule.id}`
                      ? 'Menyimpan waktu...'
                      : 'Simpan waktu'
                  }}
                </button>
                <button
                  class="button button-secondary"
                  type="button"
                  :disabled="busy"
                  @click="cancelEditTimes"
                >
                  Batal ubah
                </button>
              </div>
            </div>

            <div
              v-if="confirmingScheduleId === schedule.id"
              class="confirm-panel"
              role="group"
              :aria-label="`Konfirmasi hapus jadwal ${formatWib(schedule.pickup_at)}`"
            >
              <p>
                Hapus jadwal ini beserta penawarannya? Tindakan ini tidak dapat
                dibatalkan.
              </p>
              <div class="actions">
                <button
                  class="button button-danger"
                  type="button"
                  :disabled="busy"
                  @click="removeSchedule(schedule)"
                >
                  {{
                    pending === `delete:${schedule.id}`
                      ? 'Menghapus jadwal...'
                      : 'Ya, hapus jadwal'
                  }}
                </button>
                <button
                  class="button button-secondary"
                  type="button"
                  :disabled="busy"
                  @click="cancelDeleteSchedule"
                >
                  Batal
                </button>
              </div>
            </div>

            <div
              v-if="confirmingArchiveId === schedule.id"
              class="confirm-panel"
              role="group"
              :aria-label="`Konfirmasi arsip jadwal ${formatWib(schedule.pickup_at)}`"
            >
              <p>
                Arsipkan jadwal ini? Jadwal hilang dari toko dan daftar bawaan,
                tetapi penawaran, kuota terpakai, dan riwayat pesanan tetap utuh.
                Hanya jadwal yang batas PO-nya sudah lewat dan seluruh pesanannya
                selesai atau batal yang dapat diarsipkan.
              </p>
              <div class="actions">
                <button
                  class="button button-primary"
                  type="button"
                  :disabled="busy"
                  @click="archiveSchedule(schedule)"
                >
                  {{
                    pending === `archive:${schedule.id}`
                      ? 'Mengarsipkan jadwal...'
                      : 'Ya, arsipkan jadwal'
                  }}
                </button>
                <button
                  class="button button-secondary"
                  type="button"
                  :disabled="busy"
                  @click="cancelArchiveSchedule"
                >
                  Batal
                </button>
              </div>
            </div>

            <section class="schedule-offers" :aria-labelledby="`seller-offers-${schedule.id}`">
              <h4 :id="`seller-offers-${schedule.id}`">Penawaran</h4>
              <p v-if="schedule.offers.length === 0" class="state-note">
                Belum ada penawaran pada jadwal ini.
              </p>
              <ul v-else class="offer-list">
                <li v-for="offer in schedule.offers" :key="offer.id" class="offer-row">
                  <div class="offer-info">
                    <h5>{{ offer.product_name }}</h5>
                    <p class="product-price">{{ formatRupiah(offer.price_rupiah) }}</p>
                    <p class="product-unit">{{ offer.selling_unit }}</p>
                  </div>
                  <div class="offer-controls">
                    <p class="offer-quota">
                      Teralokasi {{ offer.allocated_quantity }} &middot; sisa
                      {{ offer.remaining_quota }} dari {{ offer.quota }}
                    </p>
                    <template v-if="!schedule.archived">
                    <div class="field quota-field">
                      <label :for="`offer-quota-${offer.id}`">Kuota</label>
                      <input
                        :id="`offer-quota-${offer.id}`"
                        v-model="quotaDrafts[offer.id]"
                        :aria-label="`Kuota ${offer.product_name}`"
                        type="number"
                        min="1"
                        max="999"
                        step="1"
                        inputmode="numeric"
                        :aria-invalid="Boolean(quotaErrors[offer.id])"
                        :aria-describedby="
                          quotaErrors[offer.id]
                            ? `offer-quota-${offer.id}-error`
                            : `offer-quota-${offer.id}-help`
                        "
                        @input="clearError(quotaErrors, String(offer.id))"
                      />
                      <p :id="`offer-quota-${offer.id}-help`" class="field-help">
                        Bilangan bulat 1 sampai 999; tidak boleh di bawah jumlah teralokasi.
                      </p>
                      <p
                        v-if="quotaErrors[offer.id]"
                        :id="`offer-quota-${offer.id}-error`"
                        class="field-error"
                      >
                        {{ quotaErrors[offer.id] }}
                      </p>
                    </div>
                    <div class="field price-field">
                      <label :for="`offer-price-${offer.id}`">Harga</label>
                      <input
                        :id="`offer-price-${offer.id}`"
                        v-model="priceDrafts[offer.id]"
                        :aria-label="`Harga ${offer.product_name}`"
                        type="number"
                        min="1000"
                        max="1000000"
                        step="1"
                        inputmode="numeric"
                        :aria-invalid="Boolean(priceErrors[offer.id])"
                        :aria-describedby="
                          priceErrors[offer.id]
                            ? `offer-price-${offer.id}-error`
                            : `offer-price-${offer.id}-help`
                        "
                        @input="clearError(priceErrors, String(offer.id))"
                      />
                      <p :id="`offer-price-${offer.id}-help`" class="field-help">
                        Rupiah 1.000 sampai 1.000.000. Pesanan lama tetap memakai harga
                        saat dipesan.
                      </p>
                      <p
                        v-if="priceErrors[offer.id]"
                        :id="`offer-price-${offer.id}-error`"
                        class="field-error"
                      >
                        {{ priceErrors[offer.id] }}
                      </p>
                    </div>
                    <div class="offer-actions">
                      <button
                        class="button button-secondary"
                        type="button"
                        :disabled="busy"
                        @click="saveOffer(schedule, offer)"
                      >
                        {{
                          pending === `offer:${offer.id}`
                            ? 'Menyimpan penawaran...'
                            : 'Simpan penawaran'
                        }}
                      </button>
                      <button
                        class="button button-danger"
                        type="button"
                        data-remove-offer
                        :data-remove-offer-id="offer.id"
                        :disabled="busy"
                        @click="confirmRemoveOffer(offer)"
                      >
                        Hapus penawaran
                      </button>
                    </div>
                    </template>
                    <p v-else class="state-note">
                      Penawaran arsip ditampilkan apa adanya. Pulihkan jadwal untuk
                      mengubah kuota atau harga.
                    </p>
                  </div>
                  <p
                    v-if="offerSaveErrors[offer.id]"
                    :id="`offer-save-error-${offer.id}`"
                    class="alert alert-error offer-save-error"
                    role="alert"
                    tabindex="-1"
                  >
                    {{ offerSaveErrors[offer.id] }}
                  </p>
                </li>
              </ul>

              <div
                v-if="confirmedOffer(schedule) && !schedule.archived"
                class="confirm-panel"
                role="group"
                :aria-label="`Konfirmasi hapus penawaran ${confirmedOffer(schedule).product_name}`"
              >
                <p>Hapus penawaran ini dari jadwal? Kuota dan produk pada jadwal ini hilang.</p>
                <div class="actions">
                  <button
                    class="button button-danger"
                    type="button"
                    :disabled="busy"
                    @click="removeOffer(schedule, confirmedOffer(schedule))"
                  >
                    {{
                      pending === `remove-offer:${confirmedOffer(schedule).id}`
                        ? 'Menghapus penawaran...'
                        : 'Ya, hapus penawaran'
                    }}
                  </button>
                  <button
                    class="button button-secondary"
                    type="button"
                    :disabled="busy"
                    @click="cancelRemoveOffer($event, schedule)"
                  >
                    Batal
                  </button>
                </div>
              </div>

              <div v-if="!schedule.archived" class="offer-add">
                <button
                  v-if="addingFor !== schedule.id && availableProducts(schedule).length > 0"
                  class="button button-secondary"
                  type="button"
                  data-add-offer
                  :disabled="busy"
                  @click="startAddOffer(schedule)"
                >
                  Tambah penawaran
                </button>
                <p v-else-if="availableProducts(schedule).length === 0" class="field-help">
                  Semua produk aktif sudah ditawarkan pada jadwal ini.
                </p>

                <div
                  v-if="addingFor === schedule.id"
                  class="inline-form"
                  role="group"
                  :aria-label="`Tambah penawaran jadwal ${formatWib(schedule.pickup_at)}`"
                >
                  <div class="field">
                    <label :for="`add-offer-product-${schedule.id}`">Produk dari katalog</label>
                    <select
                      :id="`add-offer-product-${schedule.id}`"
                      v-model="addDraft.product_id"
                      :aria-invalid="Boolean(addErrors.product_id)"
                      @change="clearError(addErrors, 'product_id')"
                    >
                      <option value="">Pilih produk</option>
                      <option
                        v-for="product in availableProducts(schedule)"
                        :key="product.id"
                        :value="String(product.id)"
                      >
                        {{ product.name }} &middot; {{ formatRupiah(product.price_rupiah) }}
                      </option>
                    </select>
                    <p v-if="addErrors.product_id" class="field-error">
                      {{ addErrors.product_id }}
                    </p>
                  </div>
                  <div class="field">
                    <label :for="`add-offer-quota-${schedule.id}`">Kuota</label>
                    <input
                      :id="`add-offer-quota-${schedule.id}`"
                      v-model="addDraft.quota"
                      type="number"
                      min="1"
                      max="999"
                      step="1"
                      inputmode="numeric"
                      :aria-invalid="Boolean(addErrors.quota)"
                      @input="clearError(addErrors, 'quota')"
                    />
                    <p v-if="addErrors.quota" class="field-error">
                      {{ addErrors.quota }}
                    </p>
                  </div>
                  <div class="actions">
                    <button
                      class="button button-primary"
                      type="button"
                      :disabled="busy"
                      @click="saveNewOffer(schedule)"
                    >
                      {{
                        pending === `add:${schedule.id}`
                          ? 'Menambah penawaran...'
                          : 'Tambah penawaran'
                      }}
                    </button>
                    <button
                      class="button button-secondary"
                      type="button"
                      :disabled="busy"
                      @click="cancelAddOffer"
                    >
                      Batal
                    </button>
                  </div>
                </div>
              </div>
            </section>
          </li>
        </ul>
      </section>
    </template>
  </section>
</template>

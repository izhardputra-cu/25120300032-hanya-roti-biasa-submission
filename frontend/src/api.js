const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS'])
const ACCOUNT_FIELD_MESSAGES = {
  name: 'Nama harus 2 sampai 100 karakter.',
  email: 'Masukkan alamat email yang valid.',
  password: 'Password harus 12 sampai 128 karakter.',
}

const PRODUCT_FIELD_MESSAGES = {
  name: 'Nama produk harus 2 sampai 80 karakter.',
  selling_unit: 'Unit jual harus 2 sampai 40 karakter.',
  price_rupiah: 'Harga harus bilangan bulat Rp1.000 sampai Rp1.000.000.',
  description: 'Deskripsi maksimal 400 karakter.',
}

const SCHEDULE_FIELD_MESSAGES = {
  pickup_at: 'Isi tanggal dan waktu pengambilan dalam WIB.',
  order_cutoff_at: 'Batas PO harus sebelum waktu pengambilan, dalam WIB.',
  offers: 'Pilih produk dari katalog dan isi kuotanya.',
  product_id: 'Pilih produk yang tersimpan di katalog.',
  quota: 'Kuota harus bilangan bulat 1 sampai 999.',
  price_rupiah: 'Harga harus bilangan bulat Rp1.000 sampai Rp1.000.000.',
}

const ORDER_FIELD_MESSAGES = {
  checkout_key: 'Kunci checkout tidak valid. Muat ulang tinjauan lalu coba lagi.',
  schedule_id: 'Jadwal pesanan tidak valid.',
  items: 'Isi keranjang tidak valid.',
  offer_id: 'Penawaran pada keranjang tidak valid.',
  quantity: 'Jumlah harus bilangan bulat 1 sampai 999.',
  quoted_price_rupiah: 'Harga tinjauan tidak valid.',
  note: 'Keterangan harus 3 sampai 200 karakter.',
  received_total_rupiah:
    'Jumlah dana harus bilangan bulat Rp1.000 sampai Rp49.950.000.000.',
  reason: 'Alasan harus 3 sampai 300 karakter.',
  refund_outcome: 'Pilih penyelesaian dana.',
}

function messagesFor(path) {
  if (
    path.startsWith('/api/orders') ||
    path.startsWith('/api/seller/orders')
  ) {
    return ORDER_FIELD_MESSAGES
  }
  if (path.startsWith('/api/seller/products')) {
    return PRODUCT_FIELD_MESSAGES
  }
  if (path.startsWith('/api/seller/schedules')) {
    return SCHEDULE_FIELD_MESSAGES
  }
  return ACCOUNT_FIELD_MESSAGES
}

function fieldMessage(field, path) {
  return messagesFor(path)[field] || 'Isian ini tidak valid.'
}

let csrfToken = null

export class ApiError extends Error {
  constructor(status, message, fields = {}, locations = []) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.fields = fields
    // Full paths such as "offers.0.quota" let a form map a nested server
    // validation error back to the exact field the user edited.
    this.locations = locations
  }
}

export function setCsrfToken(token) {
  csrfToken = token
}

export function clearCsrfToken() {
  csrfToken = null
}

function errorFromResponse(response, payload, path) {
  if (response.status === 422 && Array.isArray(payload?.detail)) {
    const fields = {}
    const locations = []
    for (const item of payload.detail) {
      const location = Array.isArray(item.loc) ? item.loc : []
      const parts = location.filter((part) => part !== 'body')
      const field = parts[parts.length - 1]
      if (!field) {
        continue
      }
      const message = fieldMessage(field, path)
      if (!fields[field]) {
        fields[field] = message
      }
      locations.push({ path: parts.join('.'), field, message })
    }
    return new ApiError(422, 'Periksa kembali isian formulir.', fields, locations)
  }
  if (response.status === 422 && typeof payload?.detail === 'string') {
    return new ApiError(422, payload.detail)
  }
  if (response.status === 401) {
    return new ApiError(401, 'Sesi atau kredensial tidak valid. Silakan masuk lagi.')
  }
  if (response.status === 403) {
    return new ApiError(
      403,
      'Permintaan tidak dapat diverifikasi. Muat ulang halaman lalu coba lagi.',
    )
  }
  if (response.status === 404) {
    return new ApiError(404, 'Data yang diminta tidak ditemukan.')
  }
  if (response.status === 409) {
    const detail = typeof payload?.detail === 'string' ? payload.detail : ''
    if (path.startsWith('/api/seller/') || path.startsWith('/api/orders')) {
      // Order and seller conflicts carry an actionable business message.
      return new ApiError(
        409,
        detail || 'Data ini masih dipakai atau sudah ada. Periksa lalu coba lagi.',
      )
    }
    return new ApiError(
      409,
      'Email sudah terdaftar. Masuk dengan email itu atau gunakan email lain.',
    )
  }
  if (response.status >= 500) {
    return new ApiError(response.status, 'Server sedang bermasalah. Coba lagi sebentar.')
  }
  return new ApiError(response.status, 'Permintaan gagal. Coba lagi.')
}

async function send(path, { method = 'GET', body, headers = {} } = {}) {
  const requestHeaders = { Accept: 'application/json', ...headers }
  if (body !== undefined) {
    requestHeaders['Content-Type'] = 'application/json'
  }
  let response
  try {
    response = await fetch(path, {
      method,
      credentials: 'include',
      headers: requestHeaders,
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(
      0,
      'Jaringan tidak tersedia. Periksa koneksi lalu coba lagi.',
    )
  }

  if (response.status === 204) {
    return null
  }

  const text = await response.text()
  let payload = null
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      payload = null
    }
  }
  if (!response.ok) {
    throw errorFromResponse(response, payload, path)
  }
  return payload
}

export async function fetchSession() {
  const data = await send('/api/auth/session')
  setCsrfToken(data.csrf_token)
  return data
}

export async function apiRequest(path, options = {}) {
  const method = (options.method || 'GET').toUpperCase()
  const unsafe = !SAFE_METHODS.has(method)
  if (unsafe && !csrfToken) {
    await fetchSession()
  }
  const headers = { ...(options.headers || {}) }
  if (unsafe && csrfToken) {
    headers['X-CSRF-Token'] = csrfToken
  }
  try {
    return await send(path, { method, body: options.body, headers })
  } catch (error) {
    if (unsafe && error instanceof ApiError && error.status === 403 && !options.retried) {
      await fetchSession()
      return apiRequest(path, { ...options, retried: true })
    }
    throw error
  }
}

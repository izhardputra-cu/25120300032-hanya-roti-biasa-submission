// Status values stay machine-readable in the API; the UI owns the Indonesian
// labels. Every stored value from T5 to T7 has a label so it is never shown raw.
export const ORDER_STATUS_LABELS = {
  menunggu_pembayaran: 'Menunggu pembayaran',
  menunggu_pemeriksaan: 'Menunggu pemeriksaan',
  terkonfirmasi: 'Terkonfirmasi',
  siap_diambil: 'Siap diambil',
  selesai: 'Selesai',
  batal: 'Batal',
}

export function orderStatusLabel(status) {
  return ORDER_STATUS_LABELS[status] || 'Status tidak dikenal'
}

export function orderStatusClass(status) {
  if (status === 'batal') {
    return 'status-tag-closed'
  }
  if (status === 'selesai' || status === 'siap_diambil' || status === 'terkonfirmasi') {
    return 'status-tag-open'
  }
  return ''
}

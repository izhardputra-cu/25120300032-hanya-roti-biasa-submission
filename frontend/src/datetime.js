// Schedule times are stored and transported as UTC. The UI reads and writes WIB
// explicitly; it never depends on the browser's local timezone.
const TIME_ZONE = 'Asia/Jakarta'

const dateFormatter = new Intl.DateTimeFormat('id-ID', {
  timeZone: TIME_ZONE,
  day: 'numeric',
  month: 'long',
  year: 'numeric',
})

const timeFormatter = new Intl.DateTimeFormat('id-ID', {
  timeZone: TIME_ZONE,
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
})

const inputFormatter = new Intl.DateTimeFormat('en-CA', {
  timeZone: TIME_ZONE,
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
})

function partsOf(formatter, date) {
  const parts = {}
  for (const part of formatter.formatToParts(date)) {
    if (part.type !== 'literal') {
      parts[part.type] = part.value
    }
  }
  return parts
}

function parseIso(value) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

export function formatWib(iso) {
  const date = parseIso(iso)
  if (date === null) {
    return 'Waktu tidak tersedia'
  }
  const day = partsOf(dateFormatter, date)
  const time = partsOf(timeFormatter, date)
  return `${day.day} ${day.month} ${day.year}, ${time.hour}.${time.minute} WIB`
}

export function toWibInputValue(iso) {
  const date = parseIso(iso)
  if (date === null) {
    return ''
  }
  const parts = partsOf(inputFormatter, date)
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`
}

export function fromWibInputValue(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/.exec(value || '')
  if (!match) {
    return null
  }
  const normalized = match[6] === undefined ? `${value}:00` : value
  const iso = `${normalized}+07:00`
  return parseIso(iso) === null ? null : iso
}

export function wibInputsInOrder(pickupValue, cutoffValue) {
  const pickup = fromWibInputValue(pickupValue)
  const cutoff = fromWibInputValue(cutoffValue)
  if (pickup === null || cutoff === null) {
    return false
  }
  return Date.parse(cutoff) < Date.parse(pickup)
}

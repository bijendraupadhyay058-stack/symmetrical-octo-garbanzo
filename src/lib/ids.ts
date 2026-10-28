/** RFC 4122 v4 UUID. Uses crypto.randomUUID when available (secure contexts). */
export function uuid(): string {
  const c = globalThis.crypto
  if (c?.randomUUID) return c.randomUUID()
  const b = new Uint8Array(16)
  c.getRandomValues(b)
  b[6] = (b[6] & 0x0f) | 0x40
  b[8] = (b[8] & 0x3f) | 0x80
  const h = [...b].map((x) => x.toString(16).padStart(2, '0')).join('')
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`
}

let last = 0

/**
 * Current time as ISO string, strictly increasing within this app session so
 * that entries saved in the same millisecond still have a stable order.
 */
export function nowISO(): string {
  const t = Math.max(Date.now(), last + 1)
  last = t
  return new Date(t).toISOString()
}

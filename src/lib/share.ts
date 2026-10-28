/** Save a file to the device (works on Android Chrome and desktop). */
export function downloadBlob(blob: Blob, fileName: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = fileName
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 10_000)
}

/** Indian mobile → wa.me international format (91XXXXXXXXXX). */
export function waNumber(mobile: string): string {
  const d = mobile.replace(/\D/g, '')
  if (d.length === 10) return '91' + d
  if (d.length === 12 && d.startsWith('91')) return d
  if (d.length === 11 && d.startsWith('0')) return '91' + d.slice(1)
  return d
}

export function whatsappUrl(text: string, mobile?: string): string {
  const num = mobile ? waNumber(mobile) : ''
  return `https://wa.me/${num}?text=${encodeURIComponent(text)}`
}

export type ShareOutcome = 'shared' | 'whatsapp' | 'downloaded' | 'cancelled'

/**
 * Share a PDF (or other file) using Android's share sheet (Web Share API Level 2)
 * so it can be sent on WhatsApp with the attachment. Where file sharing is not
 * supported, the file is downloaded and WhatsApp opens with the message text.
 */
export async function shareFile(file: Blob, fileName: string, text: string, mobile?: string): Promise<ShareOutcome> {
  const f = new File([file], fileName, { type: file.type || 'application/pdf' })
  const nav = navigator as Navigator & { canShare?: (d: ShareData) => boolean }
  if (nav.share && nav.canShare?.({ files: [f] })) {
    try {
      await nav.share({ files: [f], text, title: fileName })
      return 'shared'
    } catch (e) {
      if ((e as DOMException)?.name === 'AbortError') return 'cancelled'
    }
  }
  downloadBlob(f, fileName)
  window.open(whatsappUrl(text, mobile), '_blank', 'noopener')
  return 'downloaded'
}

/** Share plain text (reminders). */
export async function shareText(text: string, mobile?: string): Promise<ShareOutcome> {
  if (mobile) {
    window.open(whatsappUrl(text, mobile), '_blank', 'noopener')
    return 'whatsapp'
  }
  if (navigator.share) {
    try {
      await navigator.share({ text })
      return 'shared'
    } catch (e) {
      if ((e as DOMException)?.name === 'AbortError') return 'cancelled'
    }
  }
  window.open(whatsappUrl(text), '_blank', 'noopener')
  return 'whatsapp'
}

/** Resize a photo before storing it (keeps bill photos small and readable). */
export async function compressImage(file: File, maxSide = 1600, quality = 0.82, type = 'image/jpeg'): Promise<Blob> {
  if (!file.type.startsWith('image/')) return file
  const bitmap = await createImageBitmap(file)
  const scale = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height))
  const w = Math.round(bitmap.width * scale)
  const h = Math.round(bitmap.height * scale)
  const canvas = document.createElement('canvas')
  canvas.width = w
  canvas.height = h
  const ctx = canvas.getContext('2d')!
  if (type === 'image/jpeg') {
    ctx.fillStyle = '#fff'
    ctx.fillRect(0, 0, w, h)
  }
  ctx.drawImage(bitmap, 0, 0, w, h)
  const blob = await new Promise<Blob | null>((res) => canvas.toBlob(res, type, quality))
  return blob && blob.size < file.size ? blob : file
}

export function blobToDataUrl(b: Blob): Promise<string> {
  return new Promise((res, rej) => {
    const r = new FileReader()
    r.onload = () => res(String(r.result))
    r.onerror = () => rej(r.error)
    r.readAsDataURL(b)
  })
}

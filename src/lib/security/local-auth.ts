/**
 * Device-level unlock for the auto-lock screen.
 *
 * - A PBKDF2 hash of the user's password is kept on the device so the app can
 *   be unlocked while offline. The password itself is never stored.
 * - Optional biometric / screen-lock unlock uses WebAuthn with the platform
 *   authenticator (fingerprint, face or device PIN on Android). It gates access
 *   to this device's app session only; server access always relies on the
 *   Supabase session.
 */
const ITERATIONS = 210_000

function b64(buf: ArrayBuffer | Uint8Array): string {
  const bytes = buf instanceof Uint8Array ? buf : new Uint8Array(buf)
  let s = ''
  for (const b of bytes) s += String.fromCharCode(b)
  return btoa(s)
}

function unb64(s: string): Uint8Array<ArrayBuffer> {
  const bin = atob(s)
  const out = new Uint8Array(new ArrayBuffer(bin.length))
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i)
  return out
}

async function derive(password: string, salt: Uint8Array<ArrayBuffer>, iterations: number): Promise<string> {
  const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(password), 'PBKDF2', false, ['deriveBits'])
  const bits = await crypto.subtle.deriveBits({ name: 'PBKDF2', hash: 'SHA-256', salt, iterations }, key, 256)
  return b64(bits)
}

const pwKey = (scope: string) => `fintax.unlock.${scope}`
const bioKey = (scope: string) => `fintax.bio.${scope}`

export async function rememberPassword(scope: string, password: string) {
  const salt = crypto.getRandomValues(new Uint8Array(new ArrayBuffer(16)))
  const hash = await derive(password, salt, ITERATIONS)
  localStorage.setItem(pwKey(scope), JSON.stringify({ salt: b64(salt), hash, iterations: ITERATIONS }))
}

export function hasLocalPassword(scope: string): boolean {
  try {
    return !!localStorage.getItem(pwKey(scope))
  } catch {
    return false
  }
}

export async function verifyLocalPassword(scope: string, password: string): Promise<boolean> {
  const raw = localStorage.getItem(pwKey(scope))
  if (!raw) return false
  const { salt, hash, iterations } = JSON.parse(raw)
  const candidate = await derive(password, unb64(salt), iterations)
  // constant-time-ish comparison
  let diff = candidate.length ^ hash.length
  for (let i = 0; i < Math.min(candidate.length, hash.length); i++) diff |= candidate.charCodeAt(i) ^ hash.charCodeAt(i)
  return diff === 0
}

export function forgetLocalSecrets(scope: string) {
  localStorage.removeItem(pwKey(scope))
  localStorage.removeItem(bioKey(scope))
}

export async function biometricAvailable(): Promise<boolean> {
  try {
    return !!window.PublicKeyCredential && (await PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable())
  } catch {
    return false
  }
}

export function biometricEnabled(scope: string): boolean {
  try {
    return !!localStorage.getItem(bioKey(scope))
  } catch {
    return false
  }
}

export async function enableBiometric(scope: string, label: string): Promise<void> {
  const cred = (await navigator.credentials.create({
    publicKey: {
      challenge: crypto.getRandomValues(new Uint8Array(32)),
      rp: { name: 'FIN TAX PRO CashBook' },
      user: { id: new TextEncoder().encode(scope.slice(0, 60)), name: label || 'owner', displayName: label || 'Owner' },
      pubKeyCredParams: [{ type: 'public-key', alg: -7 }, { type: 'public-key', alg: -257 }],
      authenticatorSelection: { authenticatorAttachment: 'platform', userVerification: 'required', residentKey: 'discouraged' },
      timeout: 60_000,
      attestation: 'none',
    },
  })) as PublicKeyCredential | null
  if (!cred) throw new Error('Biometric registration was cancelled')
  localStorage.setItem(bioKey(scope), b64(cred.rawId))
}

export function disableBiometric(scope: string) {
  localStorage.removeItem(bioKey(scope))
}

export async function verifyBiometric(scope: string): Promise<boolean> {
  const id = localStorage.getItem(bioKey(scope))
  if (!id) return false
  try {
    const res = await navigator.credentials.get({
      publicKey: {
        challenge: crypto.getRandomValues(new Uint8Array(32)),
        allowCredentials: [{ type: 'public-key', id: unb64(id) }],
        userVerification: 'required',
        timeout: 60_000,
      },
    })
    return !!res
  } catch {
    return false
  }
}

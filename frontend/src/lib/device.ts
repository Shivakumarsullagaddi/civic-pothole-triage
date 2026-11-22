const KEY = 'pothole-device-id'
let memoryId: string | null = null

function randomId(): string {
  return crypto.randomUUID().replace(/-/g, '')
}

/** A random per-browser id for rate limits and trust. Not an account; easily reset. */
export function deviceId(): string {
  try {
    const existing = localStorage.getItem(KEY)
    if (existing) return existing
    const id = randomId()
    localStorage.setItem(KEY, id)
    return id
  } catch {
    // Storage blocked (private mode etc.): keep one id for this page session.
    memoryId ??= randomId()
    return memoryId
  }
}

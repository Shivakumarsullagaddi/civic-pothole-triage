/** sessionStorage wrapper that never throws (private mode, blocked storage). */
export function getSession(key: string): string {
  try {
    return sessionStorage.getItem(key) ?? ''
  } catch {
    return ''
  }
}

export function setSession(key: string, value: string): void {
  try {
    sessionStorage.setItem(key, value)
  } catch {
    /* storage unavailable: keep the value in memory only */
  }
}

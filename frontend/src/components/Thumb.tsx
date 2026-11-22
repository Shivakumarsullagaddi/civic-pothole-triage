import { useEffect, useRef, useState } from 'react'
import { authority } from '../api/client'

// Object URLs survive for the whole session so scrolling back does not refetch.
const cache = new Map<string, Promise<string>>()

export function forgetPhotos(reportId: string): void {
  for (const key of [...cache.keys()]) if (key.startsWith(`${reportId}:`)) cache.delete(key)
}

export function loadPhoto(token: string, reportId: string, index: number): Promise<string> {
  const key = `${reportId}:${index}`
  let p = cache.get(key)
  if (!p) {
    p = authority.photo(token, reportId, index)
    p.catch(() => cache.delete(key))
    cache.set(key, p)
  }
  return p
}

/** A private report photo, fetched with the authority token only when scrolled into view. */
export default function Thumb({ token, reportId, index = 0, size = 56 }: {
  token: string; reportId: string | null | undefined; index?: number; size?: number
}) {
  const ref = useRef<HTMLSpanElement>(null)
  const [url, setUrl] = useState<string | null>(null)
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const io = new IntersectionObserver(([e]) => e.isIntersecting && setVisible(true), { rootMargin: '200px' })
    io.observe(el)
    return () => io.disconnect()
  }, [])

  useEffect(() => {
    if (!visible || !reportId) return
    let alive = true
    loadPhoto(token, reportId, index).then((u) => alive && setUrl(u)).catch(() => alive && setUrl(null))
    return () => {
      alive = false
    }
  }, [visible, token, reportId, index])

  return (
    <span ref={ref} className="thumb" style={{ width: size, height: size }}>
      {url ? <img src={url} alt="" /> : <span className="thumb-ph" aria-hidden="true" />}
    </span>
  )
}

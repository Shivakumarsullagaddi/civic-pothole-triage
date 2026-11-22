import { useState } from 'react'

export type PhotoBox = { x1: number; y1: number; x2: number; y2: number; score: number }
export type PhotoFrame = { url: string; width: number; height: number; boxes: PhotoBox[] }

/**
 * The original photos with detected pothole boxes drawn on top (SVG overlay in the photo's own
 * pixel coordinates, so it scales with the image). One button hides/shows the boxes for all
 * photos in the group; the photo underneath is always the untouched original.
 */
export default function BoxedPhotos({ frames, bestFrame, onDelete }: {
  frames: PhotoFrame[]
  bestFrame?: number | null
  onDelete?: (index: number) => void // admins only
}) {
  const [showBoxes, setShowBoxes] = useState(true)
  const total = frames.reduce((n, f) => n + f.boxes.length, 0)
  if (!frames.length) return null

  return (
    <div className="boxed">
      <div className="row" style={{ alignItems: 'center', margin: '8px 0' }}>
        <button onClick={() => setShowBoxes((v) => !v)} aria-pressed={!showBoxes} disabled={total === 0}>
          {showBoxes ? 'Hide boxes' : 'Show boxes'}
        </button>
        <span className="muted">
          {total === 0 ? 'No pothole boxes detected' : `${total} pothole box${total === 1 ? '' : 'es'} detected`}
        </span>
      </div>
      <div className="boxed-grid">
        {frames.map((f, i) => (
          <figure key={f.url} className={`boxed-photo${i === bestFrame ? ' best' : ''}`}>
            <div className="boxed-stage">
              <img src={f.url} alt={`photo ${i + 1}`} />
              {showBoxes && f.width > 0 && f.height > 0 && (
                <svg viewBox={`0 0 ${f.width} ${f.height}`} preserveAspectRatio="none" aria-hidden="true">
                  {f.boxes.map((b, k) => {
                    const stroke = Math.max(2, f.width / 220)
                    const label = `${Math.round(b.score * 100)}%`
                    const fs = Math.max(12, f.width / 40)
                    return (
                      <g key={k}>
                        <rect x={b.x1} y={b.y1} width={b.x2 - b.x1} height={b.y2 - b.y1}
                              fill="none" stroke="#ff2d55" strokeWidth={stroke} />
                        <rect x={b.x1} y={Math.max(0, b.y1 - fs * 1.3)} width={fs * (label.length * 0.62 + 0.6)}
                              height={fs * 1.3} fill="#ff2d55" />
                        <text x={b.x1 + fs * 0.3} y={Math.max(fs, b.y1 - fs * 0.3)} fontSize={fs}
                              fill="#fff" fontFamily="system-ui, sans-serif">{label}</text>
                      </g>
                    )
                  })}
                </svg>
              )}
            </div>
            <figcaption className="muted">
              Photo {i + 1}{i === bestFrame ? ' · used for severity' : ''} · {f.boxes.length} box{f.boxes.length === 1 ? '' : 'es'}
              {onDelete && (
                <button className="small-btn danger photo-del" onClick={() => onDelete(i)} title="Delete this photo">
                  🗑 Delete
                </button>
              )}
            </figcaption>
          </figure>
        ))}
      </div>
    </div>
  )
}

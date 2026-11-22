import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type ReportOut, type WardOut } from '../api/client'
import BoxedPhotos, { type PhotoFrame } from '../components/BoxedPhotos'
import { SeverityBadge, StatusPill, TrustMeter } from '../components/ui'
import { deviceId } from '../lib/device'

const BURST_FRAMES = 3
const BURST_GAP_MS = 300
const SEND_STEPS = ['Uploading photos', 'Checking the photo is genuine', 'Looking for the pothole', 'Finding the responsible office']

type Fix = { lat: number; lng: number; accuracy: number; at: number }
type Shot = { blob: Blob; url: string }
type Step = 'capture' | 'review' | 'sending' | 'result'

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

/** Grab the whole video frame (edge to edge, no crop) as a JPEG. */
function grabFrame(video: HTMLVideoElement, canvas: HTMLCanvasElement): Promise<Blob> {
  canvas.width = video.videoWidth
  canvas.height = video.videoHeight
  canvas.getContext('2d')!.drawImage(video, 0, 0, canvas.width, canvas.height)
  return new Promise((resolve, reject) =>
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('Capture failed'))), 'image/jpeg', 0.9),
  )
}

type TrustSummary = { signals?: { name: string; penalty: number; detail: string; hard: boolean }[]; corroborated?: string }
type DetectionFrames = {
  frames?: { width: number; height: number; boxes: PhotoFrame['boxes']; ms?: number }[]
  best_frame?: number
  severity_reasons?: string[]
  mode?: string
}

/** Pair the photos this phone sent with the boxes the server found in each one. */
function framesWithBoxes(shots: Shot[], raw: unknown): PhotoFrame[] {
  const d = (raw ?? {}) as DetectionFrames
  return shots.map((s, i) => ({
    url: s.url,
    width: d.frames?.[i]?.width ?? 0,
    height: d.frames?.[i]?.height ?? 0,
    boxes: d.frames?.[i]?.boxes ?? [],
  }))
}

const OUTCOME: Record<string, { icon: string; title: string; tone: string; text: (r: ReportOut) => string }> = {
  accepted: {
    icon: '✓', title: 'Report accepted', tone: 'good',
    text: (r) => (r.issue_report_count && r.issue_report_count > 1
      ? `Merged with an existing pothole: ${r.issue_report_count} people have reported it.`
      : 'A new pothole has been logged and sent to the responsible office.'),
  },
  needs_review: {
    icon: '⏸', title: 'Held for confirmation', tone: 'warn',
    text: (r) => (((r.trust_signals ?? {}) as TrustSummary).signals?.some((s) => s.name === 'uncertain_detection')
      ? "We're not sure this is a pothole: it could be a road marking, patch or shadow. It stays unverified until another person reports the same spot. A closer photo helps."
      : 'It shows as unverified until another person reports the same pothole.'),
  },
  rejected: { icon: '✕', title: 'Report not accepted', tone: 'bad', text: (r) => r.reject_reason ?? 'It failed the photo checks.' },
  no_damage: {
    icon: '?', title: 'No pothole found', tone: 'warn',
    text: () => 'We could not see a pothole in this photo, so it was not sent. Retake it closer, with the pothole in the middle of the frame.',
  },
}

const REPAIR: Record<string, { title: string; tone: string }> = {
  verified_fixed: { title: 'Repair confirmed: the pothole is gone', tone: 'good' },
  reopened: { title: 'Reopened: the pothole is still there', tone: 'bad' },
  inconclusive: { title: 'Repair could not be confirmed from this photo', tone: 'warn' },
}

export default function ReportPage() {
  const videoRef = useRef<HTMLVideoElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const uploadRef = useRef<HTMLInputElement>(null)
  const startingRef = useRef(false)

  const [cameraOn, setCameraOn] = useState(false)
  const [cameraError, setCameraError] = useState<string | null>(null)
  const [fix, setFix] = useState<Fix | null>(null)
  const [gpsError, setGpsError] = useState<string | null>(null)
  const [shots, setShots] = useState<Shot[]>([])
  const [source, setSource] = useState<'camera' | 'upload'>('camera')
  const [step, setStep] = useState<Step>('capture')
  const [sendStep, setSendStep] = useState(0)
  const [capturing, setCapturing] = useState(false)
  const [flash, setFlash] = useState(false)
  const [result, setResult] = useState<ReportOut | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [ward, setWard] = useState<WardOut | null | undefined>(undefined) // undefined = not looked up
  const lastLookup = useRef<{ lat: number; lng: number } | null>(null)

  // GPS: watch continuously while the page is open.
  useEffect(() => {
    if (!('geolocation' in navigator)) {
      setGpsError('This browser has no GPS access.')
      return
    }
    const id = navigator.geolocation.watchPosition(
      (p) => {
        setGpsError(null)
        setFix({ lat: p.coords.latitude, lng: p.coords.longitude, accuracy: p.coords.accuracy, at: p.timestamp })
      },
      (e) => setGpsError(e.message || 'Location unavailable'),
      { enableHighAccuracy: true, maximumAge: 0, timeout: 20000 },
    )
    return () => navigator.geolocation.clearWatch(id)
  }, [])

  // Which ward will this go to? Look up again only after moving more than ~30 m.
  useEffect(() => {
    if (!fix) return
    const prev = lastLookup.current
    if (prev && Math.abs(prev.lat - fix.lat) < 0.0003 && Math.abs(prev.lng - fix.lng) < 0.0003) return
    lastLookup.current = { lat: fix.lat, lng: fix.lng }
    api.wardAt(fix.lat, fix.lng).then(setWard).catch(() => setWard(undefined))
  }, [fix])

  const stopCamera = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop())
    streamRef.current = null
    setCameraOn(false)
  }, [])
  useEffect(() => stopCamera, [stopCamera])

  // Revoke preview URLs when shots change or the page closes.
  useEffect(() => () => shots.forEach((s) => URL.revokeObjectURL(s.url)), [shots])

  // Walk the progress text while the server works (purely informative).
  useEffect(() => {
    if (step !== 'sending') return
    setSendStep(0)
    const t = setInterval(() => setSendStep((s) => Math.min(s + 1, SEND_STEPS.length - 1)), 700)
    return () => clearInterval(t)
  }, [step])

  async function startCamera() {
    if (startingRef.current) return // ignore double clicks while the camera is starting
    startingRef.current = true
    setCameraError(null)
    try {
      if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
        setCameraError('The camera needs a secure (https://) address. Open the https link of this site.')
        return
      }
      streamRef.current?.getTracks().forEach((t) => t.stop()) // never run two streams
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: 'environment' }, width: { ideal: 1920 }, height: { ideal: 1080 } },
        audio: false,
      })
      streamRef.current = stream
      const video = videoRef.current
      if (!video) {
        stream.getTracks().forEach((t) => t.stop())
        return
      }
      video.srcObject = stream
      try {
        await video.play()
      } catch (e) {
        // "play() was interrupted by a new load request" is harmless: the stream reloaded.
        // Try once more; only a real failure reaches the user.
        if (e instanceof DOMException && e.name === 'AbortError') await video.play()
        else throw e
      }
      setCameraOn(true)
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return // a newer start took over
      const msg = e instanceof DOMException && e.name === 'NotAllowedError'
        ? 'Camera permission was blocked. Allow camera access in the browser and try again.'
        : e instanceof Error ? e.message : 'Camera unavailable'
      setCameraError(msg)
    } finally {
      startingRef.current = false
    }
  }

  async function captureBurst() {
    const video = videoRef.current
    const canvas = canvasRef.current
    if (!video || !canvas || !video.videoWidth) return
    setCapturing(true)
    setFlash(true)
    setTimeout(() => setFlash(false), 180)
    try {
      const next: Shot[] = []
      for (let i = 0; i < BURST_FRAMES; i++) {
        if (i > 0) await sleep(BURST_GAP_MS)
        const blob = await grabFrame(video, canvas)
        next.push({ blob, url: URL.createObjectURL(blob) })
      }
      setShots(next)
      setSource('camera')
      setResult(null)
      setStep('review')
      stopCamera()
    } finally {
      setCapturing(false)
    }
  }

  function onUpload(files: FileList | null) {
    if (!files?.length) return
    stopCamera()
    setShots([...files].slice(0, BURST_FRAMES).map((f) => ({ blob: f, url: URL.createObjectURL(f) })))
    setSource('upload')
    setResult(null)
    setStep('review')
  }

  function restart() {
    setShots([])
    setResult(null)
    setSubmitError(null)
    setStep('capture')
  }

  async function submit() {
    if (!fix || !shots.length) return
    setSubmitError(null)
    setStep('sending')
    const form = new FormData()
    shots.forEach((s, i) => form.append('frames', s.blob, `frame_${i}.jpg`))
    form.append('lat', String(fix.lat))
    form.append('lng', String(fix.lng))
    form.append('accuracy_m', String(fix.accuracy))
    form.append('captured_at', new Date().toISOString())
    form.append('device_id', deviceId())
    form.append('capture_source', source)
    try {
      setResult(await api.createReport(form))
      setStep('result')
    } catch (e) {
      setSubmitError(e instanceof Error ? e.message : 'Sending failed')
      setStep('review')
    }
  }

  const gpsTone = !fix ? (gpsError ? 'bad' : 'muted') : fix.accuracy <= 20 ? 'good' : fix.accuracy <= 50 ? 'warn' : 'bad'
  const stepIndex = { capture: 0, review: 1, sending: 2, result: 2 }[step]
  const outcome = result ? OUTCOME[result.state] ?? OUTCOME.accepted : null
  const repair = result?.repair_check as { outcome?: string; detail?: string } | null | undefined
  const trust = (result?.trust_signals ?? {}) as TrustSummary
  const det = (result?.detections ?? {}) as DetectionFrames
  const boxes = det.frames?.[det.best_frame ?? 0]?.boxes.length ?? 0

  return (
    <div className="report">
      <div className="report-hero">
        <h1>Report a pothole</h1>
        <p className="muted">Three steps. Your photo is checked, the pothole is detected, and it goes to the right ward office.</p>
        <ol className="stepper" aria-label="Progress">
          {['Photo', 'Review', 'Sent'].map((label, i) => (
            <li key={label} className={i < stepIndex ? 'done' : i === stepIndex ? 'current' : ''}>
              <span className="stepper-dot">{i < stepIndex ? '✓' : i + 1}</span>
              {label}
            </li>
          ))}
        </ol>
      </div>

      {/* Location card */}
      <section className="loc-card">
        <span className={`loc-icon ${gpsTone}`} aria-hidden="true">📍</span>
        <div className="loc-main">
          {fix ? (
            <>
              <div className="loc-title">
                {ward ? `Ward ${ward.ward_no} · ${ward.name}` : ward === null ? 'Outside the GBA area' : 'Finding your ward…'}
              </div>
              <div className="muted loc-sub">
                {ward ? `${ward.corporation} City Corporation${ward.name_kn ? ` · ${ward.name_kn}` : ''}` : ward === null ? 'Reports here cannot be routed to an office.' : ''}
              </div>
            </>
          ) : (
            <>
              <div className="loc-title">{gpsError ? 'Location unavailable' : 'Finding your location…'}</div>
              <div className="muted loc-sub">{gpsError ?? 'Allow location access so the report reaches the right office.'}</div>
            </>
          )}
        </div>
        {fix && <span className={`gps-chip ${gpsTone}`}>±{Math.round(fix.accuracy)} m</span>}
      </section>

      {/* Step 1: capture */}
      {step === 'capture' && (
        <section className="capture">
          <div className={`viewfinder${cameraOn ? ' live' : ''}`}>
            <video ref={videoRef} playsInline muted />
            {cameraOn && (
              <>
                <span className="vf-corner tl" /><span className="vf-corner tr" />
                <span className="vf-corner bl" /><span className="vf-corner br" />
                <span className="vf-hint">Stand 1–2 m away · fill the frame with road</span>
                {flash && <span className="vf-flash" />}
              </>
            )}
            {!cameraOn && (
              <div className="vf-empty">
                <div className="vf-empty-icon" aria-hidden="true">📷</div>
                <p>Point your camera at the pothole</p>
                <button className="primary big" onClick={startCamera}>Open camera</button>
              </div>
            )}
          </div>
          <canvas ref={canvasRef} hidden />
          {cameraError && <p className="bad">{cameraError}</p>}
          <div className="capture-bar">
            <button className="link-btn" onClick={() => uploadRef.current?.click()}>Upload a photo instead</button>
            {cameraOn && (
              <button className="shutter" onClick={captureBurst} disabled={capturing} aria-label="Take photo">
                <span />
              </button>
            )}
            <span className="muted small capture-note">{cameraOn ? 'Takes 3 quick frames' : 'Uploads count as lower trust'}</span>
          </div>
          <input ref={uploadRef} type="file" accept="image/*" multiple hidden onChange={(e) => onUpload(e.target.files)} />
        </section>
      )}

      {/* Step 2: review */}
      {(step === 'review' || step === 'sending') && (
        <section className="review panel">
          <div className="review-head">
            <h2>Check your photo</h2>
            <span className="pill">{source === 'camera' ? `Live camera · ${shots.length} frames` : 'Gallery upload'}</span>
          </div>
          <div className="review-main">
            <img src={shots[0]?.url} alt="Your photo" />
          </div>
          {shots.length > 1 && (
            <div className="review-strip">
              {shots.map((s, i) => <img key={s.url} src={s.url} alt={`frame ${i + 1}`} />)}
            </div>
          )}
          {submitError && <p className="bad">{submitError}</p>}
          {step === 'sending' ? (
            <div className="sending" role="status">
              <span className="spinner" aria-hidden="true" />
              <div>
                <strong>{SEND_STEPS[sendStep]}…</strong>
                <div className="muted small">Step {sendStep + 1} of {SEND_STEPS.length}</div>
              </div>
            </div>
          ) : (
            <div className="review-actions">
              <button onClick={restart}>Retake</button>
              <button className="primary big" onClick={submit} disabled={!fix}>
                {fix ? 'Send report' : 'Waiting for location…'}
              </button>
            </div>
          )}
        </section>
      )}

      {/* Step 3: result */}
      {step === 'result' && result && outcome && (
        <section className="result">
          <div className={`result-hero ${outcome.tone}`}>
            <span className="result-icon" aria-hidden="true">{outcome.icon}</span>
            <div>
              <h2>{outcome.title}</h2>
              <p>{outcome.text(result)}</p>
            </div>
          </div>

          {repair?.outcome && REPAIR[repair.outcome] && (
            <div className={`panel callout ${REPAIR[repair.outcome].tone}`}>
              <h3>{REPAIR[repair.outcome].title}</h3>
              <p className="muted">{repair.detail}</p>
            </div>
          )}

          {result.issue_id && <div className="panel facts">
            <div><span>Sent to</span><strong>{result.authority_name ?? 'No office (outside GBA)'}</strong></div>
            <div><span>Severity</span><SeverityBadge severity={result.severity} /></div>
            <div><span>Status</span>{result.issue_status ? <StatusPill status={result.issue_status} /> : <span className="muted">—</span>}</div>
            <div><span>Photo trust</span><TrustMeter score={result.trust_score} /></div>
          </div>}

          {result.state !== 'rejected' && (
            <div className="panel">
              <h3>What we detected</h3>
              <p className="muted small">
                {boxes ? `${boxes} pothole${boxes === 1 ? '' : 's'} found` : 'No pothole box found'}
                {det.severity_reasons?.length ? ` · ${det.severity_reasons.join('; ')}` : ''}
              </p>
              <BoxedPhotos frames={framesWithBoxes(shots, result.detections)} bestFrame={det.best_frame} />
            </div>
          )}

          {(trust.signals?.length || trust.corroborated) && (
            <div className="panel">
              <h3>Photo checks</h3>
              <ul className="reasons">
                {trust.signals?.map((s) => (
                  <li key={s.name} className={s.hard ? 'bad' : undefined}>{s.detail}</li>
                ))}
                {trust.corroborated && <li className="good">{trust.corroborated}</li>}
              </ul>
            </div>
          )}

          <div className="result-actions">
            {result.state === 'no_damage' || result.state === 'rejected' ? (
              <button className="primary big" onClick={restart}>📷 Retake photo</button>
            ) : (
              <>
                {result.issue_id && <Link className="btn primary" to={`/issue/${result.issue_id}`}>Track this pothole</Link>}
                {result.issue_id && <Link className="btn" to={`/map?focus=${result.issue_id}`}>See it on the map</Link>}
                <button onClick={restart}>{result.state === 'needs_review' ? '📷 Retake closer' : 'Report another'}</button>
              </>
            )}
          </div>
        </section>
      )}
    </div>
  )
}

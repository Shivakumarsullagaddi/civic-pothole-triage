import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import Map, { Layer, NavigationControl, Popup, Source, type MapLayerMouseEvent, type MapRef } from 'react-map-gl/maplibre'
import type { StyleSpecification } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { api, type IssueDetail, type IssueFeatureCollection, type WardProps } from '../api/client'
import { DeadlineBar, SeverityBadge, StatusPill, Timeline } from '../components/ui'
import { ago, STATUS_COLORS, STATUS_LABEL } from '../lib/format'

const BENGALURU = { longitude: 77.5946, latitude: 12.9716, zoom: 11 }
const FOCUS_ZOOM = 17

const OSM_STYLE: StyleSpecification = {
  version: 8,
  sources: {
    osm: {
      type: 'raster',
      tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
      tileSize: 256,
      maxzoom: 19,
      attribution: '© OpenStreetMap contributors',
    },
  },
  layers: [{ id: 'osm', type: 'raster', source: 'osm' }],
}

const circleColor = ['match', ['get', 'status'], ...Object.entries(STATUS_COLORS).flat(), '#000000'] as unknown as string
// Worse potholes get bigger pins (zoom must stay the top-level interpolate input).
const SEV_SCALE = ['match', ['get', 'severity'], 'critical', 1.6, 'high', 1.3, 'medium', 1.1, 1]
const circleRadius = ['interpolate', ['linear'], ['zoom'], 10, ['*', 4, SEV_SCALE], 16, ['*', 10, SEV_SCALE]] as unknown as number
const ringRadius = ['interpolate', ['linear'], ['zoom'], 10, ['*', 9, SEV_SCALE], 16, ['*', 18, SEV_SCALE]] as unknown as number

const CORPORATION_COLORS: Record<string, string> = {
  Central: '#8b5cf6',
  North: '#0ea5e9',
  South: '#f97316',
  East: '#10b981',
  West: '#e11d48',
}
const corpColor = ['match', ['get', 'corporation'], ...Object.entries(CORPORATION_COLORS).flat(), '#6b7280'] as unknown as string

const FILTERABLE = ['open', 'escalated', 'reopened', 'acknowledged', 'unverified', 'claimed_fixed', 'verified_fixed']
const DEFAULT_ON = new Set(['open', 'escalated', 'reopened', 'acknowledged', 'unverified', 'claimed_fixed'])

type WardPick = { lng: number; lat: number; props: WardProps; key: string }

/** [minLng, minLat, maxLng, maxLat] of any GeoJSON geometry. */
function bboxOf(geom: GeoJSON.Geometry): [number, number, number, number] {
  const b: [number, number, number, number] = [Infinity, Infinity, -Infinity, -Infinity]
  const walk = (c: unknown): void => {
    if (Array.isArray(c) && typeof c[0] === 'number') {
      const [x, y] = c as number[]
      b[0] = Math.min(b[0], x); b[1] = Math.min(b[1], y); b[2] = Math.max(b[2], x); b[3] = Math.max(b[3], y)
    } else if (Array.isArray(c)) c.forEach(walk)
  }
  walk('coordinates' in geom ? geom.coordinates : [])
  return b
}

/** Leave room for the side panel on wide screens, the bottom sheet on phones. */
function cameraPadding(): { top: number; bottom: number; left: number; right: number } {
  return window.innerWidth > 760
    ? { top: 60, bottom: 60, left: 300, right: 420 }
    : { top: 40, bottom: Math.round(window.innerHeight * 0.5), left: 20, right: 20 }
}

function IssuePanel({ id, onClose }: { id: string; onClose: () => void }) {
  const [issue, setIssue] = useState<IssueDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    setIssue(null)
    setError(null)
    api.issue(id).then(setIssue).catch((e: Error) => setError(e.message))
  }, [id])

  return (
    <aside className="map-side" aria-label="Pothole details">
      <div className="map-side-head">
        <div className="map-side-pills">
          {issue && <StatusPill status={issue.status} />}
          {issue && <SeverityBadge severity={issue.severity} />}
          {issue?.overdue && <span className="pill pill-bad">Overdue</span>}
        </div>
        <button className="icon-btn" onClick={onClose} aria-label="Close">×</button>
      </div>
      {error && <p className="bad">{error}</p>}
      {!issue && !error && <div className="skeleton" style={{ height: 220 }} />}
      {issue && (
        <div className="map-side-body">
          <h2>{issue.ward_name ? `Ward ${issue.ward_no} · ${issue.ward_name}` : 'Outside GBA wards'}</h2>
          <p className="muted">
            {issue.corporation ? `${issue.corporation} City Corporation · ` : ''}reported {ago(issue.opened_at)} ·{' '}
            {issue.report_count} report{issue.report_count === 1 ? '' : 's'}
          </p>
          <div className="panel facts">
            <div><span>Responsible office</span><strong>{issue.authority_name ?? 'None assigned'}</strong></div>
            <div><span>Deadline</span><DeadlineBar opened={issue.opened_at} due={issue.due_at} overdue={issue.overdue} /></div>
            <div><span>Escalation</span><strong>{issue.escalation_level === 0 ? 'Ward office' : `Level ${issue.escalation_level}`}</strong></div>
          </div>
          <div className="row">
            <Link className="btn primary" to={`/issue/${issue.id}`}>Full status page →</Link>
            <a className="btn" target="_blank" rel="noreferrer"
               href={`https://www.google.com/maps/dir/?api=1&destination=${issue.lat},${issue.lng}`}>🧭 Directions</a>
          </div>
          <h3>History</h3>
          <Timeline events={issue.events.slice(-6)} />
          {issue.events.length > 6 && (
            <Link to={`/issue/${issue.id}`} className="small">See all {issue.events.length} events</Link>
          )}
        </div>
      )}
    </aside>
  )
}

export default function MapPage() {
  const [params, setParams] = useSearchParams()
  const focus = params.get('focus')
  const mapRef = useRef<MapRef>(null)
  const [data, setData] = useState<IssueFeatureCollection | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(focus)
  const [wardPick, setWardPick] = useState<WardPick | null>(null)
  const [wards, setWards] = useState<GeoJSON.FeatureCollection<GeoJSON.Geometry, WardProps> | null>(null)
  const [visible, setVisible] = useState<Set<string>>(() => new Set(DEFAULT_ON))
  const [showWards, setShowWards] = useState(true)
  const [panelOpen, setPanelOpen] = useState(() => window.innerWidth > 760)

  const load = useCallback(() => {
    setError(null)
    api.issues().then(setData).catch((e: Error) => setError(e.message))
  }, [])
  useEffect(load, [load])

  // Ward boundaries rarely change: load once.
  useEffect(() => {
    api.wards().then(setWards).catch(() => setWards(null))
  }, [])

  const counts = useMemo(() => {
    const c: Record<string, number> = {}
    data?.features.forEach((f) => (c[f.properties.status] = (c[f.properties.status] ?? 0) + 1))
    return c
  }, [data])
  const shown = useMemo(() => (data?.features ?? []).filter((f) => visible.has(f.properties.status)).length, [data, visible])

  const flyToIssue = useCallback((id: string, lng: number, lat: number) => {
    setSelectedId(id)
    setWardPick(null)
    setParams({ focus: id }, { replace: true })
    const map = mapRef.current
    if (map) map.flyTo({ center: [lng, lat], zoom: Math.max(map.getZoom(), FOCUS_ZOOM), duration: 1200, padding: cameraPadding(), essential: true })
  }, [setParams])

  // Deep link (?focus=<issue>) or a focus set before the map finished loading.
  useEffect(() => {
    if (!data || !focus) return
    const f = data.features.find((x) => x.id === focus)
    if (f) {
      const [lng, lat] = f.geometry.coordinates
      setSelectedId(focus)
      setTimeout(() => mapRef.current?.flyTo({ center: [lng, lat], zoom: FOCUS_ZOOM, duration: 1200, padding: cameraPadding() }), 300)
    }
    // run once per data load
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data])

  function closeIssue() {
    setSelectedId(null)
    setParams({}, { replace: true })
  }

  function toggle(status: string) {
    setVisible((prev) => {
      const next = new Set(prev)
      if (next.has(status)) next.delete(status)
      else next.add(status)
      return next
    })
  }

  function onClick(e: MapLayerMouseEvent) {
    const issue = e.features?.find((f) => f.layer.id === 'issues')
    if (issue && issue.geometry.type === 'Point') {
      const [lng, lat] = issue.geometry.coordinates
      return flyToIssue(String(issue.properties?.id), lng, lat)
    }
    const ward = e.features?.find((f) => f.layer.id === 'ward-fill')
    if (ward) {
      const props = ward.properties as WardProps
      setSelectedId(null)
      setWardPick({ lng: e.lngLat.lng, lat: e.lngLat.lat, props, key: `${props.corporation}-${props.ward_no}` })
      const [x0, y0, x1, y1] = bboxOf(ward.geometry)
      mapRef.current?.fitBounds([[x0, y0], [x1, y1]], { padding: cameraPadding(), duration: 1000, maxZoom: 16 })
      return
    }
    setWardPick(null)
  }

  const statusFilter = ['in', ['get', 'status'], ['literal', [...visible]]] as unknown as boolean
  const selectedFilter = ['==', ['get', 'id'], selectedId ?? ''] as unknown as boolean
  const wardFilter = ['all', ['==', ['get', 'corporation'], wardPick?.props.corporation ?? ''], ['==', ['get', 'ward_no'], wardPick?.props.ward_no ?? -1]] as unknown as boolean

  return (
    <div className="map-page">
      <aside className={`map-panel${panelOpen ? '' : ' collapsed'}`}>
        <div className="map-panel-head">
          <div>
            <div className="map-count">{data ? shown : '…'}</div>
            <div className="muted small">potholes shown{data ? ` of ${data.features.length}` : ''}</div>
          </div>
          <button className="icon-btn" onClick={() => setPanelOpen((v) => !v)} aria-label={panelOpen ? 'Hide panel' : 'Show panel'}>
            {panelOpen ? '‹' : '›'}
          </button>
        </div>
        {panelOpen && (
          <>
            {error && <p className="bad small">{error}</p>}
            <div className="map-section-title">Status</div>
            <div className="map-filters">
              {FILTERABLE.map((s) => (
                <button key={s} className={`map-filter${visible.has(s) ? ' on' : ''}`} onClick={() => toggle(s)} aria-pressed={visible.has(s)}>
                  <span className="pill-dot" style={{ background: STATUS_COLORS[s] }} />
                  <span>{STATUS_LABEL[s] ?? s}</span>
                  <span className="map-filter-count">{counts[s] ?? 0}</span>
                </button>
              ))}
            </div>
            <label className="map-toggle">
              <input type="checkbox" checked={showWards} onChange={(e) => setShowWards(e.target.checked)} />
              Ward boundaries
            </label>
            {showWards && (
              <div className="map-corps">
                {Object.entries(CORPORATION_COLORS).map(([name, color]) => (
                  <span key={name}><span className="pill-dot" style={{ background: color }} />{name}</span>
                ))}
              </div>
            )}
            <div className="muted small map-help">Bigger pin = more severe. Tap a pin to fly to it; tap a ward to zoom to it.</div>
            <div className="row" style={{ margin: '8px 0 0' }}>
              <button onClick={load}>↻ Refresh</button>
              <button onClick={() => mapRef.current?.flyTo({ center: [BENGALURU.longitude, BENGALURU.latitude], zoom: BENGALURU.zoom, duration: 1000 })}>⤢ All Bengaluru</button>
              <Link className="btn primary" to="/report">+ Report</Link>
            </div>
          </>
        )}
      </aside>

      {data && (
        <Map
          ref={mapRef}
          initialViewState={BENGALURU}
          mapStyle={OSM_STYLE}
          interactiveLayerIds={showWards ? ['issues', 'ward-fill'] : ['issues']}
          onClick={onClick}
          cursor="pointer"
          style={{ width: '100%', height: '100%' }}
        >
          <NavigationControl position="bottom-right" />
          {wards && (
            <Source id="wards" type="geojson" data={wards}>
              <Layer id="ward-fill" type="fill" layout={{ visibility: showWards ? 'visible' : 'none' }}
                     paint={{ 'fill-color': corpColor, 'fill-opacity': 0.06 }} />
              <Layer id="ward-line" type="line" layout={{ visibility: showWards ? 'visible' : 'none' }}
                     paint={{ 'line-color': corpColor, 'line-width': 0.8, 'line-opacity': 0.6 }} />
              <Layer id="ward-picked" type="line" filter={wardFilter}
                     paint={{ 'line-color': corpColor, 'line-width': 3, 'line-opacity': 0.95 }} />
            </Source>
          )}
          <Source id="issues" type="geojson" data={data}>
            <Layer
              id="issue-ring"
              type="circle"
              filter={selectedFilter}
              paint={{ 'circle-radius': ringRadius, 'circle-color': circleColor, 'circle-opacity': 0.25,
                       'circle-stroke-width': 2, 'circle-stroke-color': circleColor }}
            />
            <Layer
              id="issues"
              type="circle"
              filter={statusFilter}
              paint={{
                'circle-radius': circleRadius,
                'circle-color': circleColor,
                'circle-stroke-width': 2,
                'circle-stroke-color': '#ffffff',
              }}
            />
          </Source>
          {wardPick && (
            <Popup key={wardPick.key} longitude={wardPick.lng} latitude={wardPick.lat} onClose={() => setWardPick(null)} closeOnClick={false} maxWidth="280px">
              <div className="map-pop">
                <div className="map-pop-title">Ward {wardPick.props.ward_no} · {wardPick.props.name}</div>
                {wardPick.props.name_kn && <div className="map-pop-sub">{wardPick.props.name_kn}</div>}
                <div className="map-pop-meta">{wardPick.props.corporation} City Corporation · {wardPick.props.zone ?? 'zone unknown'}</div>
              </div>
            </Popup>
          )}
        </Map>
      )}

      {selectedId && <IssuePanel id={selectedId} onClose={closeIssue} />}
    </div>
  )
}

import type { ReactNode } from 'react'
import type { Box, Watch, WatchRuntime, Zone } from '../lib/api'
import { useLive } from '../lib/live'
import { LiveImage } from './LiveImage'
import { TripwireShape } from './Tripwire'
import { cx } from './ui'

type Props = {
  cameraId: number
  /** the camera's own width / height */
  aspect?: number
  /** every view is this shape, whatever the camera: a phone's tall picture sits centred in it */
  frame?: number
  watches?: Watch[]
  focusWatchId?: number
  showDetections?: boolean
  showLabels?: boolean
  fps?: number
  className?: string
  children?: ReactNode
  rounded?: boolean
}

function tone(rt: WatchRuntime | undefined) {
  if (!rt) return 'var(--muted)'
  if (rt.paused) return 'var(--muted)'
  if (rt.phase === 'active' && rt.cond) return 'var(--alert)'
  if (rt.phase === 'pending' || rt.cond) return 'var(--warn)'
  return 'var(--accent)'
}

export function ZoneShape({ zone, color, dashed }: { zone: Zone; color: string; dashed?: boolean }) {
  const pts = zone.points.map(([x, y]) => `${x},${y}`).join(' ')
  return (
    <polygon
      points={pts}
      fill={color}
      fillOpacity={0.08}
      stroke={color}
      strokeWidth={2}
      strokeDasharray={dashed ? '6 4' : undefined}
      vectorEffect="non-scaling-stroke"
      strokeLinejoin="round"
    />
  )
}

export function BoxShape({ box, color, width = 2 }: { box: Box; color: string; width?: number }) {
  // the Vigil target: a faint outline with solid corner brackets
  const [x1, y1, x2, y2] = box
  const L = Math.min(x2 - x1, y2 - y1) * 0.28
  const d = `M${x1},${y1 + L}V${y1}H${x1 + L}M${x2 - L},${y1}H${x2}V${y1 + L}M${x2},${y2 - L}V${y2}H${x2 - L}M${x1 + L},${y2}H${x1}V${y2 - L}`
  return (
    <g>
      <rect x={x1} y={y1} width={x2 - x1} height={y2 - y1} fill="none" stroke={color} strokeOpacity={0.35} strokeWidth={1} vectorEffect="non-scaling-stroke" />
      <path d={d} fill="none" stroke={color} strokeWidth={width + 1} vectorEffect="non-scaling-stroke" strokeLinecap="square" />
    </g>
  )
}

function Tag({ x, y, color, children }: { x: number; y: number; color: string; children: ReactNode }) {
  return (
    <div
      className="absolute -translate-y-full whitespace-nowrap px-1.5 py-[2px] font-mono text-[10.5px] font-medium uppercase tracking-[0.08em] text-black/90"
      style={{ left: `${x * 100}%`, top: `${y * 100}%`, background: color, maxWidth: '60%', overflow: 'hidden', textOverflow: 'ellipsis' }}
    >
      {children}
    </div>
  )
}

export function CameraView({ cameraId, aspect = 16 / 9, frame = 16 / 9, watches = [], focusWatchId, showDetections = true, showLabels = true, fps = 5, className, children, rounded = true }: Props) {
  const perception = useLive((s) => s.perception[cameraId])
  const rtById = new Map((perception?.watches ?? []).map((w) => [w.id, w]))
  const shown = focusWatchId ? watches.filter((w) => w.id === focusWatchId) : watches
  const focusRt = focusWatchId ? rtById.get(focusWatchId) : undefined

  return (
    <div className={cx('relative flex w-full items-center justify-center overflow-hidden bg-black', rounded && 'rounded-lg', className)} style={{ aspectRatio: String(frame) }}>
      {Math.abs(aspect - frame) > 0.02 && (
        // a soft, dark copy of the feed fills the sides so a tall or wide camera still reads as one tile
        <LiveImage cameraId={cameraId} fps={1} className="absolute inset-0 h-full w-full scale-110 opacity-45 blur-2xl" />
      )}
      {/* the picture at its true shape; zones, boxes and labels are drawn in its coordinates */}
      <div className="relative max-h-full max-w-full" style={aspect < frame ? { height: '100%', aspectRatio: String(aspect) } : { width: '100%', aspectRatio: String(aspect) }}>
      <LiveImage cameraId={cameraId} fps={fps} className="absolute inset-0 h-full w-full" />
      <svg className="pointer-events-none absolute inset-0 h-full w-full" viewBox="0 0 1 1" preserveAspectRatio="none">
        {shown.map((w) =>
          w.spec.zone ? <ZoneShape key={w.id} zone={w.spec.zone} color={tone(rtById.get(w.id))} dashed={w.status !== 'active'} /> : null,
        )}
        {shown.map((w) =>
          w.spec.line && w.spec.crossing !== 'none' ? (
            <TripwireShape key={`l${w.id}`} line={w.spec.line} crossing={w.spec.crossing} color={tone(rtById.get(w.id))} />
          ) : null,
        )}
        {showDetections &&
          perception?.detections.map((d, i) => (
            <BoxShape key={i} box={d.box} color={focusWatchId ? 'rgba(242,242,240,0.45)' : 'rgba(242,242,240,0.85)'} width={focusWatchId ? 1 : 1.5} />
          ))}
        {focusRt?.tracks.map((t) => (
          <BoxShape key={t.id} box={t.box} color={(t.score ?? 0) >= focusRt.threshold ? 'var(--alert)' : 'var(--accent)'} width={2.5} />
        ))}
      </svg>
      {showLabels && (
        <div className="pointer-events-none absolute inset-0">
          {shown.map((w) => {
            const pts = w.spec.zone?.points ?? (w.spec.crossing !== 'none' ? w.spec.line : null)
            if (!pts) return null
            const xs = pts.map((p) => p[0])
            const ys = pts.map((p) => p[1])
            const rt = rtById.get(w.id)
            const val = rt ? (rt.kind === 'state' ? `${Math.round((rt.score ?? 0) * 100)}%` : `${rt.count ?? 0}`) : ''
            return (
              <Tag key={w.id} x={Math.min(...xs)} y={Math.max(0.03, Math.min(...ys))} color={tone(rt)}>
                {w.name} {val && <span className="num opacity-80">· {val}</span>}
              </Tag>
            )
          })}
          {focusRt?.tracks.map((t) => (
            <Tag key={t.id} x={t.box[0]} y={Math.max(0.03, t.box[1])} color={(t.score ?? 0) >= focusRt.threshold ? 'var(--alert)' : 'var(--accent)'}>
              {t.label} #{t.id} {t.score !== null && <span className="num">{Math.round(t.score * 100)}%</span>}
            </Tag>
          ))}
          {showDetections && !focusWatchId &&
            perception?.detections.slice(0, 12).map((d, i) => (
              <Tag key={i} x={d.box[0]} y={Math.max(0.03, d.box[1])} color="rgba(242,242,240,0.85)">
                {d.label} <span className="num">{Math.round(d.conf * 100)}</span>
              </Tag>
            ))}
        </div>
      )}
      {children}
      </div>
    </div>
  )
}

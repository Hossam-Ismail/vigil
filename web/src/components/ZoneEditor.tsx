import { useRef, useState } from 'react'
import type { Box, Crossing, Point, Zone } from '../lib/api'
import { BoxShape, ZoneShape } from './CameraView'
import { LiveImage } from './LiveImage'
import { TripwireShape } from './Tripwire'

type Rect = [number, number, number, number]

function zoneToRect(z: Zone | null): Rect | null {
  if (!z || z.points.length < 3) return null
  const xs = z.points.map((p) => p[0])
  const ys = z.points.map((p) => p[1])
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)]
}

export function rectToZone([x1, y1, x2, y2]: Rect): Zone {
  return { points: [[x1, y1], [x2, y1], [x2, y2], [x1, y2]] }
}

const clamp = (v: number) => Math.max(0, Math.min(1, v))

type Drag =
  | { mode: 'line-new'; ox: number; oy: number }
  | { mode: 'line-end'; end: number }
  | { mode: 'new'; ox: number; oy: number }
  | { mode: 'move'; ox: number; oy: number; start: Rect }
  | { mode: 'corner'; corner: number; start: Rect }

/** Draw, move or resize the watched region on a live camera view. Candidate boxes can be clicked. */
export function ZoneEditor({
  cameraId,
  zone,
  onChange,
  aspect = 16 / 9,
  candidates = [],
  line = null,
  crossing = 'none',
  onLineChange,
}: {
  cameraId: number
  zone: Zone | null
  onChange: (z: Zone | null) => void
  aspect?: number
  candidates?: Box[]
  line?: Point[] | null
  crossing?: Crossing
  onLineChange?: (l: Point[]) => void
}) {
  const ref = useRef<HTMLDivElement>(null)
  const [drag, setDrag] = useState<Drag | null>(null)
  const lineMode = crossing !== 'none' && !!onLineChange
  const rect = lineMode ? null : zoneToRect(zone)

  const pos = (e: React.PointerEvent) => {
    const r = ref.current!.getBoundingClientRect()
    return [clamp((e.clientX - r.left) / r.width), clamp((e.clientY - r.top) / r.height)] as const
  }

  const onDown = (e: React.PointerEvent) => {
    const [x, y] = pos(e)
    ;(e.target as Element).setPointerCapture?.(e.pointerId)
    const target = e.target as HTMLElement
    if (lineMode) {
      const end = target.dataset.end
      setDrag(end !== undefined && line ? { mode: 'line-end', end: Number(end) } : { mode: 'line-new', ox: x, oy: y })
      return
    }
    const corner = target.dataset.corner
    if (corner !== undefined && rect) {
      setDrag({ mode: 'corner', corner: Number(corner), start: rect })
    } else if (target.dataset.body && rect) {
      setDrag({ mode: 'move', ox: x, oy: y, start: rect })
    } else {
      setDrag({ mode: 'new', ox: x, oy: y })
    }
  }

  const onMove = (e: React.PointerEvent) => {
    if (!drag) return
    const [x, y] = pos(e)
    if (drag.mode === 'line-new') {
      if (Math.abs(x - drag.ox) < 0.01 && Math.abs(y - drag.oy) < 0.01) return
      onLineChange?.([[drag.ox, drag.oy], [x, y]])
      return
    }
    if (drag.mode === 'line-end') {
      if (!line) return
      const next = line.map((p) => [...p]) as Point[]
      next[drag.end] = [x, y]
      onLineChange?.(next)
      return
    }
    if (drag.mode === 'new') {
      if (Math.abs(x - drag.ox) < 0.01 && Math.abs(y - drag.oy) < 0.01) return
      onChange(rectToZone([Math.min(x, drag.ox), Math.min(y, drag.oy), Math.max(x, drag.ox), Math.max(y, drag.oy)]))
    } else if (drag.mode === 'move') {
      const [x1, y1, x2, y2] = drag.start
      const dx = Math.max(-x1, Math.min(1 - x2, x - drag.ox))
      const dy = Math.max(-y1, Math.min(1 - y2, y - drag.oy))
      onChange(rectToZone([x1 + dx, y1 + dy, x2 + dx, y2 + dy]))
    } else {
      let [x1, y1, x2, y2] = drag.start
      if (drag.corner === 0 || drag.corner === 3) x1 = x
      else x2 = x
      if (drag.corner === 0 || drag.corner === 1) y1 = y
      else y2 = y
      onChange(rectToZone([Math.min(x1, x2), Math.min(y1, y2), Math.max(x1, x2), Math.max(y1, y2)]))
    }
  }

  const onUp = () => setDrag(null)

  const corners = rect
    ? [
        [rect[0], rect[1]],
        [rect[2], rect[1]],
        [rect[2], rect[3]],
        [rect[0], rect[3]],
      ]
    : []

  return (
    <div
      ref={ref}
      className="relative w-full overflow-hidden rounded-lg bg-black cursor-crosshair touch-none"
      style={{ aspectRatio: String(aspect) }}
      onPointerDown={onDown}
      onPointerMove={onMove}
      onPointerUp={onUp}
      onPointerCancel={onUp}
    >
      <LiveImage cameraId={cameraId} fps={3} className="absolute inset-0 h-full w-full pointer-events-none" />
      <svg className="absolute inset-0 h-full w-full pointer-events-none" viewBox="0 0 1 1" preserveAspectRatio="none">
        {!rect && !lineMode && <rect x={0} y={0} width={1} height={1} fill="none" stroke="var(--accent)" strokeWidth={3} strokeDasharray="8 6" vectorEffect="non-scaling-stroke" />}
        {!lineMode && candidates.map((b, i) => (
          <BoxShape key={i} box={b} color="rgba(255,255,255,0.35)" width={1} />
        ))}
        {!lineMode && zone && <ZoneShape zone={zone} color="var(--accent)" />}
        {lineMode && line && <TripwireShape line={line} crossing={crossing} color="var(--accent)" />}
      </svg>
      {lineMode &&
        line?.map(([px, py], i) => (
          <div
            key={`end${i}`}
            data-end={i}
            className="absolute size-4 -translate-x-1/2 -translate-y-1/2 cursor-grab rounded-full border-2 border-accent bg-black"
            style={{ left: `${px * 100}%`, top: `${py * 100}%`, zIndex: 3 }}
          />
        ))}
      {!lineMode && candidates.map((b, i) => (
        <button
          key={i}
          type="button"
          title="Use this region"
          onPointerDown={(e) => {
            e.stopPropagation()
            onChange(rectToZone(b))
          }}
          className="absolute rounded-sm border border-transparent hover:border-white/70 hover:bg-white/10"
          style={{ left: `${b[0] * 100}%`, top: `${b[1] * 100}%`, width: `${(b[2] - b[0]) * 100}%`, height: `${(b[3] - b[1]) * 100}%`, cursor: 'pointer', zIndex: 1 }}
        />
      ))}
      {rect && (
        <div
          data-body="1"
          className="absolute cursor-move"
          style={{ left: `${rect[0] * 100}%`, top: `${rect[1] * 100}%`, width: `${(rect[2] - rect[0]) * 100}%`, height: `${(rect[3] - rect[1]) * 100}%`, zIndex: 2 }}
        />
      )}
      {corners.map(([cx_, cy], i) => (
        <div
          key={i}
          data-corner={i}
          className="absolute size-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-accent bg-black"
          style={{ left: `${cx_ * 100}%`, top: `${cy * 100}%`, cursor: i % 2 === 0 ? 'nwse-resize' : 'nesw-resize', zIndex: 3 }}
        />
      ))}
    </div>
  )
}

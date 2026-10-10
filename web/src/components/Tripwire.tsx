import type { Crossing, Point } from '../lib/api'

export const CROSS_DIR: Record<Exclude<Crossing, 'none' | 'any'>, Point> = {
  down: [0, 1],
  up: [0, -1],
  left: [-1, 0],
  right: [1, 0],
}

export const CROSS_LABEL: Record<Crossing, string> = {
  none: 'Anywhere in the region',
  any: 'Crossing the line (either way)',
  down: 'Crossing the line moving down ↓',
  up: 'Crossing the line moving up ↑',
  left: 'Crossing the line moving left ←',
  right: 'Crossing the line moving right →',
}

/** SVG tripwire in normalized coordinates (viewBox 0..1, preserveAspectRatio none). */
export function TripwireShape({ line, crossing, color }: { line: Point[]; crossing: Crossing; color: string }) {
  if (line.length !== 2) return null
  const [[x1, y1], [x2, y2]] = line
  const mx = (x1 + x2) / 2
  const my = (y1 + y2) / 2
  const dirs: Point[] = crossing === 'any' ? [CROSS_DIR.down, CROSS_DIR.up] : crossing === 'none' ? [] : [CROSS_DIR[crossing]]
  const L = 0.07
  return (
    <g>
      <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="black" strokeOpacity={0.6} strokeWidth={6} vectorEffect="non-scaling-stroke" strokeLinecap="round" />
      <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={color} strokeWidth={3} vectorEffect="non-scaling-stroke" strokeLinecap="round" strokeDasharray="10 6" />
      {dirs.map(([dx, dy], i) => {
        const ex = mx + dx * L
        const ey = my + dy * L
        const hx = dy !== 0 ? 0.018 : 0
        const hy = dx !== 0 ? 0.03 : 0
        return (
          <g key={i}>
            <line x1={mx} y1={my} x2={ex} y2={ey} stroke={color} strokeWidth={3} vectorEffect="non-scaling-stroke" />
            <polygon
              points={`${ex + dx * 0.025},${ey + dy * 0.035} ${ex + hx},${ey + hy} ${ex - hx},${ey - hy}`}
              fill={color}
            />
          </g>
        )
      })}
    </g>
  )
}

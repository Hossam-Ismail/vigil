/** Score history over the last few minutes, with the decision threshold as a dashed line. */
export function Sparkline({
  points,
  threshold,
  max = 1,
  height = 64,
  window = 120,
  stepped,
}: {
  points: [number, number][]
  threshold?: number
  max?: number
  height?: number
  window?: number
  stepped?: boolean
}) {
  const W = 300
  const H = height
  const pad = 3
  const x = (t: number) => W + (t / window) * W
  const y = (v: number) => pad + (1 - Math.min(v, max) / max) * (H - 2 * pad)
  const pts = points.filter(([t]) => t >= -window)
  let d = ''
  pts.forEach(([t, v], i) => {
    if (i === 0) d += `M${x(t).toFixed(1)},${y(v).toFixed(1)}`
    else if (stepped) d += `H${x(t).toFixed(1)}V${y(v).toFixed(1)}`
    else d += `L${x(t).toFixed(1)},${y(v).toFixed(1)}`
  })
  const area = pts.length ? `${d}L${x(pts[pts.length - 1][0]).toFixed(1)},${H}L${x(pts[0][0]).toFixed(1)},${H}Z` : ''
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height }} preserveAspectRatio="none">
      <defs>
        <linearGradient id="spark-fill" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.25" />
          <stop offset="100%" stopColor="var(--accent)" stopOpacity="0" />
        </linearGradient>
      </defs>
      {threshold !== undefined && (
        <line x1={0} x2={W} y1={y(threshold)} y2={y(threshold)} stroke="var(--alert)" strokeOpacity={0.7} strokeDasharray="4 4" vectorEffect="non-scaling-stroke" />
      )}
      {area && <path d={area} fill="url(#spark-fill)" />}
      {d && <path d={d} fill="none" stroke="var(--accent)" strokeWidth={1.75} vectorEffect="non-scaling-stroke" strokeLinejoin="round" />}
    </svg>
  )
}

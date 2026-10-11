import type { MetricKind, MetricPoint } from '../lib/api'

/** A metric over time: bars for totals (crossings) and shares (occupancy), a line with a peak band for counts. */
export function MetricChart({
  kind,
  series,
  hours,
  bucket,
  height = 140,
}: {
  kind: MetricKind
  series: MetricPoint[]
  hours: number
  bucket: number
  height?: number
}) {
  const W = 600
  const H = height
  const padL = 34
  const padB = 20
  const now = Date.now() / 1000
  const t0 = now - hours * 3600
  const x = (t: number) => padL + ((t - t0) / (now - t0)) * (W - padL - 4)
  const top = kind === 'occupancy' ? 100 : Math.max(1, ...series.map((p) => (kind === 'count' ? p.peak : p.value)))
  const yMax = kind === 'occupancy' ? 100 : niceCeil(top)
  const y = (v: number) => 4 + (1 - Math.min(v, yMax) / yMax) * (H - padB - 8)
  const bw = Math.max(1.5, (bucket / (now - t0)) * (W - padL - 4) - 1.5)
  const ticks = [t0, t0 + (now - t0) / 2, now]
  const label = (t: number) => {
    const d = new Date(t * 1000)
    return hours > 48 ? d.toLocaleDateString([], { weekday: 'short' }) : d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
  }
  const line = series.map((p, i) => `${i ? 'L' : 'M'}${(x(p.ts) + bw / 2).toFixed(1)},${y(p.value).toFixed(1)}`).join('')
  const band = series.length
    ? series.map((p, i) => `${i ? 'L' : 'M'}${(x(p.ts) + bw / 2).toFixed(1)},${y(p.peak).toFixed(1)}`).join('') +
      [...series].reverse().map((p) => `L${(x(p.ts) + bw / 2).toFixed(1)},${y(p.value).toFixed(1)}`).join('') + 'Z'
    : ''
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height }} role="img" aria-label="Metric over time">
      {[0, 0.5, 1].map((f) => (
        <g key={f}>
          <line x1={padL} x2={W} y1={y(yMax * f)} y2={y(yMax * f)} stroke="var(--color-line)" strokeDasharray={f ? '3 4' : undefined} />
          <text x={padL - 6} y={y(yMax * f) + 4} textAnchor="end" fontSize="10.5" fill="var(--color-muted)">
            {fmt(yMax * f)}{kind === 'occupancy' ? '%' : ''}
          </text>
        </g>
      ))}
      {kind === 'count' ? (
        <>
          {band && <path d={band} fill="var(--accent)" fillOpacity={0.14} />}
          {line && <path d={line} fill="none" stroke="var(--accent)" strokeWidth={2} strokeLinejoin="round" />}
          {series.length > 0 && (
            <circle cx={x(series[series.length - 1].ts) + bw / 2} cy={y(series[series.length - 1].value)} r={3.5} fill="var(--accent)" />
          )}
        </>
      ) : (
        series.map((p) => (
          <rect key={p.ts} x={x(p.ts)} y={y(p.value)} width={bw} height={Math.max(0, H - padB - 4 - y(p.value))} rx={1.5} fill="var(--accent)" fillOpacity={0.85} />
        ))
      )}
      {ticks.map((t, i) => (
        <text key={t} x={i === 0 ? padL : i === 2 ? W - 2 : x(t)} y={H - 4} textAnchor={i === 0 ? 'start' : i === 2 ? 'end' : 'middle'} fontSize="10.5" fill="var(--color-muted)">
          {i === 2 ? 'now' : label(t)}
        </text>
      ))}
    </svg>
  )
}

function niceCeil(v: number) {
  if (v <= 5) return Math.ceil(v)
  const p = 10 ** Math.floor(Math.log10(v))
  return Math.ceil(v / p) * p
}

function fmt(v: number) {
  return Number.isInteger(v) ? String(v) : v.toFixed(1)
}

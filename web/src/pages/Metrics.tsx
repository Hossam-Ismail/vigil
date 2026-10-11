import { BarChart3, BellOff } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Page } from '../components/Layout'
import { MetricChart } from '../components/MetricChart'
import { PromptBar } from '../components/PromptBar'
import { Card, cx, Empty } from '../components/ui'
import type { Camera, MetricOut } from '../lib/api'
import { useFetch, useInterval } from '../lib/hooks'

const RANGES = [
  { label: '1 hour', hours: 1, bucket: 120 },
  { label: '24 hours', hours: 24, bucket: 1800 },
  { label: '7 days', hours: 168, bucket: 3 * 3600 },
]

/** The headline number for a metric, plus the two supporting stats under it. */
export function metricHeadline(m: MetricOut): { value: string; unit: string; stats: [string, string][] } {
  const s = m.summary
  const unit = m.metric.unit
  const n = (v: number | null | undefined, d = 1) => (v === null || v === undefined ? '—' : Number.isInteger(v) ? String(v) : v.toFixed(d))
  if (m.metric.kind === 'count')
    return { value: n(s.now as number | null), unit: `${unit} now`, stats: [['average', n(s.avg)], ['peak', n(s.peak, 0)]] }
  if (m.metric.kind === 'crossings')
    return { value: n(s.total), unit, stats: [['last hour', n(s.last_hour)], ['per hour', n(s.per_hour)]] }
  return {
    value: s.pct === null || s.pct === undefined ? '—' : `${n(s.pct)}%`,
    unit: 'of the time',
    stats: [['right now', s.now === null || s.now === undefined ? '—' : s.now ? 'yes' : 'no'], ['checks', n(s.checks)]],
  }
}

export function MetricCard({ m, hours, bucket }: { m: MetricOut; hours: number; bucket: number }) {
  const h = metricHeadline(m)
  return (
    <Card className="flex flex-col gap-3 p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Link to={`/watches/${m.watch_id}`} className="block truncate font-medium hover:underline">{m.metric.name}</Link>
          <div className="truncate text-[12.5px] text-muted">{m.camera_name}{m.status !== 'active' && ` · ${m.status}`}</div>
        </div>
        {!m.alerts && (
          <span className="inline-flex shrink-0 items-center gap-1 rounded-md border border-line px-2 py-0.5 text-[11px] text-muted" title="This watch only measures; it never alerts">
            <BellOff className="size-3" /> tracking only
          </span>
        )}
      </div>
      <div className="flex items-end justify-between gap-4">
        <div className="flex items-baseline gap-2">
          <span className="num text-[44px] font-semibold leading-none text-accent">{h.value}</span>
          <span className="text-[13px] text-muted">{h.unit}</span>
        </div>
        <div className="flex gap-5 text-right">
          {h.stats.map(([k, v]) => (
            <div key={k}>
              <div className="num text-[17px] font-medium">{v}</div>
              <div className="text-[11px] uppercase tracking-wide text-muted">{k}</div>
            </div>
          ))}
        </div>
      </div>
      {m.series.length ? (
        <MetricChart kind={m.metric.kind} series={m.series} hours={hours} bucket={bucket} />
      ) : (
        <div className="grid h-[140px] place-items-center rounded-lg border border-dashed border-line text-[12.5px] text-muted">
          Collecting… the first point lands within a minute.
        </div>
      )}
    </Card>
  )
}

export function Metrics() {
  const [range, setRange] = useState(1)
  const r = RANGES[range]
  const metrics = useFetch<MetricOut[]>(`/api/metrics?hours=${r.hours}&bucket=${r.bucket}`, [range])
  const cams = useFetch<Camera[]>('/api/cameras')
  useInterval(() => metrics.reload(), 15000)
  const list = metrics.data ?? []
  return (
    <Page
      title="Metrics"
      subtitle="Numbers your cameras keep: counts, walk-ins, and how much of the time something is true."
      actions={
        <div className="flex rounded-lg border border-line p-0.5">
          {RANGES.map((x, i) => (
            <button
              key={x.label}
              onClick={() => setRange(i)}
              className={cx('rounded-md px-3 py-1.5 text-[12.5px]', i === range ? 'bg-panel-2 text-ink' : 'text-muted hover:text-ink')}
            >
              {x.label}
            </button>
          ))}
        </div>
      }
    >
      <div className="mb-6"><PromptBar cameras={cams.data ?? []} compact /></div>
      {list.length ? (
        <div className="grid gap-4 lg:grid-cols-2">
          {list.map((m) => <MetricCard key={m.watch_id} m={m} hours={r.hours} bucket={r.bucket} />)}
        </div>
      ) : (
        <Card>
          <Empty icon={<BarChart3 className="size-8" />} title="No metrics yet">
            Ask for a number instead of an alert: “Count walk-ins at the front door”, “How many people are waiting in line?”
            or “What % of the time is the staging area empty?”
          </Empty>
        </Card>
      )}
    </Page>
  )
}

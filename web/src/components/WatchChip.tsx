import { Link } from 'react-router-dom'
import type { Watch, WatchRuntime } from '../lib/api'
import { useLive } from '../lib/live'
import { cx, KindBadge, Meter } from './ui'

export function liveRuntime(w: Watch, perception?: { watches: WatchRuntime[] }): WatchRuntime | null {
  return perception?.watches.find((r) => r.id === w.id) ?? w.runtime
}

export function runtimeTone(rt: WatchRuntime | null): 'alert' | 'warn' | 'ok' | 'accent' {
  if (!rt) return 'accent'
  if (rt.phase === 'active' && rt.cond) return 'alert'
  if (rt.phase === 'pending' || rt.cond) return 'warn'
  return 'ok'
}

export function RuntimeValue({ w, rt }: { w: Watch; rt: WatchRuntime | null }) {
  if (!rt) return <span className="text-muted">—</span>
  if (w.spec.kind === 'state') return <span className="num">{Math.round((rt.score ?? 0) * 100)}%</span>
  return (
    <span className="num">
      {rt.count ?? 0}
      <span className="text-muted"> {w.spec.kind === 'count' ? `${w.spec.count_op} ${w.spec.count_value}` : 'seen'}</span>
    </span>
  )
}

export function WatchChip({ w }: { w: Watch }) {
  const perception = useLive((s) => s.perception[w.camera_id])
  const rt = liveRuntime(w, perception)
  const tone = runtimeTone(rt)
  const alerting = tone === 'alert'
  const meterVal = w.spec.kind === 'state' ? rt?.score ?? 0 : Math.min(1, (rt?.count ?? 0) / Math.max(1, w.spec.count_value * 2))
  return (
    <Link
      to={`/watches/${w.id}`}
      className={cx(
        'group block rounded-lg border px-3 py-2 transition-colors',
        alerting ? 'border-alert/50 bg-alert-soft' : 'border-line bg-panel-2 hover:border-line-2',
      )}
    >
      <div className="flex items-center gap-2">
        {alerting ? <span className="size-1.5 rounded-full bg-alert pulse-alert" /> : <span className={cx('size-1.5 rounded-full', w.status === 'active' ? (tone === 'warn' ? 'bg-warn' : 'bg-ok') : 'bg-muted')} />}
        <span className="min-w-0 flex-1 truncate text-[13px] font-medium">{w.name}</span>
        <span className="hud hidden text-[9.5px] text-muted group-hover:inline">OPEN →</span>
        <KindBadge kind={w.spec.kind} />
        <span className="text-[12.5px] w-14 text-right">
          {w.status === 'active' ? <RuntimeValue w={w} rt={rt} /> : <span className="text-muted capitalize">{w.status}</span>}
        </span>
      </div>
      {w.status === 'active' && (
        <div className="mt-1.5">
          <Meter value={meterVal} threshold={w.spec.kind === 'state' ? rt?.threshold : 0.5} tone={tone} />
        </div>
      )}
    </Link>
  )
}

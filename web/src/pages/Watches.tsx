import { Eye } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Page } from '../components/Layout'
import { PromptBar } from '../components/PromptBar'
import { Card, cx, Empty, KindBadge, Meter, StatusPill } from '../components/ui'
import { liveRuntime, runtimeTone, RuntimeValue } from '../components/WatchChip'
import type { Camera, Watch } from '../lib/api'
import { pct, timeAgo } from '../lib/format'
import { useFetch, useInterval } from '../lib/hooks'
import { useLive } from '../lib/live'

function Row({ w }: { w: Watch }) {
  const perception = useLive((s) => s.perception[w.camera_id])
  const rt = liveRuntime(w, perception)
  const tone = runtimeTone(rt)
  const f1 = w.metrics?.cv?.f1
  return (
    <Link to={`/watches/${w.id}`} className="grid grid-cols-[minmax(0,2.2fr)_minmax(0,1fr)_110px_120px_90px] items-center gap-4 px-4 py-3 hover:bg-panel-2 max-lg:grid-cols-[minmax(0,1fr)_110px]">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="truncate font-medium">{w.name}</span>
          <KindBadge kind={w.spec.kind} />
        </div>
        <div className="truncate text-[12.5px] text-muted">“{w.prompt}”</div>
      </div>
      <div className="truncate text-[12.5px] text-ink-2 max-lg:hidden">{w.camera_name}</div>
      <div><StatusPill status={w.status} alerting={tone === 'alert'} /></div>
      <div className="max-lg:hidden">
        {w.status === 'active' ? (
          <div>
            <div className="text-[12.5px]"><RuntimeValue w={w} rt={rt} /></div>
            {w.spec.kind === 'state' && <div className="mt-1"><Meter value={rt?.score ?? 0} threshold={rt?.threshold} tone={tone} /></div>}
          </div>
        ) : <span className="text-muted">—</span>}
      </div>
      <div className="text-right text-[12px] text-muted max-lg:hidden">
        <div className="num">{f1 !== undefined ? `F1 ${pct(f1)}` : w.metrics?.mode ?? '—'}</div>
        <div>{w.last_event ? timeAgo(w.last_event.ts) : 'no events'}</div>
      </div>
    </Link>
  )
}

export function Watches() {
  const watches = useFetch<Watch[]>('/api/watches')
  const cams = useFetch<Camera[]>('/api/cameras')
  useInterval(() => watches.reload(), 10000)
  const list = watches.data ?? []
  return (
    <Page title="Watches" subtitle="Each watch is a small vision model built from one sentence.">
      <div className="mb-6"><PromptBar cameras={cams.data ?? []} compact /></div>
      {list.length ? (
        <Card className={cx('divide-y divide-line overflow-hidden')}>
          <div className="grid grid-cols-[minmax(0,2.2fr)_minmax(0,1fr)_110px_120px_90px] gap-4 px-4 py-2 text-[11.5px] uppercase tracking-wide text-muted max-lg:hidden">
            <span>Watch</span><span>Camera</span><span>Status</span><span>Now</span><span className="text-right">Model</span>
          </div>
          {list.map((w) => <Row key={w.id} w={w} />)}
        </Card>
      ) : (
        <Card><Empty icon={<Eye className="size-8" />} title="No watches yet">Describe what you want to be alerted about above, and Vigil will build a detector for it.</Empty></Card>
      )}
    </Page>
  )
}

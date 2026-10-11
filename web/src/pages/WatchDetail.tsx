import { ArrowLeft, Pause, Play, RefreshCw, Save, Settings2, Trash2, Wand2, X } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { CameraView } from '../components/CameraView'
import { EventRow } from '../components/EventRow'
import { Page } from '../components/Layout'
import { SampleThumb } from '../components/SampleThumb'
import { Button, Card, cx, Empty, KindBadge, SectionTitle, StatusPill } from '../components/ui'
import { liveRuntime, runtimeTone } from '../components/WatchChip'
import { ZoneEditor } from '../components/ZoneEditor'
import { api, type Camera, type Sample, type VEvent, type Watch, type WatchSpec } from '../lib/api'
import { dateTime, duration, ORIGIN_LABEL, SOURCE_LABEL, timeAgo } from '../lib/format'
import { useFetch, useInterval } from '../lib/hooks'
import { useLive } from '../lib/live'
import { ModelSummary } from './NewWatch'
import { PlanEditor } from '../components/PlanEditor'

type Filter = 'all' | 'yes' | 'no' | 'review'

function LiveState({ w }: { w: Watch }) {
  const perception = useLive((s) => s.perception[w.camera_id])
  const rt = liveRuntime(w, perception)
  const tone = runtimeTone(rt)
  const isState = w.spec.kind === 'state'
  const tripwire = w.spec.kind === 'presence' && w.spec.crossing !== 'none'
  const phaseText =
    w.status !== 'active'
      ? w.status === 'paused' ? 'Paused' : w.status_detail || w.status
      : !rt
        ? 'Starting…'
        : rt.phase === 'active' && rt.cond
          ? 'Condition is true — alert raised'
          : rt.phase === 'pending'
            ? `Condition looks true — confirming for ${duration(w.spec.min_duration_s)}`
            : 'All normal'

  return (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-[11.5px] uppercase tracking-wide text-muted">
            {isState ? 'Probability YES' : tripwire ? 'Crossings · last minute' : 'Matching objects'}
          </div>
          <div className={cx('num mt-0.5 text-[34px] font-semibold leading-none', tone === 'alert' ? 'text-alert' : tone === 'warn' ? 'text-warn' : 'text-ink')}>
            {rt ? (isState ? `${Math.round((rt.score ?? 0) * 100)}%` : rt.count ?? 0) : '—'}
          </div>
        </div>
        <div className="text-right">
          <div className={cx('inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[12px] font-medium',
            tone === 'alert' ? 'bg-alert-soft text-alert' : tone === 'warn' ? 'bg-warn-soft text-warn' : 'bg-ok-soft text-ok')}>
            <span className={cx('size-1.5 rounded-full', tone === 'alert' ? 'bg-alert pulse-alert' : tone === 'warn' ? 'bg-warn' : 'bg-ok live-dot')} />
            {phaseText}
          </div>
          {rt && isState && <div className="num mt-1.5 text-[11.5px] text-muted">alerts above {Math.round(rt.threshold * 100)}%</div>}
          {!isState && (
            <div className="num mt-1.5 text-[11.5px] text-muted">
              {tripwire ? `alerts on each crossing (${w.spec.crossing})` : `alerts when count ${w.spec.count_op} ${w.spec.count_value}`}
            </div>
          )}
        </div>
      </div>
    </Card>
  )
}

function TeachBar({ w, onDone }: { w: Watch; onDone: () => void }) {
  const [busy, setBusy] = useState<number | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const teach = async (label: number) => {
    setBusy(label)
    setMsg(null)
    try {
      const r = await api.post<{ added: Sample[] }>(`/api/watches/${w.id}/teach`, { label })
      setMsg(`Added ${r.added.length} example${r.added.length === 1 ? '' : 's'} and retrained.`)
      onDone()
    } catch (e) {
      setMsg((e as Error).message)
    } finally {
      setBusy(null)
    }
  }
  return (
    <Card className="flex flex-wrap items-center gap-2 px-4 py-3">
      <div className="min-w-[180px] flex-1">
        <div className="text-[13px] font-medium">Teach it from what you see</div>
        <div className="text-[12px] text-muted">{msg ?? (w.spec.kind === 'state' ? 'Label the watched region as it looks right now.' : 'Label the objects currently in view.')}</div>
      </div>
      <Button size="sm" loading={busy === 1} onClick={() => teach(1)} className="border-alert/40 text-alert">
        This is a YES
      </Button>
      <Button size="sm" loading={busy === 0} onClick={() => teach(0)}>
        This is normal
      </Button>
    </Card>
  )
}


/** What you're looking at, in three lines; open after building a watch (?new=1), closable, and back on request. */
function WatchGuide({ w }: { w: Watch }) {
  const [params, setParams] = useSearchParams()
  const [open, setOpen] = useState(params.has('new'))
  const close = () => { setOpen(false); if (params.has('new')) { params.delete('new'); setParams(params, { replace: true }) } }
  if (!open) {
    return <button onClick={() => setOpen(true)} className="mb-4 text-[12.5px] text-muted underline-offset-2 hover:text-ink hover:underline">How to read this page</button>
  }
  const presence = w.spec.kind !== 'state'
  return (
    <div className="slide-in mb-5 rounded-2xl border border-accent/40 bg-accent/5 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="hud flex items-center gap-2 text-[11px] text-accent"><span className="size-1.5 rounded-full bg-accent live-dot" />WATCHING NOW · {w.name}</div>
        <button onClick={close} className="text-muted hover:text-ink" aria-label="Close"><X className="size-4" /></button>
      </div>
      <ol className="mt-3 grid gap-3 text-[14px] md:grid-cols-3">
        <li><span className="num mr-1.5 text-accent">1</span><b className="font-medium">The video is what Vigil sees.</b> <span className="text-muted">{presence ? 'Boxes mark what it found; red means it matches your request.' : 'The bar on the right shows how sure it is, right now.'}</span></li>
        <li><span className="num mr-1.5 text-accent">2</span><b className="font-medium">When it happens, you get an alert.</b> <span className="text-muted">It shows up in Alerts below, and as an iMessage if your number is set up.</span></li>
        <li><span className="num mr-1.5 text-accent">3</span><b className="font-medium">Teach it.</b> <span className="text-muted">Mark an alert right or wrong; that watch learns from it.</span></li>
      </ol>
    </div>
  )
}

export function WatchDetail() {
  const { id } = useParams()
  const wid = Number(id)
  const nav = useNavigate()
  const watch = useFetch<Watch>(`/api/watches/${wid}`)
  const samples = useFetch<Sample[]>(`/api/watches/${wid}/samples`)
  const events = useFetch<VEvent[]>(`/api/events?watch_id=${wid}&limit=30`)
  const cams = useFetch<Camera[]>('/api/cameras')
  const [filter, setFilter] = useState<Filter>('all')
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<WatchSpec | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const modelTick = useLive((s) => s.modelTick)
  const eventTick = useLive((s) => s.eventTick)
  const build = useLive((s) => s.builds[wid])

  useEffect(() => {
    watch.reload()
    samples.reload()
  }, [modelTick]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    events.reload()
  }, [eventTick]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (build?.stage === 'done' || build?.stage === 'error') {
      watch.reload()
      samples.reload()
    }
  }, [build?.stage]) // eslint-disable-line react-hooks/exhaustive-deps
  useInterval(() => watch.reload(), watch.data?.status === 'building' ? 2000 : 15000)

  const w = watch.data
  const cam = cams.data?.find((c) => c.id === w?.camera_id)
  const aspect = cam?.width && cam.height ? cam.width / cam.height : 16 / 9

  const filtered = useMemo(() => {
    const all = samples.data ?? []
    if (filter === 'yes') return all.filter((s) => s.label === 1)
    if (filter === 'no') return all.filter((s) => s.label === 0)
    if (filter === 'review') return all.filter((s) => s.label === null)
    return all
  }, [samples.data, filter])

  if (watch.error) return <Page title="Watch"><Card><Empty title="Watch not found">{watch.error}</Empty></Card></Page>
  if (!w) return null

  const act = async (name: string, fn: () => Promise<unknown>) => {
    setBusy(name)
    try {
      await fn()
      await watch.reload()
    } finally {
      setBusy(null)
    }
  }

  const cycle = async (s: Sample) => {
    const next = s.label === 1 ? 0 : s.label === 0 ? null : 1
    samples.setData((list) => (list ?? []).map((x) => (x.id === s.id ? { ...x, label: next, source: 'user' } : x)))
    await api.patch(`/api/samples/${s.id}`, { label: next })
  }

  const saveSpec = async () => {
    if (!draft) return
    await act('save', () => api.patch(`/api/watches/${w.id}`, { spec: draft, name: draft.name }))
    setEditing(false)
  }

  const m = w.metrics ?? {}
  const counts = w.samples
  return (
    <Page
      wide
      title={
        <span className="flex items-center gap-2">
          <Link to="/watches" className="rounded-md p-1 text-muted hover:bg-panel-2 hover:text-ink" aria-label="Back">
            <ArrowLeft className="size-5" />
          </Link>
          <span className="truncate">{w.name}</span>
          <KindBadge kind={w.spec.kind} />
          <StatusPill status={w.status} alerting={!!(w.runtime?.cond && w.runtime.phase === 'active')} />
        </span>
      }
      subtitle={<>on <Link className="text-ink-2 hover:underline" to={`/cameras/${w.camera_id}`}>{w.camera_name}</Link> · created {timeAgo(w.created_at)}</>}
      actions={
        <>
          {w.status === 'active' && <Button icon={<Pause className="size-4" />} loading={busy === 'pause'} onClick={() => act('pause', () => api.post(`/api/watches/${w.id}/pause`))}>Pause</Button>}
          {w.status === 'paused' && <Button icon={<Play className="size-4" />} loading={busy === 'resume'} onClick={() => act('resume', () => api.post(`/api/watches/${w.id}/resume`))}>Resume</Button>}
          <Button
            icon={<Wand2 className="size-4" />}
            loading={busy === 'build' || w.status === 'building'}
            onClick={() => act('build', () => api.post(`/api/watches/${w.id}/build`, {}))}
          >
            {w.status === 'draft' ? 'Build' : 'Rebuild'}
          </Button>
          <Button variant="ghost" icon={<Settings2 className="size-4" />} onClick={() => { setDraft(w.spec); setEditing((v) => !v) }}>Edit rule</Button>
          <Button
            variant="danger"
            icon={<Trash2 className="size-4" />}
            onClick={async () => {
              if (!confirm(`Delete “${w.name}” and its training data?`)) return
              await api.del(`/api/watches/${w.id}`)
              nav('/watches')
            }}
          />
        </>
      }
    >
      <Card className="mb-5 px-4 py-3">
        <div className="text-[15px] leading-6">“{w.prompt}”</div>
        <div className="mt-1 text-[13px] text-muted">{w.spec.summary}</div>
        {w.status === 'building' && <div className="mt-2 text-[12.5px] text-info">{build?.message ?? w.status_detail}</div>}
        {w.status !== 'building' && w.status_detail && w.status_detail !== 'ready' && <div className="mt-2 text-[12.5px] text-warn">{w.status_detail}</div>}
      </Card>


      {editing && draft && (
        <Card className="mb-5 p-5 slide-in">
          <div className="grid gap-6 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
            <div>
              <SectionTitle>Region</SectionTitle>
              <ZoneEditor cameraId={w.camera_id} zone={draft.zone} onChange={(z) => setDraft({ ...draft, zone: z })} aspect={aspect}
                line={draft.line} crossing={draft.crossing} onLineChange={(l) => setDraft({ ...draft, line: l })} />
              <div className="mt-2 flex justify-end">
                <Button size="sm" variant="ghost" onClick={() => setDraft({ ...draft, zone: null })}>Use whole frame</Button>
              </div>
            </div>
            <div>
              <SectionTitle>Rule</SectionTitle>
              <PlanEditor spec={draft} onChange={setDraft} />
              <div className="mt-5 flex gap-2">
                <Button variant="primary" icon={<Save className="size-4" />} loading={busy === 'save'} onClick={saveSpec}>Save</Button>
                <Button variant="ghost" onClick={() => setEditing(false)}>Cancel</Button>
              </div>
              <div className="mt-2 text-[12px] text-muted">Changing the region or labels changes what the model sees; rebuild afterwards for best results.</div>
            </div>
          </div>
        </Card>
      )}

      <WatchGuide w={w} />
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
        <div className="flex flex-col gap-4">
          <CameraView cameraId={w.camera_id} aspect={aspect} watches={[w]} focusWatchId={w.id} fps={6} />
          {(w.status === 'active' || w.status === 'paused') && <TeachBar w={w} onDone={() => { samples.reload(); watch.reload() }} />}
        </div>
        <div className="flex flex-col gap-4">
          <LiveState w={w} />
          <Card className="p-4">
            <SectionTitle>How it decides</SectionTitle>
            <p className="text-[14px] leading-relaxed text-ink-2">{w.metrics?.dataset?.how ?? w.spec.summary}</p>
            <div className="mt-3 flex flex-wrap gap-1.5">
              {(w.metrics?.dataset?.models ?? []).map((md) => (
                <span key={md.name} className="rounded-md border border-line bg-panel-2 px-2 py-1 text-[12px] text-ink-2">{md.name}</span>
              ))}
              <span className="rounded-md border border-line bg-panel-2 px-2 py-1 text-[12px] text-ink-2">a second AI double-checks each alert</span>
            </div>
            <div className="mt-3 text-[12.5px] text-muted">Ready-made models, nothing to train. Mark alerts right or wrong below and this watch learns from it.</div>
            <details className="mt-3 text-[12.5px]">
              <summary className="cursor-pointer text-muted hover:text-ink">Technical details</summary>
              <div className="mt-3">
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-muted">Model v{w.model_version}</span>
                  <Button size="sm" variant="ghost" icon={<RefreshCw className="size-3.5" />} loading={busy === 'retrain'} onClick={() => act('retrain', () => api.post(`/api/watches/${w.id}/retrain`))}>Retrain</Button>
                </div>
                <ModelSummary m={m} />
                <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-muted">
                  {m.sources && Object.entries(m.sources).map(([k, v]) => <span key={k}>{v} from {SOURCE_LABEL[k] ?? k}</span>)}
                  {m.trained_at && <span>trained {timeAgo(m.trained_at)}{m.reason ? ` (${m.reason})` : ''}</span>}
                </div>
              </div>
            </details>
          </Card>
        </div>
      </div>

      <div className="mt-8">
        <SectionTitle
          right={
            <div className="flex rounded-lg border border-line bg-panel p-0.5 text-[12.5px]">
              {([
                ['all', `All ${counts.total}`],
                ['yes', `Yes ${counts.yes}`],
                ['no', `No ${counts.no}`],
                ['review', `Needs review ${counts.unlabeled}`],
              ] as [Filter, string][]).map(([k, label]) => (
                <button key={k} onClick={() => setFilter(k)} className={cx('rounded-md px-2.5 h-7', filter === k ? 'bg-panel-3 text-ink' : 'text-muted hover:text-ink')}>
                  {label}
                </button>
              ))}
            </div>
          }
        >
          Training data
        </SectionTitle>
        <div className="mb-3 text-[12.5px] text-muted">
          Every example the model learned from. Click one to change its label (yes → no → needs review); the model retrains in milliseconds.
        </div>
        {filtered.length ? (
          <div className="grid gap-2 [grid-template-columns:repeat(auto-fill,minmax(120px,1fr))]">
            {filtered.map((s) => (
              <div key={s.id}>
                <SampleThumb s={s} onCycle={cycle} />
                <div className="mt-0.5 truncate text-[10.5px] text-muted">
                  {SOURCE_LABEL[s.source] ?? s.source} · {ORIGIN_LABEL[s.origin] ?? s.origin}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <Card><Empty title="No examples here">{filter === 'review' ? 'Nothing waiting for review.' : 'Build the watch to collect examples.'}</Empty></Card>
        )}
      </div>

      <div className="mt-8">
        <SectionTitle>Events</SectionTitle>
        {events.data?.length ? (
          <Card className="divide-y divide-line">
            {events.data.map((e) => <EventRow key={e.id} e={e} onChange={() => events.reload()} hideWatch />)}
          </Card>
        ) : (
          <Card><Empty title="No events yet">When this watch fires, alerts appear here with a snapshot and clip.</Empty></Card>
        )}
        {w.last_event && <div className="mt-2 text-[12px] text-muted">Last event {dateTime(w.last_event.ts)}</div>}
      </div>
    </Page>
  )
}

import { AlertTriangle, ArrowLeft, Check, Crosshair, Eye, Maximize, ShieldAlert, Sparkles, Wand2 } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { CameraView } from '../components/CameraView'
import { Page } from '../components/Layout'
import { SampleThumb } from '../components/SampleThumb'
import { Button, Card, cx, KindBadge, Spinner } from '../components/ui'
import { ZoneEditor } from '../components/ZoneEditor'
import { PlanEditor } from '../components/PlanEditor'
import { api, type ApiError, type Camera, type Health, type Metrics, type Watch, type PolicyRefusal, type WatchSpec } from '../lib/api'
import { pct } from '../lib/format'
import { useFetch, useNow } from '../lib/hooks'
import { clearBuild, useLive } from '../lib/live'

const ZONE_METHOD: Record<string, string> = {
  set_of_mark: 'I marked candidate regions and picked the one that matches your description.',
  vlm_box: 'I located the region directly in the image.',
  siglip_rank: 'I ranked candidate regions by how well they match your description.',
  single_candidate: 'I found one region that matches.',
  full_frame: 'Watching the whole frame.',
  error: 'I could not locate the region automatically.',
}

const STAGES = [
  { key: 'collect', label: 'Collect frames', hint: 'History + a short live capture' },
  { key: 'candidates', label: 'Find candidates', hint: 'Crops of the region or objects' },
  { key: 'label', label: 'Auto-label', hint: 'The brain answers your question' },
  { key: 'train', label: 'Train model', hint: 'A small head on vision embeddings' },
  { key: 'done', label: 'Live', hint: 'Running on every frame' },
] as const

export function ModelSummary({ m }: { m: Metrics }) {
  const trained = m.mode === 'trained'
  const cv = m.cv
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      <Stat label="Examples" value={`${m.n ?? 0}`} sub={`${m.n_pos ?? 0} yes · ${m.n_neg ?? 0} no`} />
      <Stat
        label="Model"
        value={trained ? 'Trained' : m.mode === 'oneclass_neg' ? 'Calibrated' : 'Zero-shot'}
        sub={trained ? (m.low_data ? 'few examples so far' : `${m.cv_folds}-fold validated`) : m.mode === 'oneclass_neg' ? 'waiting for a YES example' : 'from text only'}
      />
      <Stat label="Validated F1" value={cv ? pct(cv.f1) : '—'} sub={cv ? `precision ${pct(cv.precision)} · recall ${pct(cv.recall)}` : 'needs 2+ of each label'} />
      <Stat
        label="Accuracy"
        value={cv ? pct(cv.accuracy) : m.fit ? pct(m.fit.accuracy) : '—'}
        sub={m.zero_shot ? `text prompt alone: ${pct(m.zero_shot.accuracy)}` : 'no labels yet'}
      />
    </div>
  )
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-lg border border-line bg-panel-2 px-3 py-2.5">
      <div className="text-[11.5px] uppercase tracking-wide text-muted">{label}</div>
      <div className="num mt-0.5 text-[20px] font-semibold">{value}</div>
      {sub && <div className="text-[11.5px] text-muted">{sub}</div>}
    </div>
  )
}

function CompileStatus() {
  const [start] = useState(() => Date.now() / 1000)
  const now = useNow(1000)
  const health = useFetch<Health>('/api/health')
  const brain = health.data?.brain
  const elapsed = Math.max(0, Math.round(now - start))
  return (
    <Card className="p-5">
      <div className="flex items-center gap-2 text-[13.5px] font-medium">
        <Spinner className="size-4 text-accent" /> Understanding your request
        <span className="num ml-auto text-[12px] text-muted">{elapsed}s</span>
      </div>
      <ul className="mt-4 flex flex-col gap-2.5 text-[13px] text-muted">
        <li>Reading what you asked for and what should count as an alert</li>
        <li>Looking at the current frame from this camera</li>
        <li>Finding the region or objects to focus on</li>
      </ul>
      <div className="mt-5 flex flex-col gap-2">
        {[80, 64, 72].map((w, i) => <div key={i} className="shimmer h-3 rounded" style={{ width: `${w}%` }} />)}
      </div>
      {brain && (
        <div className="mt-5 text-[12px] text-muted">
          Using {brain.label}.
          {brain.name === 'local' && ' Running on this Mac takes about a minute; with a Claude API key it takes a few seconds.'}
          {brain.name === 'heuristic' && ' This basic offline mode only understands simple requests; add a Claude key or a local model in Settings.'}
        </div>
      )}
    </Card>
  )
}

function BuildView({ watch, cam }: { watch: Watch; cam?: Camera }) {
  const build = useLive((s) => s.builds[watch.id])
  const samples = useLive((s) => s.buildSamples[watch.id]) ?? []
  const stage = build?.stage ?? 'collect'
  const idx = STAGES.findIndex((s) => s.key === stage)
  const done = stage === 'done'
  const failed = stage === 'error'
  const nYes = samples.filter((s) => s.label === 1).length
  const nNo = samples.filter((s) => s.label === 0).length
  const nUnsure = samples.filter((s) => s.label === null).length

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
      <div className="flex flex-col gap-4">
        <CameraView cameraId={watch.camera_id} aspect={cam?.width && cam.height ? cam.width / cam.height : 16 / 9} watches={[watch]} showDetections={false} fps={4} />
        <Card className="p-4">
          <div className="mb-3 flex items-center justify-between">
            <div className="text-[13px] font-semibold">Training examples</div>
            <div className="num text-[12px] text-muted">
              <span className="text-alert">{nYes} yes</span> · {nNo} no{nUnsure ? ` · ${nUnsure} need review` : ''}
            </div>
          </div>
          {samples.length ? (
            <div className="grid grid-cols-4 sm:grid-cols-6 gap-2">
              {samples.map((s) => (
                <SampleThumb key={s.id} s={s} size="sm" />
              ))}
            </div>
          ) : (
            <div className="grid grid-cols-6 gap-2">
              {Array.from({ length: 12 }).map((_, i) => (
                <div key={i} className="shimmer aspect-[4/3] rounded-lg" />
              ))}
            </div>
          )}
        </Card>
      </div>
      <Card className="p-5 h-fit">
        <div className="flex items-center gap-2 text-[12px] uppercase tracking-wide text-muted">
          <Wand2 className="size-3.5" /> Building your detector
        </div>
        <div className="mt-1 text-[17px] font-semibold">{watch.name}</div>
        <ol className="mt-5 flex flex-col">
          {STAGES.map((s, i) => {
            const state = failed && i === idx ? 'error' : i < idx || done ? 'done' : i === idx ? 'now' : 'todo'
            return (
              <li key={s.key} className="relative flex gap-3 pb-5 last:pb-0">
                {i < STAGES.length - 1 && <span className={cx('absolute left-[11px] top-6 bottom-0 w-px', state === 'done' ? 'bg-accent' : 'bg-line')} />}
                <span
                  className={cx(
                    'relative z-10 flex size-6 shrink-0 items-center justify-center rounded-full border text-[11px] font-bold',
                    state === 'done' && 'border-accent bg-accent text-accent-ink',
                    state === 'now' && 'border-accent text-accent',
                    state === 'todo' && 'border-line text-muted',
                    state === 'error' && 'border-alert bg-alert text-white',
                  )}
                >
                  {state === 'done' ? <Check className="size-3.5" /> : state === 'now' && !done ? <Spinner className="size-3.5 text-accent" /> : i + 1}
                </span>
                <div className="min-w-0 pt-0.5">
                  <div className={cx('text-[13.5px] font-medium', state === 'todo' && 'text-muted')}>
                    {s.key === 'label' && build?.brain ? `Auto-label with ${build.brain}` : s.label}
                  </div>
                  <div className="text-[12px] text-muted">{state === 'now' || (state === 'error') ? build?.message : s.hint}</div>
                </div>
              </li>
            )
          })}
        </ol>
        <div className="mt-5 h-1 w-full overflow-hidden rounded-full bg-panel-3">
          <div className={cx('h-full rounded-full transition-[width] duration-500', failed ? 'bg-alert' : 'bg-accent')} style={{ width: `${(build?.progress ?? 0.02) * 100}%` }} />
        </div>
        {done && build?.metrics && (
          <div className="mt-5 slide-in">
            <ModelSummary m={build.metrics} />
            <div className="mt-3 text-[12.5px] text-muted">{build.message}</div>
          </div>
        )}
        {(done || failed) && (
          <div className="mt-5 flex gap-2">
            <Link to={`/watches/${watch.id}`} onClick={() => clearBuild(watch.id)}>
              <Button variant="primary" icon={<Eye className="size-4" />}>Open watch</Button>
            </Link>
            <Link to="/" onClick={() => clearBuild(watch.id)}>
              <Button variant="ghost">Back to live</Button>
            </Link>
          </div>
        )}
      </Card>
    </div>
  )
}

export function NewWatch() {
  const [params, setParams] = useSearchParams()
  const resumeId = params.get('watch')
  const nav = useNavigate()
  const [watch, setWatch] = useState<Watch | null>(null)
  const cameraId = watch?.camera_id ?? Number(params.get('camera'))
  const prompt = watch?.prompt ?? params.get('prompt') ?? ''
  const cams = useFetch<Camera[]>('/api/cameras')
  const cam = cams.data?.find((c) => c.id === cameraId)
  const [spec, setSpec] = useState<WatchSpec | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [policy, setPolicy] = useState<PolicyRefusal | null>(null)
  const [phase, setPhase] = useState<'compiling' | 'review' | 'building'>('compiling')
  const [busy, setBusy] = useState(false)
  const started = useRef(false)
  const aspect = cam?.width && cam.height ? cam.width / cam.height : 16 / 9

  const compile = async () => {
    setError(null)
    setPhase('compiling')
    try {
      const w = await api.post<Watch>('/api/watches/draft', { camera_id: cameraId, prompt })
      setWatch(w)
      setSpec(w.spec)
      setPhase('review')
      // make a reload resume this draft instead of compiling a second one
      setParams({ watch: String(w.id) }, { replace: true })
    } catch (e) {
      setError((e as Error).message)
      setPolicy((e as ApiError).policy ?? null)
    }
  }

  useEffect(() => {
    if (started.current) return
    if (resumeId) {
      started.current = true
      api
        .get<Watch>(`/api/watches/${resumeId}`)
        .then((w) => {
          if (w.status === 'active' || w.status === 'paused') return nav(`/watches/${w.id}`, { replace: true })
          setWatch(w)
          setSpec(w.spec)
          setPhase(w.status === 'building' ? 'building' : 'review')
        })
        .catch((e) => setError((e as Error).message))
      return
    }
    if (!cameraId || !prompt) return
    started.current = true
    compile()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cameraId, prompt, resumeId])

  const startBuild = async () => {
    if (!watch || !spec) return
    setBusy(true)
    try {
      clearBuild(watch.id)
      await api.patch(`/api/watches/${watch.id}`, { spec, name: spec.name })
      const w = await api.post<Watch>(`/api/watches/${watch.id}/build`, {})
      setWatch(w)
      setPhase('building')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const discard = async () => {
    if (watch) await api.del(`/api/watches/${watch.id}`).catch(() => {})
    nav('/')
  }

  const candidates = useMemo(() => watch?.proposal?.candidates ?? [], [watch])
  const method = watch?.proposal?.method ?? null
  const compileInfo = watch?.metrics?.compile

  return (
    <Page
      wide
      title={
        <span className="flex items-center gap-2">
          <button onClick={() => (phase === 'review' ? discard() : nav(-1))} className="rounded-md p-1 text-muted hover:bg-panel-2 hover:text-ink" aria-label="Back">
            <ArrowLeft className="size-5" />
          </button>
          New watch
        </span>
      }
      subtitle={
        <span className="flex items-center gap-1.5">
          on <span className="text-ink-2 font-medium">{cam?.name ?? `camera ${cameraId}`}</span>
        </span>
      }
    >
      <Card className="mb-5 flex items-start gap-3 px-4 py-3">
        <Sparkles className="mt-0.5 size-4 shrink-0 text-accent" />
        <div className="text-[15px] leading-6">“{prompt}”</div>
      </Card>

      {policy && (
        <Card className="mb-5 border-warn/50 bg-warn-soft px-4 py-3 text-[13.5px]">
          <div className="flex items-center gap-2 font-medium text-warn"><ShieldAlert className="size-4" /> Vigil won't watch for this</div>
          <div className="mt-1 text-ink">{policy.reason}</div>
          <div className="mt-1 text-ink-2">{policy.suggestion}</div>
          <div className="mt-2 text-[12px] text-muted">Vigil watches objects, events and conditions, never kinds of people. It does not identify anyone or watch private spaces.</div>
          <div className="mt-3 flex gap-2">
            <Button size="sm" onClick={() => nav('/')}>Write a different request</Button>
          </div>
        </Card>
      )}

      {error && !policy && (
        <Card className="mb-5 border-alert/40 bg-alert-soft px-4 py-3 text-[13.5px]">
          <div className="flex items-center gap-2 font-medium text-alert"><AlertTriangle className="size-4" /> Something went wrong</div>
          <div className="mt-1 text-ink-2">{error}</div>
          <div className="mt-3 flex gap-2">
            <Button size="sm" onClick={phase === 'compiling' ? compile : startBuild}>Try again</Button>
            <Button size="sm" variant="ghost" onClick={() => nav('/')}>Cancel</Button>
          </div>
        </Card>
      )}

      {phase === 'compiling' && !error && (
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
          <div className="relative">
            <CameraView cameraId={cameraId} aspect={aspect} showDetections={false} fps={4}>
              <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-transparent via-accent/10 to-transparent bg-[length:100%_40%] bg-no-repeat animate-[scan_2.2s_ease-in-out_infinite]" />
            </CameraView>
          </div>
          <CompileStatus />
        </div>
      )}

      {phase === 'review' && watch && spec && (
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
          <div className="flex flex-col gap-3">
            <ZoneEditor cameraId={cameraId} zone={spec.zone} onChange={(z) => setSpec({ ...spec, zone: z })} aspect={aspect} candidates={candidates}
              line={spec.line} crossing={spec.crossing} onLineChange={(l) => setSpec({ ...spec, line: l })} />
            <div className="flex flex-wrap items-center gap-2 text-[12.5px] text-muted">
              <Crosshair className="size-3.5 text-accent" />
              <span className="flex-1 min-w-[200px]">
                {spec.crossing !== 'none'
                  ? 'Alerts fire when someone crosses this line in the arrow’s direction. Drag the ends to move it, or draw a new line.'
                  : <>{method ? ZONE_METHOD[method] ?? method : 'Draw the region to watch.'} Drag on the image to redraw{candidates.length > 1 ? ', or click a dashed box' : ''}.</>}
              </span>
              <Button size="sm" variant="ghost" icon={<Maximize className="size-3.5" />} onClick={() => setSpec({ ...spec, zone: null })}>
                Whole frame
              </Button>
            </div>
          </div>
          <Card className="p-5">
            <div className="flex items-center gap-2">
              <KindBadge kind={spec.kind} />
              {compileInfo && <span className="text-[12px] text-muted">compiled by {compileInfo.brain} in {(compileInfo.ms / 1000).toFixed(1)}s</span>}
            </div>
            <p className="mt-2 text-[14px] leading-6 text-ink-2">{spec.summary}</p>
            {[...(spec.clarifications ?? []), ...(watch.warnings ?? [])].length > 0 && (
              <div className="mt-3 rounded-lg border border-warn/40 bg-warn-soft px-3 py-2 text-[12.5px] text-ink-2">
                {[...(spec.clarifications ?? []), ...(watch.warnings ?? [])].map((c) => (
                  <div key={c} className="flex gap-1.5"><AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-warn" />{c}</div>
                ))}
              </div>
            )}
            <div className="my-5 h-px bg-line" />
            <PlanEditor spec={spec} onChange={setSpec} />
            <div className="mt-6 flex items-center gap-2">
              <Button variant="primary" loading={busy} onClick={startBuild} icon={<Wand2 className="size-4" />}>
                Build &amp; start watching
              </Button>
              <Button variant="ghost" onClick={discard}>Discard</Button>
            </div>
          </Card>
        </div>
      )}

      {phase === 'building' && watch && <BuildView watch={{ ...watch, spec: spec ?? watch.spec }} cam={cam} />}
    </Page>
  )
}

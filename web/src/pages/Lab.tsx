import { FlaskConical, Pause, Play } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { CameraView } from '../components/CameraView'
import { Page } from '../components/Layout'
import { Button, Card, cx, Field, inputCls } from '../components/ui'
import { api, type Camera } from '../lib/api'
import { useFetch } from '../lib/hooks'

type Scored = { option: string; p: number }
type ClipResult = { video: Scored[]; image: Scored[]; ms_video: number; ms_image: number; frames: number; span_s: number }

const DEFAULT_OPTIONS = 'a person touching their hair\na person sitting still'

/** Test bench: does a video-text model (a 1.5 s clip) answer better than a single frame? */
export function Lab() {
  const cams = useFetch<Camera[]>('/api/cameras')
  const [cameraId, setCameraId] = useState<number | null>(null)
  const [text, setText] = useState(DEFAULT_OPTIONS)
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<ClipResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [history, setHistory] = useState<{ video: string; image: string }[]>([])
  const busy = useRef(false)
  const cam = cams.data?.find((c) => c.id === cameraId) ?? cams.data?.[0]
  const options = text.split('\n').map((s) => s.trim()).filter(Boolean)

  useEffect(() => {
    if (!running || !cam) return
    const tick = async () => {
      if (busy.current) return // never stack requests; one check finishes before the next starts
      busy.current = true
      try {
        const r = await api.post<ClipResult>('/api/lab/clip', { camera_id: cam.id, options, seconds: 1.5 })
        setResult(r)
        setError(null)
        const top = (xs: Scored[]) => xs.reduce((a, b) => (b.p > a.p ? b : a)).option
        setHistory((h) => [{ video: top(r.video), image: top(r.image) }, ...h].slice(0, 20))
      } catch (e) {
        setError((e as Error).message)
      } finally {
        busy.current = false
      }
    }
    tick()
    const t = setInterval(tick, 1000)
    return () => clearInterval(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running, cam?.id, text])

  const aspect = cam?.width && cam.height ? cam.width / cam.height : 16 / 9
  return (
    <Page wide title={<span className="flex items-center gap-2"><FlaskConical className="size-5 text-accent" /> Lab</span>}
      subtitle="Try a video model on a live camera: it judges the last 1.5 seconds against your options">
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <div className="flex flex-col gap-3">
          {cam ? <CameraView key={cam.id} cameraId={cam.id} aspect={aspect} showDetections={false} fps={6} /> : <Card className="p-6 text-muted">No cameras yet.</Card>}
          <div className="flex flex-wrap gap-2 text-[12.5px]">
            {(cams.data ?? []).map((c) => (
              <button key={c.id} onClick={() => setCameraId(c.id)}
                className={cx('rounded-full border px-3 py-1', c.id === cam?.id ? 'border-accent text-accent' : 'border-line text-muted hover:text-ink')}>
                {c.name}
              </button>
            ))}
          </div>
        </div>
        <div className="flex flex-col gap-4">
          <Card className="p-5">
            <Field label="Options (one per line)" hint="Describe each possibility as a scene, e.g. “a person waving”">
              <textarea className={cx(inputCls, 'h-auto min-h-[96px] py-2 leading-5')} value={text} onChange={(e) => setText(e.target.value)} />
            </Field>
            <div className="mt-3 flex items-center gap-3">
              <Button variant="primary" disabled={!cam || options.length < 2} icon={running ? <Pause className="size-4" /> : <Play className="size-4" />}
                onClick={() => setRunning((r) => !r)}>
                {running ? 'Stop' : 'Start checking'}
              </Button>
              <span className="text-[12px] text-muted">One check per second. The first one loads the model (~10 s).</span>
            </div>
            {error && <div className="mt-3 text-[12.5px] text-alert">{error}</div>}
          </Card>
          {result && (
            <div className="grid gap-4 sm:grid-cols-2">
              <Bars title="Video model · last 1.5 s" sub={`${result.frames} frames over ${result.span_s}s · ${Math.round(result.ms_video)} ms`} rows={result.video} />
              <Bars title="Single frame · SigLIP2" sub={`newest frame only · ${Math.round(result.ms_image)} ms`} rows={result.image} />
            </div>
          )}
          {history.length > 0 && (
            <Card className="p-4">
              <div className="mb-2 text-[12px] font-semibold uppercase tracking-wide text-muted">Last answers, newest first</div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[12.5px]">
                <div className="text-muted">video model</div><div className="text-muted">single frame</div>
                {history.map((h, i) => (
                  <div key={i} className="contents">
                    <div className="truncate">{h.video}</div>
                    <div className="truncate text-ink-2">{h.image}</div>
                  </div>
                ))}
              </div>
            </Card>
          )}
        </div>
      </div>
    </Page>
  )
}

function Bars({ title, sub, rows }: { title: string; sub: string; rows: Scored[] }) {
  const best = Math.max(...rows.map((r) => r.p))
  return (
    <Card className="p-4">
      <div className="text-[13px] font-semibold">{title}</div>
      <div className="mb-3 text-[11.5px] text-muted">{sub}</div>
      <div className="flex flex-col gap-2.5">
        {rows.map((r) => (
          <div key={r.option}>
            <div className="flex justify-between gap-2 text-[12.5px]">
              <span className={cx('truncate', r.p === best && 'font-medium text-ink')}>{r.option}</span>
              <span className="num text-muted">{Math.round(r.p * 100)}%</span>
            </div>
            <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-panel-3">
              <div className={cx('h-full rounded-full', r.p === best ? 'bg-accent' : 'bg-line-2')} style={{ width: `${r.p * 100}%` }} />
            </div>
          </div>
        ))}
      </div>
    </Card>
  )
}

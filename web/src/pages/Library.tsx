import { Boxes, CheckCircle2, CircleDashed, ExternalLink, FlaskConical, Gauge, Play } from 'lucide-react'
import { Link, useNavigate } from 'react-router-dom'
import { Page } from '../components/Layout'
import { Button, Card, cx } from '../components/ui'
import type { Camera } from '../lib/api'
import { useFetch, useInterval } from '../lib/hooks'

export type LibModel = {
  id: string
  name: string
  what: string
  repo: string
  url: string
  kind: string
  native: boolean
  license: string
  speed_ms: number | null
  classes: string[]
  measured: string
  examples: string[]
  note: string
  status: string
  watches: string[]
}

/** The prebuilt model library: what each model answers, how fast it is here, and prompts that pick it. */
export function Library() {
  const lib = useFetch<LibModel[]>('/api/library')
  const cams = useFetch<Camera[]>('/api/cameras')
  useInterval(() => lib.reload(), 5000)
  const nav = useNavigate()
  const camId = cams.data?.[0]?.id
  const tryPrompt = (p: string) => camId !== undefined && nav(`/new?camera=${camId}&prompt=${encodeURIComponent(p)}`)
  const native = (lib.data ?? []).filter((m) => m.native)
  const other = (lib.data ?? []).filter((m) => !m.native)
  return (
    <Page wide title={<span className="flex items-center gap-2"><Boxes className="size-6 text-accent" /> Model library</span>}
      subtitle="Ten prebuilt vision models, already trained. Describe what to watch for and Vigil picks the right one automatically: no training, live in seconds.">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {native.map((m) => <ModelCard key={m.id} m={m} onTry={tryPrompt} />)}
      </div>
      <h2 className="mt-10 mb-3 text-[13px] font-semibold uppercase tracking-wide text-muted">Also in the library, not running watches yet</h2>
      <div className="grid gap-3 md:grid-cols-2">
        {other.map((m) => <ModelCard key={m.id} m={m} onTry={tryPrompt} />)}
      </div>
    </Page>
  )
}

function ModelCard({ m, onTry }: { m: LibModel; onTry: (p: string) => void }) {
  const ready = m.status === 'ready'
  return (
    <Card className={cx('flex flex-col p-4', !m.native && 'opacity-90')}>
      <div className="flex items-start justify-between gap-2">
        <div className="text-[15px] font-semibold leading-snug">{m.name}</div>
        <span className={cx('flex shrink-0 items-center gap-1 text-[11px]', ready ? 'text-ok' : 'text-muted')}>
          {ready ? <CheckCircle2 className="size-3.5" /> : <CircleDashed className="size-3.5 animate-spin" />}
          {ready ? 'ready' : m.status}
        </span>
      </div>
      <p className="mt-1 text-[12.5px] leading-snug text-ink-2">{m.what}</p>
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11.5px] text-muted">
        {m.speed_ms !== null && <span className="flex items-center gap-1"><Gauge className="size-3.5" />{m.speed_ms} ms on this Mac</span>}
        <a href={m.url} target="_blank" rel="noreferrer" className="flex items-center gap-1 hover:text-ink">{m.repo}<ExternalLink className="size-3" /></a>
      </div>
      {m.classes.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {m.classes.map((c) => <span key={c} className="rounded border border-line px-1.5 py-0.5 font-mono text-[10.5px] text-ink-2">{c}</span>)}
        </div>
      )}
      {m.measured && <div className="mt-2 rounded-md bg-panel-2 px-2 py-1.5 text-[11.5px] leading-snug text-ink-2">Measured: {m.measured}</div>}
      {m.note && <div className="mt-2 text-[11.5px] leading-snug text-warn">{m.note}</div>}
      <div className="mt-auto pt-3">
        {m.native ? (
          <div className="flex flex-col gap-1.5">
            {m.examples.slice(0, 2).map((e) => (
              <button key={e} onClick={() => onTry(e)}
                className="flex items-center gap-1.5 rounded-md border border-line px-2 py-1 text-left text-[12px] text-muted hover:border-accent hover:text-ink">
                <Play className="size-3 shrink-0 text-accent" /><span className="truncate">{e}</span>
              </button>
            ))}
            {m.watches.length > 0 && <div className="text-[11.5px] text-accent">Running: {m.watches.join(', ')}</div>}
          </div>
        ) : m.kind === 'xclip' ? (
          <Link to="/lab"><Button size="sm" icon={<FlaskConical className="size-3.5" />}>Try it in the Lab</Button></Link>
        ) : null}
        <div className="mt-2 text-[10.5px] text-muted">License: {m.license}</div>
      </div>
    </Card>
  )
}

/** Compact strip for the Live dashboard. */
export function LibraryStrip() {
  const lib = useFetch<LibModel[]>('/api/library')
  const native = (lib.data ?? []).filter((m) => m.native)
  if (!native.length) return null
  return (
    <div className="mb-5 flex flex-wrap items-center gap-2 text-[12px]">
      <Link to="/models" className="flex items-center gap-1.5 font-semibold text-ink hover:text-accent"><Boxes className="size-4 text-accent" /> Prebuilt models</Link>
      {native.map((m) => (
        <Link key={m.id} to="/models" title={m.what}
          className={cx('flex items-center gap-1.5 rounded-full border px-2.5 py-1', m.watches.length ? 'border-accent/60 text-ink' : 'border-line text-muted hover:text-ink')}>
          <span className={cx('size-1.5 rounded-full', m.status === 'ready' ? (m.watches.length ? 'bg-accent live-dot' : 'bg-ok') : 'bg-warn')} />
          {m.name}{m.watches.length > 0 && <span className="text-accent">· {m.watches.length} live</span>}
        </Link>
      ))}
    </div>
  )
}

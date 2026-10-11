import { ArrowRight, Check, Sparkles, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, type ApiError, type Camera, type Watch } from '../lib/api'
import { useFetch } from '../lib/hooks'
import { LoopVideo } from '../pages/landing/motion'
import { cx } from './ui'

type Example = {
  id: string; cat: string; title: string; camera: string; preview: string; poster: string
  prompt: string; safe?: string; how: string; expect: string; camera_id: number | null
}
type Step = { label: string; detail?: string; state: 'doing' | 'done' | 'bad' }
type Verdict = { allowed: boolean; category: string; reason: string; suggestion: string }

/** The dashboard's walkthrough: pick an example, check the prompt, click Build, and land on the watch running live.
 *  Each click does the real thing: it adds the footage as a camera, understands the request, and starts the watch. */
export function ExamplesPanel() {
  const examples = useFetch<Example[]>('/api/examples')
  const list = examples.data ?? []
  const [i, setI] = useState(0)
  const [prompt, setPrompt] = useState('')
  const [steps, setSteps] = useState<Step[]>([])
  const [busy, setBusy] = useState(false)
  const [secs, setSecs] = useState(0)
  const [refusal, setRefusal] = useState<{ reason: string; rewrite: string } | null>(null)
  const nav = useNavigate()
  const ex = list[i]
  const panel = useRef<HTMLElement>(null)
  // handed over from the website: ?example=<id>&ep=<prompt>
  const [hand] = useState(() => { const q = new URLSearchParams(window.location.search); return { id: q.get('example'), prompt: q.get('ep') } })

  useEffect(() => {
    if (!hand.id || !list.length) return
    const k = list.findIndex((x) => x.id === hand.id)
    if (k >= 0) setI(k)
    panel.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [list.length]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!ex) return
    setPrompt(hand.id === ex.id && hand.prompt ? hand.prompt : ex.prompt)
  }, [ex?.id]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!busy) return
    const t0 = Date.now()
    const id = setInterval(() => setSecs(Math.round((Date.now() - t0) / 1000)), 500)
    return () => clearInterval(id)
  }, [busy])

  if (!ex) return null

  const pick = (k: number) => { if (!busy) { setI(k); setSteps([]); setRefusal(null) } }
  const set = (k: number, st: Step) => setSteps((s) => { const n = [...s]; n[k] = st; return n })

  const build = async () => {
    const q = prompt.trim()
    if (!q || busy) return
    setBusy(true); setSteps([]); setRefusal(null)
    try {
      // every build starts with the safety check, so a misuse request stops here and nothing is set up
      set(0, { label: 'Checking it against the safety policy', state: 'doing' })
      const v = await api.post<Verdict>('/api/safety/check', { text: q })
      if (!v.allowed) {
        set(0, { label: 'Refused by the safety policy', detail: 'nothing was set up or watched', state: 'bad' })
        setRefusal({ reason: v.reason, rewrite: (q === ex.prompt && ex.safe) || v.suggestion })
        setBusy(false)
        return
      }
      set(0, { label: 'Passed the safety check', detail: 'it watches an event, not a person', state: 'done' })
      set(1, { label: 'Adding the footage as a camera', state: 'doing' })
      const cam = await api.post<Camera>(`/api/examples/${ex.id}/camera`)
      set(1, { label: 'Camera ready', detail: cam.name, state: 'done' })
      set(2, { label: 'Understanding your request', detail: 'what to look for, who to tell', state: 'doing' })
      const w = await api.post<Watch>('/api/watches/draft', { camera_id: cam.id, prompt: q })
      set(2, { label: 'Request understood', detail: w.name, state: 'done' })
      set(3, { label: 'Starting the watch', state: 'doing' })
      await api.post(`/api/watches/${w.id}/build`, {})
      set(3, { label: 'Watching now', detail: 'opening it…', state: 'done' })
      setTimeout(() => nav(`/watches/${w.id}?new=1`), 700)
    } catch (e) {
      const err = e as ApiError
      if (err.policy) {
        setSteps((s) => [...s.filter((x) => x.state === 'done'), { label: 'Refused by the safety policy', detail: 'nothing is watched', state: 'bad' }])
        setRefusal({ reason: err.policy.reason, rewrite: ex.safe || err.policy.suggestion })
      } else {
        setSteps((s) => [...s.filter((x) => x.state === 'done'), { label: 'Couldn’t build it', detail: err.message || 'Something went wrong.', state: 'bad' }])
      }
      setBusy(false)
    }
  }

  return (
    <section ref={panel} className="mb-8 scroll-mt-4 rounded-2xl border border-line bg-panel p-4 md:p-5">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <div className="hud flex items-center gap-2 text-[11px] text-accent"><Sparkles className="size-3.5" />TRY A READY-MADE EXAMPLE</div>
          <div className="mt-1 text-[20px] font-semibold">Pick one, check the prompt, and build it. It runs live in about 20 seconds.</div>
        </div>
        <div className="text-[12.5px] text-muted">Real footage · each click sets up a real camera and watch</div>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <div className="relative self-start overflow-hidden rounded-xl border border-line bg-black">
          <div className="hud absolute inset-x-0 top-0 z-10 flex items-center justify-between bg-gradient-to-b from-black/80 to-transparent px-3.5 py-2.5 text-[10.5px] text-white/80">
            <span className="flex items-center gap-1.5"><span className="size-1.5 rounded-full bg-accent live-dot" />{ex.camera}</span>
            <span>{ex.cat}</span>
          </div>
          <div className="relative aspect-video">
            {list.map((x, k) => (
              <div key={x.id} className={cx('absolute inset-0 transition-opacity duration-500', k === i ? 'opacity-100' : 'opacity-0')} aria-hidden={k !== i}>
                <LoopVideo src={x.preview} poster={x.poster} label={x.camera} className="h-full w-full object-cover" />
              </div>
            ))}
          </div>
          <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/85 to-transparent px-3.5 pb-3 pt-8 text-[13px] text-white/85">{ex.expect}</div>
        </div>

        <div className="flex flex-col">
          <label htmlFor="example-prompt" className="text-[13px] text-ink-2">1 · The prompt <span className="text-muted">(edit it if you like)</span></label>
          <textarea id="example-prompt" value={prompt} rows={3} maxLength={300} disabled={busy}
            onChange={(e) => setPrompt(e.target.value)}
            className="mt-1.5 resize-none rounded-xl border-2 border-line-2 bg-bg p-3.5 text-[16px] leading-relaxed outline-none transition-colors focus:border-accent disabled:opacity-70" />
          <div className="mt-2 text-[12.5px] text-muted">How Vigil runs it: {ex.how}</div>
          <div className="mt-4 text-[13px] text-ink-2">2 · Build it</div>
          <button onClick={build} disabled={busy || !prompt.trim()}
            className="hud mt-1.5 flex min-h-[52px] items-center justify-between rounded-lg bg-accent px-5 text-accent-ink transition-[filter,transform] hover:brightness-110 active:translate-y-px disabled:opacity-70">
            {busy ? `Building… ${secs}s` : 'Build this watch'} <ArrowRight className="size-4" />
          </button>
          <ol className="mt-3 flex flex-col gap-2" aria-live="polite">
            {steps.map((st, k) => (
              <li key={k} className="slide-in flex gap-2.5 text-[13.5px]">
                <span className={cx('mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full',
                  st.state === 'bad' ? 'bg-alert text-white' : st.state === 'done' ? 'bg-accent text-accent-ink' : 'border-2 border-accent border-t-transparent animate-spin')}>
                  {st.state === 'done' ? <Check className="size-3" /> : st.state === 'bad' ? <X className="size-3" /> : null}
                </span>
                <span><span className={st.state === 'bad' ? 'text-alert' : 'text-ink'}>{st.label}</span>{st.detail && <span className="text-muted"> · {st.detail}</span>}</span>
              </li>
            ))}
          </ol>
          {refusal && (
            <div className="slide-in mt-3 rounded-xl border border-alert/50 bg-alert-soft p-3.5">
              <div className="text-[14.5px] leading-snug">{refusal.reason}</div>
              {refusal.rewrite && (
                <button onClick={() => { setPrompt(refusal.rewrite); setRefusal(null); setSteps([]) }}
                  className="group mt-3 flex w-full items-start gap-2 rounded-lg border border-line bg-bg/60 px-3 py-2.5 text-left transition-colors hover:border-accent">
                  <span className="hud mt-0.5 shrink-0 text-[10px] text-accent">USE THE SAFE VERSION</span>
                  <span className="flex-1 text-[14px]">“{refusal.rewrite}”</span>
                  <ArrowRight className="mt-0.5 size-4 shrink-0 text-muted group-hover:text-accent" />
                </button>
              )}
            </div>
          )}
          {!steps.length && <div className="mt-3 text-[12.5px] text-muted">3 · You land on the watch: the video shows what Vigil sees, and alerts appear right under it.</div>}
        </div>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-3" role="tablist" aria-label="Examples">
        {list.map((x, k) => (
          <button key={x.id} role="tab" aria-selected={k === i} onClick={() => pick(k)} disabled={busy}
            className={cx('group flex gap-3 rounded-xl border p-2.5 text-left transition-colors disabled:opacity-60',
              k === i ? 'border-accent bg-panel-2' : 'border-line hover:border-line-2')}>
            <img src={x.poster} alt="" className="h-14 w-24 shrink-0 rounded-md object-cover" loading="lazy" />
            <div className="min-w-0">
              <div className="text-[11.5px] text-muted">{x.cat}</div>
              <div className={cx('text-[14px] leading-snug', k === i ? 'text-ink' : 'text-ink-2 group-hover:text-ink')}>{x.title}</div>
              {x.id === 'crowd' ? <div className="hud mt-0.5 text-[9.5px] text-alert">SHOULD BE REFUSED</div>
                : x.camera_id ? <div className="hud mt-0.5 text-[9.5px] text-accent">CAMERA ADDED</div> : null}
            </div>
          </button>
        ))}
      </div>
    </section>
  )
}

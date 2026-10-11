import { BrainCircuit, ChevronDown, Database, ExternalLink, Repeat, Search, Zap } from 'lucide-react'
import type { ReactNode } from 'react'
import type { Camera, DatasetInfo, WatchSpec } from '../lib/api'
import { ActionsEditor } from './ActionsEditor'
import { PlanEditor } from './PlanEditor'
import { cx, inputCls, Spinner } from './ui'

/** The plan a person reviews before Vigil trains: what it looks for, what it learns from, what happens. */
export function WatchPlan({ watchId, spec, onChange, cam, dataset }: {
  watchId: number
  spec: WatchSpec
  onChange: (s: WatchSpec) => void
  cam?: Camera
  dataset?: DatasetInfo
}) {
  const set = <K extends keyof WatchSpec>(k: K, v: WatchSpec[K]) => onChange({ ...spec, [k]: v })
  const often: { key: WatchSpec['trigger']; label: string; sub: string }[] = [
    { key: 'rising', label: 'Once', sub: 'each time it starts' },
    { key: 'sustained', label: 'Keep reminding', sub: `every ${Math.round(spec.cooldown_s / 60) || 1} min while it lasts` },
    ...(spec.kind === 'presence' ? [{ key: 'per_object' as const, label: 'Every new one', sub: 'each new arrival' }] : []),
  ]
  return (
    <div className="flex flex-col gap-5">
      <Section icon={<Search className="size-4" />} title="Look for">
        <input
          className={cx(inputCls, 'text-[15px]')}
          value={spec.positive_label}
          onChange={(e) => onChange({ ...spec, positive_label: e.target.value, question: `Is there ${e.target.value}?` })}
        />
        <div className="mt-1.5 text-[12px] text-muted">on {cam?.name ?? 'this camera'}, anywhere in view</div>
      </Section>

      <Section icon={<BrainCircuit className="size-4" />} title="Vigil trains a model for this">
        <Dataset watchId={watchId} d={dataset} />
      </Section>

      <Section icon={<Zap className="size-4" />} title="When it happens">
        <ActionsEditor actions={spec.actions ?? []} onChange={(a) => set('actions', a)} />
      </Section>

      <Section icon={<Repeat className="size-4" />} title="How often">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {often.map((o) => (
            <button
              key={o.key}
              onClick={() => set('trigger', o.key)}
              className={cx('rounded-lg border px-3 py-2 text-left', spec.trigger === o.key ? 'border-accent bg-accent-soft' : 'border-line bg-panel-2 hover:border-line-2')}
            >
              <div className="text-[13px] font-medium">{o.label}</div>
              <div className="text-[11.5px] text-muted">{o.sub}</div>
            </button>
          ))}
        </div>
      </Section>

      <details className="group rounded-lg border border-line bg-panel-2 px-3 py-2.5">
        <summary className="flex cursor-pointer list-none items-center gap-2 text-[13px] font-medium">
          <ChevronDown className="size-4 transition-transform group-open:rotate-180" /> Advanced
          <span className="font-normal text-muted">timing, area, double-check, wording</span>
        </summary>
        <div className="mt-4"><PlanEditor spec={spec} onChange={onChange} compact /></div>
      </details>
    </div>
  )
}

function Section({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <div>
      <div className="mb-2 flex items-center gap-2 text-[12px] font-semibold uppercase tracking-wide text-muted">
        <span className="text-accent">{icon}</span>{title}
      </div>
      {children}
    </div>
  )
}

function Dataset({ watchId, d }: { watchId: number; d?: DatasetInfo }) {
  if (!d || d.state === 'searching') {
    return (
      <div className="rounded-lg border border-line bg-panel-2 p-3 text-[13px]">
        <div className="flex items-center gap-2"><Spinner className="size-4 text-accent" /> Finding public training data for your request…</div>
        {d?.message && <div className="mt-1 text-[12px] text-muted">{d.message}</div>}
      </div>
    )
  }
  if (d.state === 'pretrained') {
    return (
      <div className="rounded-lg border border-accent/40 bg-panel-2 p-3 text-[13px]">
        <div className="flex items-start gap-2">
          <Database className="mt-0.5 size-4 shrink-0 text-accent" />
          <div>
            Ready instantly: Vigil's detector was trained on{' '}
            <a href="https://cocodataset.org" target="_blank" rel="noreferrer" className="font-medium text-ink underline decoration-line-2 underline-offset-2">COCO</a>
            {' '}(118,000 public images), and <span className="text-ink">{(d.classes ?? []).join(', ')}</span> is one of the 80 things it already knows.
            <div className="mt-1 text-[12px] text-muted">No extra training needed. Your YES/NO answers still tune it to this camera.</div>
          </div>
        </div>
      </div>
    )
  }
  if (d.state === 'none' || d.state === 'off' || !d.plan) {
    return (
      <div className="rounded-lg border border-line bg-panel-2 p-3 text-[13px] text-ink-2">
        No open public dataset matches this yet, so Vigil will learn from this camera: the AI labels a few dozen frames and a model is trained on them. It improves with every YES or NO.
      </div>
    )
  }
  const p = d.plan
  return (
    <div className="rounded-lg border border-accent/40 bg-panel-2 p-3">
      <div className="flex items-start gap-2 text-[13px]">
        <Database className="mt-0.5 size-4 shrink-0 text-accent" />
        <div className="min-w-0">
          <div>
            A {p.kind === 'detector' ? 'detector' : 'classifier'} fine-tuned on{' '}
            <a href={p.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-medium text-ink underline decoration-line-2 underline-offset-2">
              {p.repo}<ExternalLink className="size-3" />
            </a>
          </div>
          <div className="mt-0.5 text-[12px] text-muted">
            learns <span className="text-ink-2">{p.target.join(', ')}</span>
            {p.other.length > 0 && <> vs <span className="text-ink-2">{p.other.join(', ')}</span></>}
            {' · '}license {p.license}
          </div>
        </div>
      </div>
      {p.previews.length > 0 && (
        <div className="mt-3 grid grid-cols-3 gap-1.5">
          {p.previews.map((n) => (
            <img key={n} src={`/api/watches/${watchId}/dataset/${n}`} alt="" className="aspect-[4/3] w-full rounded-md object-cover" />
          ))}
        </div>
      )}
      <div className="mt-2 text-[11.5px] text-muted">
        {p.kind === 'detector' ? 'Boxes show what the model learns to find.' : 'Examples of what counts as YES.'} Trains on this Mac in a few minutes, then tests itself on images it never saw.
      </div>
    </div>
  )
}

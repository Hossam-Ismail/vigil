import { Bell, ShieldCheck, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { EventRow, FeedbackButtons } from '../components/EventRow'
import { Page } from '../components/Layout'
import { Card, Empty, EventPill, Toggle } from '../components/ui'
import { api, media, type VEvent } from '../lib/api'
import { dateTime } from '../lib/format'
import { useFetch } from '../lib/hooks'
import { useLive } from '../lib/live'

function EventDrawer({ id, onClose, onChange }: { id: number; onClose: () => void; onChange: () => void }) {
  const [e, setE] = useState<VEvent | null>(null)
  const tick = useLive((s) => s.events.find((x) => x.id === id))
  useEffect(() => {
    api.get<VEvent>(`/api/events/${id}`).then(setE).catch(() => setE(null))
  }, [id, tick])
  useEffect(() => {
    const k = (ev: KeyboardEvent) => ev.key === 'Escape' && onClose()
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [onClose])
  if (!e) return null
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/50" onClick={onClose}>
      <div className="slide-in h-full w-full max-w-[640px] overflow-y-auto border-l border-line bg-bg p-5" onClick={(ev) => ev.stopPropagation()}>
        <div className="flex items-start gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <EventPill status={e.status} />
              <span className="text-[12px] text-muted">{dateTime(e.ts)}</span>
            </div>
            <h2 className="mt-1.5 text-[19px] font-semibold">{e.message}</h2>
            <div className="text-[13px] text-muted">
              <Link className="hover:underline" to={`/watches/${e.watch_id}`}>{e.watch_name}</Link> · {e.camera_name}
            </div>
          </div>
          <button onClick={onClose} className="rounded-md p-1.5 text-muted hover:bg-panel-2 hover:text-ink" aria-label="Close">
            <X className="size-5" />
          </button>
        </div>

        <div className="mt-4 overflow-hidden rounded-lg border border-line bg-black">
          {e.clip_path ? (
            <video src={media(e.clip_path)} poster={media(e.snapshot_path)} controls autoPlay muted loop playsInline className="block w-full" />
          ) : (
            <img src={media(e.snapshot_path)} alt="" className="block w-full" />
          )}
        </div>
        {!e.clip_path && <div className="mt-1 text-[11.5px] text-muted">Clip is being saved…</div>}

        {e.verdict && (
          <Card className="mt-4 p-3">
            <div className="flex items-center gap-1.5 text-[12px] font-medium text-muted">
              <ShieldCheck className="size-3.5" /> {e.detail.verifier ?? 'Verifier'}
              {e.detail.verify_ms !== undefined && <span className="num">· {(e.detail.verify_ms / 1000).toFixed(1)}s</span>}
              {e.detail.verify_confidence !== undefined && <span className="num">· {Math.round(e.detail.verify_confidence * 100)}% sure</span>}
            </div>
            <div className="mt-1 text-[13.5px]">{e.verdict}</div>
          </Card>
        )}

        <div className="mt-4 grid grid-cols-[120px_1fr] gap-4">
          {e.crop_path && <img src={media(e.crop_path)} alt="" className="w-full rounded-md border border-line" />}
          <div className="text-[13px]">
            <div className="text-muted">Was this right?</div>
            <div className="mt-2"><FeedbackButtons e={e} onChange={(n) => { setE(n); onChange() }} /></div>
            <div className="mt-2 text-[12px] text-muted">Your answer becomes a training example and the watch retrains immediately.</div>
          </div>
        </div>

        {e.detail.actions && e.detail.actions.length > 0 && (
          <div className="mt-4 flex flex-col gap-1 text-[12px]">
            {e.detail.actions.map((a, i) => (
              <div key={i} className={a.ok ? 'text-muted' : 'text-warn'}>
                {a.ok
                  ? a.action === 'imessage' ? `iMessaged ${a.to} · a YES/NO reply trains this watch`
                    : a.action === 'hubspot' ? `HubSpot ${a.object} #${a.id} created`
                    : `${a.action} sent`
                  : `${a.action} failed: ${a.error}`}
              </div>
            ))}
          </div>
        )}
        {e.detail.notified && e.detail.notified.length > 0 && (
          <div className="mt-4 text-[12px] text-muted">
            Sent to {e.detail.notified.map((n) => `${n.channel}${n.ok ? '' : ' (failed)'}`).join(', ')}
          </div>
        )}
      </div>
    </div>
  )
}

export function Events() {
  const [params, setParams] = useSearchParams()
  const [showFiltered, setShowFiltered] = useState(true)
  const events = useFetch<VEvent[]>(`/api/events?limit=200&include_suppressed=${showFiltered}`, [showFiltered])
  const eventTick = useLive((s) => s.eventTick)
  const open = params.get('open')
  useEffect(() => {
    events.reload()
  }, [eventTick]) // eslint-disable-line react-hooks/exhaustive-deps

  const list = events.data ?? []
  const filtered = list.filter((e) => e.status === 'suppressed').length
  return (
    <Page
      title="Events"
      subtitle="Every alert, with the evidence and the double-check verdict. Marking alerts right or wrong trains the watch."
      actions={
        <label className="flex items-center gap-2 text-[12.5px] text-muted">
          Show alerts the double-check filtered out
          <Toggle checked={showFiltered} onChange={setShowFiltered} label="Show filtered" />
        </label>
      }
    >
      {list.length ? (
        <Card className="divide-y divide-line overflow-hidden">
          {list.map((e) => (
            <EventRow key={e.id} e={e} onOpen={(x) => setParams({ open: String(x.id) })} onChange={() => events.reload()} />
          ))}
        </Card>
      ) : (
        <Card>
          <Empty icon={<Bell className="size-8" />} title="No events yet">
            Alerts from your watches land here, each with a snapshot, a short clip and the verifier's reasoning.
          </Empty>
        </Card>
      )}
      {showFiltered && filtered > 0 && (
        <div className="mt-3 text-[12px] text-muted">
          {filtered} alert{filtered === 1 ? ' was' : 's were'} filtered out by the double-check and never reached you. Each one also became a training example.
        </div>
      )}
      {open && <EventDrawer id={Number(open)} onClose={() => setParams({})} onChange={() => events.reload()} />}
    </Page>
  )
}

import { Check, Film, ShieldCheck, X } from 'lucide-react'
import { useState } from 'react'
import { api, media, type VEvent } from '../lib/api'
import { clock, timeAgo } from '../lib/format'
import { cx, EventPill } from './ui'

export function FeedbackButtons({ e, onChange }: { e: VEvent; onChange?: (e: VEvent) => void }) {
  const [busy, setBusy] = useState(false)
  const send = async (fb: VEvent['feedback']) => {
    setBusy(true)
    try {
      const next = await api.post<VEvent>(`/api/events/${e.id}/feedback`, { feedback: e.feedback === fb ? null : fb })
      onChange?.(next)
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="flex items-center gap-1" onClick={(ev) => ev.stopPropagation()}>
      <button
        disabled={busy}
        onClick={() => send('correct')}
        title="Correct alert — teach the model this is a YES"
        className={cx('inline-flex h-7 items-center gap-1 rounded-md border px-2 text-[12px] font-medium',
          e.feedback === 'correct' ? 'border-ok/50 bg-ok-soft text-ok' : 'border-line text-muted hover:text-ink hover:border-line-2')}
      >
        <Check className="size-3.5" /> Correct
      </button>
      <button
        disabled={busy}
        onClick={() => send('false_alarm')}
        title="False alarm — teach the model this is normal"
        className={cx('inline-flex h-7 items-center gap-1 rounded-md border px-2 text-[12px] font-medium',
          e.feedback === 'false_alarm' ? 'border-alert/50 bg-alert-soft text-alert' : 'border-line text-muted hover:text-ink hover:border-line-2')}
      >
        <X className="size-3.5" /> False alarm
      </button>
    </div>
  )
}

export function EventRow({ e, onOpen, onChange, hideWatch }: { e: VEvent; onOpen?: (e: VEvent) => void; onChange?: (e: VEvent) => void; hideWatch?: boolean }) {
  return (
    <div
      role={onOpen ? 'button' : undefined}
      onClick={() => onOpen?.(e)}
      className={cx('flex flex-wrap items-center gap-x-3 gap-y-2 px-3 py-2.5 sm:flex-nowrap', onOpen && 'cursor-pointer hover:bg-panel-2', e.status === 'suppressed' && 'opacity-60')}
    >
      <div className="relative shrink-0">
        {e.snapshot_path ? (
          <img src={media(e.snapshot_path)} alt="" className="h-12 w-20 rounded-md object-cover bg-panel-2 sm:h-14 sm:w-24" loading="lazy" />
        ) : (
          <div className="h-12 w-20 rounded-md bg-panel-2 sm:h-14 sm:w-24" />
        )}
        {e.clip_path && <Film className="absolute bottom-1 right-1 size-3.5 text-white drop-shadow" />}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-[13.5px] font-medium">{e.message}</span>
          <span className="shrink-0 whitespace-nowrap"><EventPill status={e.status} /></span>
        </div>
        <div className="truncate text-[12px] text-muted">
          {!hideWatch && <>{e.watch_name} · </>}
          {e.camera_name} · <span title={clock(e.ts)}>{timeAgo(e.ts)}</span>
        </div>
        {e.verdict && (
          <div className="mt-0.5 flex items-start gap-1 truncate text-[12px] text-ink-2">
            <ShieldCheck className="mt-[2px] size-3.5 shrink-0 text-muted" />
            <span className="truncate">{e.verdict}</span>
          </div>
        )}
      </div>
      {/* on phones the buttons get their own line under the text instead of squeezing it */}
      <div className="flex w-full justify-end sm:w-auto">
        <FeedbackButtons e={e} onChange={onChange} />
      </div>
    </div>
  )
}

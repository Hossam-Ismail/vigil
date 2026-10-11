import { MessageSquareHeart, Star, X } from 'lucide-react'
import { useState } from 'react'
import { useLocation } from 'react-router-dom'
import { api } from '../lib/api'
import { Button, cx, inputCls } from './ui'

const KINDS = [
  { key: 'idea', label: 'Idea' },
  { key: 'bug', label: 'Something broke' },
  { key: 'accuracy', label: 'Wrong alert / missed one' },
  { key: 'general', label: 'Other' },
]

/** Floating "Beta feedback" button and its form. */
export function FeedbackButton() {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button onClick={() => setOpen(true)}
        className="fixed bottom-4 left-4 z-40 flex items-center gap-2 rounded-full border border-accent/50 bg-panel px-3.5 py-2 text-[12.5px] font-medium text-ink shadow-xl shadow-black/30 hover:border-accent">
        <MessageSquareHeart className="size-4 text-accent" /> Beta feedback
      </button>
      {open && <FeedbackModal onClose={() => setOpen(false)} />}
    </>
  )
}

export function FeedbackModal({ onClose }: { onClose: () => void }) {
  const loc = useLocation()
  const [rating, setRating] = useState<number | null>(null)
  const [kind, setKind] = useState('idea')
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const send = async () => {
    setBusy(true)
    setError(null)
    try {
      await api.post('/api/feedback', { rating, kind, text, page: loc.pathname })
      setDone(true)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={onClose}>
      <div className="w-full max-w-[440px] rounded-xl border border-line bg-panel p-5 shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <div className="text-[16px] font-semibold">Help shape the Vigil beta</div>
          <button onClick={onClose} className="text-muted hover:text-ink" aria-label="Close"><X className="size-4" /></button>
        </div>
        {done ? (
          <div className="py-6 text-center text-[14px]">Thank you! The team reads every message.</div>
        ) : (
          <>
            <div className="mt-4 text-[12.5px] text-muted">How is Vigil working for you?</div>
            <div className="mt-1.5 flex gap-1">
              {[1, 2, 3, 4, 5].map((n) => (
                <button key={n} onClick={() => setRating(n)} aria-label={`${n} stars`}>
                  <Star className={cx('size-6', rating && n <= rating ? 'fill-accent text-accent' : 'text-line-2')} />
                </button>
              ))}
            </div>
            <div className="mt-4 flex flex-wrap gap-1.5">
              {KINDS.map((k) => (
                <button key={k.key} onClick={() => setKind(k.key)}
                  className={cx('rounded-full border px-2.5 py-1 text-[12px]', kind === k.key ? 'border-accent text-accent' : 'border-line text-muted hover:text-ink')}>
                  {k.label}
                </button>
              ))}
            </div>
            <textarea className={cx(inputCls, 'mt-3 h-auto min-h-[100px] py-2 leading-5')} placeholder="What should we fix, add or keep?"
              value={text} onChange={(e) => setText(e.target.value)} />
            {error && <div className="mt-2 text-[12.5px] text-alert">{error}</div>}
            <div className="mt-4 flex justify-end gap-2">
              <Button variant="ghost" onClick={onClose}>Cancel</Button>
              <Button variant="primary" loading={busy} disabled={!rating && !text.trim()} onClick={send}>Send feedback</Button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

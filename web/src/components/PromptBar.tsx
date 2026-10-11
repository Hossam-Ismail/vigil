import { ArrowUp, Sparkles } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { Camera } from '../lib/api'
import { suggestionsFor, useAuth } from '../lib/auth'
import { cx } from './ui'

const EXAMPLES = [
  'Text me when a package is left on the front step',
  'Count walk-ins at the front door',
  'How many people are waiting in line?',
  'Text me if the garage door has been open for 15 minutes',
  'When the staging area for Line 1 is empty for 2 minutes, add a restock task in HubSpot',
  'Text the shift lead if anyone at the pump isn’t wearing a hard hat',
  'Tell facilities in Slack if anything blocks the fire exit for 5 minutes',
  'Text me when more than 4 people are waiting to pay',
  'When a truck backs into dock 2, post in Slack and log the arrival',
  'Text me when a parking spot opens up in the front row',
]

/** A request handed over from the marketing site's demo (?prompt=…&cam=<part of a camera name>), read once. */
function handedOver() {
  const q = new URLSearchParams(window.location.search)
  return { prompt: q.get('prompt') ?? '', cam: (q.get('cam') ?? '').toLowerCase() }
}

export function PromptBar({ cameras, defaultCamera, compact }: { cameras: Camera[]; defaultCamera?: number; compact?: boolean }) {
  const [hand] = useState(handedOver)
  const [text, setText] = useState(hand.prompt)
  const [cam, setCam] = useState<number | undefined>(defaultCamera)
  const nav = useNavigate()
  const ref = useRef<HTMLTextAreaElement>(null)
  const { me } = useAuth()
  const examples = me ? suggestionsFor(me.profile) : EXAMPLES

  useEffect(() => {
    if (cam !== undefined || !cameras.length) return
    const match = hand.cam ? cameras.find((c) => c.name.toLowerCase().includes(hand.cam)) : undefined
    setCam(defaultCamera ?? match?.id ?? cameras[0].id)
  }, [cameras, cam, defaultCamera, hand.cam])

  useEffect(() => {
    if (hand.prompt) ref.current?.focus()
  }, [hand.prompt])

  const submit = () => {
    if (!text.trim() || cam === undefined) return
    nav(`/new?camera=${cam}&prompt=${encodeURIComponent(text.trim())}`)
  }

  return (
    <div className={cx('rounded-2xl border border-line bg-panel shadow-[0_1px_0_0_rgba(255,255,255,0.03)_inset]', compact ? 'p-2' : 'p-3')}>
      <div className="flex items-start gap-2">
        <Sparkles className="mt-2.5 ml-1 size-4 shrink-0 text-accent" />
        <textarea
          ref={ref}
          rows={compact ? 1 : 2}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              submit()
            }
          }}
          placeholder="What should I watch for, and what then? e.g. “Text me when a package is left on the front step”"
          className="min-h-[40px] flex-1 resize-none bg-transparent py-2 text-[15px] leading-6 outline-none placeholder:text-muted/70"
        />
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-2 pl-7">
        <select
          value={cam ?? ''}
          onChange={(e) => setCam(Number(e.target.value))}
          className="h-8 rounded-lg border border-line bg-panel-2 px-2 text-[12.5px] text-ink-2 outline-none"
          aria-label="Camera"
        >
          {cameras.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        {!compact &&
          examples.slice(0, 4).map((ex) => (
            <button
              key={ex}
              onClick={() => {
                setText(ex)
                ref.current?.focus()
              }}
              className="hidden lg:inline-flex h-8 items-center rounded-lg border border-line px-2.5 text-[12px] text-muted hover:text-ink hover:border-line-2 truncate max-w-[260px]"
            >
              {ex}
            </button>
          ))}
        <button
          onClick={submit}
          disabled={!text.trim() || cam === undefined}
          className="ml-auto inline-flex size-9 items-center justify-center rounded-xl bg-accent text-accent-ink disabled:opacity-30"
          aria-label="Create watch"
        >
          <ArrowUp className="size-4.5" />
        </button>
      </div>
    </div>
  )
}

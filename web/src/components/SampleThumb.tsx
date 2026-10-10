import { Check, HelpCircle, Minus } from 'lucide-react'
import type { Sample } from '../lib/api'
import { media } from '../lib/api'
import { ORIGIN_LABEL, SOURCE_LABEL } from '../lib/format'
import { cx } from './ui'

export function SampleThumb({ s, onCycle, size = 'md' }: { s: Sample; onCycle?: (s: Sample) => void; size?: 'sm' | 'md' }) {
  const tone = s.label === 1 ? 'yes' : s.label === 0 ? 'no' : 'unsure'
  const title = [
    s.label === 1 ? 'YES' : s.label === 0 ? 'NO' : 'Needs review',
    s.reason && `“${s.reason}”`,
    `${SOURCE_LABEL[s.source] ?? s.source}${s.confidence !== null ? ` · ${Math.round((s.confidence ?? 0) * 100)}% sure` : ''}`,
    ORIGIN_LABEL[s.origin] && `from ${ORIGIN_LABEL[s.origin]}`,
    onCycle && 'Click to change the label',
  ]
    .filter(Boolean)
    .join('\n')
  return (
    <button
      type="button"
      title={title}
      onClick={() => onCycle?.(s)}
      disabled={!onCycle}
      className={cx(
        'slide-in group relative block w-full overflow-hidden rounded-lg border-2 bg-panel-2 text-left aspect-[4/3]',
        tone === 'yes' && 'border-alert/70',
        tone === 'no' && 'border-line',
        tone === 'unsure' && 'border-dashed border-warn/60',
        onCycle && 'cursor-pointer hover:brightness-110',
      )}
    >
      <img src={media(s.image_path)} alt="" className="absolute inset-0 h-full w-full object-cover" loading="lazy" />
      <span
        className={cx(
          'absolute left-1 top-1 inline-flex items-center gap-0.5 rounded-md px-1 py-[1px] text-[10px] font-bold uppercase',
          tone === 'yes' && 'bg-alert text-white',
          tone === 'no' && 'bg-black/70 text-white/90',
          tone === 'unsure' && 'bg-warn text-black',
        )}
      >
        {tone === 'yes' ? <Check className="size-3" /> : tone === 'no' ? <Minus className="size-3" /> : <HelpCircle className="size-3" />}
        {tone === 'yes' ? 'yes' : tone === 'no' ? 'no' : '?'}
      </span>
      {s.source === 'user' && <span className="absolute right-1 top-1 rounded bg-accent px-1 text-[9.5px] font-bold text-accent-ink">YOU</span>}
      {size === 'md' && s.reason && (
        <span className="absolute inset-x-0 bottom-0 line-clamp-2 bg-gradient-to-t from-black/85 to-transparent px-1.5 pb-1 pt-4 text-[10.5px] leading-tight text-white/90 opacity-0 transition-opacity group-hover:opacity-100">
          {s.reason}
        </span>
      )}
    </button>
  )
}

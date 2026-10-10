import { Loader2 } from 'lucide-react'
import type { ButtonHTMLAttributes, ReactNode } from 'react'
import type { EventStatus, WatchKind, WatchStatus } from '../lib/api'

export function cx(...c: (string | false | null | undefined)[]) {
  return c.filter(Boolean).join(' ')
}

type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  size?: 'sm' | 'md'
  loading?: boolean
  icon?: ReactNode
}

export function Button({ variant = 'secondary', size = 'md', loading, icon, className, children, disabled, ...rest }: BtnProps) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={cx(
        'inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition-colors select-none whitespace-nowrap',
        'disabled:opacity-50 disabled:cursor-not-allowed',
        size === 'sm' ? 'h-7 px-2.5 text-[12.5px]' : 'h-9 px-3.5 text-[13.5px]',
        variant === 'primary' && 'bg-accent text-accent-ink hover:brightness-110',
        variant === 'secondary' && 'bg-panel-2 text-ink border border-line hover:bg-panel-3 hover:border-line-2',
        variant === 'ghost' && 'text-ink-2 hover:bg-panel-2 hover:text-ink',
        variant === 'danger' && 'text-alert border border-line hover:bg-alert-soft hover:border-alert/40',
        className,
      )}
    >
      {loading ? <Loader2 className="size-3.5 animate-spin" /> : icon}
      {children}
    </button>
  )
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cx('rounded-xl border border-line bg-panel', className)}>{children}</div>
}

export function SectionTitle({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 mb-3">
      <h2 className="text-[13px] font-semibold uppercase tracking-[0.08em] text-muted">{children}</h2>
      {right}
    </div>
  )
}

const KIND_STYLE: Record<WatchKind, string> = {
  state: 'text-info bg-info-soft',
  presence: 'text-accent bg-accent-soft',
  count: 'text-warn bg-warn-soft',
}

export function KindBadge({ kind }: { kind: WatchKind }) {
  return (
    <span className={cx('inline-flex items-center rounded-md px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide', KIND_STYLE[kind])}>
      {kind}
    </span>
  )
}

const STATUS_STYLE: Record<string, { cls: string; label: string; dot?: string }> = {
  draft: { cls: 'text-muted bg-panel-3', label: 'Draft' },
  building: { cls: 'text-info bg-info-soft', label: 'Building', dot: 'bg-info live-dot' },
  active: { cls: 'text-ok bg-ok-soft', label: 'Watching', dot: 'bg-ok live-dot' },
  paused: { cls: 'text-muted bg-panel-3', label: 'Paused' },
  error: { cls: 'text-alert bg-alert-soft', label: 'Error' },
}

export function StatusPill({ status, alerting }: { status: WatchStatus; alerting?: boolean }) {
  if (alerting && status === 'active')
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-alert-soft px-2 py-0.5 text-[11.5px] font-semibold text-alert">
        <span className="size-1.5 rounded-full bg-alert pulse-alert" /> Alerting
      </span>
    )
  const s = STATUS_STYLE[status] ?? STATUS_STYLE.draft
  return (
    <span className={cx('inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11.5px] font-semibold', s.cls)}>
      {s.dot && <span className={cx('size-1.5 rounded-full', s.dot)} />}
      {s.label}
    </span>
  )
}

const EVENT_STYLE: Record<EventStatus, { cls: string; label: string }> = {
  pending: { cls: 'text-muted bg-panel-3', label: 'Pending' },
  verifying: { cls: 'text-info bg-info-soft', label: 'Double-checking' },
  confirmed: { cls: 'text-alert bg-alert-soft', label: 'Alert sent' },
  unverified: { cls: 'text-warn bg-warn-soft', label: 'Sent (unverified)' },
  suppressed: { cls: 'text-muted bg-panel-3', label: 'Filtered out' },
}

export function EventPill({ status }: { status: EventStatus }) {
  const s = EVENT_STYLE[status] ?? EVENT_STYLE.pending
  return <span className={cx('inline-flex rounded-full px-2 py-0.5 text-[11.5px] font-semibold', s.cls)}>{s.label}</span>
}

export function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="block">
      <span className="block text-[12px] font-medium text-ink-2 mb-1">{label}</span>
      {children}
      {hint && <span className="block text-[11.5px] text-muted mt-1">{hint}</span>}
    </label>
  )
}

export const inputCls =
  'w-full h-9 rounded-lg border border-line bg-panel-2 px-3 text-[13.5px] text-ink placeholder:text-muted/70 outline-none focus:border-accent/70 focus:ring-2 focus:ring-accent/20'

export function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label?: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={cx('relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors', checked ? 'bg-accent' : 'bg-line-2')}
    >
      <span className={cx('inline-block size-4 rounded-full bg-white shadow transition-transform', checked ? 'translate-x-[18px]' : 'translate-x-0.5')} />
    </button>
  )
}

export function Meter({ value, threshold, tone }: { value: number | null; threshold?: number; tone?: 'alert' | 'warn' | 'ok' | 'accent' }) {
  const v = Math.max(0, Math.min(1, value ?? 0))
  const color = tone === 'alert' ? 'bg-alert' : tone === 'warn' ? 'bg-warn' : tone === 'ok' ? 'bg-ok' : 'bg-accent'
  return (
    <div className="relative h-1.5 w-full rounded-full bg-panel-3 overflow-hidden">
      <div className={cx('absolute inset-y-0 left-0 rounded-full transition-[width] duration-300', color)} style={{ width: `${v * 100}%` }} />
      {threshold !== undefined && <div className="absolute inset-y-[-2px] w-px bg-ink/60" style={{ left: `${threshold * 100}%` }} />}
    </div>
  )
}

export function Empty({ icon, title, children, action }: { icon?: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center text-center py-14 px-6">
      {icon && <div className="mb-3 text-muted">{icon}</div>}
      <div className="text-[15px] font-semibold">{title}</div>
      {children && <div className="mt-1 max-w-md text-[13px] text-muted">{children}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cx('animate-spin text-muted', className ?? 'size-4')} />
}

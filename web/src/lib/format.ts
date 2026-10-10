export function timeAgo(ts: number, now = Date.now() / 1000): string {
  const d = Math.max(0, now - ts)
  if (d < 10) return 'just now'
  if (d < 60) return `${Math.floor(d)}s ago`
  if (d < 3600) return `${Math.floor(d / 60)}m ago`
  if (d < 86400) return `${Math.floor(d / 3600)}h ago`
  return `${Math.floor(d / 86400)}d ago`
}

export function clock(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export function dateTime(ts: number): string {
  return new Date(ts * 1000).toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

export function pct(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return `${(v * 100).toFixed(digits)}%`
}

export function duration(s: number): string {
  if (s < 60) return `${Math.round(s)}s`
  if (s < 3600) return `${Math.round(s / 60)}m`
  return `${(s / 3600).toFixed(s % 3600 ? 1 : 0)}h`
}

export const KIND_LABEL = { state: 'State', presence: 'Presence', count: 'Count' } as const

export const TRIGGER_LABEL = {
  rising: 'Once when it starts',
  sustained: 'Repeat while it lasts',
  per_object: 'Each new arrival',
} as const

export const SOURCE_LABEL: Record<string, string> = {
  anthropic: 'Claude',
  local: 'Local VLM',
  heuristic: 'Zero-shot',
  user: 'You',
}

export const ORIGIN_LABEL: Record<string, string> = {
  history: 'history',
  live: 'live',
  active: 'active learning',
  verifier: 'alert check',
  feedback: 'feedback',
  teach: 'taught',
}

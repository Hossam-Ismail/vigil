export type Point = [number, number]
export type Zone = { points: Point[] }
export type Box = [number, number, number, number]

export type WatchKind = 'state' | 'presence' | 'count'
export type Crossing = 'none' | 'any' | 'down' | 'up' | 'left' | 'right'
export type Severity = 'info' | 'warning' | 'critical'

export type WatchSpec = {
  name: string
  kind: WatchKind
  summary: string
  question: string
  positive_label: string
  negative_label: string
  targets: string[]
  target_question: string
  locate: string
  locate_noun: string
  zone: Zone | null
  line: Point[] | null
  crossing: Crossing
  count_op: '>=' | '>' | '<=' | '<' | '=='
  count_value: number
  min_duration_s: number
  cooldown_s: number
  trigger: 'rising' | 'sustained' | 'per_object'
  verify_with_vlm: boolean
  severity: Severity
  alert_message: string
  check_interval_s: number
  clarifications: string[]
  actions: Action[]
}

export type ActionType = 'imessage' | 'hubspot' | 'webhook' | 'slack' | 'ntfy'
export type Action = { type: ActionType; target: string; object: '' | 'ticket' | 'task' | 'note'; note: string }
export type ActionResult = { action: ActionType; ok: boolean; error?: string; to?: string; object?: string; id?: string }

export type Integrations = {
  imessage_to?: string
  imessage_bridge?: string
  public_url?: string
  hubspot_token_set?: boolean
  hubspot_token_hint?: string
}

export type IntegrationsStatus = {
  imessage: { url: string; ok: boolean; dry_run?: boolean; watching?: boolean; last_error?: string; error?: string; default_to: string }
  hubspot: { configured: boolean }
}

export type Track = { id: number; label: string; box: Box; score: number | null; confirmed: boolean }

export type WatchRuntime = {
  id: number
  kind: WatchKind
  score: number | null
  count: number | null
  cond: boolean
  phase: 'idle' | 'pending' | 'active'
  threshold: number
  head_mode: string
  paused: boolean
  tracks: Track[]
  spark?: [number, number][]
}

export type Metrics = {
  mode?: string
  n?: number
  n_pos?: number
  n_neg?: number
  cv?: { accuracy: number; precision: number; recall: number; f1: number }
  cv_folds?: number
  zero_shot?: { accuracy: number; f1: number }
  fit?: { accuracy: number }
  low_data?: boolean
  trained_at?: number
  train_ms?: number
  reason?: string
  sources?: Record<string, number>
  compile?: { brain: string; ms: number; zone: ZoneProposal; warnings: string[] }
}

export type ZoneProposal = { method: string | null; candidates?: Box[]; chosen?: number; ms?: number; error?: string }

export type WatchStatus = 'draft' | 'building' | 'active' | 'paused' | 'error'

export type Watch = {
  id: number
  camera_id: number
  name: string
  prompt: string
  spec: WatchSpec
  status: WatchStatus
  status_detail: string
  model_version: number
  metrics: Metrics
  created_at: number
  updated_at: number
  camera_name: string
  runtime: WatchRuntime | null
  samples: { total: number; yes: number; no: number; unlabeled: number }
  last_event: { ts: number; status: string } | null
  event_count: number
  proposal?: ZoneProposal
  warnings?: string[]
}

export type CameraKind = 'rtsp' | 'http' | 'file' | 'webcam' | 'browser' | 'demo'

export type Camera = {
  id: number
  name: string
  kind: CameraKind
  url: string
  enabled: boolean
  status: string
  error: string
  fps: number
  width: number | null
  height: number | null
  last_frame_ts: number | null
  history_frames: number
  demo: { auto: boolean; levels: Record<string, number> } | null
  watch_count: number
  active_watches: number
}

export type Sample = {
  id: number
  watch_id: number
  ts: number
  image_path: string
  label: 0 | 1 | null
  source: string
  confidence: number | null
  reason: string
  score: number | null
  origin: string
}

export type EventStatus = 'pending' | 'verifying' | 'confirmed' | 'suppressed' | 'unverified'

export type VEvent = {
  id: number
  watch_id: number
  camera_id: number
  ts: number
  score: number | null
  status: EventStatus
  verdict: string
  message: string
  snapshot_path: string
  crop_path: string
  clip_path: string
  feedback: 'correct' | 'false_alarm' | 'missed' | null
  detail: { verifier?: string; verify_ms?: number; verify_confidence?: number; notified?: { channel: string; ok: boolean; error?: string }[]; actions?: ActionResult[] }
  watch_name: string
  camera_name: string
}

export type Detection = { label: string; conf: number; box: Box; source: string }

export type Perception = {
  camera_id: number
  ts: number
  motion: number
  tick_ms: number
  detections: Detection[]
  watches: WatchRuntime[]
}

export type BrainOption = { name: string; label: string; available: boolean }

export type Health = {
  version: string
  device: string
  models_ready: boolean
  brain: { name: string; label: string; preference: string }
  brains: BrainOption[]
  cameras: number
  watches_active: number
  embed_model: string
  detectors: { coco: string; open_vocab: string }
}

export type Channel = {
  id: string
  type: 'webhook' | 'ntfy' | 'slack' | 'desktop'
  target: string
  enabled: boolean
  min_severity: Severity
}

export type Settings = {
  integrations: Integrations
  channels: Channel[]
  brain: string
  brains: BrainOption[]
  public_url: string
  active_learning_per_hour: number
}

export type BuildMsg = {
  watch_id: number
  stage: 'collect' | 'candidates' | 'label' | 'train' | 'done' | 'error'
  progress: number
  message: string
  brain?: string
  samples?: Sample[]
  metrics?: Metrics
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) {
    let msg = res.statusText
    try {
      const data = await res.json()
      msg = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)
    } catch {
      /* not json */
    }
    throw new ApiError(res.status, msg)
  }
  return res.json() as Promise<T>
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body ?? {}),
  patch: <T>(path: string, body: unknown) => request<T>('PATCH', path, body),
  put: <T>(path: string, body: unknown) => request<T>('PUT', path, body),
  del: <T>(path: string) => request<T>('DELETE', path),
}

export const media = (p: string) => (p ? `/media/${p}` : '')

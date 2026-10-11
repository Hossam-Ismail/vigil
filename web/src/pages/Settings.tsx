import { BellRing, Brain, Cpu, EyeOff, Lock, MessageCircle, Plus, Send, ShieldCheck, Ticket, Trash2 } from 'lucide-react'
import { type ReactNode, useEffect, useState } from 'react'
import { Page } from '../components/Layout'
import { Button, Card, cx, Field, inputCls, SectionTitle, Toggle } from '../components/ui'
import { api, type ActionResult, type Channel, type Health, type IntegrationsStatus, type Privacy, type Settings as SettingsT } from '../lib/api'
import { useFetch, useInterval } from '../lib/hooks'
import { useAuth, signOut, type Me } from '../lib/auth'
import { BetaPill } from './Welcome'

const BRAIN_INFO: Record<string, { title: string; body: string }> = {
  auto: { title: 'Automatic', body: 'Use Claude when an API key is set, otherwise the local model, otherwise the built-in fallback.' },
  anthropic: { title: 'Claude (cloud)', body: 'Best understanding and labeling. Images of labeled crops and alerts are sent to the Claude API. Set ANTHROPIC_API_KEY and restart.' },
  local: { title: 'Local vision model', body: 'Runs on this Mac with MLX. Nothing leaves the machine. Slower labeling (a few seconds per image).' },
  heuristic: { title: 'Built-in (basic)', body: 'No language model: keyword parsing and zero-shot image-text matching. Works offline, least accurate.' },
}

const CHANNEL_INFO: Record<Channel['type'], { label: string; placeholder: string; hint: string }> = {
  ntfy: { label: 'Phone push (ntfy)', placeholder: 'vigil-alerts-8f3k2 (topic) or https://ntfy.example.com/topic', hint: 'Install the free ntfy app and subscribe to the same topic. Pick a hard-to-guess topic.' },
  webhook: { label: 'Webhook', placeholder: 'https://example.com/hooks/vigil', hint: 'POSTs JSON with the event, watch, camera and a base64 snapshot.' },
  slack: { label: 'Slack', placeholder: 'https://hooks.slack.com/services/…', hint: 'An incoming-webhook URL for the channel.' },
  desktop: { label: 'Mac notification', placeholder: '', hint: 'Shows a macOS notification on the machine running Vigil.' },
}

export function Settings() {
  const s = useFetch<SettingsT>('/api/settings')
  const health = useFetch<Health>('/api/health')
  const [channels, setChannels] = useState<Channel[]>([])
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState<string | null>(null)
  const [testResult, setTestResult] = useState<Record<string, string>>({})
  const [notif, setNotif] = useState(typeof Notification !== 'undefined' ? Notification.permission : 'denied')

  useEffect(() => {
    if (s.data) setChannels(s.data.channels)
  }, [s.data])

  const update = (i: number, patch: Partial<Channel>) => {
    setChannels((c) => c.map((x, j) => (j === i ? { ...x, ...patch } : x)))
    setDirty(true)
  }

  const save = async () => {
    setSaving(true)
    try {
      s.setData(await api.put<SettingsT>('/api/settings', { channels }))
      setDirty(false)
    } finally {
      setSaving(false)
    }
  }

  const setBrain = async (brain: string) => {
    s.setData(await api.put<SettingsT>('/api/settings', { brain }))
    health.reload()
  }

  const test = async (ch: Channel) => {
    if (dirty) await save()
    setTesting(ch.id)
    try {
      const r = await api.post<{ ok: boolean; error?: string }>('/api/settings/test-notify', { channel_id: ch.id })
      setTestResult((t) => ({ ...t, [ch.id]: r.ok ? 'Sent ✓' : `Failed: ${r.error}` }))
    } catch (e) {
      setTestResult((t) => ({ ...t, [ch.id]: (e as Error).message }))
    } finally {
      setTesting(null)
    }
  }

  const add = (type: Channel['type']) => {
    setChannels((c) => [...c, { id: `${type}-${Date.now().toString(36)}`, type, target: '', enabled: true, min_severity: 'info' }])
    setDirty(true)
  }

  return (
    <Page title="Settings">
      <AccountPanel />
      <SectionTitle>Brain</SectionTitle>
      <div className="mb-2 text-[13px] text-muted">
        The brain understands your requests, labels training examples and double-checks alerts. The fast per-watch models always run locally.
      </div>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {['auto', 'anthropic', 'local', 'heuristic'].map((name) => {
          const opt = s.data?.brains.find((b) => b.name === name)
          const available = name === 'auto' || opt?.available
          const selected = s.data?.brain === name
          return (
            <button
              key={name}
              onClick={() => setBrain(name)}
              className={cx('rounded-xl border p-3.5 text-left transition-colors', selected ? 'border-accent bg-accent-soft' : 'border-line bg-panel hover:border-line-2')}
            >
              <div className="flex items-center gap-2 text-[13.5px] font-semibold">
                <Brain className="size-4" /> {BRAIN_INFO[name].title}
              </div>
              <div className="mt-1 text-[12px] leading-snug text-muted">{BRAIN_INFO[name].body}</div>
              {name !== 'auto' && (
                <div className={cx('mt-2 text-[11.5px] font-medium', available ? 'text-ok' : 'text-warn')}>
                  {available ? `Available${opt?.label ? ` · ${opt.label}` : ''}` : name === 'anthropic' ? 'No API key found' : 'Model not downloaded'}
                </div>
              )}
            </button>
          )
        })}
      </div>
      {health.data && <div className="mt-2 text-[12.5px] text-muted">In use now: <span className="text-ink">{health.data.brain.label}</span></div>}

      <PrivacyPanel settings={s.data} onSaved={s.setData} />

      <Integrations settings={s.data} onSaved={s.setData} />

      <div className="mt-10">
        <SectionTitle
          right={
            <div className="flex flex-wrap gap-1">
              {(Object.keys(CHANNEL_INFO) as Channel['type'][]).map((t) => (
                <Button key={t} size="sm" variant="ghost" icon={<Plus className="size-3.5" />} onClick={() => add(t)}>
                  {CHANNEL_INFO[t].label}
                </Button>
              ))}
            </div>
          }
        >
          Notifications
        </SectionTitle>
        <div className="flex flex-col gap-2">
          <Card className="flex items-center gap-3 px-4 py-3">
            <BellRing className="size-4 text-muted" />
            <div className="flex-1">
              <div className="text-[13.5px] font-medium">Browser notifications</div>
              <div className="text-[12px] text-muted">Pop up alerts from this tab even when it's in the background.</div>
            </div>
            {notif === 'granted' ? (
              <span className="text-[12.5px] text-ok">Enabled</span>
            ) : (
              <Button size="sm" onClick={async () => setNotif(await Notification.requestPermission())} disabled={notif === 'denied'}>
                {notif === 'denied' ? 'Blocked in browser' : 'Enable'}
              </Button>
            )}
          </Card>
          {channels.map((ch, i) => (
            <Card key={ch.id} className="p-4">
              <div className="flex flex-wrap items-center gap-3">
                <div className="min-w-[140px] font-medium text-[13.5px]">{CHANNEL_INFO[ch.type].label}</div>
                {ch.type !== 'desktop' && (
                  <input className={cx(inputCls, 'min-w-[240px] flex-1')} placeholder={CHANNEL_INFO[ch.type].placeholder} value={ch.target} onChange={(e) => update(i, { target: e.target.value })} />
                )}
                <select className={cx(inputCls, 'w-[150px]')} value={ch.min_severity} onChange={(e) => update(i, { min_severity: e.target.value as Channel['min_severity'] })}>
                  <option value="info">All alerts</option>
                  <option value="warning">Warning and up</option>
                  <option value="critical">Critical only</option>
                </select>
                <Toggle checked={ch.enabled} onChange={(v) => update(i, { enabled: v })} label="Enabled" />
                <Button size="sm" icon={<Send className="size-3.5" />} loading={testing === ch.id} onClick={() => test(ch)}>Test</Button>
                <Button size="sm" variant="ghost" icon={<Trash2 className="size-3.5" />} onClick={() => { setChannels((c) => c.filter((_, j) => j !== i)); setDirty(true) }} />
              </div>
              <div className="mt-1.5 text-[12px] text-muted">{testResult[ch.id] ?? CHANNEL_INFO[ch.type].hint}</div>
            </Card>
          ))}
        </div>
        <div className="mt-3 flex gap-2">
          <Button variant="primary" disabled={!dirty} loading={saving} onClick={save}>Save notifications</Button>
        </div>
      </div>

      {health.data && (
        <div className="mt-10">
          <SectionTitle>System</SectionTitle>
          <Card className="grid gap-4 p-4 sm:grid-cols-2 text-[12.5px]">
            <Field label="Compute"><div className="flex items-center gap-2"><Cpu className="size-4 text-muted" /><span className="num">{health.data.device.toUpperCase()}</span>{!health.data.models_ready && <span className="text-warn">warming up…</span>}</div></Field>
            <Field label="Embedding backbone"><span className="num">{health.data.embed_model}</span></Field>
            <Field label="Object detector"><span className="num">{health.data.detectors.coco}</span></Field>
            <Field label="Open-vocabulary detector"><span className="num">{health.data.detectors.open_vocab}</span></Field>
            <Field label="Version"><span className="num">{health.data.version}</span></Field>
            <Field label="Active learning"><span className="num">up to {s.data?.active_learning_per_hour} brain labels / watch / hour</span></Field>
          </Card>
        </div>
      )}
    </Page>
  )
}

const NEVER = [
  'Identify or recognize people, or follow a particular person',
  'Single out people by gender, race, religion, age or appearance',
  'Look at bodies, or watch bathrooms, changing rooms or other homes',
  'Guess emotions, intentions or health, or watch covertly',
]

function PrivacyPanel({ settings, onSaved }: { settings: SettingsT | null | undefined; onSaved: (s: SettingsT) => void }) {
  const p = settings?.privacy
  const refused = Object.values(settings?.policy_refusals ?? {}).reduce((a, b) => a + b, 0)
  const save = async (patch: Partial<Privacy>) => onSaved(await api.put<SettingsT>('/api/settings', { privacy: patch }))
  if (!p) return null
  return (
    <div className="mt-10">
      <SectionTitle>Privacy &amp; safety</SectionTitle>
      <div className="grid gap-2 lg:grid-cols-2">
        <Card className="flex flex-col gap-4 p-4">
          <div className="flex items-start gap-3">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 text-[13.5px] font-semibold"><Lock className="size-4 text-accent" /> Private mode</div>
              <div className="mt-0.5 text-[12px] leading-snug text-muted">
                {p.private_mode
                  ? 'On: video and images never leave this computer. Watches are built and double-checked by the local model.'
                  : 'Off: the Claude brain may see the few frames it labels or double-checks (never the live stream). Nothing is stored by Vigil anywhere else.'}
              </div>
            </div>
            <Toggle checked={p.private_mode} onChange={(v) => save({ private_mode: v })} label="Private mode" />
          </div>
          <div className="flex items-start gap-3">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 text-[13.5px] font-semibold"><EyeOff className="size-4 text-accent" /> Blur faces</div>
              <div className="mt-0.5 text-[12px] leading-snug text-muted">Heads are pixelated in alert snapshots and clips, which are what gets texted or shown.</div>
            </div>
            <Toggle checked={p.blur_faces} onChange={(v) => save({ blur_faces: v })} label="Blur faces" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Keep background frames">
              <select className={inputCls} value={p.keep_history_days} onChange={(e) => save({ keep_history_days: Number(e.target.value) })}>
                {[1, 3, 7, 14, 30].map((d) => <option key={d} value={d}>{d} day{d > 1 ? 's' : ''}</option>)}
              </select>
            </Field>
            <Field label="Keep alerts and clips">
              <select className={inputCls} value={p.keep_events_days} onChange={(e) => save({ keep_events_days: Number(e.target.value) })}>
                {[7, 30, 90, 365].map((d) => <option key={d} value={d}>{d} days</option>)}
              </select>
            </Field>
          </div>
        </Card>
        <Card className="p-4">
          <div className="flex items-center gap-2 text-[13.5px] font-semibold"><ShieldCheck className="size-4 text-accent" /> What Vigil won't watch for</div>
          <div className="mt-0.5 text-[12px] leading-snug text-muted">Vigil watches objects, events and conditions, never kinds of people. Requests like these are refused before any model is built:</div>
          <ul className="mt-2 flex flex-col gap-1.5 text-[12.5px]">
            {NEVER.map((x) => <li key={x} className="flex gap-2"><span className="text-alert">✕</span>{x}</li>)}
          </ul>
          <div className="mt-3 text-[12px] text-muted">
            Video stays on this machine · camera passwords stay here · the app only listens on this computer (127.0.0.1)
            {refused > 0 && <> · <span className="num">{refused}</span> request{refused === 1 ? '' : 's'} refused so far</>}
          </div>
        </Card>
      </div>
    </div>
  )
}

function Step({ n, title, done, optional, children }: { n: number; title: string; done: boolean; optional?: boolean; children?: ReactNode }) {
  return (
    <li className="flex gap-3">
      <span className={cx('num mt-[1px] grid size-5 shrink-0 place-items-center text-[11px]', done ? 'bg-accent text-accent-ink' : 'border border-line-2 text-muted')}>{done ? '✓' : n}</span>
      <div className="min-w-0 flex-1">
        <div className="font-medium">{title}{optional && <span className="ml-1.5 font-normal text-muted">(optional)</span>}</div>
        <div className="text-muted">{children}</div>
      </div>
    </li>
  )
}

function PermissionHint({ pane, children }: { pane: 'full_disk_access' | 'automation' | 'camera'; children: ReactNode }) {
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-2">
      <span>{children}</span>
      <Button size="sm" onClick={() => api.post('/api/system/open-settings', { pane })}>Open System Settings</Button>
    </div>
  )
}

function Integrations({ settings, onSaved }: { settings: SettingsT | null | undefined; onSaved: (s: SettingsT) => void }) {
  const status = useFetch<IntegrationsStatus>('/api/integrations/status')
  const [to, setTo] = useState('')
  const [bridge, setBridge] = useState('')
  const [token, setToken] = useState('')
  const [saving, setSaving] = useState(false)
  const [result, setResult] = useState<Record<string, string>>({})

  useEffect(() => {
    if (!settings) return
    setTo(settings.integrations?.imessage_to ?? '')
    setBridge(settings.integrations?.imessage_bridge ?? '')
  }, [settings])

  const save = async (patch: Record<string, string>) => {
    setSaving(true)
    try {
      onSaved(await api.put<SettingsT>('/api/settings', { integrations: patch }))
      status.reload()
    } finally {
      setSaving(false)
    }
  }

  const test = async (type: 'imessage' | 'hubspot') => {
    setResult((r) => ({ ...r, [type]: 'Sending…' }))
    try {
      const r = await api.post<ActionResult>('/api/actions/test', { action: { type, target: '', object: type === 'hubspot' ? 'note' : '', note: '' } })
      setResult((x) => ({ ...x, [type]: r.ok ? (type === 'hubspot' ? `Logged HubSpot note #${r.id} ✓` : `Sent to ${r.to} ✓`) : `Failed: ${r.error}` }))
    } catch (e) {
      setResult((x) => ({ ...x, [type]: (e as Error).message }))
    }
  }

  useInterval(() => status.reload(), 5000)
  const im = status.data?.imessage
  const integ = settings?.integrations
  const imReady = !!(im?.ok && im.can_send && integ?.imessage_to)
  const imState = !im ? 'checking' : !im.ok ? 'starting' : im.dry_run ? 'test mode' : imReady ? (im.reads_replies ? 'agent live' : 'alerts only') : "set up"
  return (
    <div className="mt-10">
      <SectionTitle>Integrations</SectionTitle>
      <div className="mb-2 text-[13px] text-muted">Each watch can do more than notify: text you, open a CRM ticket, call your systems. Set the accounts up once here, then pick them under “Then” on any watch.</div>
      <div className="grid gap-2 lg:grid-cols-2">
        <Card className="p-4">
          <div className="flex items-center gap-2 text-[13.5px] font-semibold">
            <MessageCircle className="size-4 text-accent" /> iMessage agent <span className="font-normal text-muted">built on Photon Spectrum</span>
            <span className={cx('hud ml-auto', imReady ? 'text-accent' : 'text-warn')}>{imState}</span>
          </div>
          <div className="mt-1 text-[12px] leading-snug text-muted">Vigil lives in your iMessage. It texts you alerts with the photo, and you can text it back: set up a new watch, ask for a live photo or a count, pause a watch, or tell it an alert was wrong. Runs through this Mac's Messages app with Photon's open-source Spectrum SDK. Nothing to install on the phone.</div>
          <ol className="mt-3 flex flex-col gap-2.5 text-[12.5px]">
            <Step done={!!im?.ok} n={1} title="Vigil's iMessage helper is running">
              {im?.setup_problem || (!im ? 'Checking…' : im.ok ? (im.managed ? 'Started automatically by Vigil.' : 'Running.') : 'Starting it… this takes a few seconds.')}
            </Step>
            <Step done={!!im?.messages_found} n={2} title="This Mac is signed in to Messages">
              {im?.messages_found ? 'Messages is set up.' : 'Open the Messages app and sign in with your Apple ID.'}
            </Step>
            <Step done={!!integ?.imessage_to} n={3} title="Your number: alerts go here, and only it can talk to Vigil">
              <div className="mt-1.5 flex gap-2">
                <input className={inputCls} placeholder="+1 415 555 0100 or you@icloud.com" value={to} onChange={(e) => setTo(e.target.value)} />
                <Button size="sm" variant="primary" loading={saving} onClick={() => save({ imessage_to: to })}>Save</Button>
              </div>
            </Step>
            <Step done={!!im?.sent_ok} n={4} title="Send yourself a test text">
              <div className="mt-1.5 flex flex-wrap items-center gap-2">
                <Button size="sm" icon={<Send className="size-3.5" />} disabled={!im?.ok || !integ?.imessage_to || !!im?.dry_run} onClick={() => test('imessage')}>Send test text</Button>
                <span>The first time, macOS asks to let {im?.host_app ?? 'Vigil'} control Messages: click OK.</span>
              </div>
              {im?.needs?.includes('automation') && (
                <PermissionHint pane="automation">macOS blocked sending. Open Automation and turn on <b>Messages</b> under {im.host_app}.</PermissionHint>
              )}
              {result.imessage && <div className="mt-1.5">{result.imessage}</div>}
            </Step>
            <Step done={!!im?.reads_replies} n={5} title="Turn on the conversation">
              {im?.reads_replies ? 'Spectrum is connected: Vigil reads your texts and answers them.' : (
                <PermissionHint pane="full_disk_access">
                  So Vigil can read what you text it, give <b>{im?.host_app ?? 'the app that runs Vigil'}</b> Full Disk Access (Messages keeps incoming texts in a protected folder that Spectrum reads). Vigil notices within 30 seconds, no restart.
                </PermissionHint>
              )}
            </Step>
          </ol>
          <div className="mt-3 rounded-lg border border-line bg-panel-2 p-3 text-[12px]">
            <div className="hud mb-1.5 text-muted">Then text Vigil</div>
            <div className="flex flex-wrap gap-1.5">
              {['Text me when a package is left at the door', "What's happening at the dock?", 'How many cars are in the lot?', 'What are you watching?', 'Pause dock', 'YES / NO after an alert'].map((t) => (
                <span key={t} className="rounded-full border border-line-2 px-2 py-0.5 text-ink-2">{t}</span>
              ))}
            </div>
            <div className="mt-1.5 text-muted">Same safety rules as the app: requests to watch people by who they are are refused. {im?.replied ? `${im.replied} answered so far.` : ''}</div>
          </div>
          {im?.dry_run && <div className="mt-2 text-[12px] text-warn">The helper is in test mode (DRY_RUN), so texts are only logged. Stop it and Vigil starts a live one automatically.</div>}
          <details className="mt-3 text-[12px] text-muted">
            <summary className="cursor-pointer">Advanced: helper on another Mac</summary>
            <div className="mt-2 flex gap-2">
              <input className={inputCls} placeholder="http://127.0.0.1:8790" value={bridge} onChange={(e) => setBridge(e.target.value)} />
              <Button size="sm" loading={saving} onClick={() => save({ imessage_bridge: bridge })}>Save</Button>
            </div>
          </details>
        </Card>
        <Card className="p-4">
          <div className="flex items-center gap-2 text-[13.5px] font-semibold"><Ticket className="size-4 text-accent" /> HubSpot</div>
          <div className="mt-1 text-[12px] leading-snug text-muted">Open a ticket, create a task or log a note when a watch fires, with the snapshot link and time attached.</div>
          <div className="mt-3">
            <Field label="Private app token" hint="Settings → Integrations → Private apps; scopes: tickets, crm.objects (write)">
              <input className={inputCls} type="password" placeholder={integ?.hubspot_token_set ? `Saved (${integ.hubspot_token_hint})` : 'pat-na1-…'} value={token} onChange={(e) => setToken(e.target.value)} />
            </Field>
          </div>
          <div className={cx('mt-2 text-[12px]', status.data?.hubspot.configured ? 'text-ok' : 'text-muted')}>{status.data?.hubspot.configured ? 'Connected' : 'Not connected'}</div>
          <div className="mt-3 flex gap-2">
            <Button size="sm" variant="primary" loading={saving} disabled={!token} onClick={async () => { await save({ hubspot_token: token }); setToken('') }}>Save</Button>
            <Button size="sm" icon={<Send className="size-3.5" />} disabled={!status.data?.hubspot.configured} onClick={() => test('hubspot')}>Log a test note</Button>
          </div>
          {result.hubspot && <div className="mt-1.5 text-[12px] text-muted">{result.hubspot}</div>}
        </Card>
      </div>
    </div>
  )
}


type FeedbackRow = { id: number; ts: number; rating: number | null; kind: string; text: string; page: string; email: string | null }

/** The signed-in account, its AI key, and every piece of beta feedback the team has received. */
function AccountPanel() {
  const { me, setMe } = useAuth()
  const fb = useFetch<FeedbackRow[]>('/api/feedback')
  const [key, setKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  if (!me) return null
  const replaceKey = async () => {
    setBusy(true)
    setMsg(null)
    try {
      const r = await api.post<{ user: Me }>('/api/auth/ai-key', { provider: 'anthropic', key, use_cloud: true })
      setMe(r.user)
      setKey('')
      setMsg('Key checked and saved.')
    } catch (e) {
      setMsg((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const p = me.profile
  return (
    <div className="mb-10">
      <SectionTitle>Account</SectionTitle>
      <div className="grid gap-2 lg:grid-cols-2">
        <Card className="p-4 text-[13px]">
          <div className="flex items-center gap-2 font-semibold">{me.email} <BetaPill /></div>
          <div className="mt-2 grid grid-cols-[110px_1fr] gap-y-1 text-[12.5px]">
            <span className="text-muted">Using Vigil for</span><span>{p.use}{p.business_type ? ` · ${p.business_type}` : ''}{p.org ? ` · ${p.org}` : ''}</span>
            <span className="text-muted">Cameras</span><span>{p.cameras || '—'}</span>
            <span className="text-muted">Watching for</span><span className="text-ink-2">{p.goals}</span>
          </div>
          <Button size="sm" variant="ghost" className="mt-3" onClick={signOut}>Sign out</Button>
        </Card>
        <Card className="p-4 text-[13px]">
          <div className="font-semibold">Anthropic API key <span className="font-normal text-muted">{me.ai_key_hint}</span></div>
          <div className="mt-1 text-[12px] text-muted">Checked with Anthropic before it is saved. Stored only on this computer.</div>
          <div className="mt-3 flex gap-2">
            <input className={cx(inputCls, 'font-mono')} type="password" autoComplete="off" placeholder="Replace with sk-ant-…" value={key} onChange={(e) => setKey(e.target.value.trim())} />
            <Button size="sm" variant="primary" loading={busy} disabled={key.length < 20} onClick={replaceKey}>Replace</Button>
          </div>
          {msg && <div className="mt-2 text-[12px] text-muted">{msg}</div>}
        </Card>
      </div>
      <SectionTitle>Beta feedback</SectionTitle>
      <Card className="divide-y divide-line">
        {(fb.data ?? []).length === 0 && <div className="p-4 text-[13px] text-muted">No feedback yet. The “Beta feedback” button is at the bottom left of every page.</div>}
        {(fb.data ?? []).map((f) => (
          <div key={f.id} className="flex gap-3 p-3 text-[13px]">
            <div className="w-16 shrink-0 text-accent">{f.rating ? '★'.repeat(f.rating) : '—'}</div>
            <div className="min-w-0 flex-1">
              <div className="text-ink">{f.text || <span className="text-muted">(rating only)</span>}</div>
              <div className="mt-0.5 text-[11.5px] text-muted">{f.kind} · {f.email ?? 'unknown'} · {f.page} · {new Date(f.ts * 1000).toLocaleString()}</div>
            </div>
          </div>
        ))}
      </Card>
    </div>
  )
}

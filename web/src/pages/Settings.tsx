import { BellRing, Brain, Cpu, MessageCircle, Plus, Send, Ticket, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Page } from '../components/Layout'
import { Button, Card, cx, Field, inputCls, SectionTitle, Toggle } from '../components/ui'
import { api, type ActionResult, type Channel, type Health, type IntegrationsStatus, type Settings as SettingsT } from '../lib/api'
import { useFetch } from '../lib/hooks'

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

  const im = status.data?.imessage
  const integ = settings?.integrations
  return (
    <div className="mt-10">
      <SectionTitle>Integrations</SectionTitle>
      <div className="mb-2 text-[13px] text-muted">Each watch can do more than notify: text you, open a CRM ticket, call your systems. Set the accounts up once here, then pick them under “Then” on any watch.</div>
      <div className="grid gap-2 lg:grid-cols-2">
        <Card className="p-4">
          <div className="flex items-center gap-2 text-[13.5px] font-semibold"><MessageCircle className="size-4 text-accent" /> iMessage <span className="font-normal text-muted">via Photon</span></div>
          <div className="mt-1 text-[12px] leading-snug text-muted">Alerts arrive as a text with the snapshot. Reply YES or NO and the watch retrains on your answer.</div>
          <div className="mt-3 flex flex-col gap-2">
            <Field label="Send alerts to"><input className={inputCls} placeholder="+1 415 555 0100 or you@icloud.com" value={to} onChange={(e) => setTo(e.target.value)} /></Field>
            <Field label="Bridge" hint="Run imessage-bridge on a Mac signed in to Messages"><input className={inputCls} placeholder="http://127.0.0.1:8790" value={bridge} onChange={(e) => setBridge(e.target.value)} /></Field>
          </div>
          <div className={cx('mt-2 text-[12px]', im?.ok ? 'text-ok' : 'text-warn')}>
            {!im ? 'Checking bridge…' : im.ok ? `Bridge connected${im.dry_run ? ' (dry run: logs instead of sending)' : ''}${im.watching ? ' · listening for replies' : ''}` : 'Bridge not running: cd imessage-bridge && npm start'}
          </div>
          <div className="mt-3 flex gap-2">
            <Button size="sm" variant="primary" loading={saving} onClick={() => save({ imessage_to: to, imessage_bridge: bridge })}>Save</Button>
            <Button size="sm" icon={<Send className="size-3.5" />} disabled={!im?.ok || !to} onClick={() => test('imessage')}>Send test</Button>
          </div>
          {result.imessage && <div className="mt-1.5 text-[12px] text-muted">{result.imessage}</div>}
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

import { ArrowRight, Check, ExternalLink, KeyRound, Laptop, Mail, ShieldCheck, Sparkles, UserRound } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { Button, Card, cx, Field, inputCls, Toggle } from '../components/ui'
import { api, type Camera, type Webcam } from '../lib/api'
import { useAuth, signOut, type Me, type Profile } from '../lib/auth'

export function BetaPill({ className }: { className?: string }) {
  return <span className={cx('rounded-full border border-accent/60 px-2 py-0.5 font-mono text-[10.5px] font-semibold tracking-[0.18em] text-accent', className)}>BETA</span>
}

function Shell({ children, wide }: { children: ReactNode; wide?: boolean }) {
  return (
    <div className="flex min-h-full flex-col items-center justify-center px-4 py-10">
      <div className="mb-6 flex items-center gap-3">
        <img src="/vigil-mark.svg" alt="" className="size-10" />
        <span className="text-[22px] font-semibold tracking-[0.3em]">VIGIL</span>
        <BetaPill />
      </div>
      <div className={cx('w-full', wide ? 'max-w-[640px]' : 'max-w-[440px]')}>{children}</div>
      <p className="mt-6 max-w-[440px] text-center text-[12px] text-muted">
        Vigil is in beta: things may break, and your feedback shapes what we build next.
      </p>
    </div>
  )
}

/* ------------------------------------------------------------------------------------------ */
/* sign in / create account */

export function Welcome() {
  const { setMe } = useAuth()
  const [mode, setMode] = useState<'signup' | 'signin'>('signup')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [consent, setConsent] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const r = mode === 'signup'
        ? await api.post<{ user: Me }>('/api/auth/signup', { email, password, consent })
        : await api.post<{ user: Me }>('/api/auth/login', { email, password })
      setMe(r.user)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Shell>
      <Card className="p-6">
        <div className="mb-5 grid grid-cols-2 rounded-lg border border-line bg-panel-2 p-1 text-[13px]">
          {(['signup', 'signin'] as const).map((m) => (
            <button key={m} type="button" onClick={() => { setMode(m); setError(null) }}
              className={cx('rounded-md py-1.5 font-medium', mode === m ? 'bg-accent text-accent-ink' : 'text-muted hover:text-ink')}>
              {m === 'signup' ? 'Create account' : 'Sign in'}
            </button>
          ))}
        </div>
        <h1 className="text-[22px] font-semibold leading-tight">{mode === 'signup' ? 'Join the Vigil beta' : 'Welcome back'}</h1>
        <p className="mt-1 text-[13px] text-muted">
          {mode === 'signup' ? 'Tell your cameras what to watch for. The beta is open to .edu email addresses.' : 'Sign in with your school email.'}
        </p>
        <form onSubmit={submit} className="mt-5 flex flex-col gap-3.5">
          <Field label="School email">
            <input className={inputCls} type="email" autoComplete="email" required placeholder="you@university.edu" value={email} onChange={(e) => setEmail(e.target.value)} />
          </Field>
          <Field label="Password" hint={mode === 'signup' ? 'At least 8 characters, with a letter and a number' : undefined}>
            <input className={inputCls} type="password" autoComplete={mode === 'signup' ? 'new-password' : 'current-password'} required minLength={mode === 'signup' ? 8 : 1}
              value={password} onChange={(e) => setPassword(e.target.value)} />
          </Field>
          {mode === 'signup' && (
            <label className="flex cursor-pointer items-start gap-2.5 rounded-lg border border-line bg-panel-2 p-3 text-[12.5px] leading-snug text-ink-2">
              <input type="checkbox" className="mt-0.5 accent-[var(--accent)]" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
              <span>
                I'll only connect cameras I'm allowed to use, let people know where cameras are, and follow local recording laws.
                I understand Vigil is a beta, and that it refuses requests that target people by who they are.
              </span>
            </label>
          )}
          {error && <div className="text-[12.5px] text-alert">{error}</div>}
          <Button variant="primary" loading={busy} disabled={mode === 'signup' && !consent} className="mt-1 w-full justify-center" icon={<ArrowRight className="size-4" />}>
            {mode === 'signup' ? 'Create account' : 'Sign in'}
          </Button>
        </form>
      </Card>
    </Shell>
  )
}

/* ------------------------------------------------------------------------------------------ */
/* onboarding: verify → about you → AI key → camera */

const STEPS = [
  { key: 'verify', label: 'Verify email', icon: Mail },
  { key: 'profile', label: 'About you', icon: UserRound },
  { key: 'ai_key', label: 'AI key', icon: KeyRound },
  { key: 'camera', label: 'Camera', icon: Laptop },
] as const

export function Onboarding() {
  const { me } = useAuth()
  if (!me) return null
  const idx = STEPS.findIndex((s) => s.key === me.next)
  return (
    <Shell wide>
      <ol className="mb-5 grid grid-cols-4 gap-2">
        {STEPS.map((s, i) => (
          <li key={s.key} className={cx('flex items-center gap-2 rounded-lg border px-2.5 py-2 text-[12px]',
            i < idx ? 'border-accent/40 text-ink-2' : i === idx ? 'border-accent text-ink' : 'border-line text-muted')}>
            <span className={cx('flex size-5 shrink-0 items-center justify-center rounded-full text-[10.5px] font-bold',
              i < idx ? 'bg-accent text-accent-ink' : i === idx ? 'border border-accent text-accent' : 'border border-line')}>
              {i < idx ? <Check className="size-3" /> : i + 1}
            </span>
            <span className="truncate">{s.label}</span>
          </li>
        ))}
      </ol>
      <Card className="p-6">
        {me.next === 'verify' && <VerifyStep me={me} />}
        {me.next === 'profile' && <ProfileStep me={me} />}
        {me.next === 'ai_key' && <KeyStep />}
        {me.next === 'camera' && <CameraStep />}
      </Card>
      <div className="mt-3 text-center text-[12px] text-muted">
        Signed in as {me.email} · <button className="underline hover:text-ink" onClick={signOut}>sign out</button>
      </div>
    </Shell>
  )
}

function StepTitle({ title, sub }: { title: string; sub: ReactNode }) {
  return (
    <div className="mb-5">
      <h1 className="text-[21px] font-semibold leading-tight">{title}</h1>
      <p className="mt-1 text-[13px] leading-relaxed text-muted">{sub}</p>
    </div>
  )
}

function VerifyStep({ me }: { me: Me }) {
  const { setMe, mail } = useAuth()
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [wait, setWait] = useState(30)
  useEffect(() => {
    if (wait <= 0) return
    const t = setTimeout(() => setWait((w) => w - 1), 1000)
    return () => clearTimeout(t)
  }, [wait])

  const verify = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      setMe((await api.post<{ user: Me }>('/api/auth/verify', { code })).user)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const resend = async () => {
    setError(null)
    try {
      await api.post('/api/auth/resend')
      setMsg('A new code is on its way.')
      setWait(30)
    } catch (err) {
      setError((err as Error).message)
    }
  }
  return (
    <form onSubmit={verify}>
      <StepTitle title="Check your email" sub={<>We sent a 6-digit code to <span className="text-ink">{me.email}</span>. It expires in 10 minutes.</>} />
      <input className={cx(inputCls, 'h-14 text-center font-mono text-[26px] tracking-[0.5em]')} inputMode="numeric" autoComplete="one-time-code"
        maxLength={6} placeholder="••••••" value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))} autoFocus />
      {mail === 'log' && (
        <div className="mt-3 rounded-lg border border-warn/40 bg-warn-soft px-3 py-2 text-[12px] text-ink-2">
          Email sending isn't set up on this server yet, so the code was written to the server log instead of sent.
        </div>
      )}
      {error && <div className="mt-3 text-[12.5px] text-alert">{error}</div>}
      {msg && !error && <div className="mt-3 text-[12.5px] text-ok">{msg}</div>}
      <div className="mt-5 flex items-center gap-3">
        <Button variant="primary" loading={busy} disabled={code.length !== 6} icon={<ShieldCheck className="size-4" />}>Verify</Button>
        <button type="button" disabled={wait > 0} onClick={resend} className="text-[12.5px] text-muted hover:text-ink disabled:opacity-50">
          {wait > 0 ? `Resend code in ${wait}s` : 'Resend code'}
        </button>
      </div>
    </form>
  )
}

const USES = [
  { key: 'home', label: 'Home', sub: 'My house, garage, yard or pets' },
  { key: 'business', label: 'Small business', sub: 'A shop, café, office or clinic' },
  { key: 'enterprise', label: 'Enterprise', sub: 'Several sites, warehouses or plants' },
  { key: 'research', label: 'Research', sub: 'A lab, study or experiment' },
  { key: 'education', label: 'School or campus', sub: 'Buildings, rooms, facilities' },
]
const BUSINESS = ['Retail store', 'Restaurant or café', 'Warehouse or logistics', 'Manufacturing', 'Construction', 'Parking or property',
  'Gas station or convenience store', 'Healthcare or clinic', 'Office', 'Other']
const GOAL_HINT: Record<string, string> = {
  home: 'e.g. “a package left at the door”, “the garage left open at night”, “the dog on the couch”',
  business: 'e.g. “a long line at the register”, “an empty shelf”, “a table waiting to be cleared”',
  enterprise: 'e.g. “a missing hard hat”, “a truck at the dock”, “a blocked fire exit”',
  research: 'e.g. “how often the lab bench is used”, “people crossing the hallway per hour”',
  education: 'e.g. “how full the study room is”, “a door left open after hours”',
}

function ProfileStep({ me }: { me: Me }) {
  const { setMe } = useAuth()
  const [p, setP] = useState<Profile>({ use: '', business_type: '', cameras: '', goals: '', role: '', org: '', ...me.profile })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const set = (k: keyof Profile, v: string) => setP((x) => ({ ...x, [k]: v }))
  const isBiz = p.use === 'business' || p.use === 'enterprise'
  const save = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      setMe((await api.post<{ user: Me }>('/api/auth/profile', { profile: p })).user)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <form onSubmit={save} className="flex flex-col gap-4">
      <StepTitle title="What are you using Vigil for?" sub="This tunes the examples and suggestions you'll see." />
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {USES.map((u) => (
          <button key={u.key} type="button" onClick={() => set('use', u.key)}
            className={cx('rounded-lg border px-3 py-2.5 text-left', p.use === u.key ? 'border-accent bg-accent-soft' : 'border-line bg-panel-2 hover:border-line-2')}>
            <div className="text-[13.5px] font-medium">{u.label}</div>
            <div className="text-[11.5px] text-muted">{u.sub}</div>
          </button>
        ))}
      </div>
      {isBiz && (
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="What kind of business?">
            <select className={inputCls} value={BUSINESS.includes(p.business_type ?? '') ? p.business_type : p.business_type ? 'Other' : ''}
              onChange={(e) => set('business_type', e.target.value)}>
              <option value="" disabled>Choose one</option>
              {BUSINESS.map((b) => <option key={b}>{b}</option>)}
            </select>
          </Field>
          <Field label="Business name (optional)">
            <input className={inputCls} value={p.org} onChange={(e) => set('org', e.target.value)} />
          </Field>
          <Field label="Your role (optional)">
            <input className={inputCls} placeholder="e.g. owner, operations manager" value={p.role} onChange={(e) => set('role', e.target.value)} />
          </Field>
        </div>
      )}
      {p.use && (
        <>
          <Field label="How many cameras do you have?">
            <div className="flex flex-wrap gap-2">
              {['1', '2–5', '6–20', '20+', 'None yet'].map((c) => (
                <button key={c} type="button" onClick={() => set('cameras', c)}
                  className={cx('rounded-full border px-3 py-1 text-[12.5px]', p.cameras === c ? 'border-accent text-accent' : 'border-line text-muted hover:text-ink')}>{c}</button>
              ))}
            </div>
          </Field>
          <Field label={p.use === 'home' ? 'Describe specific things you might want Vigil to see' : 'What would you like Vigil to watch for?'} hint={GOAL_HINT[p.use]}>
            <textarea className={cx(inputCls, 'h-auto min-h-[90px] py-2 leading-5')} value={p.goals} onChange={(e) => set('goals', e.target.value)} />
          </Field>
        </>
      )}
      {error && <div className="text-[12.5px] text-alert">{error}</div>}
      <div><Button variant="primary" loading={busy} disabled={!p.use} icon={<ArrowRight className="size-4" />}>Continue</Button></div>
    </form>
  )
}

function KeyStep() {
  const { setMe } = useAuth()
  const [key, setKey] = useState('')
  const [cloud, setCloud] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const save = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      setMe((await api.post<{ user: Me }>('/api/auth/ai-key', { provider: 'anthropic', key, use_cloud: cloud })).user)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <form onSubmit={save} className="flex flex-col gap-4">
      <StepTitle title="Connect your AI key" sub={<>Vigil uses Claude to understand what you ask for and to double-check alerts before it texts you. Add your Anthropic API key: Vigil checks it with Anthropic, and it stays on this computer.</>} />
      <Field label="Anthropic API key" hint={<a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 underline hover:text-ink">Get a key at console.anthropic.com <ExternalLink className="size-3" /></a>}>
        <input className={cx(inputCls, 'font-mono')} type="password" autoComplete="off" placeholder="sk-ant-…" value={key} onChange={(e) => setKey(e.target.value.trim())} />
      </Field>
      <div className="flex items-start justify-between gap-4 rounded-lg border border-line bg-panel-2 px-3 py-2.5">
        <div>
          <div className="text-[13px] font-medium">Let Claude double-check alerts</div>
          <div className="text-[12px] leading-snug text-muted">A few frames from each alert are sent to Anthropic for the check. Turn off to keep every image on this computer.</div>
        </div>
        <Toggle checked={cloud} onChange={setCloud} label="Let Claude double-check alerts" />
      </div>
      <div className="text-[12px] text-muted">Anthropic bills your key per request. Vigil only calls it when you create a watch and when an alert fires, never for every frame.</div>
      {error && <div className="text-[12.5px] text-alert">{error}</div>}
      <div><Button variant="primary" loading={busy} disabled={key.length < 20} icon={<KeyRound className="size-4" />}>Check key &amp; continue</Button></div>
    </form>
  )
}

function CameraStep() {
  const { setMe } = useAuth()
  const [cams, setCams] = useState<Camera[]>([])
  const [webcams, setWebcams] = useState<Webcam[]>([])
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const load = () => {
    api.get<Camera[]>('/api/cameras').then(setCams).catch(() => {})
    api.get<Webcam[]>('/api/webcams').then(setWebcams).catch(() => {})
  }
  useEffect(load, [])
  const addWebcam = async (w: Webcam) => {
    setBusy(w.name)
    setError(null)
    try {
      await api.post('/api/cameras', { name: w.name, kind: 'webcam', url: w.name, enabled: true })
      load()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(null)
    }
  }
  const finish = async () => {
    setBusy('finish')
    try {
      setMe((await api.post<{ user: Me }>('/api/auth/finish')).user)
    } catch (err) {
      setError((err as Error).message)
      setBusy(null)
    }
  }
  const added = new Set(cams.filter((c) => c.kind === 'webcam').map((c) => c.url))
  return (
    <div className="flex flex-col gap-4">
      <StepTitle title="Connect a camera" sub="Start with this computer's camera. IP cameras (RTSP/ONVIF) and phones can be added any time under Cameras." />
      <div className="flex flex-col gap-2">
        {webcams.length === 0 && <div className="text-[12.5px] text-muted">No camera found on this computer.</div>}
        {webcams.map((w) => (
          <div key={w.name} className="flex items-center gap-3 rounded-lg border border-line bg-panel-2 px-3 py-2.5">
            <Laptop className="size-4 text-accent" />
            <div className="min-w-0 flex-1">
              <div className="truncate text-[13.5px] font-medium">{w.name}</div>
              <div className="text-[11.5px] text-muted">{w.kind === 'builtin' ? 'Built-in camera' : w.kind === 'phone' ? 'Phone (Continuity Camera)' : 'USB camera'}</div>
            </div>
            {added.has(w.name) || added.has(String(w.index))
              ? <span className="flex items-center gap-1 text-[12.5px] text-ok"><Check className="size-3.5" /> Connected</span>
              : <Button size="sm" loading={busy === w.name} onClick={() => addWebcam(w)}>Connect</Button>}
          </div>
        ))}
      </div>
      {cams.length > 0 && (
        <div className="text-[12.5px] text-muted">
          Cameras ready: <span className="text-ink-2">{cams.map((c) => c.name).join(', ')}</span>
        </div>
      )}
      {error && <div className="text-[12.5px] text-alert">{error}</div>}
      <div className="flex items-center gap-3">
        <Button variant="primary" loading={busy === 'finish'} disabled={cams.length === 0} onClick={finish} icon={<Sparkles className="size-4" />}>Open Vigil</Button>
        {cams.length === 0 && <span className="text-[12px] text-muted">Connect at least one camera to continue.</span>}
      </div>
    </div>
  )
}

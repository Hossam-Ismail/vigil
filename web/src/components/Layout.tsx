import { BarChart3, Bell, Brain, Camera, Eye, LayoutGrid, Settings, X, FlaskConical } from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { api, media, type Health } from '../lib/api'
import { timeAgo } from '../lib/format'
import { dismissToast, useLive } from '../lib/live'
import { cx } from './ui'

const NAV = [
  { to: '/', label: 'Live', icon: LayoutGrid, end: true },
  { to: '/watches', label: 'Watches', icon: Eye },
  { to: '/metrics', label: 'Metrics', icon: BarChart3 },
  { to: '/events', label: 'Inbox', icon: Bell },
  { to: '/cameras', label: 'Cameras', icon: Camera },
  { to: '/lab', label: 'Lab', icon: FlaskConical },
  { to: '/settings', label: 'Settings', icon: Settings },
]

export function Logo({ className }: { className?: string }) {
  return <img src="/vigil-mark.svg" alt="" className={className} />
}

function BrainStatus() {
  const [h, setH] = useState<Health | null>(null)
  const connected = useLive((s) => s.connected)
  useEffect(() => {
    const load = () => api.get<Health>('/api/health').then(setH).catch(() => setH(null))
    load()
    const id = setInterval(load, 15000)
    return () => clearInterval(id)
  }, [])
  return (
    <NavLink to="/settings" className="hud hidden items-center gap-2 text-muted hover:text-ink lg:flex" title={h ? `Brain: ${h.brain.label}` : 'connecting'}>
      <span className={cx('size-1.5 rounded-full', connected ? 'bg-accent live-dot' : 'bg-alert')} />
      {connected ? 'ONLINE' : 'RECONNECTING'} · <Clock />
      {h && <span className="max-w-[220px] truncate normal-case tracking-normal text-[12px] text-muted"><Brain className="mr-1 inline size-3.5" />{h.models_ready ? h.brain.label : 'warming up models…'}</span>}
    </NavLink>
  )
}

function Toasts() {
  const toasts = useLive((s) => s.toasts)
  const nav = useNavigate()
  useEffect(() => {
    if (!toasts.length) return
    const id = setTimeout(() => dismissToast(toasts[0].id), 12000)
    return () => clearTimeout(id)
  }, [toasts])
  return (
    <div className="fixed bottom-4 right-4 z-50 flex w-[360px] max-w-[calc(100vw-2rem)] flex-col gap-2">
      {toasts.map(({ id, event }) => (
        <div key={id} className="slide-in flex gap-3 rounded-xl border border-alert/40 bg-panel p-2.5 shadow-2xl shadow-black/40">
          <button onClick={() => { dismissToast(id); nav(`/events?open=${event.id}`) }} className="shrink-0">
            <img src={media(event.snapshot_path)} alt="" className="h-14 w-24 rounded-md object-cover bg-panel-2" />
          </button>
          <button className="min-w-0 flex-1 text-left" onClick={() => { dismissToast(id); nav(`/events?open=${event.id}`) }}>
            <div className="flex items-center gap-1.5 text-[11.5px] font-semibold text-alert">
              <span className="size-1.5 rounded-full bg-alert pulse-alert" /> {event.watch_name}
            </div>
            <div className="truncate text-[13px] font-medium">{event.message}</div>
            <div className="truncate text-[11.5px] text-muted">{event.camera_name} · {timeAgo(event.ts)}</div>
          </button>
          <button onClick={() => dismissToast(id)} className="self-start text-muted hover:text-ink" aria-label="Dismiss">
            <X className="size-4" />
          </button>
        </div>
      ))}
    </div>
  )
}

function Clock() {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(id)
  }, [])
  return <span className="num">{now.toLocaleTimeString([], { hour12: false })}</span>
}

export function Layout() {
  const unseen = useLive((s) => s.events.filter((e) => e.status === 'confirmed' || e.status === 'unverified').length)
  return (
    <div className="flex h-full flex-col">
      <header className="flex shrink-0 flex-wrap items-center gap-x-6 gap-y-2 border-b border-line bg-bg px-4 py-3 md:px-7">
        <NavLink to="/" className="flex items-center gap-2.5 text-ink">
          <Logo className="size-8" />
          <span className="text-[18px] font-semibold tracking-[0.3em]">VIGIL</span>
        </NavLink>
        <nav aria-label="Main" className="order-3 flex w-full gap-1 overflow-x-auto md:order-none md:w-auto">
          {NAV.map(({ to, label, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                cx('hud flex h-9 shrink-0 items-center gap-1.5 px-3 transition-colors', isActive ? 'bg-accent text-accent-ink' : 'text-muted hover:text-ink')
              }
            >
              {({ isActive }) => (
                <>
                  {label}
                  {to === '/events' && unseen > 0 && <span className={cx('num', isActive ? 'text-accent-ink' : 'text-accent')}>{unseen}</span>}
                </>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-4">
          <BrainStatus />
          <NavLink to="/new" className="hud flex h-9 items-center border border-accent px-3 text-accent hover:bg-accent hover:text-accent-ink">
            + NEW WATCH
          </NavLink>
        </div>
      </header>
      <main className="min-h-0 flex-1 overflow-y-auto">
        <Outlet />
      </main>
      <Toasts />
    </div>
  )
}

export function Page({ title, subtitle, actions, children, wide }: { title: React.ReactNode; subtitle?: React.ReactNode; actions?: React.ReactNode; children: React.ReactNode; wide?: boolean }) {
  return (
    <div className={cx('mx-auto px-4 md:px-8 py-6 md:py-8', wide ? 'max-w-[1500px]' : 'max-w-[1180px]')}>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-[30px] font-semibold leading-tight tracking-tight">{title}</h1>
          {subtitle && <div className="mt-1 text-[13.5px] text-muted">{subtitle}</div>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
      {children}
    </div>
  )
}

import { Bell, Brain, Camera, Eye, LayoutGrid, Settings, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { api, media, type Health } from '../lib/api'
import { timeAgo } from '../lib/format'
import { dismissToast, useLive } from '../lib/live'
import { cx } from './ui'

const NAV = [
  { to: '/', label: 'Live', icon: LayoutGrid, end: true },
  { to: '/watches', label: 'Watches', icon: Eye },
  { to: '/events', label: 'Events', icon: Bell },
  { to: '/cameras', label: 'Cameras', icon: Camera },
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
    <NavLink to="/settings" className="block rounded-lg border border-line bg-panel px-3 py-2.5 hover:border-line-2">
      <div className="flex items-center gap-2 text-[12px] text-muted">
        <Brain className="size-3.5" /> Brain
        <span className={cx('ml-auto size-1.5 rounded-full', connected ? 'bg-ok live-dot' : 'bg-alert')} title={connected ? 'live' : 'reconnecting'} />
      </div>
      <div className="mt-0.5 truncate text-[12.5px] font-medium">{h ? h.brain.label : 'connecting…'}</div>
      {h && !h.models_ready && <div className="mt-0.5 text-[11px] text-warn">warming up vision models…</div>}
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

export function Layout() {
  const unseen = useLive((s) => s.events.filter((e) => e.status === 'confirmed' || e.status === 'unverified').length)
  return (
    <div className="flex h-full">
      <aside className="hidden md:flex w-[216px] shrink-0 flex-col border-r border-line bg-bg-2 px-3 py-4">
        <div className="flex items-center gap-2 px-2 pb-5">
          <Logo className="size-7 text-accent" />
          <span className="text-[17px] font-semibold tracking-tight">Vigil</span>
        </div>
        <nav className="flex flex-col gap-0.5">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                cx(
                  'flex items-center gap-2.5 rounded-lg px-2.5 h-9 text-[13.5px] font-medium transition-colors',
                  isActive ? 'bg-panel-2 text-ink' : 'text-ink-2 hover:bg-panel hover:text-ink',
                )
              }
            >
              <Icon className="size-4" />
              {label}
              {to === '/events' && unseen > 0 && (
                <span className="ml-auto rounded-full bg-alert px-1.5 text-[10.5px] font-bold text-white num">{unseen}</span>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto">
          <BrainStatus />
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="md:hidden flex items-center gap-2 border-b border-line px-4 h-12">
          <Logo className="size-6 text-accent" />
          <span className="font-semibold">Vigil</span>
          <nav className="ml-auto flex gap-1">
            {NAV.map(({ to, icon: Icon, end, label }) => (
              <NavLink key={to} to={to} end={end} aria-label={label} className={({ isActive }) => cx('rounded-md p-2', isActive ? 'bg-panel-2 text-ink' : 'text-muted')}>
                <Icon className="size-4" />
              </NavLink>
            ))}
          </nav>
        </header>
        <main className="min-h-0 flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>
      <Toasts />
    </div>
  )
}

export function Page({ title, subtitle, actions, children, wide }: { title: React.ReactNode; subtitle?: React.ReactNode; actions?: React.ReactNode; children: React.ReactNode; wide?: boolean }) {
  return (
    <div className={cx('mx-auto px-4 md:px-8 py-6 md:py-8', wide ? 'max-w-[1500px]' : 'max-w-[1180px]')}>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-[22px] font-semibold tracking-tight">{title}</h1>
          {subtitle && <div className="mt-1 text-[13.5px] text-muted">{subtitle}</div>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
      {children}
    </div>
  )
}

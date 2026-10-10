import { useSyncExternalStore } from 'react'
import type { BuildMsg, Camera, Metrics, Perception, Sample, VEvent } from './api'

type LiveState = {
  connected: boolean
  perception: Record<number, Perception>
  builds: Record<number, BuildMsg>
  buildSamples: Record<number, Sample[]>
  events: VEvent[]
  eventTick: number
  models: Record<number, { version: number; metrics: Metrics }>
  modelTick: number
  cameras: Record<number, Partial<Camera>>
  toasts: Toast[]
}

export type Toast = { id: number; event: VEvent }

type Listener = () => void

let state: LiveState = {
  connected: false,
  perception: {},
  builds: {},
  buildSamples: {},
  events: [],
  eventTick: 0,
  models: {},
  modelTick: 0,
  cameras: {},
  toasts: [],
}
const listeners = new Set<Listener>()
const notified = new Set<number>()

function set(patch: Partial<LiveState>) {
  state = { ...state, ...patch }
  listeners.forEach((l) => l())
}

function subscribe(l: Listener) {
  listeners.add(l)
  return () => listeners.delete(l)
}

export function useLive<T>(selector: (s: LiveState) => T): T {
  return useSyncExternalStore(subscribe, () => selector(state))
}

export function dismissToast(id: number) {
  set({ toasts: state.toasts.filter((t) => t.id !== id) })
}

export function clearBuild(watchId: number) {
  const builds = { ...state.builds }
  delete builds[watchId]
  const buildSamples = { ...state.buildSamples }
  delete buildSamples[watchId]
  set({ builds, buildSamples })
}

function onEvent(ev: VEvent) {
  const events = [ev, ...state.events.filter((e) => e.id !== ev.id)].slice(0, 200)
  const patch: Partial<LiveState> = { events, eventTick: state.eventTick + 1 }
  const alertable = ev.status === 'confirmed' || ev.status === 'unverified'
  if (alertable && !notified.has(ev.id)) {
    notified.add(ev.id)
    patch.toasts = [...state.toasts, { id: ev.id, event: ev }].slice(-4)
    if (typeof Notification !== 'undefined' && Notification.permission === 'granted' && document.hidden) {
      try {
        new Notification(`${ev.watch_name}`, { body: `${ev.message} · ${ev.camera_name}`, icon: '/favicon.svg' })
      } catch {
        /* ignore */
      }
    }
  }
  set(patch)
}

type Msg = { type: string; data: any; ts: number }

function handle(msg: Msg) {
  switch (msg.type) {
    case 'perception': {
      const p = msg.data as Perception
      set({ perception: { ...state.perception, [p.camera_id]: p } })
      break
    }
    case 'build': {
      const b = msg.data as BuildMsg
      const prev = state.buildSamples[b.watch_id] ?? []
      const buildSamples = b.samples?.length
        ? { ...state.buildSamples, [b.watch_id]: [...prev, ...b.samples] }
        : state.buildSamples
      set({ builds: { ...state.builds, [b.watch_id]: b }, buildSamples })
      break
    }
    case 'event':
      if (msg.data) onEvent(msg.data as VEvent)
      break
    case 'model':
      set({
        models: { ...state.models, [msg.data.watch_id]: { version: msg.data.version, metrics: msg.data.metrics } },
        modelTick: state.modelTick + 1,
      })
      break
    case 'camera':
      set({ cameras: { ...state.cameras, [msg.data.id]: msg.data } })
      break
  }
}

let started = false

export function startLive() {
  if (started) return
  started = true
  let retry = 500
  const connect = () => {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${location.host}/api/live`)
    ws.onopen = () => {
      retry = 500
      set({ connected: true })
    }
    ws.onmessage = (e) => {
      try {
        handle(JSON.parse(e.data))
      } catch {
        /* ignore malformed */
      }
    }
    ws.onclose = () => {
      set({ connected: false })
      setTimeout(connect, retry)
      retry = Math.min(retry * 2, 8000)
    }
  }
  connect()
}

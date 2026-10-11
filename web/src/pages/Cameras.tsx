import { Camera as CameraIcon, Film, Globe, Laptop, Radar, Smartphone, Trash2, Wifi } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { Page } from '../components/Layout'
import { Button, Card, cx, Empty, Field, inputCls, Toggle } from '../components/ui'
import { type Webcam, api, type Camera, type CameraKind } from '../lib/api'
import { useFetch } from '../lib/hooks'
import { useLive } from '../lib/live'
import { LiveImage } from '../components/LiveImage'
import { CameraStatusDot } from './Live'

type Template = { brand: string; url: string }
type Device = { ip: string; name: string; hardware: string; xaddrs: string[] }

const KINDS: { kind: CameraKind; label: string; icon: typeof Wifi; hint: string }[] = [
  { kind: 'rtsp', label: 'IP camera (RTSP)', icon: Wifi, hint: 'Reolink, Tapo, Hikvision, Dahua, Axis, UniFi, any ONVIF camera' },
  { kind: 'browser', label: 'Phone or laptop', icon: Smartphone, hint: 'Stream this device’s camera from a browser tab' },
  { kind: 'http', label: 'Stream URL', icon: Globe, hint: 'HTTP MJPEG, HLS (.m3u8) or any FFmpeg-readable URL' },
  { kind: 'file', label: 'Video file', icon: Film, hint: 'A file path on this machine; loops in real time' },
  { kind: 'webcam', label: 'USB webcam', icon: Laptop, hint: 'Built-in or USB camera, picked by name' },
  { kind: 'demo', label: 'Demo scene', icon: CameraIcon, hint: 'A simulated parts shelf you can empty and restock' },
]

function AddCamera({ onDone, onCancel }: { onDone: (c: Camera) => void; onCancel: () => void }) {
  const [kind, setKind] = useState<CameraKind>('rtsp')
  const [name, setName] = useState('')
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [scan, setScan] = useState<{ devices: Device[]; templates: Template[] } | null>(null)
  const [scanning, setScanning] = useState(false)
  const [webcams, setWebcams] = useState<Webcam[] | null>(null)

  useEffect(() => {
    if (kind !== 'webcam') return
    api.get<Webcam[]>('/api/webcams').then((list) => {
      setWebcams(list)
      setUrl((u) => (u && list.some((c) => c.name === u) ? u : list.find((c) => c.default)?.name ?? ''))
    }).catch(() => setWebcams([]))
  }, [kind])

  useEffect(() => {
    api.get<{ devices: Device[]; templates: Template[] }>('/api/discover?timeout=0.1').then(setScan).catch(() => {})
  }, [])

  const runScan = async () => {
    setScanning(true)
    try {
      setScan(await api.get('/api/discover?timeout=3'))
    } finally {
      setScanning(false)
    }
  }

  const submit = async () => {
    setBusy(true)
    setErr(null)
    try {
      const u = kind === 'demo' ? 'shelf' : url
      const fallback = kind === 'webcam' && url ? url : KINDS.find((k) => k.kind === kind)!.label
      const c = await api.post<Camera>('/api/cameras', { name: name || fallback, kind, url: u })
      onDone(c)
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card className="mb-6 p-5 slide-in">
      <div className="text-[15px] font-semibold">Add a camera</div>
      <div className="mt-4 grid gap-2 sm:grid-cols-3">
        {KINDS.map(({ kind: k, label, icon: Icon, hint }) => (
          <button
            key={k}
            onClick={() => setKind(k)}
            className={cx('rounded-lg border p-3 text-left transition-colors', kind === k ? 'border-accent bg-accent-soft' : 'border-line bg-panel-2 hover:border-line-2')}
          >
            <div className="flex items-center gap-2 text-[13.5px] font-medium"><Icon className="size-4" /> {label}</div>
            <div className="mt-0.5 text-[11.5px] text-muted">{hint}</div>
          </button>
        ))}
      </div>
      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        <Field label="Name">
          <input className={inputCls} value={name} placeholder="Front door, Aisle 3, Loading dock…" onChange={(e) => setName(e.target.value)} />
        </Field>
        {kind === 'webcam' && (
          <Field label="Camera" hint="Cameras on this computer, by name. An iPhone nearby can show up here through Continuity Camera; it is only used if you pick it.">
            {webcams === null ? (
              <div className="text-[12.5px] text-muted">Looking for cameras…</div>
            ) : webcams.length ? (
              <div className="flex flex-col gap-1.5">
                {webcams.map((c) => (
                  <label key={c.name} className={cx('flex cursor-pointer items-center gap-2.5 border px-3 py-2 text-[13px]', url === c.name ? 'border-accent bg-accent-soft' : 'border-line bg-panel-2 hover:border-line-2')}>
                    <input type="radio" name="webcam" className="accent-[var(--accent)]" checked={url === c.name} onChange={() => setUrl(c.name)} />
                    <span className="font-medium">{c.name}</span>
                    <span className="hud ml-auto text-muted">{c.kind === 'builtin' ? 'built-in' : c.kind === 'phone' ? 'iPhone · Continuity' : 'USB'}</span>
                  </label>
                ))}
              </div>
            ) : (
              <div className="text-[12.5px] text-warn">No camera found. Check that the camera is connected and that this app has camera access in System Settings → Privacy & Security → Camera.</div>
            )}
          </Field>
        )}
        {(kind === 'rtsp' || kind === 'http' || kind === 'file') && (
          <Field
            label={kind === 'file' ? 'File path' : 'Stream URL'}
            hint={kind === 'rtsp' ? 'Use the sub-stream for analysis; credentials stay on this machine.' : undefined}
          >
            <input
              className={cx(inputCls, 'num text-[12.5px]')}
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder={kind === 'rtsp' ? 'rtsp://user:pass@192.168.1.20:554/h264Preview_01_sub' : kind === 'http' ? 'https://…/stream.m3u8' : '/Users/me/Videos/dock.mp4'}
            />
          </Field>
        )}
        {kind === 'browser' && (
          <div className="text-[12.5px] text-muted sm:pt-6">After adding, open the camera page on the phone or laptop you want to use and tap <em>Start streaming</em>. The camera page shows the exact link to open on the phone.</div>
        )}
      </div>
      {kind === 'rtsp' && scan && (
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <div className="rounded-lg border border-line bg-panel-2 p-3">
            <div className="flex items-center justify-between">
              <div className="text-[12.5px] font-medium">Cameras on your network (ONVIF)</div>
              <Button size="sm" variant="ghost" icon={<Radar className="size-3.5" />} loading={scanning} onClick={runScan}>Scan</Button>
            </div>
            <div className="mt-2 flex flex-col gap-1">
              {scan.devices.length ? scan.devices.map((d) => (
                <button key={d.ip} onClick={() => { setName(d.name); setUrl(`rtsp://USER:PASSWORD@${d.ip}:554/`) }} className="flex justify-between rounded-md px-2 py-1.5 text-left text-[12.5px] hover:bg-panel-3">
                  <span>{d.name}</span><span className="num text-muted">{d.ip}</span>
                </button>
              )) : <div className="text-[12px] text-muted">{scanning ? 'Scanning…' : 'Nothing found yet. Press Scan.'}</div>}
            </div>
          </div>
          <div className="rounded-lg border border-line bg-panel-2 p-3">
            <div className="text-[12.5px] font-medium">URL formats by brand</div>
            <div className="mt-2 flex flex-col gap-0.5">
              {scan.templates.map((t) => (
                <button key={t.brand} onClick={() => setUrl(t.url)} className="flex flex-col rounded-md px-2 py-1 text-left hover:bg-panel-3">
                  <span className="text-[12px]">{t.brand}</span>
                  <span className="num truncate text-[11px] text-muted">{t.url}</span>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
      {err && <div className="mt-3 text-[13px] text-alert">{err}</div>}
      <div className="mt-5 flex gap-2">
        <Button variant="primary" loading={busy} onClick={submit}>Add camera</Button>
        <Button variant="ghost" onClick={onCancel}>Cancel</Button>
      </div>
    </Card>
  )
}

function CameraRow({ c, onChange }: { c: Camera; onChange: () => void }) {
  const live = useLive((s) => s.cameras[c.id])
  const status = live?.status ?? c.status
  const error = live?.error ?? c.error
  return (
    <div className="flex items-center gap-4 px-4 py-3">
      <Link to={`/cameras/${c.id}`} className="relative h-16 w-28 shrink-0 overflow-hidden rounded-md bg-panel-2">
        {c.enabled && <LiveImage cameraId={c.id} fps={1} className="absolute inset-0 h-full w-full object-cover" />}
      </Link>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <CameraStatusDot cam={c} />
          <Link to={`/cameras/${c.id}`} className="truncate font-medium hover:underline">{c.name}</Link>
          <span className="rounded bg-panel-3 px-1.5 text-[10.5px] uppercase text-muted">{c.kind}</span>
          {c.kind === 'webcam' && <span className="truncate text-[12px] text-muted">{c.url && !/^\d*$/.test(c.url) ? c.url : 'built-in camera'}</span>}
        </div>
        <div className="num truncate text-[12px] text-muted">
          {status}{c.width ? ` · ${c.width}×${c.height}` : ''}{c.fps ? ` · ${c.fps} fps` : ''} · {c.history_frames} frames of history · {c.watch_count} watch{c.watch_count === 1 ? '' : 'es'}
        </div>
        {error && status !== 'live' && <div className="truncate text-[12px] text-alert">{error}</div>}
      </div>
      <Toggle checked={c.enabled} onChange={async (v) => { await api.patch(`/api/cameras/${c.id}`, { enabled: v }); onChange() }} label="Enabled" />
      <Button
        variant="ghost"
        size="sm"
        icon={<Trash2 className="size-3.5" />}
        onClick={async () => {
          if (!confirm(`Remove ${c.name}? Its watches and events are deleted too.`)) return
          await api.del(`/api/cameras/${c.id}`)
          onChange()
        }}
      />
    </div>
  )
}

export function Cameras() {
  const [params, setParams] = useSearchParams()
  const cams = useFetch<Camera[]>('/api/cameras')
  const nav = useNavigate()
  const adding = params.get('add') === '1'
  return (
    <Page
      title="Cameras"
      subtitle="Vigil reads any RTSP/ONVIF camera, stream URL, video file, webcam or phone."
      actions={!adding && <Button variant="primary" onClick={() => setParams({ add: '1' })}>Add camera</Button>}
    >
      {adding && <AddCamera onCancel={() => setParams({})} onDone={(c) => { setParams({}); cams.reload(); nav(`/cameras/${c.id}`) }} />}
      {cams.data?.length ? (
        <Card className="divide-y divide-line overflow-hidden">
          {cams.data.map((c) => <CameraRow key={c.id} c={c} onChange={() => cams.reload()} />)}
        </Card>
      ) : (
        !adding && <Card><Empty icon={<CameraIcon className="size-8" />} title="No cameras">Add one to get started.</Empty></Card>
      )}
    </Page>
  )
}

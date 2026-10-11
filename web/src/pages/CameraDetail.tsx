import { ArrowLeft, PackageMinus, PackagePlus, Smartphone } from 'lucide-react'
import QRCode from 'qrcode'
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { CameraView } from '../components/CameraView'
import { EventRow } from '../components/EventRow'
import { Page } from '../components/Layout'
import { PromptBar } from '../components/PromptBar'
import { Button, Card, Empty, SectionTitle, Toggle } from '../components/ui'
import { WatchChip } from '../components/WatchChip'
import { api, type Camera, type VEvent, type Watch } from '../lib/api'
import { useFetch, useInterval } from '../lib/hooks'
import { useLive } from '../lib/live'
import { CameraStatusDot } from './Live'

/** How to turn a phone into this camera: scan the QR code (or open the link) and tap Start streaming. */
function PhoneSetup({ id }: { id: number }) {
  const link = useFetch<{ url: string | null; path: string; public: boolean }>(`/api/cameras/${id}/phone-link`)
  const [qr, setQr] = useState<string | null>(null)
  const url = link.data?.url ?? null
  useEffect(() => {
    if (!url) return
    QRCode.toDataURL(url, { margin: 1, width: 360, color: { dark: '#16181a', light: '#ffffff' } }).then(setQr).catch(() => setQr(null))
  }, [url])
  return (
    <Card className="p-4 text-[12.5px] text-muted">
      <SectionTitle>Use a phone as this camera</SectionTitle>
      {url ? (
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start">
          {qr && <img src={qr} alt="QR code that opens this camera on a phone" className="size-40 shrink-0 rounded-lg bg-white p-1.5" />}
          <ol className="flex list-decimal flex-col gap-1.5 pl-4">
            <li>Scan the code with the phone's camera{link.data?.public ? '' : ' (the phone must be on the same Wi-Fi)'}.</li>
            {!link.data?.public && <li>Safari may say the connection isn't private (Vigil's own certificate): tap <em>Show Details</em>, then <em>visit this website</em>.</li>}
            <li>Tap <em>Start streaming</em> and allow the camera.</li>
            <li>Keep the screen on and the phone plugged in.</li>
            <li className="list-none -ml-4 pt-1">Or open <span className="num select-all break-all text-ink">{url}</span></li>
          </ol>
        </div>
      ) : (
        <div>Vigil isn't reachable from other devices yet. Set a public address in Settings, or start Vigil with HTTPS on the network.</div>
      )}
    </Card>
  )
}

function DemoControls({ cam, onChange }: { cam: Camera; onChange: () => void }) {
  const demo = cam.demo!
  const send = async (body: object) => {
    await api.post(`/api/cameras/${cam.id}/demo`, body)
    onChange()
  }
  return (
    <Card className="p-4">
      <SectionTitle right={<label className="flex items-center gap-2 text-[12px] text-muted">Auto cycle <Toggle checked={demo.auto} onChange={(v) => send({ auto: v })} label="Auto cycle" /></label>}>
        Demo shelf
      </SectionTitle>
      <div className="text-[12.5px] text-muted mb-3">Empty or restock bins to test your watches. In auto mode bin A-01 is picked empty every 2½ minutes.</div>
      <div className="grid grid-cols-3 gap-2">
        {Object.entries(demo.levels).map(([bin, level]) => (
          <div key={bin} className="rounded-lg border border-line bg-panel-2 p-2">
            <div className="flex items-center justify-between text-[12px]">
              <span className="font-medium num">{bin}</span>
              <span className="num text-muted">{Math.round(level * 100)}%</span>
            </div>
            <div className="mt-1.5 flex gap-1">
              <button title="Empty" onClick={() => send({ bin, level: 0 })} className="flex-1 rounded-md border border-line py-1 text-muted hover:text-alert hover:border-alert/40"><PackageMinus className="mx-auto size-3.5" /></button>
              <button title="Restock" onClick={() => send({ bin, level: 1 })} className="flex-1 rounded-md border border-line py-1 text-muted hover:text-ok hover:border-ok/40"><PackagePlus className="mx-auto size-3.5" /></button>
            </div>
          </div>
        ))}
      </div>
    </Card>
  )
}

export function CameraDetail() {
  const { id } = useParams()
  const cid = Number(id)
  const cams = useFetch<Camera[]>('/api/cameras')
  const watches = useFetch<Watch[]>(`/api/watches?camera_id=${cid}`)
  const events = useFetch<VEvent[]>(`/api/events?camera_id=${cid}&limit=15`)
  const eventTick = useLive((s) => s.eventTick)
  const perception = useLive((s) => s.perception[cid])
  useEffect(() => { events.reload() }, [eventTick]) // eslint-disable-line react-hooks/exhaustive-deps
  useInterval(() => { watches.reload(); cams.reload() }, 5000)
  const cam = cams.data?.find((c) => c.id === cid)
  if (!cam) return null
  const aspect = cam.width && cam.height ? cam.width / cam.height : 16 / 9
  return (
    <Page
      wide
      title={
        <span className="flex items-center gap-2">
          <Link to="/" className="rounded-md p-1 text-muted hover:bg-panel-2 hover:text-ink" aria-label="Back"><ArrowLeft className="size-5" /></Link>
          <CameraStatusDot cam={cam} /> {cam.name}
        </span>
      }
      subtitle={<span className="num">{cam.kind} · {cam.width ? `${cam.width}×${cam.height} · ` : ''}{cam.fps} fps{perception ? ` · ${perception.tick_ms.toFixed(0)} ms analysis · motion ${(perception.motion * 100).toFixed(1)}%` : ''}</span>}
      actions={cam.kind === 'browser' && <Link to={`/push/${cam.id}`}><Button variant="primary" icon={<Smartphone className="size-4" />}>Stream from this device</Button></Link>}
    >
      <div className="grid gap-5 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <div className="flex flex-col gap-4">
          <CameraView cameraId={cid} aspect={aspect} watches={watches.data ?? []} fps={8} />
          <PromptBar cameras={[cam]} defaultCamera={cid} compact />
        </div>
        <div className="flex flex-col gap-4">
          <Card className="p-4">
            <SectionTitle>Watches</SectionTitle>
            <div className="flex flex-col gap-1.5">
              {(watches.data ?? []).map((w) => <WatchChip key={w.id} w={w} />)}
              {!watches.data?.length && <div className="text-[12.5px] text-muted">No watches on this camera yet.</div>}
            </div>
          </Card>
          {cam.demo && <DemoControls cam={cam} onChange={() => cams.reload()} />}
          {cam.kind === 'browser' && <PhoneSetup id={cam.id} />}
        </div>
      </div>
      <div className="mt-8">
        <SectionTitle>Recent events</SectionTitle>
        {events.data?.length ? (
          <Card className="divide-y divide-line">{events.data.map((e) => <EventRow key={e.id} e={e} onChange={() => events.reload()} />)}</Card>
        ) : (
          <Card><Empty title="Quiet so far" /></Card>
        )}
      </div>
    </Page>
  )
}

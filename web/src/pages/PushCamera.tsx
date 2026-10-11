import { Square, Video } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { Logo } from '../components/Layout'
import { Button } from '../components/ui'

/** Turns this browser tab (phone or laptop) into a camera that streams JPEG frames to Vigil. */
export function PushCamera() {
  const { id } = useParams()
  const [params] = useSearchParams()
  const key = params.get('k')
  const video = useRef<HTMLVideoElement>(null)
  const [running, setRunning] = useState(false)
  const [sent, setSent] = useState(0)
  const [err, setErr] = useState<string | null>(null)
  const [facing, setFacing] = useState<'environment' | 'user'>('environment')
  const stopRef = useRef<() => void>(() => {})

  useEffect(() => () => stopRef.current(), [])

  const start = async () => {
    setErr(null)
    if (!navigator.mediaDevices?.getUserMedia) {
      setErr('Camera access needs HTTPS (or localhost) in this browser.')
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: facing, width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false })
      const v = video.current!
      v.srcObject = stream
      await v.play()
      const proto = location.protocol === 'https:' ? 'wss' : 'ws'
      const ws = new WebSocket(`${proto}://${location.host}/api/cameras/${id}/push${key ? `?k=${encodeURIComponent(key)}` : ''}`)
      ws.binaryType = 'arraybuffer'
      const canvas = document.createElement('canvas')
      let timer: ReturnType<typeof setInterval> | undefined
      let wakeLock: { release: () => Promise<void> } | null = null
      try {
        wakeLock = await (navigator as unknown as { wakeLock?: { request: (t: string) => Promise<{ release: () => Promise<void> }> } }).wakeLock?.request('screen') ?? null
      } catch {
        /* optional */
      }
      ws.onopen = () => {
        setRunning(true)
        timer = setInterval(() => {
          if (ws.readyState !== WebSocket.OPEN || ws.bufferedAmount > 2_000_000) return
          const w = v.videoWidth
          const h = v.videoHeight
          if (!w) return
          const scale = Math.min(1, 1280 / w)
          canvas.width = Math.round(w * scale)
          canvas.height = Math.round(h * scale)
          canvas.getContext('2d')!.drawImage(v, 0, 0, canvas.width, canvas.height)
          canvas.toBlob((b) => b && b.arrayBuffer().then((buf) => { ws.send(buf); setSent((n) => n + 1) }), 'image/jpeg', 0.75)
        }, 200)
      }
      ws.onclose = () => setRunning(false)
      ws.onerror = () => setErr('Could not connect to Vigil. Is this a phone/laptop camera added under Cameras?')
      stopRef.current = () => {
        clearInterval(timer)
        ws.close()
        stream.getTracks().forEach((t) => t.stop())
        wakeLock?.release().catch(() => {})
        setRunning(false)
      }
    } catch (e) {
      setErr((e as Error).message)
    }
  }

  return (
    <div className="flex min-h-full flex-col items-center bg-bg px-4 py-6">
      <div className="flex items-center gap-2 self-start">
        <Logo className="size-6 text-accent" />
        <span className="font-semibold">Vigil camera</span>
        {running && <span className="ml-2 inline-flex items-center gap-1.5 rounded-full bg-alert-soft px-2 py-0.5 text-[11.5px] font-semibold text-alert"><span className="size-1.5 rounded-full bg-alert live-dot" /> LIVE</span>}
      </div>
      <div className="mt-4 w-full max-w-[720px] overflow-hidden rounded-xl border border-line bg-black">
        <video ref={video} muted playsInline className="block aspect-video w-full object-contain" />
      </div>
      <div className="mt-4 flex w-full max-w-[720px] flex-wrap items-center gap-2">
        {!running ? (
          <Button variant="primary" icon={<Video className="size-4" />} onClick={start}>Start streaming</Button>
        ) : (
          <Button icon={<Square className="size-4" />} onClick={() => stopRef.current()}>Stop</Button>
        )}
        <select disabled={running} value={facing} onChange={(e) => setFacing(e.target.value as 'environment' | 'user')} className="h-9 rounded-lg border border-line bg-panel-2 px-2 text-[13px]">
          <option value="environment">Back camera</option>
          <option value="user">Front camera</option>
        </select>
        <span className="num ml-auto text-[12px] text-muted">{sent} frames sent</span>
      </div>
      {err && <div className="mt-3 w-full max-w-[720px] text-[13px] text-alert">{err}</div>}
      <p className="mt-6 max-w-[720px] text-[12.5px] text-muted">
        Keep this tab open with the screen on. Vigil receives about 5 frames per second, runs your watches on them and records clips when something happens.
      </p>
    </div>
  )
}

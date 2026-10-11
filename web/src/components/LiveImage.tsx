import { CameraOff } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { cx } from './ui'

/** Polls camera snapshots with double buffering: no flicker and no long-lived connections. */
export function LiveImage({ cameraId, fps = 5, className, paused }: { cameraId: number; fps?: number; className?: string; paused?: boolean }) {
  const [src, setSrc] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)
  const alive = useRef(true)

  useEffect(() => {
    alive.current = true
    let timer: ReturnType<typeof setTimeout>
    const period = 1000 / fps
    let misses = 0
    const next = () => {
      if (!alive.current) return
      const started = performance.now()
      const img = new Image()
      const url = `/api/cameras/${cameraId}/snapshot.jpg?t=${Date.now()}`
      img.onload = () => {
        if (!alive.current) return
        setSrc(url)
        setFailed(false)
        misses = 0
        timer = setTimeout(next, Math.max(0, period - (performance.now() - started)))
      }
      img.onerror = () => {
        if (!alive.current) return
        setFailed(true)
        misses += 1
        timer = setTimeout(next, Math.min(1500 * misses, 6000))   // no video yet: ask less and less often
      }
      img.src = url
    }
    if (!paused) next()
    return () => {
      alive.current = false
      clearTimeout(timer)
    }
  }, [cameraId, fps, paused])

  if (!src)
    return (
      <div className={cx('flex items-center justify-center bg-panel-2 text-muted', className)}>
        {failed ? (
          <span className="flex items-center gap-2 text-[12.5px]">
            <CameraOff className="size-4" /> Waiting for video…
          </span>
        ) : (
          <div className="shimmer absolute inset-0" />
        )}
      </div>
    )
  return <img src={src} alt="" draggable={false} className={cx('block select-none object-fill', className)} />
}

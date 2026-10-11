import { useEffect, useRef, useState, type ReactNode } from 'react'
import { cx } from '../../components/ui'

/** Motion helpers for the marketing site. Everything here settles instantly for people who ask for reduced motion. */

export const reduced = () => typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

/** True once the element has scrolled into view (and stays true). */
export function useInView<T extends Element>(margin = '-12% 0px') {
  const ref = useRef<T>(null)
  const [seen, setSeen] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el || seen) return
    if (reduced() || !('IntersectionObserver' in window)) return setSeen(true)
    const io = new IntersectionObserver(([e]) => e.isIntersecting && setSeen(true), { rootMargin: margin })
    io.observe(el)
    return () => io.disconnect()
  }, [seen, margin])
  return [ref, seen] as const
}

export function Reveal({ children, className, delay = 0 }: { children: ReactNode; className?: string; delay?: number }) {
  const [ref, seen] = useInView<HTMLDivElement>()
  return <div ref={ref} className={cx('reveal', seen && 'in', className)} style={{ transitionDelay: `${delay}ms` }}>{children}</div>
}

/** Counts a stat like "99.4%", "41 ms" or "19/20" up from zero when it scrolls into view. */
export function CountUp({ value, ms = 1400 }: { value: string; ms?: number }) {
  const [ref, seen] = useInView<HTMLSpanElement>()
  const m = value.match(/^([^\d]*)(\d+(?:\.\d+)?)(.*)$/)
  const target = m ? parseFloat(m[2]) : 0
  const decimals = m?.[2].includes('.') ? 1 : 0
  const [n, setN] = useState(0)
  useEffect(() => {
    if (!seen || !m) return
    if (reduced()) return setN(target)
    let raf = 0
    const t0 = performance.now()
    const tick = (t: number) => {
      const k = Math.min(1, (t - t0) / ms)
      setN(target * (1 - Math.pow(1 - k, 3)))
      if (k < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [seen, target]) // eslint-disable-line react-hooks/exhaustive-deps
  if (!m) return <span ref={ref}>{value}</span>
  return <span ref={ref}>{m[1]}{n.toFixed(decimals)}{m[3]}</span>
}

/** A muted, looping clip of real footage that only plays while it is on screen. */
export function LoopVideo({ src, poster, className, label }: { src: string; poster: string; className?: string; label: string }) {
  const ref = useRef<HTMLVideoElement>(null)
  useEffect(() => {
    const v = ref.current
    if (!v) return
    if (reduced()) { v.pause(); return }
    if (!('IntersectionObserver' in window)) { v.play().catch(() => {}); return }
    const io = new IntersectionObserver(([e]) => (e.isIntersecting ? v.play().catch(() => {}) : v.pause()), { threshold: 0.15 })
    io.observe(v)
    return () => io.disconnect()
  }, [])
  return <video ref={ref} src={src} poster={poster} muted loop playsInline preload="metadata" aria-label={label} className={className} />
}

/** Types a string out once it scrolls into view, then calls onDone. */
export function useTyped(text: string, start: boolean, speed = 38) {
  const [n, setN] = useState(reduced() ? text.length : 0)
  useEffect(() => {
    if (!start || reduced()) return setN(text.length)
    setN(0)
    let i = 0
    const id = setInterval(() => { i += 1; setN(i); if (i >= text.length) clearInterval(id) }, speed)
    return () => clearInterval(id)
  }, [start, text, speed])
  return [text.slice(0, n), n >= text.length] as const
}

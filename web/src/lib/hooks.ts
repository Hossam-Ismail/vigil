import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'

export function useFetch<T>(path: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const seq = useRef(0)

  const reload = useCallback(async () => {
    if (!path) return
    const n = ++seq.current
    try {
      const d = await api.get<T>(path)
      if (n === seq.current) {
        setData(d)
        setError(null)
      }
    } catch (e) {
      if (n === seq.current) setError((e as Error).message)
    } finally {
      if (n === seq.current) setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, ...deps])

  useEffect(() => {
    reload()
  }, [reload])

  return { data, error, loading, reload, setData }
}

export function useInterval(fn: () => void, ms: number | null) {
  const saved = useRef(fn)
  saved.current = fn
  useEffect(() => {
    if (ms === null) return
    const id = setInterval(() => saved.current(), ms)
    return () => clearInterval(id)
  }, [ms])
}

export function useNow(ms = 1000) {
  const [now, setNow] = useState(() => Date.now() / 1000)
  useInterval(() => setNow(Date.now() / 1000), ms)
  return now
}

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { api } from './api'

export type Profile = { use?: string; business_type?: string; cameras?: string; goals?: string; role?: string; org?: string }

export type Me = {
  id: number
  email: string
  verified: boolean
  profile: Profile
  has_profile: boolean
  ai_provider: string
  ai_key_hint: string
  has_ai_key: boolean
  onboarded: boolean
  next: 'verify' | 'profile' | 'ai_key' | 'camera' | 'ready'
}

type AuthState = { me: Me | null; loading: boolean; mail: string; refresh: () => Promise<void>; setMe: (m: Me | null) => void }

const Ctx = createContext<AuthState>({ me: null, loading: true, mail: 'log', refresh: async () => {}, setMe: () => {} })

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null)
  const [mail, setMail] = useState('log')
  const [loading, setLoading] = useState(true)
  const refresh = useCallback(async () => {
    try {
      const r = await api.get<{ user: Me | null; mail: string }>('/api/auth/me')
      setMe(r.user)
      setMail(r.mail)
    } catch {
      setMe(null)
    } finally {
      setLoading(false)
    }
  }, [])
  useEffect(() => {
    refresh()
    // any request that comes back "sign in" or "finish setup" (session expired, signed out elsewhere) re-checks
    const onAuth = () => refresh()
    window.addEventListener('vigil:auth', onAuth)
    return () => window.removeEventListener('vigil:auth', onAuth)
  }, [refresh])
  return <Ctx.Provider value={{ me, loading, mail, refresh, setMe }}>{children}</Ctx.Provider>
}

export const useAuth = () => useContext(Ctx)

export async function signOut() {
  await api.post('/api/auth/logout').catch(() => {})
  window.location.href = '/'
}

const BY_USE: Record<string, string[]> = {
  home: [
    'Text me when a package is left on the front step',
    'Text me if the garage door has been open for 15 minutes',
    'Tell me when the dog is on the couch',
    'Text me when someone is at the front door',
  ],
  business: [
    'Text me when more than 4 people are waiting to pay',
    'Count walk-ins at the front door',
    'Tell me when a table is left with dishes for 10 minutes',
    'Text me when the shelf by the register is empty',
  ],
  enterprise: [
    'Text the shift lead if anyone at the pump isn’t wearing a hard hat',
    'When a truck backs into dock 2, post in Slack and log the arrival',
    'Tell facilities in Slack if anything blocks the fire exit for 5 minutes',
    'When the staging area for Line 1 is empty for 2 minutes, add a restock task in HubSpot',
  ],
  research: [
    'Count people crossing the hallway every hour',
    'Tell me when someone uses the lab bench',
    'What share of the time is the study room occupied?',
    'Text me when the 3D printer area has no one around for 30 minutes',
  ],
  education: [
    'How many students are in the study room right now?',
    'Text me when the bike rack is full',
    'Tell me when the lecture hall door is left open after 10 pm',
    'Count people entering the library each hour',
  ],
}

/** Example prompts for this person's use, with the things they told us they want first. */
export function suggestionsFor(p: Profile | undefined): string[] {
  const base = BY_USE[p?.use ?? ''] ?? BY_USE.business
  const own = (p?.goals ?? '').split(/[\n.;]+/).map((s) => s.trim()).filter((s) => s.length > 8).slice(0, 2)
  return [...own, ...base]
}

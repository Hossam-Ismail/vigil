import { useEffect } from 'react'
import type { ReactNode } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { AuthProvider, useAuth } from './lib/auth'
import { startLive } from './lib/live'
import { CameraDetail } from './pages/CameraDetail'
import { Cameras } from './pages/Cameras'
import { Events } from './pages/Events'
import { Metrics } from './pages/Metrics'
import { Live } from './pages/Live'
import { NewWatch } from './pages/NewWatch'
import { PushCamera } from './pages/PushCamera'
import { Settings } from './pages/Settings'
import { Lab } from './pages/Lab'
import { Onboarding, Welcome } from './pages/Welcome'
import { WatchDetail } from './pages/WatchDetail'
import { Watches } from './pages/Watches'

/** Nothing opens until there is a verified .edu account that finished setup (questions, AI key, camera). */
function Gate({ children }: { children: ReactNode }) {
  const { me, loading } = useAuth()
  const ready = me?.next === 'ready'
  useEffect(() => {
    if (ready) startLive()
  }, [ready])
  if (loading) return null
  if (!me) return <Welcome />
  if (!ready) return <Onboarding />
  return <>{children}</>
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </AuthProvider>
  )
}

function AppRoutes() {
  return (
      <Routes>
        <Route path="/push/:id" element={<PushCamera />} />
        <Route element={<Gate><Layout /></Gate>}>
          <Route index element={<Live />} />
          <Route path="new" element={<NewWatch />} />
          <Route path="watches" element={<Watches />} />
          <Route path="watches/:id" element={<WatchDetail />} />
          <Route path="metrics" element={<Metrics />} />
          <Route path="events" element={<Events />} />
          <Route path="cameras" element={<Cameras />} />
          <Route path="cameras/:id" element={<CameraDetail />} />
          <Route path="settings" element={<Settings />} />
          <Route path="lab" element={<Lab />} />
        </Route>
      </Routes>
  )
}

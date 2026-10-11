import { useEffect } from 'react'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
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
import { WatchDetail } from './pages/WatchDetail'
import { Watches } from './pages/Watches'

export default function App() {
  useEffect(() => {
    startLive()
  }, [])
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/push/:id" element={<PushCamera />} />
        <Route element={<Layout />}>
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
    </BrowserRouter>
  )
}

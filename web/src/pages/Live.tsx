import { Camera as CameraIcon, Plus } from 'lucide-react'
import { Link } from 'react-router-dom'
import { CameraView } from '../components/CameraView'
import { Page } from '../components/Layout'
import { PromptBar } from '../components/PromptBar'
import { Button, Card, cx, Empty } from '../components/ui'
import { WatchChip } from '../components/WatchChip'
import type { Camera, Watch } from '../lib/api'
import { useFetch, useInterval } from '../lib/hooks'
import { useLive } from '../lib/live'

export function CameraStatusDot({ cam }: { cam: Camera }) {
  const live = useLive((s) => s.cameras[cam.id])
  const status = live?.status ?? cam.status
  return (
    <span
      title={status}
      className={cx('size-2 rounded-full', status === 'live' ? 'bg-ok live-dot' : status === 'error' ? 'bg-alert' : 'bg-warn')}
    />
  )
}

function CameraTile({ cam, watches }: { cam: Camera; watches: Watch[] }) {
  const perception = useLive((s) => s.perception[cam.id])
  const aspect = cam.width && cam.height ? cam.width / cam.height : 16 / 9
  return (
    <Card className="overflow-hidden">
      <Link to={`/cameras/${cam.id}`} className="block">
        <CameraView cameraId={cam.id} aspect={aspect} watches={watches} rounded={false} fps={4} />
      </Link>
      <div className="p-3">
        <div className="flex items-center gap-2">
          <CameraStatusDot cam={cam} />
          <Link to={`/cameras/${cam.id}`} className="min-w-0 flex-1 truncate font-medium hover:underline">
            {cam.name}
          </Link>
          {perception && <span className="num text-[11.5px] text-muted">{perception.tick_ms.toFixed(0)} ms/frame</span>}
        </div>
        <div className="mt-2.5 flex flex-col gap-1.5">
          {watches.map((w) => (
            <WatchChip key={w.id} w={w} />
          ))}
          {!watches.length && <div className="rounded-lg border border-dashed border-line px-3 py-2.5 text-[12.5px] text-muted">No watches yet. Describe one above.</div>}
        </div>
      </div>
    </Card>
  )
}

export function Live() {
  const cams = useFetch<Camera[]>('/api/cameras')
  const watches = useFetch<Watch[]>('/api/watches')
  const modelTick = useLive((s) => s.modelTick)
  useInterval(() => watches.reload(), 8000)
  void modelTick

  const list = cams.data ?? []
  const active = (watches.data ?? []).filter((w) => w.status === 'active').length
  return (
    <Page
      wide
      title="Live"
      subtitle={`${list.length} camera${list.length === 1 ? '' : 's'} · ${active} active watch${active === 1 ? '' : 'es'}`}
      actions={
        <Link to="/cameras?add=1">
          <Button icon={<Plus className="size-4" />}>Add camera</Button>
        </Link>
      }
    >
      <div className="mb-6">
        <PromptBar cameras={list} />
      </div>
      {cams.data && !list.length ? (
        <Card>
          <Empty icon={<CameraIcon className="size-8" />} title="No cameras yet" action={<Link to="/cameras?add=1"><Button variant="primary">Add a camera</Button></Link>}>
            Connect an IP camera over RTSP, use this device's camera, or start with a demo scene.
          </Empty>
        </Card>
      ) : (
        <div className="grid gap-4 [grid-template-columns:repeat(auto-fill,minmax(min(100%,420px),1fr))]">
          {list.map((c) => (
            <CameraTile key={c.id} cam={c} watches={(watches.data ?? []).filter((w) => w.camera_id === c.id)} />
          ))}
        </div>
      )}
    </Page>
  )
}

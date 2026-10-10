import { Bell, Hash, MessageCircle, Plus, Ticket, Trash2, Webhook } from 'lucide-react'
import type { ReactNode } from 'react'
import type { Action, ActionType } from '../lib/api'
import { Button, cx, inputCls } from './ui'

export const ACTION_INFO: Record<ActionType, { label: string; icon: ReactNode; target: string; hint: string }> = {
  imessage: {
    label: 'iMessage',
    icon: <MessageCircle className="size-4" />,
    target: 'Phone or Apple ID (blank = default from Settings)',
    hint: 'Sent with the snapshot through Photon. Reply YES or NO and the watch learns from it.',
  },
  hubspot: {
    label: 'HubSpot',
    icon: <Ticket className="size-4" />,
    target: '',
    hint: 'Creates a record with the snapshot link, camera, time and your request.',
  },
  webhook: { label: 'Webhook', icon: <Webhook className="size-4" />, target: 'https://…', hint: 'POSTs the event as JSON to your system.' },
  slack: { label: 'Slack', icon: <Hash className="size-4" />, target: 'https://hooks.slack.com/services/…', hint: 'Posts to the channel behind this incoming webhook.' },
  ntfy: { label: 'Phone push', icon: <Bell className="size-4" />, target: 'ntfy topic', hint: 'Push to the free ntfy app.' },
}

export function ActionsEditor({ actions, onChange }: { actions: Action[]; onChange: (a: Action[]) => void }) {
  const set = (i: number, patch: Partial<Action>) => onChange(actions.map((a, j) => (j === i ? { ...a, ...patch } : a)))
  const add = (type: ActionType) => onChange([...actions, { type, target: '', object: type === 'hubspot' ? 'ticket' : '', note: '' }])
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between">
        <div className="text-[12.5px] font-medium text-muted">Then</div>
        <div className="text-[11.5px] text-muted">Every alert is also saved with its clip in Events.</div>
      </div>
      {actions.map((a, i) => (
        <div key={i} className="rounded-lg border border-line bg-panel-2 p-3">
          <div className="flex items-center gap-2">
            <span className="text-accent">{ACTION_INFO[a.type].icon}</span>
            <span className="min-w-[72px] text-[13px] font-medium">{ACTION_INFO[a.type].label}</span>
            {a.type === 'hubspot' ? (
              <select className={cx(inputCls, 'flex-1')} value={a.object || 'ticket'} onChange={(e) => set(i, { object: e.target.value as Action['object'] })}>
                <option value="ticket">Open a ticket</option>
                <option value="task">Create a task</option>
                <option value="note">Log a note</option>
              </select>
            ) : (
              <input className={cx(inputCls, 'flex-1')} placeholder={ACTION_INFO[a.type].target} value={a.target} onChange={(e) => set(i, { target: e.target.value })} />
            )}
            <Button size="sm" variant="ghost" icon={<Trash2 className="size-3.5" />} onClick={() => onChange(actions.filter((_, j) => j !== i))} />
          </div>
          <input className={cx(inputCls, 'mt-2')} placeholder="Add a note (optional), e.g. “Call the carrier”" value={a.note} onChange={(e) => set(i, { note: e.target.value })} />
          <div className="mt-1.5 text-[11.5px] text-muted">{ACTION_INFO[a.type].hint}</div>
        </div>
      ))}
      <div className="flex flex-wrap gap-1">
        {(Object.keys(ACTION_INFO) as ActionType[]).map((t) => (
          <Button key={t} size="sm" variant="ghost" icon={<Plus className="size-3.5" />} onClick={() => add(t)}>
            {ACTION_INFO[t].label}
          </Button>
        ))}
      </div>
    </div>
  )
}

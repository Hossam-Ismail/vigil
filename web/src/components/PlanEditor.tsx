import type { Crossing, WatchSpec } from '../lib/api'
import { TRIGGER_LABEL } from '../lib/format'
import { ActionsEditor } from './ActionsEditor'
import { CROSS_LABEL } from './Tripwire'
import { cx, Field, inputCls, Toggle } from './ui'

export function PlanEditor({ spec, onChange }: { spec: WatchSpec; onChange: (s: WatchSpec) => void }) {
  const set = <K extends keyof WatchSpec>(k: K, v: WatchSpec[K]) => onChange({ ...spec, [k]: v })
  return (
    <div className="flex flex-col gap-4">
      <Field label="Name">
        <input className={inputCls} value={spec.name} onChange={(e) => set('name', e.target.value)} />
      </Field>
      <Field label="Alert when the answer is YES">
        <textarea className={cx(inputCls, 'h-auto min-h-[60px] py-2 leading-5')} value={spec.question} onChange={(e) => set('question', e.target.value)} />
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="YES looks like" hint="Short, visual, no locations">
          <input className={inputCls} value={spec.positive_label} onChange={(e) => set('positive_label', e.target.value)} />
        </Field>
        <Field label="NO looks like">
          <input className={inputCls} value={spec.negative_label} onChange={(e) => set('negative_label', e.target.value)} />
        </Field>
      </div>
      {spec.kind === 'presence' && (
        <Field label="Trigger on" hint={spec.crossing !== 'none' ? 'Drag the line on the image; the arrow shows which way counts.' : 'Any matching object inside the region.'}>
          <select
            className={inputCls}
            value={spec.crossing}
            onChange={(e) => {
              const crossing = e.target.value as Crossing
              const line = spec.line ?? (crossing === 'left' || crossing === 'right' ? [[0.5, 0.15], [0.5, 0.95]] : [[0.1, 0.6], [0.9, 0.6]])
              onChange({ ...spec, crossing, line: crossing === 'none' ? spec.line : (line as WatchSpec['line']), trigger: crossing === 'none' ? spec.trigger : 'per_object' })
            }}
          >
            {(Object.keys(CROSS_LABEL) as Crossing[]).map((k) => <option key={k} value={k}>{CROSS_LABEL[k]}</option>)}
          </select>
        </Field>
      )}
      {spec.kind !== 'state' && (
        <div className="grid grid-cols-2 gap-3">
          <Field label="Objects to detect" hint="Comma separated">
            <input className={inputCls} value={spec.targets.join(', ')} onChange={(e) => set('targets', e.target.value.split(',').map((t) => t.trim()).filter(Boolean))} />
          </Field>
          {spec.kind === 'count' ? (
            <Field label="Alert when count is">
              <div className="flex gap-2">
                <select className={cx(inputCls, 'w-20')} value={spec.count_op} onChange={(e) => set('count_op', e.target.value as WatchSpec['count_op'])}>
                  {['<', '<=', '==', '>=', '>'].map((o) => <option key={o}>{o}</option>)}
                </select>
                <input type="number" min={0} className={inputCls} value={spec.count_value} onChange={(e) => set('count_value', Number(e.target.value))} />
              </div>
            </Field>
          ) : (
            <Field label="Per-object check (optional)">
              <input className={inputCls} value={spec.target_question} placeholder="e.g. Is this person NOT wearing a hard hat?" onChange={(e) => set('target_question', e.target.value)} />
            </Field>
          )}
        </div>
      )}
      <div className="grid grid-cols-2 gap-3">
        <Field label="Must hold for" hint="Ignores momentary blips">
          <div className="relative">
            <input type="number" min={0} className={inputCls} value={spec.min_duration_s} onChange={(e) => set('min_duration_s', Number(e.target.value))} />
            <span className="absolute right-3 top-2 text-muted text-[12.5px]">sec</span>
          </div>
        </Field>
        <Field label="Quiet period between alerts">
          <div className="relative">
            <input type="number" min={10} className={inputCls} value={spec.cooldown_s} onChange={(e) => set('cooldown_s', Number(e.target.value))} />
            <span className="absolute right-3 top-2 text-muted text-[12.5px]">sec</span>
          </div>
        </Field>
        <Field label="Alert">
          <select className={inputCls} value={spec.trigger} onChange={(e) => set('trigger', e.target.value as WatchSpec['trigger'])}>
            {(Object.keys(TRIGGER_LABEL) as (keyof typeof TRIGGER_LABEL)[])
              .filter((k) => k !== 'per_object' || spec.kind === 'presence')
              .map((k) => <option key={k} value={k}>{TRIGGER_LABEL[k]}</option>)}
          </select>
        </Field>
        <Field label="Severity">
          <select className={inputCls} value={spec.severity} onChange={(e) => set('severity', e.target.value as WatchSpec['severity'])}>
            <option value="info">Info</option>
            <option value="warning">Warning</option>
            <option value="critical">Critical</option>
          </select>
        </Field>
      </div>
      <div className="flex items-center justify-between gap-4 rounded-lg border border-line bg-panel-2 px-3 py-2.5">
        <div>
          <div className="text-[13px] font-medium">Double-check before alerting</div>
          <div className="text-[12px] text-muted">The brain reviews each alert's frames; rejections become training data.</div>
        </div>
        <Toggle checked={spec.verify_with_vlm} onChange={(v) => set('verify_with_vlm', v)} label="Double-check alerts" />
      </div>
      <Field label="Notification text">
        <input className={inputCls} value={spec.alert_message} onChange={(e) => set('alert_message', e.target.value)} />
      </Field>
      <ActionsEditor actions={spec.actions ?? []} onChange={(a) => set('actions', a)} />
    </div>
  )
}

import { ArrowRight, Camera, Check, Cpu, Film, Link2, MessageSquare, Monitor, Network, Radio, ShieldCheck, Smartphone, Webhook, X } from 'lucide-react'
import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { Logo } from '../components/Layout'
import { cx } from '../components/ui'
import { api } from '../lib/api'
import { useAuth, type Me } from '../lib/auth'
import { BetaPill } from './Welcome'
import { CountUp, LoopVideo, Reveal, reduced, useInView, useTyped } from './landing/motion'

/* Vigil's marketing site. Rules: real footage only (the brackets and labels in it are Vigil's own output), and
   every number is one we measured, with where it came from. */

const W = 'mx-auto max-w-[1240px] px-4 md:px-10'

function Eyebrow({ children }: { children: ReactNode }) {
  return <Reveal className="hud flex items-center gap-2 text-[11.5px] text-accent"><span className="h-px w-6 bg-accent" />{children}</Reveal>
}

function H2({ children, className }: { children: ReactNode; className?: string }) {
  return <Reveal delay={60}><h2 className={cx('mt-4 max-w-[820px] text-[36px] font-semibold leading-[1.08] tracking-tight md:text-[50px]', className)}>{children}</h2></Reveal>
}

/* ------------------------------------------------------------------------------------------------ hero */

const PROMPT = 'Text me when a truck enters the yard'

/** The hero's live card: a request is typed, Vigil picks a model, spots it in the footage behind, and texts you. */
function HeroWatch() {
  const [step, setStep] = useState(0) // 0 typing · 1 understanding · 2 watching · 3 spotted · 4 texted
  const [typed, setTyped] = useState(reduced() ? PROMPT.length : 0)
  useEffect(() => {
    if (reduced()) { setStep(4); return }
    let alive = true
    const wait = (ms: number) => new Promise((r) => setTimeout(r, ms))
    const run = async () => {
      while (alive) {
        setStep(0)
        for (let i = 0; i <= PROMPT.length && alive; i++) { setTyped(i); await wait(42) }
        await wait(500); if (!alive) return; setStep(1)
        await wait(1100); if (!alive) return; setStep(2)
        await wait(1500); if (!alive) return; setStep(3)
        await wait(900); if (!alive) return; setStep(4)
        await wait(3800)
      }
    }
    run()
    return () => { alive = false }
  }, [])
  const chip = (on: boolean, done: boolean, label: string, t: string) => (
    <div className={cx('flex items-center gap-2 text-[12.5px] transition-colors duration-300', on ? 'text-ink' : 'text-muted/50')}>
      <span className={cx('flex size-4 items-center justify-center rounded-full border', done ? 'border-accent bg-accent text-accent-ink' : on ? 'border-accent' : 'border-line-2')}>
        {done ? <Check className="size-3" /> : on ? <span className="size-1.5 rounded-full bg-accent live-dot" /> : null}
      </span>
      <span className="flex-1">{label}</span>
      <span className={cx('num text-[11px]', done ? 'text-accent' : 'text-transparent')}>{t}</span>
    </div>
  )
  return (
    <div className="relative w-full max-w-[410px]">
      <div className="rounded-2xl border border-line-2/70 bg-panel/85 p-5 shadow-2xl shadow-black/50 backdrop-blur-md">
        <div className="hud flex items-center justify-between text-[10.5px] text-muted">
          <span>NEW WATCH · YARD CAM</span>
          <span className={cx('flex items-center gap-1.5', step >= 2 ? 'text-accent' : '')}>
            <span className={cx('size-1.5 rounded-full', step >= 2 ? 'bg-accent live-dot' : 'bg-line-2')} />{step >= 2 ? 'LIVE' : 'DRAFT'}
          </span>
        </div>
        <div className="mt-3 min-h-[52px] rounded-lg border border-accent/60 bg-bg/70 px-3 py-2.5 text-[15px]">
          <span className={step === 0 ? 'caret' : ''}>{PROMPT.slice(0, typed)}</span>
        </div>
        <div className="mt-4 flex flex-col gap-2.5">
          {chip(step >= 1, step >= 2, 'Understood: a vehicle entering the yard', 'no training')}
          {chip(step >= 2, step >= 3, 'Watching with a people & vehicle detector', '41 ms/frame')}
          {chip(step >= 3, step >= 4, 'Truck spotted, double-checked by a second AI', '~4 s')}
        </div>
      </div>
      <div className={cx('absolute right-[-16px] top-full mt-4 w-[300px] rounded-2xl border border-white/10 bg-[#1c1c1e]/95 p-3 shadow-2xl shadow-black/60 backdrop-blur transition-all duration-500',
        step >= 4 ? 'translate-y-0 opacity-100' : 'pointer-events-none translate-y-3 opacity-0')}>
        <div className="flex items-center gap-2 text-[12px] text-white/60">
          <span className="flex size-5 items-center justify-center rounded-md bg-[#34c759] text-[10px] font-bold text-white">✓</span>
          MESSAGES · now
        </div>
        <div className="mt-1.5 flex gap-2.5">
          <img src="/landing/yard.jpg" alt="" className="size-12 shrink-0 rounded-lg object-cover" />
          <div className="text-[13.5px] leading-snug text-white"><b>Vigil</b><br />A truck just entered the yard. Photo attached. Reply NO if that's wrong.</div>
        </div>
      </div>
    </div>
  )
}

const PROMPTS = [
  'Text me when a car pulls out of a spot so I can send the next van in', 'Tell the lead when someone has no hard hat',
  'Text me if anyone smokes by the service door', 'How many people are on the plaza?', 'Text me when someone does push-ups',
  'Tell receiving when a truck backs into dock 2', 'Text me when a package is left on the step', 'Tell me if anything blocks the fire exit',
]

/* ------------------------------------------------------------------------------------------------ speed */

const TIMELINE: [string, string, string][] = [
  ['0 s', 'You type it', '“Text me if anyone smokes by the service door.”'],
  ['< 20 s', 'It is watching', 'Vigil reads the request and picks a model that already knows the scene. Nothing to train.'],
  ['41 ms', 'Every frame, checked', 'The object detector looks at each frame in 41 ms on a laptop; actions are judged on 2-second clips in 0.15 s.'],
  ['~2 s', 'Sure, not twitchy', 'It needs 3 agreeing checks out of 5 before it believes it, so one odd frame never texts you.'],
  ['~4 s', 'Double-checked', 'A second AI looks at the moment and can veto a false alarm. Median 4.2 s across 61 real alerts.'],
  ['', 'In your pocket', 'The iMessage lands with the photo. Reply NO and that watch learns.'],
]

function Speed() {
  const [ref, seen] = useInView<HTMLDivElement>('-20% 0px')
  return (
    <section id="speed" className="relative scroll-mt-20 overflow-hidden border-y border-line bg-bg-2">
      <div className="dot-grid absolute inset-0 opacity-30" />
      <div className={cx(W, 'relative py-24')}>
        <Eyebrow>SPEED</Eyebrow>
        <H2>From a sentence to a working watch in seconds, <span className="text-accent">not a project.</span></H2>
        <Reveal delay={120}>
          <p className="mt-5 max-w-[640px] text-[17px] leading-relaxed text-ink-2">
            Most camera AI means collecting footage, labeling it and training a model for weeks. Vigil skips all of that: it
            routes your sentence to models that already understand people, everyday objects and 400 human actions.
          </p>
        </Reveal>
        <div className="mt-12 grid gap-4 md:grid-cols-3">
          {[['< 20 s', 'from typing a request to a live watch'], ['41 ms', 'to check a frame for people and objects'], ['4.2 s', 'median double-check before you are texted']].map(([n, t], i) => (
            <Reveal key={t} delay={i * 90} className="rounded-xl border border-line bg-panel p-7">
              <div className="num text-[52px] leading-none text-accent"><CountUp value={n} /></div>
              <p className="mt-3 text-[15px] text-ink-2">{t}</p>
            </Reveal>
          ))}
        </div>
        {/* the path of one alert */}
        <div ref={ref} className="relative mt-14">
          <div className="absolute left-[7px] top-2 bottom-2 w-px bg-line md:left-0 md:right-0 md:top-[7px] md:bottom-auto md:h-px md:w-auto" />
          <div className={cx('absolute left-[7px] top-2 w-px bg-accent transition-all duration-[2400ms] ease-out md:left-0 md:top-[7px] md:h-px',
            seen ? 'bottom-2 md:w-full' : 'bottom-full md:w-0')} />
          <ol className="relative grid gap-8 md:grid-cols-6 md:gap-5">
            {TIMELINE.map(([t, title, d], i) => (
              <li key={title} className={cx('reveal pl-8 md:pl-0', seen && 'in')} style={{ transitionDelay: `${300 + i * 320}ms` }}>
                <span className={cx('absolute left-0 flex size-[15px] items-center justify-center rounded-full border-2 bg-bg-2 md:static md:mb-4', seen ? 'border-accent' : 'border-line-2')}>
                  <span className="size-1.5 rounded-full bg-accent" />
                </span>
                <div className="num text-[13px] text-accent">{t || '✓'}</div>
                <div className="mt-1 text-[17px] font-semibold">{title}</div>
                <p className="mt-1.5 text-[13.5px] leading-relaxed text-muted">{d}</p>
              </li>
            ))}
          </ol>
        </div>
        <Reveal className="mt-14 grid items-center gap-6 rounded-2xl border border-line bg-panel p-6 md:grid-cols-[auto_1fr]">
          <div className="num text-[46px] leading-none text-accent"><CountUp value="9" /><span className="text-ink-2"> / 63</span></div>
          <div>
            <div className="text-[18px] font-semibold">Double-checked, so your phone stays quiet.</div>
            <p className="mt-1 text-[14.5px] text-muted">Alerts in our test runs that the fast model raised but the second AI stopped before they reached a phone, like a parked van whose roof looked like an empty space.</p>
          </div>
        </Reveal>
        <Reveal className="hud mt-10 text-[10.5px] text-muted">MEASURED ON A MACBOOK WITH THE ON-DEVICE AI · DETECTOR ON 3,332 COCO FRAMES · DOUBLE-CHECK ON 61 REAL ALERTS</Reveal>
      </div>
    </section>
  )
}

/* ------------------------------------------------------------------------------------------------ use cases */

type Tile = { video?: string; img: string; prompt: string; then: string; where: string; tag: string; model: string; big?: boolean }

const TILES: Tile[] = [
  { video: '/landing/parking_vigil.mp4', img: '/landing/parking_vigil_poster.jpg', big: true, tag: 'SPOT OPENED · TEXTED', model: 'A yes/no check on every space, twice a second',
    prompt: 'Text me the moment a car pulls out of a spot, so I can send the next van in', then: 'iMessage, or update the “spaces free” sign by webhook', where: 'Aerial parking lot · real video, 2× speed' },
  { video: '/landing/smoking.mp4', img: '/landing/smoking_poster.jpg', tag: 'SMOKING · CONFIRMED', model: 'Action recognition on 2-second clips (400 human actions)',
    prompt: 'Text me if anyone smokes by the service door', then: 'iMessage with the photo, faces blurred', where: 'Service entrance · real video' },
  { img: '/landing/hardhat.jpg', tag: 'NO HARD HAT · 1 OF 2', model: 'A hard-hat detector, then a check on each head',
    prompt: 'Tell the shift lead if anyone at the pump has no hard hat', then: 'iMessage the lead', where: 'Pump station CCTV · real frame' },
  { video: '/landing/yard.mp4', img: '/landing/yard.jpg', tag: 'TRUCK · TRACKING', model: 'People & vehicle detector, 41 ms a frame',
    prompt: 'When a truck pulls into the yard, text receiving and log it in HubSpot', then: 'iMessage + HubSpot task', where: 'Lumber yard · real drone video' },
  { img: '/landing/plaza.jpg', tag: '6 PEOPLE', model: 'People counter, kept as a metric all day',
    prompt: 'How many people are on the plaza right now?', then: 'a live count, charted all day', where: 'Campus camera · real frame' },
]

/** OpenVector-style switcher: each real clip walks through prompt → model → double-check → follow-up, then moves on. */
function Switcher() {
  const [i, setI] = useState(0)
  const [hold, setHold] = useState(false)
  const [ref, seen] = useInView<HTMLDivElement>()
  const [step, setStep] = useState(0)
  useEffect(() => {
    if (!seen) return
    if (reduced()) { setStep(4); return }
    setStep(0)
    const ids = [250, 1000, 1900, 2800].map((ms, k) => setTimeout(() => setStep(k + 1), ms))
    const next = hold ? undefined : setTimeout(() => setI((x) => (x + 1) % TILES.length), 7000)
    return () => { ids.forEach(clearTimeout); if (next) clearTimeout(next) }
  }, [i, seen, hold])
  const t = TILES[i]
  const row = (k: number, label: string, body: ReactNode) => (
    <div className={cx('flex gap-3 transition-all duration-500', step >= k ? 'translate-x-0 opacity-100' : 'translate-x-2 opacity-0')}>
      <span className="hud w-[92px] shrink-0 pt-0.5 text-[10px] text-muted">{label}</span>
      <div className="text-[14px] leading-snug">{body}</div>
    </div>
  )
  return (
    <div ref={ref} className="grid gap-4 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.6fr)]" onMouseEnter={() => setHold(true)} onMouseLeave={() => setHold(false)}>
      <div className="flex flex-col gap-2" role="tablist" aria-label="Use cases">
        {TILES.map((x, k) => (
          <button key={x.prompt} role="tab" aria-selected={k === i} onClick={() => setI(k)}
            className={cx('relative overflow-hidden rounded-xl border px-4 py-3.5 text-left transition-colors duration-300',
              k === i ? 'border-accent/60 bg-panel-2' : 'border-line bg-panel hover:border-line-2')}>
            <div className="hud text-[10px] text-muted">{x.where}</div>
            <div className={cx('mt-1 text-[15px] leading-snug', k === i ? 'text-ink' : 'text-ink-2')}>“{x.prompt}”</div>
            {k === i && <span key={`${i}-${hold}`} className={cx('absolute bottom-0 left-0 h-0.5 bg-accent', hold ? 'w-full' : 'progress-7s')} />}
          </button>
        ))}
      </div>
      <div className="relative order-first min-h-[420px] overflow-hidden rounded-2xl border border-line bg-black lg:order-none">
        {TILES.map((x, k) => (
          <div key={x.prompt} className={cx('absolute inset-0 transition-opacity duration-700', k === i ? 'opacity-100' : 'opacity-0')} aria-hidden={k !== i}>
            {x.video ? <LoopVideo src={x.video} poster={x.img} label={x.where} className="h-full w-full object-cover" />
              : <img src={x.img} alt={x.where} loading="lazy" className="h-full w-full object-cover" />}
          </div>
        ))}
        <div className="absolute inset-0 bg-gradient-to-t from-black/95 via-black/40 to-transparent" />
        <span className="brackets pointer-events-none absolute inset-4" />
        <span key={i} className="sweep" />
        <span className="hud absolute left-5 top-5 flex items-center gap-1.5 rounded bg-black/65 px-2 py-1 text-[10px] text-accent">
          <span className="size-1.5 rounded-full bg-accent live-dot" />{t.tag}
        </span>
        <div className="absolute inset-x-0 bottom-0 flex flex-col gap-2.5 p-5 text-white md:p-6">
          {row(1, 'YOU SAID', <span className="text-[16px] font-medium">“{t.prompt}”</span>)}
          {row(2, 'VIGIL PICKED', t.model)}
          {row(3, 'DOUBLE-CHECK', 'A second AI looked at the moment and confirmed it')}
          {row(4, 'THEN', <span className="text-accent">→ {t.then}</span>)}
        </div>
      </div>
    </div>
  )
}

const MORE: [string, string, string][] = [
  ['Home', 'Text me when a package is left on the step.', 'iMessage with the photo'],
  ['Home', 'Text me if the garage is open for 15 minutes.', 'iMessage'],
  ['Manufacturing', 'Tell me when Line 1’s staging area runs empty.', 'restock task in HubSpot'],
  ['Warehousing', 'Tell receiving when a truck backs into dock 2.', 'Slack post, arrival logged'],
  ['Facilities', 'Tell me if anything blocks the fire exit.', 'HubSpot ticket, high priority'],
  ['Retail', 'Text me when 5 or more people wait to pay.', 'iMessage the manager'],
  ['Auto service', 'Tell the advisor when a car leaves bay 2.', 'job closed by webhook'],
  ['Fitness', 'Text me when someone does push-ups.', 'iMessage with the photo'],
]

function UseCases() {
  return (
    <section id="cases" className={cx(W, 'scroll-mt-20 py-24')}>
      <Eyebrow>USE CASES · REAL CAMERAS</Eyebrow>
      <H2>What do you still check by hand?</H2>
      <Reveal delay={120}><p className="mt-5 max-w-[620px] text-[17px] leading-relaxed text-ink-2">Every clip and frame below is real camera footage, and the brackets and labels in it are Vigil's own calls.</p></Reveal>
      <Reveal delay={120} className="mt-12"><Switcher /></Reveal>
      <Reveal className="mt-12 overflow-hidden rounded-2xl border border-line">
        <div className="hud border-b border-line bg-panel px-5 py-3 text-[10.5px] text-muted">ONE SENTENCE IN · THE FOLLOW-UP OUT</div>
        <ul className="divide-y divide-line">
          {MORE.map(([who, p, then], i) => (
            <li key={p} className="reveal in group grid items-center gap-2 bg-panel/60 px-5 py-3.5 transition-colors hover:bg-panel-2 md:grid-cols-[140px_1fr_auto]" style={{ transitionDelay: `${i * 40}ms` }}>
              <span className="hud text-[10.5px] text-muted">{who}</span>
              <span className="text-[15.5px]"><span className="mr-2 text-accent">&gt;</span>{p}</span>
              <span className="text-[13px] text-ink-2 transition-colors group-hover:text-accent">→ {then}</span>
            </li>
          ))}
        </ul>
      </Reveal>
    </section>
  )
}

/* ------------------------------------------------------------------------------------------------ parking spotlight */

function Spotlight() {
  return (
    <section className="scroll-mt-20 border-y border-line bg-bg-2">
      <div className={cx(W, 'grid items-center gap-12 py-24 lg:grid-cols-[1.35fr_1fr]')}>
        <Reveal className="relative overflow-hidden rounded-2xl border border-line">
          <LoopVideo src="/landing/parking_vigil.mp4" poster="/landing/parking_vigil_poster.jpg" label="Real aerial parking lot video: Vigil watches 161 spaces and texts when one opens" className="block w-full" />
          <span className="hud absolute left-3 top-3 rounded bg-black/65 px-2 py-1 text-[10px] text-white/80">REAL VIDEO · 2× · THE MODEL NEVER SAW THIS LOT</span>
        </Reveal>
        <div>
          <Eyebrow>SPOTLIGHT · PARKING</Eyebrow>
          <Reveal delay={60}><h3 className="mt-4 text-[34px] font-semibold leading-tight md:text-[42px]">Know the moment a spot opens.</h3></Reveal>
          <Reveal delay={120}><p className="mt-4 text-[16px] leading-relaxed text-ink-2">One sentence, applied to every space in the lot. Each space is watched on its own, and a text only goes out once an opening holds.</p></Reveal>
          <div className="mt-8 grid grid-cols-3 gap-px overflow-hidden rounded-xl border border-line bg-line">
            {[['161', 'spaces watched'], ['10', 'texts sent'], ['9', 'of them right']].map(([n, t]) => (
              <div key={t} className="bg-panel p-4"><div className="num text-[30px] text-accent"><CountUp value={n} /></div><div className="mt-1 text-[12.5px] text-muted">{t}</div></div>
            ))}
          </div>
          <Reveal delay={180}><p className="mt-4 text-[13.5px] leading-relaxed text-muted">The one miss: a white van whose roof read as an empty bay. Replying NO to that text is exactly how the watch learns.</p></Reveal>
          <Reveal delay={220} className="mt-6 flex items-baseline gap-3 rounded-xl border border-accent/40 bg-accent/5 p-5">
            <span className="num text-[38px] text-accent"><CountUp value="99.4%" /></span>
            <span className="text-[14px] text-ink-2">of 4,000 spaces called right on a second public camera set, on days the model had never seen <span className="hud text-[10px] text-muted">· PKLOT, CC BY 4.0</span></span>
          </Reveal>
        </div>
      </div>
    </section>
  )
}

/* ------------------------------------------------------------------------------------------------ iMessage */

/** The iMessage thread plays out once it scrolls into view. */
function Thread() {
  const [ref, seen] = useInView<HTMLDivElement>()
  const [shown, setShown] = useState(0)
  useEffect(() => {
    if (!seen) return
    if (reduced()) return setShown(8)
    const ids = [300, 1300, 2100, 3000, 4200, 5100, 6300, 7300].map((ms, i) => setTimeout(() => setShown(i + 1), ms))
    return () => ids.forEach(clearTimeout)
  }, [seen])
  const typing = (
    <div className="flex w-fit gap-1 rounded-2xl rounded-bl-md bg-[#26272b] px-3.5 py-3">
      {[0, 1, 2].map((i) => <span key={i} className="typing-dot size-1.5 rounded-full bg-white/70" style={{ animationDelay: `${i * 0.15}s` }} />)}
    </div>
  )
  const bubble = (i: number, node: ReactNode) => (
    <div className={cx('transition-all duration-500', shown >= i ? 'translate-y-0 opacity-100' : 'h-0 translate-y-2 overflow-hidden opacity-0')}>{node}</div>
  )
  const me = 'ml-auto w-fit max-w-[80%] rounded-2xl rounded-br-md bg-[#0a84ff] px-3.5 py-2 text-white'
  const them = 'w-fit max-w-[85%] rounded-2xl rounded-bl-md bg-[#26272b] px-3.5 py-2'
  return (
    <div ref={ref} className="mx-auto w-full max-w-[380px] rounded-[42px] border border-line-2 bg-[#0e0f11] p-4 shadow-2xl shadow-black/50">
      <div className="mx-auto mb-3 h-5 w-24 rounded-full bg-black" />
      <div className="mb-3 text-center text-[12px] text-muted">iMessage · Vigil</div>
      <div className="flex min-h-[470px] flex-col gap-2 text-[14.5px]">
        {bubble(1, <div className={me}>What's happening on the plaza?</div>)}
        {shown === 1 && typing}
        {bubble(2, <img src="/landing/plaza.jpg" alt="The live photo Vigil texted back: a campus plaza with people walking" className="w-[70%] rounded-2xl" />)}
        {bubble(3, <div className={them}>Plaza · Entrance, 7:56 PM: I see 3 people, 1 car and 1 truck.</div>)}
        {bubble(4, <div className={me}>How many people are on the plaza?</div>)}
        {shown === 4 && typing}
        {bubble(5, <div className={them}>People on the plaza: 3 people now, 6.2 on average today</div>)}
        {bubble(6, <div className={me}>Text me when a girl walks by</div>)}
        {shown === 6 && typing}
        {bubble(7, <div className={cx(them, 'border border-alert/40')}>I won't watch for that. Vigil does not single out people by gender, race, religion, age or other personal traits.</div>)}
      </div>
      <div className="hud mt-3 text-center text-[10px] text-muted">REAL REPLIES FROM THE RUNNING APP</div>
    </div>
  )
}

function IMessage() {
  return (
    <section id="imessage" className="relative scroll-mt-20 overflow-hidden">
      <div className={cx(W, 'grid items-center gap-14 py-24 md:grid-cols-2')}>
        <div>
          <Eyebrow>AGENTS IN IMESSAGE · BUILT ON PHOTON SPECTRUM</Eyebrow>
          <H2>Vigil lives in iMessage. Text it like a person.</H2>
          <Reveal delay={120}>
            <p className="mt-5 text-[17px] leading-relaxed text-ink-2">
              Start a watch, ask what a camera sees, get a live count, pause a watch, or tell it an alert was wrong. It texts
              you first when something happens, with the photo. Nothing to install on the phone.
            </p>
          </Reveal>
          <ol className="mt-8 flex flex-col gap-4">
            {[
              ['Your iPhone → Messages on the Mac', 'Plain iMessage. Only the owner’s number gets answers.'],
              ['Photon Spectrum receives it', 'Streams the message, marks it read and shows typing while Vigil works.'],
              ['Vigil’s agent decides', 'Create a watch, look, count, pause, or learn from a YES/NO. New watches pass the safety policy first.'],
              ['Spectrum replies in the thread', 'Text and photos, the same conversation, seconds later.'],
            ].map(([t, d], i) => (
              <Reveal key={t} delay={160 + i * 80}>
                <li className="flex gap-4">
                  <span className="num flex size-8 shrink-0 items-center justify-center rounded-full border border-accent/60 text-[12px] text-accent">0{i + 1}</span>
                  <div><div className="font-medium">{t}</div><div className="mt-0.5 text-[14px] text-muted">{d}</div></div>
                </li>
              </Reveal>
            ))}
          </ol>
        </div>
        <div>
          <Thread />
          <Reveal className="mx-auto mt-5 max-w-[380px] text-center text-[12.5px] leading-relaxed text-muted">iMessage goes through a Photon bridge on a Mac signed in to Messages; Vigil itself can run on a separate Windows PC. Slack, ntfy, webhooks and HubSpot work too.</Reveal>
        </div>
      </div>
    </section>
  )
}

/* ------------------------------------------------------------------------------------------------ follow-up + cameras */

function FollowUp() {
  return (
    <section className={cx(W, 'py-24')}>
      <Eyebrow>THE FOLLOW-UP</Eyebrow>
      <H2>It doesn't just see it. It does something about it.</H2>
      <div className="mt-12 grid gap-4 md:grid-cols-3">
        {[
          [MessageSquare, 'iMessage, powered by Photon', 'The text and photo go to any iPhone. Reply YES or NO and that watch learns from it.'],
          [Link2, 'HubSpot', 'Open a ticket, add a task or log a note, with the photo, camera, time and your request attached.'],
          [Webhook, 'Slack and your own systems', 'Post to Slack, or call a webhook: reorder parts, update a waitlist, change a sign.'],
        ].map(([Icon, t, d], i) => {
          const I = Icon as typeof MessageSquare
          return (
            <Reveal key={t as string} delay={i * 90} className="group h-full rounded-2xl border border-line bg-panel p-7 transition-colors duration-300 hover:border-accent/50">
              <I className="size-6 text-accent transition-transform duration-300 group-hover:-translate-y-0.5" />
              <div className="mt-5 text-[20px] font-semibold">{t as string}</div>
              <p className="mt-2 text-[14.5px] leading-relaxed text-muted">{d as string}</p>
            </Reveal>
          )
        })}
      </div>
    </section>
  )
}

function Cameras() {
  const items: [typeof Camera, string, string, string][] = [
    [Network, '01 · IP CAMERAS', 'Found for you', 'Vigil scans the network for ONVIF cameras and fills in the RTSP address. Reolink, Tapo, Hikvision, Dahua, Axis, UniFi and more.'],
    [Smartphone, '02 · PHONE OR LAPTOP', 'Scan a QR code', 'Any phone or laptop becomes a camera from a browser tab. Nothing to install.'],
    [Radio, '03 · STREAM URL', 'Paste the address', 'HLS (.m3u8), MJPEG, RTSPS or any stream FFmpeg can read.'],
    [Camera, '04 · USB WEBCAM', 'Plug it in', 'Any webcam on the computer running Vigil, including an iPhone through Continuity Camera.'],
    [Film, '05 · RECORDED VIDEO', 'Try it on past footage', 'Point Vigil at a video file and it plays back in real time, so you can test a watch before it goes live.'],
    [Monitor, '06 · EVERYTHING ELSE', 'Restream it', 'Cameras without RTSP can be restreamed through go2rtc or MediaMTX, and Vigil reads that.'],
  ]
  return (
    <section className="border-y border-line bg-bg-2">
      <div className={cx(W, 'py-24')}>
        <Eyebrow>CAMERAS</Eyebrow>
        <H2>Plug in the cameras you already have.</H2>
        <div className="mt-12 grid gap-px overflow-hidden rounded-2xl border border-line bg-line sm:grid-cols-2 lg:grid-cols-3">
          {items.map(([Icon, k, t, d], i) => (
            <Reveal key={k} delay={(i % 3) * 80} className="group h-full bg-panel p-7 transition-colors duration-300 hover:bg-panel-2">
              <div className="flex items-center justify-between">
                <span className="hud text-[10.5px] text-muted">{k}</span>
                <Icon className="size-5 text-accent opacity-70 transition-opacity group-hover:opacity-100" />
              </div>
              <div className="mt-4 text-[20px] font-semibold">{t}</div>
              <p className="mt-2 text-[14px] leading-relaxed text-muted">{d}</p>
            </Reveal>
          ))}
        </div>
        <Reveal className="mt-8 flex flex-wrap items-center gap-3 text-[15px] text-ink-2">
          <span className="rounded-lg border border-line bg-panel px-3 py-2">A camera you already have</span><span className="text-accent">+</span>
          <span className="rounded-lg border border-line bg-panel px-3 py-2">Any Mac or PC</span><span className="text-accent">+</span>
          <span className="rounded-lg border border-line bg-panel px-3 py-2">One sentence</span><span className="text-accent">=</span>
          <span className="rounded-lg border border-accent/60 bg-accent/10 px-3 py-2 text-ink">A camera that texts you when it matters</span>
        </Reveal>
      </div>
    </section>
  )
}

/* ------------------------------------------------------------------------------------------------ safety */

type Verdict = { allowed: boolean; category: string; reason: string; suggestion: string; by?: string }
const TRY = ['Alert me if the cashier is slacking off', 'Find out who keeps parking in my spot', 'Tell me when someone looks suspicious',
  'Text me when a girl walks by', 'Text me when a man is lying on the floor', 'Text me when a package is left on the step']
const CATEGORY: Record<string, string> = { identity: 'IDENTIFYING SOMEONE', protected_traits: 'PERSONAL TRAITS', bodies: 'BODIES',
  private_spaces: 'PRIVATE SPACES', covert: 'SECRET MONITORING', inference: 'JUDGING BY LOOKS', minors: 'CHILDREN', harm: 'HARM' }

/** Visitors can try to misuse Vigil here: Vigil's safety rules, plus an AI reviewer that reads the request like a person. */
function Guardrails() {
  const [text, setText] = useState('')
  const [v, setV] = useState<Verdict | null>(null)
  const [asked, setAsked] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(false)
  const check = async (t: string) => {
    const q = t.trim()
    if (!q || busy) return
    setText(q); setBusy(true); setErr(false); setAsked(q)
    try {
      setV(await api.post<Verdict>('/api/safety/check', { text: q }))
    } catch {
      setV(null); setErr(true)
    } finally {
      setBusy(false)
    }
  }
  const submit = (e: FormEvent) => { e.preventDefault(); check(text) }
  return (
    <section id="safe" className="relative scroll-mt-20 overflow-hidden">
      <div className={cx(W, 'py-24')}>
        <Eyebrow>SAFE BY DESIGN</Eyebrow>
        <H2>We thought about how this could be misused, <span className="text-accent">and built the guardrails in.</span></H2>
        <Reveal delay={120}>
          <p className="mt-5 max-w-[680px] text-[17px] leading-relaxed text-ink-2">
            A camera that understands plain English could be pointed at people instead of problems. So Vigil watches events,
            never identities. Every request is checked before it is understood, checked again after, and refused with a plain
            reason and a better way to ask.
          </p>
        </Reveal>
        <div className="mt-12 grid gap-6 lg:grid-cols-[1.1fr_1fr]">
          <Reveal className="rounded-2xl border border-line bg-panel p-6">
            <div className="hud flex items-center gap-2 text-[10.5px] text-muted"><ShieldCheck className="size-4 text-accent" /> TRY TO MISUSE IT · LIVE CHECK</div>
            <form onSubmit={submit} className="mt-4 flex gap-2">
              <input value={text} onChange={(e) => setText(e.target.value)} maxLength={300} placeholder="Type anything you’d ask a camera…" aria-label="A request to check"
                className="min-w-0 flex-1 rounded-lg border border-line-2 bg-bg px-3.5 py-3 text-[15px] outline-none transition-colors placeholder:text-muted focus:border-accent" />
              <button disabled={busy || !text.trim()} className="hud rounded-lg bg-accent px-4 text-accent-ink transition-[filter] hover:brightness-110 disabled:opacity-60">{busy ? 'Checking' : 'Check'}</button>
            </form>
            <div className="mt-3 flex flex-wrap gap-2">
              {TRY.map((t) => (
                <button key={t} onClick={() => check(t)} disabled={busy}
                  className={cx('rounded-full border px-3 py-1.5 text-[12.5px] transition-colors hover:border-accent hover:text-ink',
                    asked === t ? 'border-accent text-ink' : 'border-line text-ink-2')}>{t}</button>
              ))}
            </div>
            <div className="mt-5 min-h-[164px]" aria-live="polite">
              {busy ? (
                <div className="rounded-xl border border-line p-4">
                  <div className="hud flex items-center gap-2 text-[11px] text-accent"><span className="size-1.5 rounded-full bg-accent live-dot" />READING IT LIKE A PERSON WOULD…</div>
                  <div className="mt-2 text-[14px] text-muted">“{asked}”</div>
                  <div className="mt-4 flex flex-col gap-2">{[85, 60].map((w) => <div key={w} className="shimmer h-3 rounded" style={{ width: `${w}%` }} />)}</div>
                </div>
              ) : v ? (
                <div key={asked} className={cx('slide-in rounded-xl border p-4', v.allowed ? 'border-accent/50 bg-accent/5' : 'border-alert/50 bg-alert-soft')}>
                  <div className={cx('hud flex items-center gap-2 text-[11px]', v.allowed ? 'text-accent' : 'text-alert')}>
                    {v.allowed ? <Check className="size-4" /> : <X className="size-4" />}
                    {v.allowed ? 'ALLOWED' : `REFUSED · ${CATEGORY[v.category] ?? 'POLICY'}`}
                  </div>
                  <div className="mt-2 text-[14px] text-muted">“{asked}”</div>
                  <div className="mt-2 text-[15.5px] leading-snug">{v.reason}</div>
                  {!v.allowed && v.suggestion && (
                    <button onClick={() => check(v.suggestion)} className="group mt-3 flex w-full items-start gap-2 rounded-lg border border-line bg-bg/50 px-3 py-2.5 text-left transition-colors hover:border-accent">
                      <span className="hud mt-0.5 shrink-0 text-[10px] text-accent">ASK INSTEAD</span>
                      <span className="flex-1 text-[14px] text-ink">“{v.suggestion}”</span>
                      <ArrowRight className="mt-0.5 size-4 shrink-0 text-muted transition-colors group-hover:text-accent" />
                    </button>
                  )}
                </div>
              ) : (
                <div className="rounded-xl border border-dashed border-line p-4 text-[14px] text-muted">
                  {err ? 'Couldn’t reach Vigil just now. Try again in a moment.' : 'Pick an example or type your own. Vigil’s safety rules and an AI reviewer read it the way a person would, so rewording doesn’t sneak past.'}
                </div>
              )}
            </div>
          </Reveal>
          <div className="grid gap-4">
            <Reveal delay={90} className="rounded-2xl border border-line bg-panel p-6">
              <div className="hud text-[10.5px] text-muted">VIGIL REFUSES TO</div>
              <ul className="mt-3 grid gap-2.5 text-[14.5px] text-ink-2">
                {[['Identify or follow someone', 'No face recognition or tracking a particular person.'],
                  ['Target personal traits', 'No singling people out by race, gender, religion, age or disability, or targeting children.'],
                  ['Inspect bodies or appearance', 'No watching for nudity, body shape or attractiveness.'],
                  ['Watch private spaces', 'No bathrooms, changing rooms, bedrooms or other people’s homes.'],
                  ['Monitor people secretly', 'No hidden-camera requests or spying on people without their knowledge.'],
                  ['Judge people by their looks', 'No guessing emotions, intentions, health or social status from appearance.']].map(([t, d]) => (
                  <li key={t} className="flex gap-2.5"><X className="mt-0.5 size-4 shrink-0 text-alert" /><span><span className="text-ink">{t}.</span> <span className="text-muted">{d}</span></span></li>
                ))}
              </ul>
            </Reveal>
            <Reveal delay={160} className="rounded-2xl border border-line bg-panel p-6">
              <div className="hud text-[10.5px] text-muted">YOUR FOOTAGE STAYS YOURS</div>
              <ul className="mt-3 grid gap-2.5 text-[14.5px] text-ink-2">
                {['Runs on your own computer; in private mode (the default) no image goes to a cloud model',
                  'Faces blurred in every photo and clip it sends', 'Old footage deleted automatically: 7 days, alerts 30',
                  'Camera passwords stay on your machine'].map((t) => (
                  <li key={t} className="flex gap-2.5"><Check className="mt-0.5 size-4 shrink-0 text-accent" />{t}</li>
                ))}
              </ul>
            </Reveal>
          </div>
        </div>
        <div className="mt-6 grid gap-px overflow-hidden rounded-2xl border border-line bg-line md:grid-cols-3">
          {[['1 · Before it is understood', 'Fixed rules read the words and stop identity, profiling, private spaces and covert watching.'],
            ['2 · While it is understood', 'The AI that writes the watch applies the same policy in its own words and can refuse what rules miss.'],
            ['3 · After, on every field', 'The finished watch and every later edit are checked again, so nothing slips in through a rename.']].map(([t, d], i) => (
            <Reveal key={t} delay={i * 90} className="h-full bg-panel p-6">
              <div className="font-medium">{t}</div><p className="mt-1.5 text-[14px] leading-relaxed text-muted">{d}</p>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  )
}

/* ------------------------------------------------------------------------------------------------ results + market */

function Results() {
  return (
    <section id="results" className="scroll-mt-20 border-y border-line bg-bg-2">
      <div className={cx(W, 'py-24')}>
        <Eyebrow>MEASURED ON REAL PUBLIC DATA</Eyebrow>
        <H2>Numbers we measured, not promised.</H2>
        <div className="mt-12 grid gap-px overflow-hidden rounded-2xl border border-line bg-line sm:grid-cols-2 lg:grid-cols-4">
          {[['99.4%', 'parking spaces read correctly on days the model never saw', 'PKLot'],
            ['99%', 'of people found, with 2% false alarms', 'COCO val2017'],
            ['19/20', 'push-up clips caught, 0 of 320 false alarms', 'HMDB51 video'],
            ['86%', 'exact people counts, 98% within one', 'COCO, 1–5 people']].map(([n, t, src], i) => (
            <Reveal key={n} delay={i * 90} className="h-full bg-panel p-8">
              <div className="num text-[46px] text-accent"><CountUp value={n} /></div>
              <p className="mt-2 text-[15px] text-ink-2">{t}</p>
              <div className="hud mt-3 text-[10.5px] text-muted">{src}</div>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  )
}

function Market() {
  return (
    <section className={cx(W, 'py-24')}>
      <Eyebrow>WHO IT'S FOR</Eyebrow>
      <H2>Operations run on cameras. People still do the watching.</H2>
      <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[['Manufacturing', 'A line stalls, staging runs empty, someone skips their PPE.'], ['Logistics', 'A truck backs into a dock, a pallet blocks an exit.'],
          ['Retail & restaurants', 'The checkout line grows, a shelf empties, a table is ready.'], ['Property & facilities', 'A gate is left open, a package arrives, a spot frees up.']].map(([t, d], i) => (
          <Reveal key={t} delay={i * 70} className="h-full rounded-2xl border border-line bg-panel p-6">
            <div className="hud text-[10.5px] text-accent">{t}</div><p className="mt-2 text-[14.5px] text-ink-2">{d}</p>
          </Reveal>
        ))}
      </div>
      <div className="mt-6 grid gap-px overflow-hidden rounded-2xl border border-line bg-line md:grid-cols-3">
        {[['1B+', 'surveillance cameras worldwide by 2021, nearly all only recording', 'IHS Markit via The Verge', 'https://www.theverge.com/2019/12/9/21002515/surveillance-cameras-globally-us-china-amount-citizens'],
          ['$38,020', 'median yearly pay of one U.S. security guard: one person, one shift', 'U.S. BLS, May 2025', 'https://www.bls.gov/ooh/protective-service/security-guards.htm'],
          ['$37.8B', 'video analytics market by 2030, growing 19.5% a year', 'Grand View Research', 'https://www.grandviewresearch.com/press-release/global-video-analytics-market']].map(([n, t, src, href], i) => (
          <Reveal key={n} delay={i * 90} className="h-full bg-panel p-7">
            <div className="num text-[40px] text-accent">{n}</div>
            <p className="mt-2 text-[14.5px] text-ink-2">{t}</p>
            <a href={href} target="_blank" rel="noreferrer" className="hud mt-4 inline-block text-[10.5px] text-muted transition-colors hover:text-ink">SOURCE: {src} ↗</a>
          </Reveal>
        ))}
      </div>
      <Reveal className="mt-4 text-[13px] text-muted">These are industry figures. We have not measured Vigil’s savings or revenue.</Reveal>
    </section>
  )
}

/* ------------------------------------------------------------------------------------------------ learning + next */

function Learning() {
  return (
    <section className="border-y border-line bg-bg-2">
      <div className={cx(W, 'py-24')}>
        <Eyebrow>LEARNING FROM FEEDBACK</Eyebrow>
        <H2>Every YES or NO makes that watch sharper.</H2>
        <div className="mt-12 grid gap-4 md:grid-cols-3">
          {[['START', 'Read the image', 'A pretrained vision model turns the camera image into features it can compare.'],
            ['ADAPT', 'Learn what counts', 'A small classifier, one per watch, learns which moments match your request and which do not.'],
            ['CORRECT', 'Fix a mistake by text', 'Reply YES or NO to an alert and it becomes a labeled example. The base model stays fixed.']].map(([k, t, d], i) => (
            <Reveal key={k} delay={i * 100} className="group relative h-full rounded-2xl border border-line bg-panel p-7">
              <div className="num text-[12px] text-accent">{`0${i + 1} · ${k}`}</div>
              <div className="mt-3 text-[21px] font-semibold">{t}</div>
              <p className="mt-2 text-[14.5px] leading-relaxed text-muted">{d}</p>
              {i < 2 && <ArrowRight className="absolute -right-3 top-1/2 z-10 hidden size-6 -translate-y-1/2 rounded-full border border-line bg-bg-2 p-1 text-accent md:block" />}
            </Reveal>
          ))}
        </div>
        <Reveal className="mt-5 text-[13px] text-muted">Feedback can stop a false alarm from repeating. It can’t fix a person the detector never found, so important alerts still deserve a look at the evidence.</Reveal>
      </div>
    </section>
  )
}

function Next() {
  return (
    <section className={cx(W, 'py-24')}>
      <Eyebrow>WHAT WE’RE WORKING ON NEXT</Eyebrow>
      <H2>Honest about what still needs work.</H2>
      <div className="mt-12 grid gap-px overflow-hidden rounded-2xl border border-line bg-line md:grid-cols-3">
        {[['Easier to run', 'A simpler Windows start-up and clearer error messages.'],
          ['Handles interruptions', 'Reconnects cameras on its own and keeps clips during slow checks.'],
          ['Faster, better counts', 'Find what slows the app down and use labeled footage to improve detection.']].map(([t, d], i) => (
          <Reveal key={t} delay={i * 90} className="h-full bg-panel p-7">
            <div className="num text-[12px] text-accent">0{i + 1}</div>
            <div className="mt-3 text-[19px] font-semibold">{t}</div>
            <p className="mt-2 text-[14.5px] text-muted">{d}</p>
          </Reveal>
        ))}
      </div>
      <Reveal className="mt-4 text-[13px] text-muted">Each change will be tested on the same footage before and after.</Reveal>
    </section>
  )
}

/* ------------------------------------------------------------------------------------------------ FAQ */

const FAQ: [string, string][] = [
  ['Which cameras work?', 'Any IP camera with RTSP (Vigil finds ONVIF cameras on the network for you), stream URLs like HLS or MJPEG, USB webcams, an iPhone through Continuity Camera, any phone or laptop from a browser tab, and recorded video files.'],
  ['Do I have to train anything?', 'No. Vigil matches your sentence to vision models that already understand people, everyday objects and 400 human actions, so a watch is live in seconds. Your YES and NO replies then tune that watch over time.'],
  ['Where does my video go?', 'Vigil runs on your own Mac or PC. In private mode, the default, no image goes to a cloud model; the language model runs on the device too. Faces are blurred in every photo it sends, and old footage is deleted automatically.'],
  ['What will Vigil refuse to do?', 'Identify or follow a person, single anyone out by gender, race, religion, age or looks, watch bodies or private spaces like bathrooms, guess emotions or intent, or monitor anyone covertly. Every request is checked before and after it is understood.'],
  ['How does it reach me?', 'By iMessage through Photon Spectrum, with the photo, or as a HubSpot ticket, a Slack post or a webhook into your own systems. You can also text Vigil back to start, pause or correct a watch.'],
  ['What if the double-check is slow?', 'Vigil won’t hold an alert hostage: if the second check takes too long, the alert goes out marked “unverified” and the verdict is added when it lands. Review the evidence before acting on an important alert.'],
  ['How fast is it?', 'A sentence becomes a live watch in under 20 seconds. Each frame is checked in about 41 ms, an alert needs 3 agreeing checks out of 5, and the double-check takes about 4 seconds before the text goes out.'],
]

function Faq() {
  return (
    <section className={cx(W, 'py-24')}>
      <Eyebrow>QUESTIONS</Eyebrow>
      <H2>The things people ask first.</H2>
      <div className="mt-10 divide-y divide-line overflow-hidden rounded-2xl border border-line">
        {FAQ.map(([q, a], i) => (
          <Reveal key={q} delay={i * 50}>
            <details className="group bg-panel open:bg-panel-2">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-4 px-6 py-5 text-[17px] font-medium transition-colors hover:text-accent">
                {q}<span className="num text-[20px] text-accent transition-transform duration-300 group-open:rotate-45">+</span>
              </summary>
              <p className="max-w-[820px] px-6 pb-6 text-[15px] leading-relaxed text-ink-2">{a}</p>
            </details>
          </Reveal>
        ))}
      </div>
    </section>
  )
}

/* ------------------------------------------------------------------------------------------------ page */

function HowSteps() {
  const [ref, seen] = useInView<HTMLDivElement>()
  const [typed, done] = useTyped('Text me if anyone smokes by the service door', seen, 34)
  return (
    <section id="how" className={cx(W, 'scroll-mt-20 py-24')}>
      <Eyebrow>HOW IT WORKS</Eyebrow>
      <H2>One sentence in. A text when it happens.</H2>
      <div ref={ref} className="mt-12 grid gap-px overflow-hidden rounded-2xl border border-line bg-line md:grid-cols-3">
        <div className="bg-panel p-7">
          <div className="num text-[13px] text-accent">01 · LANGUAGE · SAY IT</div>
          <div className="mt-4 min-h-[76px] rounded-lg border border-line-2 bg-bg px-3.5 py-3 text-[15px]"><span className={done ? '' : 'caret'}>{typed}</span></div>
          <p className="mt-4 text-[14.5px] text-muted">What to watch for, how long it has to last, and who to tell. Plain English.</p>
        </div>
        <div className="bg-panel p-7">
          <div className="num text-[13px] text-accent">02 · VISION · IT PICKS THE MODEL</div>
          <div className="mt-4 grid grid-cols-2 gap-2 text-[12.5px]">
            {[['People & objects', false], ['Any named object', false], ['Yes/no about a scene', false], ['400 human actions', true]].map(([t, on], i) => (
              <div key={t as string} className={cx('rounded-md border px-2.5 py-2 transition-all duration-500', on && done ? 'border-accent bg-accent/10 text-ink' : 'border-line text-muted')}
                style={{ transitionDelay: `${i * 80}ms` }}>{t as string}</div>
            ))}
          </div>
          <p className="mt-4 text-[14.5px] text-muted">Matched to vision models that already understand the scene. Live in seconds, nothing to train.</p>
        </div>
        <div className="bg-panel p-7">
          <div className="num text-[13px] text-accent">03 · ACTION · IT FOLLOWS UP</div>
          <div className={cx('mt-4 rounded-xl border border-white/10 bg-[#1c1c1e] p-3 transition-all duration-700', done ? 'translate-y-0 opacity-100' : 'translate-y-2 opacity-0')} style={{ transitionDelay: '600ms' }}>
            <div className="flex gap-2.5">
              <img src="/landing/smoking_poster.jpg" alt="" className="size-11 shrink-0 rounded-md object-cover" />
              <div className="text-[13px] leading-snug text-white"><b>Vigil</b><br />Someone is smoking at the service entrance.</div>
            </div>
          </div>
          <p className="mt-4 text-[14.5px] text-muted">A second AI double-checks, then the text, ticket or webhook goes out. Every YES or NO makes it sharper.</p>
        </div>
      </div>
    </section>
  )
}

/** What a signed-out visitor sees first. */
export function Landing({ onSignIn }: { onSignIn: () => void }) {
  const { setMe } = useAuth()
  const [busy, setBusy] = useState(false)
  const demo = async () => {
    setBusy(true)
    try {
      setMe((await api.post<{ user: Me }>('/api/auth/login', { email: 'test', password: '123' })).user)
    } finally {
      setBusy(false)
    }
  }
  const primary = 'hud inline-flex min-h-[52px] items-center gap-2 px-6 transition-[filter,transform] duration-150 hover:brightness-110 active:translate-y-px focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:opacity-70'
  const ctas = (
    <>
      <button onClick={demo} disabled={busy} className={cx(primary, 'bg-accent text-accent-ink')}>
        {busy ? 'Opening…' : 'Try the live demo'} <ArrowRight className="size-4" />
      </button>
      <button onClick={onSignIn} className="hud inline-flex min-h-[52px] items-center border border-line-2 bg-bg/40 px-6 text-ink transition-colors hover:border-ink">Sign in</button>
    </>
  )
  return (
    <div className="h-full overflow-y-auto overflow-x-hidden bg-bg text-ink">
      <header className="sticky top-0 z-30 flex items-center gap-6 border-b border-line bg-bg/80 px-4 py-3 backdrop-blur-md md:px-10">
        <a href="#top" className="flex items-center gap-2.5">
          <Logo className="size-8" />
          <span className="text-[18px] font-semibold tracking-[0.3em]">VIGIL</span>
          <BetaPill />
        </a>
        <nav className="hud ml-6 hidden gap-7 text-muted lg:flex">
          {[['#how', 'How'], ['#speed', 'Speed'], ['#cases', 'Use cases'], ['#imessage', 'iMessage'], ['#safe', 'Safety'], ['#results', 'Results']].map(([h, l]) => (
            <a key={h} href={h} className="transition-colors hover:text-ink">{l}</a>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-4">
          <button onClick={onSignIn} className="hud hidden text-muted transition-colors hover:text-ink sm:block">Sign in</button>
          <button onClick={demo} disabled={busy} className="hud bg-accent px-3.5 py-2.5 text-accent-ink transition-[filter] hover:brightness-110">Try the demo</button>
        </div>
      </header>

      <section id="top" className="relative overflow-hidden border-b border-line">
        <video className="absolute inset-0 h-full w-full object-cover opacity-60" src="/landing/yard.mp4" poster="/landing/yard.jpg"
          autoPlay muted loop playsInline aria-label="Real footage of a lumber yard from above; Vigil follows a truck with a lime bracket" />
        <div className="absolute inset-0 bg-gradient-to-r from-bg via-bg/80 to-bg/20" />
        <div className="dot-grid absolute inset-0 opacity-40 [mask-image:linear-gradient(to_right,black,transparent_70%)]" />
        <div className="relative mx-auto grid max-w-[1240px] items-center gap-16 px-4 pb-32 pt-20 md:px-10 md:pt-28 lg:grid-cols-[1.15fr_1fr]">
          <div>
            <Reveal className="hud mb-6 flex items-center gap-2 text-[11.5px] text-accent">
              <span className="size-1.5 rounded-full bg-accent live-dot" /> A VISION AGENT FOR THE CAMERAS YOU ALREADY HAVE
            </Reveal>
            <Reveal delay={80}>
              <h1 className="max-w-[720px] text-[42px] font-semibold leading-[1.02] tracking-tight md:text-[68px]">
                Tell your cameras what to watch for.<br /><span className="text-accent">Vigil does the follow-up.</span>
              </h1>
            </Reveal>
            <Reveal delay={160}>
              <p className="mt-6 max-w-[540px] text-[18px] leading-relaxed text-ink-2">
                Describe it in one sentence. Vigil is watching in seconds, double-checks what it sees, and texts you the photo on
                iMessage. No zones to draw, no rules to tune, no model to train.
              </p>
            </Reveal>
            <Reveal delay={240} className="mt-10 flex flex-wrap gap-3">{ctas}</Reveal>
            <Reveal delay={280} className="mt-4 flex items-center gap-2 text-[13px] text-muted"><ShieldCheck className="size-4 text-accent" />Vigil watches for visible events and refuses requests that target people.</Reveal>
            <Reveal delay={320} className="mt-10 grid max-w-[520px] grid-cols-3 gap-4 border-t border-line pt-6">
              {[['< 20 s', 'sentence to live watch'], ['41 ms', 'per frame checked'], ['0', 'models to train']].map(([n, t]) => (
                <div key={t}><div className="num text-[24px] text-accent">{n}</div><div className="mt-1 text-[12.5px] text-muted">{t}</div></div>
              ))}
            </Reveal>
          </div>
          <Reveal delay={300} className="hidden justify-center lg:flex"><HeroWatch /></Reveal>
        </div>
        <div className="hud absolute bottom-3 right-4 text-[10px] text-white/45 md:right-10">REAL FOOTAGE · THE BRACKET IS VIGIL'S OWN DETECTION</div>
      </section>

      <div className="overflow-hidden border-b border-line bg-panel py-4">
        <div className="marquee flex w-max gap-10 whitespace-nowrap">
          {[...PROMPTS, ...PROMPTS].map((p, i) => (
            <span key={i} className="flex items-center gap-10 text-[15px] text-ink-2">“{p}”<span className="size-1 rounded-full bg-accent/70" /></span>
          ))}
        </div>
      </div>

      <HowSteps />
      <Speed />
      <UseCases />
      <Spotlight />
      <IMessage />
      <FollowUp />
      <Cameras />
      <Guardrails />
      <Learning />
      <Results />
      <Market />
      <Next />
      <Faq />

      <section className="relative overflow-hidden border-t border-line bg-accent text-accent-ink">
        <div className={cx(W, 'flex flex-wrap items-center justify-between gap-6 py-16')}>
          <div>
            <div className="hud text-[11px] opacity-70">NO SIGN-UP NEEDED</div>
            <h2 className="mt-2 text-[32px] font-semibold leading-tight md:text-[44px]">Try it on a real camera, right now.</h2>
          </div>
          <div className="flex flex-wrap gap-3">
            <button onClick={demo} disabled={busy} className={cx(primary, 'bg-[#1e2124] text-accent')}>
              {busy ? 'Opening…' : 'Try the live demo'} <ArrowRight className="size-4" />
            </button>
            <button onClick={onSignIn} className="hud inline-flex min-h-[52px] items-center border border-[#1e2124] px-6 transition-colors hover:bg-[#1e2124]/10">Sign in</button>
          </div>
        </div>
      </section>
      <footer className="flex flex-wrap items-center justify-between gap-3 px-4 py-6 md:px-10">
        <span className="hud flex items-center gap-2 text-[11px] text-muted"><Cpu className="size-3.5" /> VIGIL · HACKLANTA ’26 · BUILT ON PHOTON SPECTRUM</span>
        <span className="hud text-[11px] text-muted">NO FACE RECOGNITION · VIDEO STAYS ON YOUR COMPUTER</span>
      </footer>
    </div>
  )
}

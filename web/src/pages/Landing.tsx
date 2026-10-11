import { ArrowRight, Check, X } from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Logo } from '../components/Layout'
import { cx } from '../components/ui'
import { api } from '../lib/api'
import { useAuth, type Me } from '../lib/auth'
import { BetaPill } from './Welcome'

const reduced = () => typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

/** True once the element has scrolled into view (and stays true). */
function useInView<T extends Element>(margin = '-12% 0px') {
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

function Reveal({ children, className, delay = 0 }: { children: ReactNode; className?: string; delay?: number }) {
  const [ref, seen] = useInView<HTMLDivElement>()
  return <div ref={ref} className={cx('reveal', seen && 'in', className)} style={{ transitionDelay: `${delay}ms` }}>{children}</div>
}

/** Counts a stat like "99.4%" or "19/20" up from zero when it scrolls into view. */
function CountUp({ value }: { value: string }) {
  const [ref, seen] = useInView<HTMLSpanElement>()
  const m = value.match(/^(\d+(?:\.\d+)?)(.*)$/)
  const target = m ? parseFloat(m[1]) : 0
  const decimals = m?.[1].includes('.') ? 1 : 0
  const [n, setN] = useState(0)
  useEffect(() => {
    if (!seen || !m) return
    if (reduced()) return setN(target)
    let raf = 0
    const t0 = performance.now()
    const tick = (t: number) => {
      const k = Math.min(1, (t - t0) / 1400)
      setN(target * (1 - Math.pow(1 - k, 3)))
      if (k < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [seen, target]) // eslint-disable-line react-hooks/exhaustive-deps
  if (!m) return <span ref={ref}>{value}</span>
  return <span ref={ref}>{n.toFixed(decimals)}{m[2]}</span>
}

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
        await wait(3600)
      }
    }
    run()
    return () => { alive = false }
  }, [])
  const chip = (on: boolean, done: boolean, label: string) => (
    <div className={cx('flex items-center gap-2 text-[12.5px] transition-colors duration-300', on ? 'text-ink' : 'text-muted/50')}>
      <span className={cx('flex size-4 items-center justify-center rounded-full border', done ? 'border-accent bg-accent text-accent-ink' : on ? 'border-accent' : 'border-line-2')}>
        {done ? <Check className="size-3" /> : on ? <span className="size-1.5 rounded-full bg-accent live-dot" /> : null}
      </span>
      {label}
    </div>
  )
  return (
    <div className="relative w-full max-w-[400px]">
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
          {chip(step >= 1, step >= 2, 'Understanding the request')}
          {chip(step >= 2, step >= 3, 'Watching with a people & vehicle detector')}
          {chip(step >= 3, step >= 4, 'Truck spotted, double-checked')}
        </div>
      </div>
      {/* the text it sends */}
      <div className={cx('absolute right-[-16px] top-full mt-4 w-[290px] rounded-2xl border border-white/10 bg-[#1c1c1e]/95 p-3 shadow-2xl shadow-black/60 backdrop-blur transition-all duration-500',
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
  'Text me when a car pulls out of a spot so I can send the next van in', 'Tell the lead when someone has no hard hat', 'Text me if anyone smokes by the service door',
  'Count people on the plaza', 'Text me when someone does push-ups', 'Tell receiving when a truck backs into dock 2',
  'Text me when a package is left on the step', 'Text me when someone is on their phone at the register',
]

/** The iMessage thread plays out once it scrolls into view. */
function Thread() {
  const [ref, seen] = useInView<HTMLDivElement>()
  const [shown, setShown] = useState(0)
  const steps = 6
  useEffect(() => {
    if (!seen) return
    if (reduced()) return setShown(steps)
    const ids = [300, 1300, 2100, 3000, 4200, 5100].map((ms, i) => setTimeout(() => setShown(i + 1), ms))
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
  return (
    <div ref={ref} className="mx-auto w-full max-w-[380px] rounded-[40px] border border-line-2 bg-[#0e0f11] p-4 shadow-2xl shadow-black/50">
      <div className="mx-auto mb-3 h-5 w-24 rounded-full bg-black" />
      <div className="mb-3 text-center text-[12px] text-muted">iMessage · Vigil</div>
      <div className="flex min-h-[380px] flex-col gap-2 text-[14.5px]">
        {bubble(1, <div className="ml-auto w-fit max-w-[80%] rounded-2xl rounded-br-md bg-[#0a84ff] px-3.5 py-2 text-white">What's happening on the plaza?</div>)}
        {shown === 1 && typing}
        {bubble(2, <img src="/landing/plaza.jpg" alt="The live photo Vigil texted back: a campus plaza with people walking" className="w-[70%] rounded-2xl" />)}
        {bubble(3, <div className="w-fit max-w-[85%] rounded-2xl rounded-bl-md bg-[#26272b] px-3.5 py-2">Plaza · Entrance, 7:56 PM: I see 3 people, 1 car and 1 truck.</div>)}
        {bubble(4, <div className="ml-auto w-fit max-w-[80%] rounded-2xl rounded-br-md bg-[#0a84ff] px-3.5 py-2 text-white">How many people are on the plaza?</div>)}
        {shown === 4 && typing}
        {bubble(5, <div className="w-fit max-w-[85%] rounded-2xl rounded-bl-md bg-[#26272b] px-3.5 py-2">People on the plaza: 3 people now, 6.2 on average today</div>)}
      </div>
      <div className="hud mt-3 text-center text-[10px] text-muted">REAL REPLIES FROM THE RUNNING APP</div>
    </div>
  )
}

/** A real camera still that "watches" on hover: lime corners and a scan line. */
function CaseCard({ img, title, sub }: { img: string | null; title: string; sub: string }) {
  return (
    <article className="group relative overflow-hidden rounded-xl border border-line bg-panel transition-colors duration-300 hover:border-accent/60">
      <div className="relative overflow-hidden">
        {img ? <img src={img} alt={title} className="aspect-[3/2] w-full object-cover transition-transform duration-700 group-hover:scale-[1.04]" loading="lazy" />
          : <div className="dot-grid flex aspect-[3/2] items-center justify-center bg-panel-2 px-6 text-center text-[22px] font-semibold text-ink-2">“{title}”</div>}
        <span className="pointer-events-none absolute inset-3 opacity-0 transition-opacity duration-300 group-hover:opacity-100 brackets" />
        {img && <span className="sweep hidden group-hover:block" />}
        <span className="hud absolute left-3 top-3 flex items-center gap-1.5 rounded bg-black/60 px-2 py-1 text-[10px] text-accent opacity-0 transition-opacity duration-300 group-hover:opacity-100">
          <span className="size-1.5 rounded-full bg-accent live-dot" /> WATCHING
        </span>
      </div>
      <div className="p-4">
        <div className="text-[16px] font-medium">{img ? `“${title}”` : title}</div>
        <div className="hud mt-1 text-[11px] text-muted">{sub}</div>
      </div>
    </article>
  )
}

/** What a signed-out visitor sees first. Every picture here is real camera footage with Vigil's own output. */
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
  return (
    <div className="h-full overflow-y-auto overflow-x-hidden bg-bg text-ink">
      <header className="sticky top-0 z-30 flex items-center gap-6 border-b border-line bg-bg/80 px-4 py-3 backdrop-blur-md md:px-10">
        <div className="flex items-center gap-2.5">
          <Logo className="size-8" />
          <span className="text-[18px] font-semibold tracking-[0.3em]">VIGIL</span>
          <BetaPill />
        </div>
        <nav className="hud ml-6 hidden gap-7 text-muted lg:flex">
          {[['#how', 'How'], ['#imessage', 'iMessage'], ['#cases', 'Use cases'], ['#results', 'Results'], ['#safe', 'Safety']].map(([h, l]) => (
            <a key={h} href={h} className="transition-colors hover:text-ink">{l}</a>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-4">
          <button onClick={onSignIn} className="hud hidden text-muted transition-colors hover:text-ink sm:block">Sign in</button>
          <button onClick={demo} disabled={busy} className="hud bg-accent px-3.5 py-2.5 text-accent-ink transition-[filter] hover:brightness-110">Try the demo</button>
        </div>
      </header>

      {/* hero: real footage (the bracket in it is Vigil's own detection) with a watch running on top */}
      <section className="relative overflow-hidden border-b border-line">
        <video className="absolute inset-0 h-full w-full object-cover opacity-60" src="/landing/yard.mp4" poster="/landing/yard.jpg"
          autoPlay muted loop playsInline aria-label="Real footage of a lumber yard from above; Vigil follows a truck with a lime bracket" />
        <div className="absolute inset-0 bg-gradient-to-r from-bg via-bg/80 to-bg/20" />
        <div className="dot-grid absolute inset-0 opacity-40 [mask-image:linear-gradient(to_right,black,transparent_70%)]" />
        <div className="relative mx-auto grid max-w-[1240px] items-center gap-16 px-4 pb-28 pt-20 md:px-10 md:pt-28 lg:grid-cols-[1.15fr_1fr]">
          <div>
            <Reveal className="hud mb-6 flex items-center gap-2 text-[11.5px] text-accent">
              <span className="size-1.5 rounded-full bg-accent live-dot" /> LIVE // YARD CAM · REAL FOOTAGE
            </Reveal>
            <Reveal delay={80}>
              <h1 className="max-w-[720px] text-[42px] font-semibold leading-[1.02] tracking-tight md:text-[68px]">
                Tell your cameras what to watch for.<br /><span className="text-accent">Vigil does the follow-up.</span>
              </h1>
            </Reveal>
            <Reveal delay={160}>
              <p className="mt-6 max-w-[540px] text-[18px] leading-relaxed text-ink-2">
                Point any camera at anything, describe what matters in plain English, and get an iMessage the moment it happens.
                No zones to draw, no rules to tune, no model to train.
              </p>
            </Reveal>
            <Reveal delay={240} className="mt-10 flex flex-wrap gap-3">
              <button onClick={demo} disabled={busy} className={cx(primary, 'bg-accent text-accent-ink')}>
                {busy ? 'Opening…' : 'Try the live demo'} <ArrowRight className="size-4" />
              </button>
              <button onClick={onSignIn} className="hud inline-flex min-h-[52px] items-center border border-line-2 bg-bg/40 px-6 text-ink transition-colors hover:border-ink">
                Sign in
              </button>
            </Reveal>
          </div>
          <Reveal delay={300} className="hidden justify-center lg:flex"><HeroWatch /></Reveal>
        </div>
      </section>

      {/* ticker of real requests */}
      <div className="overflow-hidden border-b border-line bg-panel py-4">
        <div className="marquee flex w-max gap-10 whitespace-nowrap">
          {[...PROMPTS, ...PROMPTS].map((p, i) => (
            <span key={i} className="flex items-center gap-10 text-[15px] text-ink-2">
              “{p}”<span className="size-1 rounded-full bg-accent/70" />
            </span>
          ))}
        </div>
      </div>

      {/* how it works */}
      <section id="how" className="mx-auto max-w-[1240px] scroll-mt-20 px-4 py-24 md:px-10">
        <Reveal className="hud text-accent">HOW IT WORKS</Reveal>
        <Reveal delay={60}><h2 className="mt-4 max-w-[720px] text-[36px] font-semibold leading-tight md:text-[46px]">One sentence in. A text when it happens.</h2></Reveal>
        <div className="mt-12 grid gap-px overflow-hidden rounded-xl border border-line bg-line md:grid-cols-3">
          {[
            ['01', 'Say it', 'What to watch for and what to do. “Text me when someone is smoking by the service door.”'],
            ['02', 'It picks the model', 'Vigil matches your sentence to vision models that already know people, everyday objects and 400 human actions. Live in seconds, nothing to train.'],
            ['03', 'It acts', 'A second AI double-checks, then Vigil texts you the photo over iMessage, or files it in HubSpot, Slack or your own API.'],
          ].map(([n, t, d], i) => (
            <Reveal key={n} delay={i * 90} className="group h-full bg-panel p-8 transition-colors duration-300 hover:bg-panel-2">
              <div className="num text-[13px] text-accent">{n}</div>
              <div className="mt-3 text-[25px] font-semibold">{t}</div>
              <p className="mt-2 text-[15px] leading-relaxed text-muted">{d}</p>
              <div className="mt-6 h-px w-10 bg-accent transition-all duration-500 group-hover:w-24" />
            </Reveal>
          ))}
        </div>
      </section>

      {/* iMessage */}
      <section id="imessage" className="relative scroll-mt-20 border-y border-line bg-bg-2">
        <div className="dot-grid absolute inset-0 opacity-30" />
        <div className="relative mx-auto grid max-w-[1240px] items-center gap-14 px-4 py-24 md:grid-cols-2 md:px-10">
          <div>
            <Reveal className="hud text-accent">AGENTS IN IMESSAGE · BUILT ON PHOTON SPECTRUM</Reveal>
            <Reveal delay={60}><h2 className="mt-4 text-[36px] font-semibold leading-tight md:text-[46px]">Vigil lives in iMessage.</h2></Reveal>
            <Reveal delay={120}>
              <p className="mt-4 text-[17px] leading-relaxed text-ink-2">
                Text it like a person. Start a watch, ask what a camera sees, get a live count, pause a watch, or tell it an alert
                was wrong. It texts you first when something happens, with the photo.
              </p>
            </Reveal>
            <ul className="mt-6 flex flex-col gap-3 text-[15px] text-ink-2">
              {['Built on Spectrum, Photon’s open-source SDK: it reads, types, reacts and replies with photos',
                'Nothing to install on the phone; it runs through a Mac signed in to Messages',
                'Reply YES or NO to an alert and that watch learns from it'].map((t, i) => (
                <Reveal key={t} delay={180 + i * 70}><li className="flex gap-2.5"><Check className="mt-0.5 size-4 shrink-0 text-accent" />{t}</li></Reveal>
              ))}
            </ul>
          </div>
          <Thread />
        </div>
      </section>

      {/* who it's for */}
      <section className="mx-auto max-w-[1240px] px-4 py-24 md:px-10">
        <Reveal className="hud text-accent">WHO IT'S FOR</Reveal>
        <Reveal delay={60}><h2 className="mt-4 max-w-[760px] text-[36px] font-semibold leading-tight md:text-[46px]">Operations run on cameras. People still do the watching.</h2></Reveal>
        <Reveal delay={120}>
          <p className="mt-4 max-w-[680px] text-[17px] leading-relaxed text-ink-2">
            Manufacturing, logistics, retail, restaurants, property and facilities. The moments that matter happen on camera,
            but cameras only record, so catching them live takes a person watching a screen.
          </p>
        </Reveal>
        <div className="mt-12 grid gap-px overflow-hidden rounded-xl border border-line bg-line md:grid-cols-3">
          {[
            ['1B+', 'surveillance cameras worldwide by 2021, nearly all only recording', 'IHS Markit via The Verge', 'https://www.theverge.com/2019/12/9/21002515/surveillance-cameras-globally-us-china-amount-citizens'],
            ['$38,020', 'median yearly pay of one U.S. security guard: one person, one shift', 'U.S. BLS, May 2025', 'https://www.bls.gov/ooh/protective-service/security-guards.htm'],
            ['$37.8B', 'video analytics market by 2030, growing 19.5% a year', 'Grand View Research', 'https://www.grandviewresearch.com/press-release/global-video-analytics-market'],
          ].map(([n, t, src, href], i) => (
            <Reveal key={n} delay={i * 90} className="h-full bg-panel p-8">
              <div className="num text-[42px] text-accent">{n}</div>
              <p className="mt-2 text-[15px] text-ink-2">{t}</p>
              <a href={href} target="_blank" rel="noreferrer" className="hud mt-4 inline-block text-[10.5px] text-muted transition-colors hover:text-ink">SOURCE: {src} ↗</a>
            </Reveal>
          ))}
        </div>
      </section>

      {/* use cases: real footage where we have it, plain cards where we don't */}
      <section id="cases" className="scroll-mt-20 border-t border-line">
        <div className="mx-auto max-w-[1240px] px-4 py-24 md:px-10">
          <Reveal className="hud text-accent">USE CASES · REAL CAMERAS</Reveal>
          <Reveal delay={60}><h2 className="mt-4 text-[36px] font-semibold leading-tight md:text-[46px]">What do you check by hand?</h2></Reveal>
          <div className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {([
              ['/landing/parking.jpg', 'Text me when a car pulls out of these spots, so I can send the next van in', 'parking lot camera'],
              ['/landing/smoking.jpg', 'Text me if anyone smokes by the service door', 'faces blurred by Vigil'],
              ['/landing/hardhat.jpg', 'Tell the lead when someone has no hard hat', 'pump station CCTV'],
              ['/landing/plaza.jpg', 'How many people are on the plaza?', 'campus camera'],
              [null, 'Package on the step', '→ text me'],
              [null, 'Truck backs into dock 2', '→ tell receiving'],
            ] as [string | null, string, string][]).map(([img, title, sub], i) => (
              <Reveal key={title} delay={(i % 3) * 90}><CaseCard img={img} title={title} sub={sub} /></Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* measured results */}
      <section id="results" className="scroll-mt-20 border-y border-line bg-bg-2">
        <div className="mx-auto max-w-[1240px] px-4 py-24 md:px-10">
          <Reveal className="hud text-accent">MEASURED ON REAL PUBLIC DATA</Reveal>
          <Reveal delay={60}><h2 className="mt-4 text-[36px] font-semibold leading-tight md:text-[46px]">Numbers we measured, not promised.</h2></Reveal>
          <div className="mt-12 grid gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-2 lg:grid-cols-4">
            {[
              ['99.4%', 'parking spaces read correctly on days the model never saw', 'PKLot'],
              ['99%', 'of people found, with 2% false alarms', 'COCO val2017'],
              ['19/20', 'push-up clips caught, 0 of 320 false alarms', 'HMDB51 video'],
              ['86%', 'exact people counts, 98% within one', 'COCO, 1–5 people'],
            ].map(([n, t, src], i) => (
              <Reveal key={n} delay={i * 90} className="h-full bg-panel p-8">
                <div className="num text-[44px] text-accent"><CountUp value={n} /></div>
                <p className="mt-2 text-[15px] text-ink-2">{t}</p>
                <div className="hud mt-3 text-[10.5px] text-muted">{src}</div>
              </Reveal>
            ))}
          </div>
          <Reveal delay={120} className="relative mt-8 overflow-hidden rounded-xl border border-line">
            <img src="/landing/lot.jpg" alt="Real aerial parking lot footage: Vigil watching 161 spaces and texting when one opens" className="w-full" loading="lazy" />
            <span className="sweep" />
          </Reveal>
        </div>
      </section>

      {/* safety */}
      <section id="safe" className="mx-auto max-w-[1240px] scroll-mt-20 px-4 py-24 md:px-10">
        <Reveal className="hud text-accent">SAFE BY DESIGN</Reveal>
        <Reveal delay={60}><h2 className="mt-4 text-[36px] font-semibold leading-tight md:text-[46px]">Watches events, not people. Footage stays yours.</h2></Reveal>
        <div className="mt-12 grid gap-4 md:grid-cols-2">
          <Reveal className="h-full rounded-xl border border-line bg-panel p-8">
            <div className="hud text-[11px] text-muted">VIGIL REFUSES TO</div>
            <ul className="mt-4 flex flex-col gap-3 text-[15px] text-ink-2">
              {['Identify, recognize or follow a person', 'Single anyone out by gender, race, religion, age or looks',
                'Watch bodies, bathrooms, changing rooms or other homes', 'Guess emotions or intent, or monitor anyone covertly'].map((t) => (
                <li key={t} className="flex gap-2.5"><X className="mt-0.5 size-4 shrink-0 text-alert" />{t}</li>
              ))}
            </ul>
          </Reveal>
          <Reveal delay={90} className="h-full rounded-xl border border-line bg-panel p-8">
            <div className="hud text-[11px] text-muted">YOUR FOOTAGE STAYS YOURS</div>
            <ul className="mt-4 flex flex-col gap-3 text-[15px] text-ink-2">
              {['Runs on your own computer; in private mode (the default) no image goes to a cloud model',
                'Faces blurred in every photo and clip it sends', 'Old footage deleted automatically: 7 days, alerts 30',
                'Camera passwords stay on your machine'].map((t) => (
                <li key={t} className="flex gap-2.5"><Check className="mt-0.5 size-4 shrink-0 text-accent" />{t}</li>
              ))}
            </ul>
          </Reveal>
        </div>
      </section>

      <section className="relative overflow-hidden border-t border-line bg-accent text-accent-ink">
        <div className="relative mx-auto flex max-w-[1240px] flex-wrap items-center justify-between gap-6 px-4 py-16 md:px-10">
          <div>
            <div className="hud text-[11px] opacity-70">NO SIGN-UP NEEDED</div>
            <h2 className="mt-2 text-[32px] font-semibold leading-tight md:text-[42px]">Try it on a real camera, right now.</h2>
          </div>
          <div className="flex flex-wrap gap-3">
            <button onClick={demo} disabled={busy} className={cx(primary, 'bg-[#1e2124] text-accent')}>
              {busy ? 'Opening…' : 'Try the live demo'} <ArrowRight className="size-4" />
            </button>
            <button onClick={onSignIn} className="hud inline-flex min-h-[52px] items-center border border-[#1e2124] px-6 transition-colors hover:bg-[#1e2124]/10">Sign in</button>
          </div>
        </div>
      </section>
      <footer className="hud flex flex-wrap items-center justify-between gap-3 px-4 py-6 text-[11px] text-muted md:px-10">
        <span>VIGIL · HACKLANTA ’26</span>
        <span>NO FACE RECOGNITION · VIDEO STAYS ON YOUR COMPUTER</span>
      </footer>
    </div>
  )
}

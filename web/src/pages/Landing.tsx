import { ArrowRight, Check, X } from 'lucide-react'
import { useState } from 'react'
import { Logo } from '../components/Layout'
import { api } from '../lib/api'
import { useAuth, type Me } from '../lib/auth'
import { BetaPill } from './Welcome'

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
  const cta = (
    <div className="flex flex-wrap gap-3">
      <button onClick={demo} disabled={busy}
        className="hud inline-flex min-h-[52px] items-center gap-2 bg-accent px-6 text-accent-ink hover:brightness-105 disabled:opacity-70">
        {busy ? 'Opening…' : 'Try the live demo'} <ArrowRight className="size-4" />
      </button>
      <button onClick={onSignIn} className="hud inline-flex min-h-[52px] items-center border border-line-2 px-6 text-ink hover:border-ink">
        Sign in
      </button>
    </div>
  )
  return (
    <div className="h-full overflow-y-auto bg-bg text-ink">
      <header className="sticky top-0 z-20 flex items-center gap-6 border-b border-line bg-bg/90 px-4 py-3 backdrop-blur md:px-10">
        <div className="flex items-center gap-2.5">
          <Logo className="size-8" />
          <span className="text-[18px] font-semibold tracking-[0.3em]">VIGIL</span>
          <BetaPill />
        </div>
        <nav className="hud ml-6 hidden gap-7 text-muted lg:flex">
          <a href="#how" className="hover:text-ink">How</a>
          <a href="#imessage" className="hover:text-ink">iMessage</a>
          <a href="#cases" className="hover:text-ink">Use cases</a>
          <a href="#results" className="hover:text-ink">Results</a>
          <a href="#safe" className="hover:text-ink">Safety</a>
        </nav>
        <div className="ml-auto flex items-center gap-4">
          <button onClick={onSignIn} className="hud hidden text-muted hover:text-ink sm:block">Sign in</button>
          <button onClick={demo} disabled={busy} className="hud bg-accent px-3.5 py-2.5 text-accent-ink">Try the demo</button>
        </div>
      </header>

      {/* hero: real footage, the bracket is Vigil's own detection */}
      <section className="relative overflow-hidden border-b border-line">
        <video className="absolute inset-0 h-full w-full object-cover opacity-55" src="/landing/yard.mp4" poster="/landing/yard.jpg"
          autoPlay muted loop playsInline aria-label="Real footage of a lumber yard from above; Vigil follows a truck with a lime bracket" />
        <div className="absolute inset-0 bg-gradient-to-r from-bg via-bg/75 to-bg/10" />
        <div className="relative mx-auto max-w-[1200px] px-4 py-24 md:px-10 md:py-36">
          <div className="hud mb-6 flex items-center gap-2 text-accent"><span className="size-1.5 rounded-full bg-accent live-dot" /> LIVE // YARD CAM · REAL FOOTAGE, THE BRACKET IS VIGIL'S</div>
          <h1 className="max-w-[760px] text-[40px] font-semibold leading-[1.05] tracking-tight md:text-[64px]">
            Tell your cameras what to watch for. <span className="text-accent">Vigil does the follow-up.</span>
          </h1>
          <p className="mt-6 max-w-[560px] text-[18px] leading-relaxed text-ink-2">
            Point any camera at anything, describe what matters in plain English, and get an iMessage the moment it happens.
            No zones to draw, no rules to tune, no model to train.
          </p>
          <div className="mt-10">{cta}</div>
        </div>
      </section>

      {/* how it works */}
      <section id="how" className="mx-auto max-w-[1200px] scroll-mt-20 px-4 py-20 md:px-10">
        <div className="grid gap-px overflow-hidden rounded-xl border border-line bg-line md:grid-cols-3">
          {[
            ['01', 'Say it', 'One sentence: what to watch for and what to do. “Text me when someone is smoking by the service door.”'],
            ['02', 'It picks the model', 'Vigil matches your sentence to vision models that already know people, everyday objects and 400 human actions. Live in seconds, nothing to train.'],
            ['03', 'It acts', 'A second AI double-checks, then Vigil texts you the photo over iMessage, or files it in HubSpot, Slack or your own API.'],
          ].map(([n, t, d]) => (
            <div key={n} className="bg-panel p-7">
              <div className="num text-[13px] text-accent">{n}</div>
              <div className="mt-3 text-[24px] font-semibold">{t}</div>
              <p className="mt-2 text-[15px] leading-relaxed text-muted">{d}</p>
            </div>
          ))}
        </div>
      </section>

      {/* iMessage */}
      <section id="imessage" className="scroll-mt-20 border-y border-line bg-bg-2">
        <div className="mx-auto grid max-w-[1200px] items-center gap-12 px-4 py-20 md:grid-cols-2 md:px-10">
          <div>
            <div className="hud text-accent">AGENTS IN IMESSAGE · BUILT ON PHOTON SPECTRUM</div>
            <h2 className="mt-4 text-[36px] font-semibold leading-tight md:text-[44px]">Vigil lives in iMessage.</h2>
            <p className="mt-4 text-[17px] leading-relaxed text-ink-2">
              Text it like a person. Start a watch, ask what a camera sees, get a live count, pause a watch, or tell it an alert
              was wrong. It texts you first when something happens, with the photo.
            </p>
            <ul className="mt-6 flex flex-col gap-3 text-[15px] text-ink-2">
              {['Built on Spectrum, Photon’s open-source SDK: it reads, types, reacts and replies with photos',
                'Nothing to install on the phone; it runs through a Mac signed in to Messages',
                'Reply YES or NO to an alert and that watch learns from it'].map((t) => (
                <li key={t} className="flex gap-2.5"><Check className="mt-0.5 size-4 shrink-0 text-accent" />{t}</li>
              ))}
            </ul>
          </div>
          <div className="mx-auto w-full max-w-[380px] rounded-[36px] border border-line-2 bg-[#111214] p-4 shadow-2xl">
            <div className="mb-3 text-center text-[12px] text-muted">iMessage · Vigil</div>
            <div className="flex flex-col gap-2 text-[14.5px]">
              <div className="ml-auto max-w-[80%] rounded-2xl rounded-br-md bg-[#0a84ff] px-3.5 py-2 text-white">What's happening on the plaza?</div>
              <img src="/landing/plaza.jpg" alt="The live photo Vigil texted back: a campus plaza with people walking" className="w-[70%] rounded-2xl" />
              <div className="max-w-[85%] rounded-2xl rounded-bl-md bg-[#26272b] px-3.5 py-2">Plaza · Entrance, 7:56 PM: I see 3 people, 1 car and 1 truck.</div>
              <div className="ml-auto max-w-[80%] rounded-2xl rounded-br-md bg-[#0a84ff] px-3.5 py-2 text-white">How many people are on the plaza?</div>
              <div className="max-w-[85%] rounded-2xl rounded-bl-md bg-[#26272b] px-3.5 py-2">People on the plaza: 3 people now, 6.2 on average today</div>
            </div>
            <div className="hud mt-4 text-center text-[10px] text-muted">REAL REPLIES FROM THE RUNNING APP</div>
          </div>
        </div>
      </section>

      {/* who it's for */}
      <section className="mx-auto max-w-[1200px] px-4 py-20 md:px-10">
        <div className="hud text-accent">WHO IT'S FOR</div>
        <h2 className="mt-4 max-w-[760px] text-[36px] font-semibold leading-tight md:text-[44px]">Operations run on cameras. People still do the watching.</h2>
        <p className="mt-4 max-w-[680px] text-[17px] leading-relaxed text-ink-2">
          Manufacturing, logistics, retail, restaurants, property and facilities. The moments that matter happen on camera,
          but cameras only record, so catching them live takes a person watching a screen.
        </p>
        <div className="mt-10 grid gap-px overflow-hidden rounded-xl border border-line bg-line md:grid-cols-3">
          {[
            ['1B+', 'surveillance cameras worldwide by 2021, nearly all only recording', 'IHS Markit via The Verge', 'https://www.theverge.com/2019/12/9/21002515/surveillance-cameras-globally-us-china-amount-citizens'],
            ['$38,020', 'median yearly pay of one U.S. security guard: one person, one shift', 'U.S. BLS, May 2025', 'https://www.bls.gov/ooh/protective-service/security-guards.htm'],
            ['$37.8B', 'video analytics market by 2030, growing 19.5% a year', 'Grand View Research', 'https://www.grandviewresearch.com/press-release/global-video-analytics-market'],
          ].map(([n, t, src, href]) => (
            <div key={n} className="bg-panel p-7">
              <div className="num text-[40px] text-accent">{n}</div>
              <p className="mt-2 text-[15px] text-ink-2">{t}</p>
              <a href={href} target="_blank" rel="noreferrer" className="hud mt-4 inline-block text-[10.5px] text-muted hover:text-ink">SOURCE: {src}</a>
            </div>
          ))}
        </div>
      </section>

      {/* use cases: real footage where we have it, plain cards where we don't */}
      <section id="cases" className="scroll-mt-20 border-t border-line">
        <div className="mx-auto max-w-[1200px] px-4 py-20 md:px-10">
          <h2 className="text-[36px] font-semibold leading-tight md:text-[44px]">What do you check by hand?</h2>
          <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {[
              ['/landing/parking.jpg', 'Text me when a spot opens up', 'parking lot camera'],
              ['/landing/smoking.jpg', 'Text me if anyone smokes by the service door', 'faces blurred by Vigil'],
              ['/landing/hardhat.jpg', 'Tell the lead when someone has no hard hat', 'pump station CCTV'],
              ['/landing/plaza.jpg', 'How many people are on the plaza?', 'campus camera'],
              [null, 'Package on the step', '→ text me'],
              [null, 'Truck backs into dock 2', '→ tell receiving'],
            ].map(([img, title, sub]) => (
              <article key={title} className="overflow-hidden rounded-xl border border-line bg-panel">
                {img ? <img src={img} alt={title ?? ''} className="aspect-[3/2] w-full object-cover" loading="lazy" />
                  : <div className="flex aspect-[3/2] items-center justify-center bg-panel-2 px-6 text-center text-[22px] font-semibold text-ink-2">“{title}”</div>}
                <div className="p-4">
                  <div className="text-[16px] font-medium">{img ? `“${title}”` : title}</div>
                  <div className="hud mt-1 text-[11px] text-muted">{sub}</div>
                </div>
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* measured results */}
      <section id="results" className="scroll-mt-20 border-y border-line bg-bg-2">
        <div className="mx-auto max-w-[1200px] px-4 py-20 md:px-10">
          <div className="hud text-accent">MEASURED ON REAL PUBLIC DATA</div>
          <h2 className="mt-4 text-[36px] font-semibold leading-tight md:text-[44px]">Every answer makes it sharper.</h2>
          <div className="mt-10 grid gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-2 lg:grid-cols-4">
            {[
              ['99.4%', 'parking spaces read correctly on days the model never saw', 'PKLot'],
              ['99%', 'of people found, with 2% false alarms', 'COCO val2017'],
              ['19/20', 'push-up clips caught, 0 of 320 false alarms', 'HMDB51 video'],
              ['86%', 'exact people counts, 98% within one', 'COCO, 1–5 people'],
            ].map(([n, t, src]) => (
              <div key={n} className="bg-panel p-7">
                <div className="num text-[40px] text-accent">{n}</div>
                <p className="mt-2 text-[15px] text-ink-2">{t}</p>
                <div className="hud mt-3 text-[10.5px] text-muted">{src}</div>
              </div>
            ))}
          </div>
          <img src="/landing/lot.jpg" alt="Real aerial parking lot footage: Vigil watching 161 spaces and texting when one opens" className="mt-8 w-full rounded-xl border border-line" loading="lazy" />
        </div>
      </section>

      {/* safety */}
      <section id="safe" className="mx-auto max-w-[1200px] scroll-mt-20 px-4 py-20 md:px-10">
        <div className="hud text-accent">SAFE BY DESIGN</div>
        <h2 className="mt-4 text-[36px] font-semibold leading-tight md:text-[44px]">Watches events, not people. Footage stays yours.</h2>
        <div className="mt-10 grid gap-4 md:grid-cols-2">
          <div className="rounded-xl border border-line bg-panel p-7">
            <div className="hud text-[11px] text-muted">VIGIL REFUSES TO</div>
            <ul className="mt-4 flex flex-col gap-3 text-[15px] text-ink-2">
              {['Identify, recognize or follow a person', 'Single anyone out by gender, race, religion, age or looks',
                'Watch bodies, bathrooms, changing rooms or other homes', 'Guess emotions or intent, or monitor anyone covertly'].map((t) => (
                <li key={t} className="flex gap-2.5"><X className="mt-0.5 size-4 shrink-0 text-alert" />{t}</li>
              ))}
            </ul>
          </div>
          <div className="rounded-xl border border-line bg-panel p-7">
            <div className="hud text-[11px] text-muted">YOUR FOOTAGE STAYS YOURS</div>
            <ul className="mt-4 flex flex-col gap-3 text-[15px] text-ink-2">
              {['Runs on your own computer; in private mode (the default) no image goes to a cloud model',
                'Faces blurred in every photo and clip it sends', 'Old footage deleted automatically: 7 days, alerts 30',
                'Camera passwords stay on your machine'].map((t) => (
                <li key={t} className="flex gap-2.5"><Check className="mt-0.5 size-4 shrink-0 text-accent" />{t}</li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      <section className="border-t border-line bg-accent text-accent-ink">
        <div className="mx-auto flex max-w-[1200px] flex-wrap items-center justify-between gap-6 px-4 py-14 md:px-10">
          <h2 className="text-[30px] font-semibold leading-tight md:text-[38px]">Try it on a real camera, right now.</h2>
          <div className="flex flex-wrap gap-3">
            <button onClick={demo} disabled={busy} className="hud inline-flex min-h-[52px] items-center gap-2 bg-[#1e2124] px-6 text-accent">
              {busy ? 'Opening…' : 'Try the live demo'} <ArrowRight className="size-4" />
            </button>
            <button onClick={onSignIn} className="hud inline-flex min-h-[52px] items-center border border-[#1e2124] px-6">Sign in</button>
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

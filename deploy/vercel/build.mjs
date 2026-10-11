// Builds the Vercel front door for Vigil: a page with a QR code that turns a phone into a Vigil camera, and
// redirects to wherever Vigil itself is running (the Mac, through a tunnel).
//
//   SITE=https://vigil-camera.vercel.app TARGET=https://xxxx.trycloudflare.com PHONE_PATH=/push/24?k=... node build.mjs
//
// Vercel can't run Vigil's models, so this site only points at the running app; re-run with the new TARGET
// whenever the tunnel address changes, then `vercel deploy --prod`.
import { writeFileSync, mkdirSync, copyFileSync } from 'node:fs'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const QRCode = require('../../web/node_modules/qrcode')

const SITE = (process.env.SITE || '').replace(/\/$/, '')
const TARGET = (process.env.TARGET || '').replace(/\/$/, '')
const PHONE_PATH = process.env.PHONE_PATH || ''
if (!SITE || !TARGET || !PHONE_PATH) throw new Error('set SITE, TARGET and PHONE_PATH')

mkdirSync('public', { recursive: true })
copyFileSync('vigil-mark.svg', 'public/vigil-mark.svg')

writeFileSync('vercel.json', JSON.stringify({
  outputDirectory: 'public',
  redirects: [
    { source: '/phone', destination: TARGET + PHONE_PATH, permanent: false },
    { source: '/app', destination: TARGET + '/', permanent: false },
    { source: '/app/:path*', destination: TARGET + '/:path*', permanent: false },
  ],
  headers: [{ source: '/(.*)', headers: [{ key: 'Cache-Control', value: 'no-store' }] }],
}, null, 2))

const qr = await QRCode.toString(SITE + '/phone', { type: 'svg', margin: 1, color: { dark: '#1e2124', light: '#ffffff' } })

writeFileSync('public/index.html', `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vigil</title>
<meta name="description" content="Point any camera at anything, type what to watch for, and Vigil texts you on iMessage the moment it happens.">
<link rel="icon" href="/vigil-mark.svg">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Chakra+Petch:wght@400;500;600&family=JetBrains+Mono:wght@500&display=swap" rel="stylesheet">
<style>
  :root { --bg:#2a2d30; --panel:#25282b; --line:#3a3e42; --ink:#f2f2f0; --muted:#a3a9ae; --accent:#c8f560; --accent-ink:#1e2124; }
  * { box-sizing: border-box; margin: 0 }
  body { background: var(--bg); color: var(--ink); font-family: 'Chakra Petch', -apple-system, sans-serif; min-height: 100vh;
         display: flex; align-items: center; justify-content: center; padding: 32px 16px }
  main { width: 100%; max-width: 880px; display: grid; grid-template-columns: 1fr auto; gap: 48px; align-items: center }
  .brand { display: flex; align-items: center; gap: 12px; font-weight: 600; font-size: 20px; letter-spacing: .3em }
  .brand img { width: 36px; height: 36px }
  .pill { font: 500 11px 'JetBrains Mono', monospace; letter-spacing: .14em; color: var(--accent); border: 1px solid var(--accent);
          border-radius: 999px; padding: 3px 9px }
  h1 { font-size: clamp(30px, 5vw, 44px); line-height: 1.08; letter-spacing: -.01em; margin: 28px 0 14px; font-weight: 600 }
  p.lead { color: var(--muted); font-size: 16px; line-height: 1.55; max-width: 460px }
  ol { margin: 26px 0 0; padding-left: 20px; color: var(--muted); line-height: 1.9; font-size: 15px }
  ol b { color: var(--ink); font-weight: 500 }
  .buttons { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 28px }
  a.btn { font: 500 13px 'JetBrains Mono', monospace; letter-spacing: .12em; text-transform: uppercase; text-decoration: none;
          padding: 13px 18px; border: 1px solid var(--accent); color: var(--accent) }
  a.btn.primary { background: var(--accent); color: var(--accent-ink) }
  .qr { background: #fff; padding: 14px; border-radius: 16px; width: 300px }
  .qr svg { display: block; width: 100%; height: auto }
  .qr-cap { text-align: center; color: var(--muted); font: 500 12px 'JetBrains Mono', monospace; letter-spacing: .12em; margin-top: 12px }
  .phone-only { display: none }
  @media (max-width: 760px) {
    main { grid-template-columns: 1fr; gap: 0 }
    .qr-wrap { display: none }
    .phone-only { display: inline-block }
    .desk-only { display: none }
  }
</style>
</head>
<body>
<main>
  <section>
    <div class="brand"><img src="/vigil-mark.svg" alt=""> VIGIL <span class="pill">BETA</span></div>
    <h1>Turn your phone into a Vigil camera.</h1>
    <p class="lead">Point it at anything, tell Vigil what to watch for in plain English, and get an iMessage the moment it happens.</p>
    <ol>
      <li class="desk-only"><b>Scan the code</b> with your iPhone camera.</li>
      <li class="phone-only"><b>Tap “Use this phone”</b> below.</li>
      <li><b>Start streaming</b> and allow the camera.</li>
      <li><b>Open Vigil</b> and type what to watch for on the “iPhone” camera.</li>
    </ol>
    <div class="buttons">
      <a class="btn primary phone-only" href="/phone">Use this phone</a>
      <a class="btn primary desk-only" href="/app">Open Vigil</a>
      <a class="btn phone-only" href="/app">Open Vigil</a>
    </div>
  </section>
  <aside class="qr-wrap">
    <div class="qr">${qr}</div>
    <div class="qr-cap">SCAN WITH YOUR PHONE</div>
  </aside>
</main>
</body>
</html>
`)
console.log('built for', SITE, '->', TARGET)

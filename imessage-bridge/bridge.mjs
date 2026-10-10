// Vigil <-> iMessage, built on Photon's Spectrum SDK (https://github.com/photon-hq/spectrum-ts)
// with the local iMessage provider (@spectrum-ts/imessage-local).
//
//   POST /send    {to, text, attachments?}   Vigil calls this when a watch fires
//   GET  /health                             Vigil's Settings page shows this
//   replies       every direct message is forwarded to Vigil at POST {VIGIL_URL}/api/imessage/inbound
//                 ("yes" / "no" to an alert becomes a training label for that watch)
//
// Needs macOS, Messages signed in, and Full Disk Access for the terminal that runs it (to read chat.db).
// DRY_RUN=1 logs instead of sending and skips the listener, so it runs anywhere.
import http from 'node:http'

const PORT = Number(process.env.PORT || 8790)
const VIGIL_URL = (process.env.VIGIL_URL || 'http://127.0.0.1:8765').replace(/\/$/, '')
const DRY_RUN = !!process.env.DRY_RUN
const ALLOW = (process.env.ALLOW_FROM || '').split(',').map((s) => s.trim()).filter(Boolean)

let app = null
let imessage = null
let spectrum = null
let listening = false
let lastError = ''
const sent = []

if (!DRY_RUN) {
  spectrum = await import('@spectrum-ts/core')
  const { localIMessage } = await import('@spectrum-ts/imessage-local')
  try {
    app = await spectrum.Spectrum({ providers: [localIMessage.config()] })
    imessage = localIMessage(app)
    listening = true
    listen().catch((e) => {
      listening = false
      lastError = `listener stopped: ${e.message}`
      console.error(lastError)
    })
  } catch (e) {
    lastError = `Spectrum could not start (grant Full Disk Access to this terminal): ${e.message}`
    console.error(lastError)
  }
}

async function listen() {
  for await (const [, message] of app.messages) {
    if (message.direction !== 'inbound' || message.content?.type !== 'text') continue
    const from = message.sender?.id
    if (!from || (ALLOW.length && !ALLOW.some((a) => from.includes(a)))) continue
    try {
      const r = await fetch(`${VIGIL_URL}/api/imessage/inbound`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ from, text: message.content.text }),
      })
      const out = await r.json().catch(() => ({}))
      console.log(`reply from ${from}: "${message.content.text}" ->`, out.ok ? out.feedback : out.reason)
    } catch (e) {
      lastError = `could not reach Vigil: ${e.message}`
      console.error(lastError)
    }
  }
}

function json(res, code, body) {
  res.writeHead(code, { 'content-type': 'application/json' })
  res.end(JSON.stringify(body))
}

const server = http.createServer(async (req, res) => {
  if (req.method === 'GET' && req.url === '/health') {
    return json(res, 200, { ok: true, sdk: 'spectrum-ts', dry_run: DRY_RUN, watching: listening, sent: sent.length, last_error: lastError })
  }
  if (req.method === 'POST' && req.url === '/send') {
    let raw = ''
    for await (const chunk of req) raw += chunk
    let body
    try {
      body = JSON.parse(raw || '{}')
    } catch {
      return json(res, 400, { ok: false, error: 'bad JSON' })
    }
    const { to, text, attachments = [] } = body
    if (!to || (!text && !attachments.length)) return json(res, 400, { ok: false, error: 'to and text are required' })
    sent.push({ to, at: Date.now() })
    if (DRY_RUN) {
      console.log(`[dry run] to ${to}: ${text}${attachments.length ? ` (+${attachments.length} image)` : ''}`)
      return json(res, 200, { ok: true, dry_run: true })
    }
    if (!imessage) return json(res, 503, { ok: false, error: lastError || 'Spectrum not started' })
    try {
      const space = await imessage.space.create(to)
      const parts = [...(text ? [spectrum.text(text)] : []), ...attachments.map((p) => spectrum.attachment(p))]
      await space.send(...parts)
      return json(res, 200, { ok: true })
    } catch (e) {
      lastError = String(e?.message || e)
      return json(res, 502, { ok: false, error: lastError })
    }
  }
  json(res, 404, { ok: false, error: 'not found' })
})

server.listen(PORT, '127.0.0.1', () =>
  console.log(`Vigil iMessage bridge (Photon Spectrum) on http://127.0.0.1:${PORT}${DRY_RUN ? ' (dry run)' : ''}, replies -> ${VIGIL_URL}`),
)

for (const sig of ['SIGINT', 'SIGTERM']) {
  process.on(sig, async () => {
    server.close()
    if (app) await app.stop().catch(() => {})
    process.exit(0)
  })
}

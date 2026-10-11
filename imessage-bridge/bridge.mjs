// Vigil <-> iMessage, built on Photon's Spectrum SDK (https://github.com/photon-hq/spectrum-ts)
// with the local iMessage provider (@spectrum-ts/imessage-local).
//
//   POST /send    {to, text, attachments?}   Vigil calls this when a watch fires
//   GET  /health                             Vigil's Settings page shows this, as a checklist
//   agent         every text from the owner goes to Vigil (POST {VIGIL_URL}/api/imessage/inbound), which answers
//                 as an agent: build a watch, send a live photo, report a count, pause, learn from YES/NO.
//                 The answer goes back in the same conversation with Spectrum (read receipt, typing, tapback,
//                 text and photo).
//
// Needs macOS with Messages signed in. Two permissions, asked for once:
//   - Automation -> Messages: lets Vigil SEND texts (macOS asks the first time a text goes out)
//   - Full Disk Access: lets Vigil READ replies (Messages keeps them in ~/Library/Messages/chat.db)
// Without Full Disk Access Spectrum cannot start, so sending falls back to Messages' own AppleScript; texts
// still go out, replies just are not read until access is granted (the bridge retries every 30 s).
// DRY_RUN=1 logs instead of sending, for machines without Messages.
import { execFile } from 'node:child_process'
import { copyFileSync, existsSync, mkdirSync } from 'node:fs'
import http from 'node:http'
import { homedir } from 'node:os'
import { basename, join } from 'node:path'

const PORT = Number(process.env.PORT || 8790)
const VIGIL_URL = (process.env.VIGIL_URL || 'http://127.0.0.1:8765').replace(/\/$/, '')
const DRY_RUN = !!process.env.DRY_RUN
const ALLOW = (process.env.ALLOW_FROM || '').split(',').map((s) => s.trim()).filter(Boolean)
const MESSAGES_DB = join(homedir(), 'Library', 'Messages', 'chat.db')
// the app macOS will ask about (permissions belong to the app that started Vigil, not to node)
const HOST_APP = { 'com.apple.Terminal': 'Terminal', 'com.googlecode.iterm2': 'iTerm', 'com.microsoft.VSCode': 'Visual Studio Code',
  'com.anthropic.claudefordesktop': 'Claude' }[process.env.__CFBundleIdentifier] || process.env.TERM_PROGRAM || 'the app that runs Vigil'

let app = null
let imessage = null
let spectrum = null
let listening = false
let lastError = ''
let lastSendError = ''
let sentOk = 0
let repliedOk = 0
const sent = []

async function startSpectrum() {
  if (DRY_RUN || imessage) return
  try {
    spectrum ??= await import('@spectrum-ts/core')
    const { localIMessage } = await import('@spectrum-ts/imessage-local')
    app = await spectrum.Spectrum({ providers: [localIMessage.config()] })
    imessage = localIMessage(app)
    listening = true
    lastError = ''
    console.log('Spectrum started: sending and reading replies')
    listen().catch((e) => {
      listening = false
      imessage = null
      lastError = `listener stopped: ${e.message}`
      console.error(lastError)
    })
  } catch (e) {
    imessage = null
    lastError = /unable to open database|authorization denied|not permitted/i.test(e.message)
      ? 'needs_full_disk_access'
      : `Spectrum could not start: ${e.message}`
  }
}

async function listen() {
  for await (const [space, message] of app.messages) {
    if (message.direction !== 'inbound' || message.content?.type !== 'text') continue
    const from = message.sender?.id
    if (!from || (ALLOW.length && !ALLOW.some((a) => from.includes(a)))) continue
    handle(space, message, from).catch((e) => {
      lastError = `could not answer ${from}: ${e.message}`
      console.error(lastError)
    })
  }
}

// Vigil is the agent: it decides what to say and do; Spectrum carries the conversation.
async function handle(space, message, from) {
  const text = message.content.text
  const best = (p) => p?.catch?.(() => {})  // read receipts / typing are best-effort per platform
  best(message.read())
  best(space.startTyping())
  let out = {}
  try {
    const r = await fetch(`${VIGIL_URL}/api/imessage/inbound`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ from, text }),
    })
    out = await r.json().catch(() => ({}))
  } finally {
    best(space.stopTyping())
  }
  console.log(`${from}: "${text}" -> ${out.intent || out.reason || 'no answer'}`)
  if (!out.ok || !out.reply) return  // not an owner: stay silent
  if (out.react) best(message.react(out.react))
  const parts = [spectrum.text(out.reply), ...(out.attachments || []).filter((p) => existsSync(p)).map((p) => spectrum.attachment(p))]
  await space.send(...(parts.length > 1 ? parts : [parts[0]]))
  repliedOk += 1
}

// Messages' own scripting interface: works without Full Disk Access (macOS asks for Automation once).
const SEND_SCRIPT = `on run argv
  set theTo to item 1 of argv
  set theText to item 2 of argv
  tell application "Messages"
    set svc to 1st account whose service type = iMessage
    set who to participant theTo of svc
    if theText is not "" then send theText to who
    repeat with i from 3 to count of argv
      send (POSIX file (item i of argv)) to who
    end repeat
  end tell
end run`

function sendViaAppleScript(to, text, attachments) {
  // Messages only attaches files from places it may read; stage them under ~/Pictures/Vigil
  const staged = attachments.filter((p) => existsSync(p)).map((p) => {
    const dir = join(homedir(), 'Pictures', 'Vigil')
    mkdirSync(dir, { recursive: true })
    const dst = join(dir, `${Date.now()}-${basename(p)}`)
    copyFileSync(p, dst)
    return dst
  })
  return new Promise((resolve, reject) => {
    execFile('osascript', ['-e', SEND_SCRIPT, to, text || '', ...staged], { timeout: 30000 }, (err, _out, stderr) => {
      if (!err) return resolve()
      const msg = String(stderr || err.message)
      reject(new Error(/-1743|not allowed|Not authorized/i.test(msg) ? 'needs_automation' : msg.trim()))
    })
  })
}

function health() {
  const messagesSignedIn = existsSync(MESSAGES_DB) || existsSync(join(homedir(), 'Library', 'Messages'))
  const needs = []
  if (!DRY_RUN) {
    if (lastSendError === 'needs_automation') needs.push('automation')
    if (!listening) needs.push('full_disk_access')
  }
  return {
    ok: true,
    sdk: 'spectrum-ts',
    dry_run: DRY_RUN,
    mode: DRY_RUN ? 'test' : 'live',
    can_send: !DRY_RUN && lastSendError !== 'needs_automation',
    reads_replies: listening,
    watching: listening,
    messages_found: messagesSignedIn,
    host_app: HOST_APP,
    needs,
    sent: sent.length,
    sent_ok: sentOk,
    replied: repliedOk,
    agent: listening,
    last_error: lastError === 'needs_full_disk_access' ? '' : lastError,
    last_send_error: lastSendError === 'needs_automation' ? '' : lastSendError,
  }
}

function json(res, code, body) {
  res.writeHead(code, { 'content-type': 'application/json' })
  res.end(JSON.stringify(body))
}

const server = http.createServer(async (req, res) => {
  if (req.method === 'GET' && req.url === '/health') return json(res, 200, health())
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
      console.log(`[test mode] to ${to}: ${text}${attachments.length ? ` (+${attachments.length} image)` : ''}`)
      return json(res, 200, { ok: true, dry_run: true })
    }
    try {
      if (imessage) {
        const space = await imessage.space.create(to)
        const parts = [...(text ? [spectrum.text(text)] : []), ...attachments.map((p) => spectrum.attachment(p))]
        await space.send(...parts)
      } else {
        await sendViaAppleScript(to, text, attachments)
      }
      lastSendError = ''
      sentOk += 1
      return json(res, 200, { ok: true, via: imessage ? 'spectrum' : 'messages' })
    } catch (e) {
      lastSendError = String(e?.message || e)
      const help = lastSendError === 'needs_automation'
        ? `macOS blocked Vigil from using Messages. Allow ${HOST_APP} under System Settings > Privacy & Security > Automation > Messages.`
        : lastSendError
      return json(res, 502, { ok: false, error: help, needs: lastSendError === 'needs_automation' ? 'automation' : undefined })
    }
  }
  json(res, 404, { ok: false, error: 'not found' })
})

await startSpectrum()
setInterval(() => { if (!imessage && !DRY_RUN) startSpectrum() }, 30000)  // picks up Full Disk Access once granted

server.listen(PORT, '127.0.0.1', () =>
  console.log(`Vigil iMessage bridge (Photon Spectrum) on http://127.0.0.1:${PORT} · ${DRY_RUN ? 'test mode' : 'live'} · `
    + `${listening ? 'reading replies' : 'sending only until Full Disk Access is granted'} · replies -> ${VIGIL_URL}`),
)

for (const sig of ['SIGINT', 'SIGTERM']) {
  process.on(sig, async () => {
    server.close()
    if (app) await app.stop().catch(() => {})
    process.exit(0)
  })
}

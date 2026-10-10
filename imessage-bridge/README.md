# Vigil iMessage bridge

Sends Vigil alerts as iMessages (with the snapshot) using Photon's [Spectrum SDK](https://github.com/photon-hq/spectrum-ts) and its local iMessage provider (`@spectrum-ts/imessage-local`),
and forwards replies back to Vigil. Answering **YES** or **NO** to an alert labels that event, and the watch
retrains on it right away: the self-improving loop runs from your phone.

```bash
cd imessage-bridge
npm install
npm start            # real sends; needs macOS + Messages signed in
npm run dry          # logs instead of sending
```

Give the terminal that runs it **Full Disk Access** (System Settings → Privacy & Security) so it can read replies.

| Variable | Default | |
|---|---|---|
| `PORT` | `8790` | Vigil's Settings → iMessage points here |
| `VIGIL_URL` | `http://127.0.0.1:8765` | where replies are forwarded |
| `ALLOW_FROM` | (anyone) | comma-separated numbers/emails whose replies count |
| `DRY_RUN` | off | log instead of sending |

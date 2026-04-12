# Slack Archive

A lightweight personal web app for archiving noteworthy content from Slack — AI links, restaurant recs, memorable moments, etc. Flask + SQLite, no build step, runs on a Mac Mini.

---

## Running the app

```bash
cd slack-archive
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
gunicorn -w 2 -b 0.0.0.0:5055 app:app
```

Visit `http://localhost:5055` to verify it's working.

> Use `127.0.0.1:5055` instead of `0.0.0.0:5055` if you don't need Tailscale direct access.

---

## Auto-start on boot (launchd)

Create `~/Library/LaunchAgents/com.slackarchive.plist`, replacing the paths with your actual paths:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.slackarchive</string>
  <key>ProgramArguments</key>
  <array>
    <string>/path/to/slack-archive/.venv/bin/gunicorn</string>
    <string>-w</string><string>2</string>
    <string>-b</string><string>0.0.0.0:5055</string>
    <string>app:app</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/path/to/slack-archive</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
</dict>
</plist>
```

Then load it:

```bash
launchctl load ~/Library/LaunchAgents/com.slackarchive.plist
```

To stop or unload:

```bash
launchctl unload ~/Library/LaunchAgents/com.slackarchive.plist
```

---

## Cloudflare Tunnel (public access)

**Prerequisites:** A domain managed through Cloudflare (free account works).

### 1. Install cloudflared

```bash
brew install cloudflared
```

### 2. Authenticate

```bash
cloudflared tunnel login
```

Opens a browser. Select your domain. A cert is saved to `~/.cloudflared/cert.pem`.

### 3. Create a named tunnel

```bash
cloudflared tunnel create slack-archive
```

Note the tunnel UUID printed — you'll need it next.

### 4. Create the config file

Create `~/.cloudflared/config.yml`:

```yaml
tunnel: <YOUR-TUNNEL-UUID>
credentials-file: /Users/<you>/.cloudflared/<YOUR-TUNNEL-UUID>.json

ingress:
  - hostname: archive.yourdomain.com
    service: http://localhost:5055
  - service: http_status:404
```

### 5. Add a DNS record

```bash
cloudflared tunnel route dns slack-archive archive.yourdomain.com
```

This creates the CNAME in your Cloudflare DNS automatically.

### 6. Test it

```bash
cloudflared tunnel run slack-archive
```

Visit `https://archive.yourdomain.com` — you should see the app. Ctrl-C to stop.

### 7. Install as a system service (auto-start on boot)

```bash
sudo cloudflared service install
sudo launchctl start com.cloudflare.cloudflared
```

The service reads `~/.cloudflared/config.yml` and starts on login.

---

## Access model

| | Cloudflare tunnel | Tailscale |
|---|---|---|
| Who can access | Anyone with the URL | Only devices on your tailnet |
| Share with friends | Yes — just send the URL | They'd need a Tailscale invite |
| Your own remote access | Yes | Yes |

**To lock it down:** Cloudflare Zero Trust → Access → Applications → add your hostname → set a policy (e.g. allowlist specific email addresses). Free for up to 50 users. Visitors get an email-OTP challenge before seeing the app.

**Tailscale direct access:** make sure gunicorn binds to `0.0.0.0:5055` (not `127.0.0.1`), then reach it at `http://<tailscale-ip>:5055` from any device on your tailnet.

---

## Backups

`archive.db` lives next to `app.py` and is covered by Time Machine automatically. For a manual snapshot:

```bash
cp archive.db archive.db.bak
```

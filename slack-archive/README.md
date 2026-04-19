# Slack Archive

A lightweight personal web app for archiving noteworthy content from Slack — AI links, restaurant recs, memorable moments, etc. Flask + SQLite, no build step, runs on a Mac Mini.

---

## Slack app integration

A message shortcut ("Archive message") lets anyone in the workspace archive a message directly from Slack without touching the web UI.

### What it does

1. Right-click any Slack message → **More message shortcuts** → **Archive message**
2. A modal opens with a preview of the message, a category dropdown (populated from your existing categories), and an optional tags field
3. On submit, the message is archived and you get a confirmation DM

### Setup at api.slack.com/apps

1. Create a new Slack app → **From scratch**
2. **OAuth & Permissions** → Bot Token Scopes: `chat:write`, `channels:history`, `groups:history`, `im:write`
3. **Interactivity & Shortcuts** → turn on Interactivity → Request URL: `https://yourwebsite.com/slack/events`

4. Same page → **Shortcuts** → **Create New Shortcut** → **On messages** → Name: `Archive message` → Callback ID: `archive_message`
5. Install the app to your workspace → copy the **Bot User OAuth Token**
6. **Basic Information** → copy the **Signing Secret**

### Environment variables

Copy `.env.example` to `.env` and fill in the values:

```bash
cp .env.example .env
```

```
SLACK_BOT_TOKEN=xoxb-...
SLACK_SIGNING_SECRET=...
```

The app reads these on startup via `python-dotenv`. Restart gunicorn after editing `.env`.

### New columns added to the DB

Three columns are added automatically via migration on first run with the new code:

| column | stores |
|---|---|
| `slack_message_ts` | Slack message timestamp |
| `slack_channel_id` | Channel the message came from |
| `slack_author_id` | Slack user ID of the original message author |

The submitting user's Slack ID is stored in the existing `source` column.

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
```

This installs `/Library/LaunchDaemons/com.cloudflare.cloudflared.plist`, but the generated plist doesn't include the right arguments. Edit it:

```bash
sudo nano /Library/LaunchDaemons/com.cloudflare.cloudflared.plist
```

Replace the `ProgramArguments` array with:

```xml
<key>ProgramArguments</key>
<array>
    <string>/opt/homebrew/bin/cloudflared</string>
    <string>--config</string>
    <string>/var/root/.cloudflared/config.yml</string>
    <string>tunnel</string>
    <string>run</string>
    <string>slack-archive</string>
</array>
```

Copy your credentials into root's home so the daemon can find them:

```bash
sudo mkdir -p /var/root/.cloudflared
sudo cp ~/.cloudflared/config.yml /var/root/.cloudflared/
sudo cp ~/.cloudflared/<YOUR-TUNNEL-UUID>.json /var/root/.cloudflared/
sudo cp ~/.cloudflared/cert.pem /var/root/.cloudflared/
```

Edit `/var/root/.cloudflared/config.yml` and update `credentials-file` to point to `/var/root/.cloudflared/<YOUR-TUNNEL-UUID>.json`.

Then load the service:

```bash
sudo launchctl unload /Library/LaunchDaemons/com.cloudflare.cloudflared.plist
sudo launchctl load /Library/LaunchDaemons/com.cloudflare.cloudflared.plist
sudo launchctl list | grep cloudflared  # should show a PID
```

---

## Rotating the Cloudflare tunnel token

If you rotate the token in the Cloudflare dashboard, the credentials file on disk becomes invalid and the tunnel will fail to connect. Update both copies with the new credentials:

```bash
cloudflared tunnel token slack-archive | python3 -c "import sys,base64,json; token=sys.stdin.read().strip(); data=json.loads(base64.urlsafe_b64decode(token+'==')); secret=base64.b64encode(base64.urlsafe_b64decode(data['s']+'==')).decode(); print(json.dumps({'AccountTag':data['a'],'TunnelSecret':secret,'TunnelID':data['t'],'Endpoint':''}))" | tee ~/.cloudflared/afe65215-808c-47bd-8cff-d115eb3c2fa1.json | sudo tee /var/root/.cloudflared/afe65215-808c-47bd-8cff-d115eb3c2fa1.json
```

Then reload the daemon:

```bash
sudo launchctl unload /Library/LaunchDaemons/com.cloudflare.cloudflared.plist
sudo launchctl load /Library/LaunchDaemons/com.cloudflare.cloudflared.plist
sudo launchctl list | grep cloudflared  # should show a PID
```

**Important:** the credentials file must use long-form keys (`AccountTag`, `TunnelSecret`, `TunnelID`, `Endpoint`) — the short-form keys (`a`, `s`, `t`) from the raw decoded token will not work.

---

## Service architecture

The app runs as two separate launchd services on the Mac Mini. Understanding the difference matters for headless operation.

| | cloudflared | slack-archive (gunicorn) |
|---|---|---|
| plist location | `/Library/LaunchDaemons/` | `~/Library/LaunchAgents/` |
| Runs as | root | your user account |
| Starts at | system boot | GUI login |
| Installed by | `sudo cloudflared service install` | manual |

**LaunchDaemons** start at boot regardless of who (if anyone) is logged in.  
**LaunchAgents** only start when the owning user has an active GUI session — SSH does not count.

### Headless Mac Mini caveat

If the Mac Mini reboots without auto-login enabled, cloudflared comes back up automatically but gunicorn does not — the site will be down until someone physically logs into the desktop.

Check whether auto-login is configured:

```bash
defaults read /Library/Preferences/com.apple.loginwindow autoLoginUser 2>/dev/null || echo "auto-login not set"
```

Note: FileVault disables auto-login. Check with `fdesetup status`.

### Option: run gunicorn as a LaunchDaemon (survives headless reboots)

This requires gunicorn to run as root (or a dedicated user). The simplest approach is root.

1. Copy the plist to the system location:

```bash
sudo cp ~/Library/LaunchAgents/com.slackarchive.plist /Library/LaunchDaemons/com.slackarchive.plist
sudo launchctl unload ~/Library/LaunchAgents/com.slackarchive.plist
```

2. Edit the system plist to add log paths (optional but recommended):

```bash
sudo nano /Library/LaunchDaemons/com.slackarchive.plist
```

Add before `</dict>`:

```xml
<key>StandardOutPath</key>
<string>/Library/Logs/com.slackarchive.out.log</string>
<key>StandardErrorPath</key>
<string>/Library/Logs/com.slackarchive.err.log</string>
```

3. Load it:

```bash
sudo launchctl load /Library/LaunchDaemons/com.slackarchive.plist
```

The `make restart` / `make logs` targets in the Makefile would need updating to use `sudo` and the new paths if you switch.

---

## Logs

| service | log location |
|---|---|
| gunicorn stdout | `~/Library/Logs/com.slackarchive.out.log` |
| gunicorn stderr | `~/Library/Logs/com.slackarchive.err.log` |
| cloudflared stdout | `/Library/Logs/com.cloudflare.cloudflared.out.log` |
| cloudflared stderr | `/Library/Logs/com.cloudflare.cloudflared.err.log` |

Tail gunicorn errors (also available via `make logs`):

```bash
tail -f ~/Library/Logs/com.slackarchive.err.log
```

Check service status:

```bash
launchctl list | grep slackarchive       # gunicorn — PID in first column = running
sudo launchctl list | grep cloudflared   # cloudflared — PID in first column = running
```

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

# lsbc-memory-hole

A personal toolbox of small web apps hosted on a Mac Mini, served publicly via Cloudflare tunnel at `lsbc-memory-hole.com` and privately via Tailscale. Each app lives in its own subdirectory and is self-contained — no shared infrastructure, no monorepo build system.

## Apps

### [slack-archive](./slack-archive/)

A lightweight web app for archiving noteworthy content from Slack — AI links, restaurant recs, memorable moments, etc. Flask + SQLite, zero build step. Includes a Slack message shortcut ("Memory Hole") for archiving directly from Slack without touching the web UI.

## Adding a new app

Each app should be self-contained in its own subdirectory:

```
lsbc-memory-hole/
  slack-archive/    ← existing
  my-new-app/       ← drop it here
    app.py
    requirements.txt
    README.md
    ...
```

Common patterns used in this repo:
- Flask + SQLite for persistence (no external DB)
- Tailwind Play CDN for styling (no build step)
- gunicorn as the WSGI server
- launchd (LaunchAgent or LaunchDaemon) for auto-start
- Cloudflare tunnel for public access

Each app gets its own launchd plist and runs on its own port.

## Infrastructure

| component | how it runs |
|---|---|
| Cloudflare tunnel | LaunchDaemon — starts at boot, survives headless reboots |
| App processes (gunicorn) | LaunchAgent — starts on GUI login; see app README for headless options |

See individual app READMEs for setup, log locations, and operational notes.

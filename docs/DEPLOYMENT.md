# Deploying to a VPS with your own domain

This walks through hosting the calendar at a subdomain (the examples use
`calendar.bogdantruta.com`) on any Linux VPS, with DNS on Cloudflare and
automatic HTTPS via Caddy. Total time: ~15 minutes.

## 0. What you need

- A VPS (any small instance works — 1 vCPU / 512 MB is plenty), Ubuntu 22.04+
  assumed below
- Your domain's DNS managed in Cloudflare
- An LLM API key (OpenRouter/Gemini/…)

## 1. Point the subdomain at your VPS (Cloudflare)

In the Cloudflare dashboard → your domain → **DNS** → **Add record**:

| Field | Value |
| --- | --- |
| Type | `A` |
| Name | `calendar` |
| IPv4 address | your VPS's public IP |
| Proxy status | **DNS only** (grey cloud) |

Start with **DNS only** so Caddy can obtain its Let's Encrypt certificate
without surprises. Once everything works you can optionally flip it to
**Proxied** (orange cloud) for Cloudflare's DDoS shielding — if you do, also
set *SSL/TLS → Overview → Full (strict)* in Cloudflare, or you'll get redirect
loops.

DNS propagates in a minute or two; verify with `nslookup calendar.bogdantruta.com`.

## 2. Prepare the VPS

```bash
# Docker + compose plugin
curl -fsSL https://get.docker.com | sh

# Firewall: only SSH and web traffic
sudo ufw allow OpenSSH
sudo ufw allow 80,443/tcp
sudo ufw enable
```

## 3. Install the app

```bash
git clone https://github.com/Bogzx/ftmo-calendar
cd ftmo-calendar
mkdir data
```

`data/config.toml` — feed-only mode (no Google account anywhere):

```toml
[llm]
provider = "openai-compatible"
base_url = "https://openrouter.ai/api/v1"
models = ["deepseek/deepseek-v4-flash", "deepseek/deepseek-v4-pro"]

[calendar]
enabled = false
```

`.env` (next to `compose.yaml`):

```bash
LLM_API_KEY="sk-or-v1-..."
# optional but recommended — get pinged on changes and failures:
# DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..."
```

Bind the app to localhost only (Caddy will be the public face). Edit
`compose.yaml`:

```yaml
    ports:
      - "127.0.0.1:8080:8080"
```

Start it:

```bash
sudo docker compose up -d
curl -s http://127.0.0.1:8080/healthz   # expect {"ok": true, ...} after ~30s
```

## 4. HTTPS with Caddy

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy
```

`/etc/caddy/Caddyfile`:

```
calendar.bogdantruta.com {
    reverse_proxy localhost:8080
}
```

```bash
sudo systemctl reload caddy
```

Caddy fetches and renews the certificate automatically. That's the whole
HTTPS story.

## 5. Verify

- `https://calendar.bogdantruta.com/` — landing page with the countdown
- `https://calendar.bogdantruta.com/feed.ics` — the feed (subscribe to this)
- `https://calendar.bogdantruta.com/healthz` — `"ok": true`
- `https://calendar.bogdantruta.com/stats` — usage numbers

Subscribe from your own Google Calendar (*Other calendars → + → From URL*) and
share the `/status` page with your group.

## 6. Operating it

| Task | Command |
| --- | --- |
| Logs | `sudo docker compose logs -f` |
| Update to a new release | `git pull && sudo docker compose up -d --build` |
| Restart | `sudo docker compose restart` |
| Health from outside | point UptimeRobot (or similar) at `/healthz` |

Everything stateful lives in `./data` (`state.json`, `stats.json`, the feed)
and in `.env` — back those up and the deployment is fully reproducible.

The container restarts itself (`restart: unless-stopped`) and has a Docker
healthcheck; a failing FTMO sync never takes the feed down, and if you set the
Discord webhook you'll hear about every change and every failure.

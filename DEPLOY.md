# SailReady — POC deployment (single VM)

Deliberately NOT production infrastructure (that's Milestone C: Terraform,
RDS, Lambda). This is one small VM running the same compose stack as local
dev, behind Caddy (auto-TLS) and oauth2-proxy (Google sign-in + invite list).

```
internet → Caddy :443 (Let's Encrypt) → oauth2-proxy (Google + allowlist) → API
                                                  DB / watcher / mailpit internal only
```

## What you need

| Thing | Spec / source |
|---|---|
| VM | 2 vCPU / 2–4 GB / 40 GB disk, Ubuntu 24.04. The app is I/O-bound (waits on weather APIs) — CPU stays near idle. ~$6–12/mo: Hetzner CX22, Lightsail, DO basic droplet |
| Open ports | 22 (your IP only if possible), 80, 443 |
| DNS | A record `app.sailready.ai` → VM public IP (set TTL low while testing) |
| Google OAuth client | console.cloud.google.com → APIs & Services → Credentials → OAuth client (Web). Origin `https://app.sailready.ai`, redirect URI `https://app.sailready.ai/oauth2/callback` |

## Steps

```bash
# on the VM
sudo apt update && sudo apt install -y docker.io docker-compose-v2 git
git clone <your repo> sailready && cd sailready/deploy

cp .env.example .env && nano .env       # domain, postgres pw, Google creds, cookie secret
nano authenticated-emails.txt           # the invite list

docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml run --rm api alembic upgrade head

# chart data (one-time, ~2 minutes)
./get-enc.sh
docker compose -f docker-compose.prod.yml run --rm api python -m app.charts.ingest_enc data/enc
docker compose -f docker-compose.prod.yml run --rm api python -m app.charts.warm_tiles
```

Visit `https://app.sailready.ai/app` → Google sign-in → in. Each allowlisted
user gets their own row + RLS isolation automatically on first sign-in
(`ensure_user`), and HTTPS means **GPS/find-me works** here even though it
can't on the LAN prototype.

## Inviting someone

Add their email to `authenticated-emails.txt` — oauth2-proxy re-reads the
file automatically. Remove the line to revoke.

## Things to know (POC-grade, accepted)

- **Alert emails** land in the internal Mailpit, not real inboxes. View via
  `ssh -L 8025:mailpit:8025` or temporarily publish `127.0.0.1:8025:8025`.
  Real outbound mail (SES/Resend) is a Milestone C item.
- **DB role password**: migration 0001 creates `sailready_app` with a fixed
  password. The DB is internal-network only so exposure is nil, but change it
  anyway (see .env.example comment).
- **Backups**: `docker compose -f docker-compose.prod.yml exec db pg_dump -U sailready sailready | gzip > backup.sql.gz`
  in a daily cron + VM snapshots. Good enough for a POC.
- **Updates**: `git pull && docker compose -f docker-compose.prod.yml up -d --build`
  then run any new migrations. The app-version banner tells open tabs to reload.
- **The dev compose is unchanged** — local work continues exactly as before
  with AUTH_MODE=dev.

## Cost reality

VM ~$6–12/mo + domain you already own. Open-Meteo stays on the free
non-commercial tier until the app charges money. Everything else (NOAA,
Nominatim, OSM tiles) is free with polite usage, which the caches enforce.

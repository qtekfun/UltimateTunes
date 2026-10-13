<!--
SPDX-FileCopyrightText: 2026 UltimateTunes contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Tailscale (`tailscale serve`) — step by step

**Example only; nothing is deployed by the project.** This is the recommended way to run UltimateTunes at home: HTTPS with a valid certificate, reachable only from devices in your tailnet, no open port on your router, no reverse proxy to maintain.

What you end up with:

```
phone / laptop (tailnet) ──HTTPS──> tailscale serve (host, :443) ──> 127.0.0.1:8044 ──> api ──> worker ──> YouTube, MusicBrainz…
                                                                                          └──> pot-provider (optional)
```

Files in this folder:

| File | What |
|---|---|
| `compose.override.yml` | Overlay for `server/compose.yaml`: never pull the locally built image, and pin the network the api is published on so its gateway is known (`UT_TRUSTED_PROXIES`). |
| `.env.example` | Every variable this setup needs, with the PO token provider on. |

## 1. Build the image (on your workstation)

Publishing to GHCR is paused (RELEASING.md), so build the image from a checkout and load it on the server. Name the tag after the commit, so you always know what runs:

```sh
git pull
TAG=local-$(git rev-parse --short HEAD)
docker build -f server/Dockerfile -t ghcr.io/qtekfun/ultimatetunes-server:$TAG .
# Copy it to the server (about 1 GB, compressed on the way):
docker save ghcr.io/qtekfun/ultimatetunes-server:$TAG | gzip -1 | ssh <server> 'gunzip | docker load'
echo $TAG    # goes into UT_VERSION
```

If you build on the server itself, skip the `docker save` line.

## 2. Prepare the stack folder (on the server)

```sh
mkdir -p ~/stacks/ultimatetunes && cd ~/stacks/ultimatetunes
REF=master   # or the commit you built
curl -fsSLo compose.yaml https://raw.githubusercontent.com/qtekfun/UltimateTunes/$REF/server/compose.yaml
curl -fsSLo compose.override.yml https://raw.githubusercontent.com/qtekfun/UltimateTunes/$REF/deploy/tailscale/compose.override.yml
curl -fsSLo .env https://raw.githubusercontent.com/qtekfun/UltimateTunes/$REF/deploy/tailscale/.env.example
head -3 compose.yaml    # must start with "# SPDX-FileCopyrightText"
```

Download the files rather than pasting them from a terminal: a pasted code fence or a lost `#` breaks the YAML (`yaml: construct errors ... cli.named`).

The library folder: a new, empty folder for UltimateTunes (do not point it at a library another player manages; UltimateTunes writes `Artist/Album/NN - Title.ext` into it). The containers run as uid 10001:

```sh
sudo mkdir -p /srv/ultimatetunes/music
sudo chown 10001:10001 /srv/ultimatetunes/music
```

## 3. Secrets

Two fresh random values, readable only by you, never committed:

```sh
mkdir -p secrets && chmod 700 secrets
openssl rand -hex 32 > secrets/worker_token
openssl rand -hex 32 > secrets/admin_session_secret
chmod 600 secrets/*
```

## 4. `.env`

Edit the `.env` you downloaded:

- `UT_VERSION`: the tag from step 1 (`local-…`).
- `UT_MUSIC_PATH`: the folder from step 2.
- `UT_BIND=127.0.0.1:8044`: keep it on loopback; `tailscale serve` is what publishes it.
- `UT_TRUSTED_PROXIES=10.213.46.1/32`: the gateway pinned in `compose.override.yml`. `tailscale serve` reaches the api through Docker's port publishing, so the api sees that gateway as the caller and must be told to believe its `X-Forwarded-For` (the tailnet address of your device). Without it, `/admin` answers 403.
- `COMPOSE_PROFILES=pot` and `UT_YTDLP_POT_PROVIDER_URL=http://bgutil:4416`: the optional PO token provider, below. Remove both lines if you do not want it.

Check that nothing overlaps your networks: the stack uses `10.213.44.0/24` (api–worker), `10.213.45.0/24` (worker egress), `10.213.46.0/24` (the api's published network, from the override) and `10.213.47.0/24` (PO token provider). `ip -4 route` and `docker network inspect $(docker network ls -q) --format '{{.Name}} {{range .IPAM.Config}}{{.Subnet}}{{end}}'` list what is taken; if one overlaps, change it in `.env` (and the override's subnet together with `UT_TRUSTED_PROXIES`).

### The PO token provider (`pot` profile)

YouTube sometimes answers downloads with "Sign in to confirm you're not a bot". The worker then pauses on its own (30 min, doubling up to 4 h), but the real remedy is the provider: a small container (about 80–115 MiB) that mints the proof-of-origin tokens YouTube expects. Only the worker can reach it; it publishes nothing and is not on the api's networks (docs/architecture.md, SPEC §11, D13).

- Its own log prints every token it mints (upstream offers no switch); it is capped at 2 × 1 MB. Do not share `docker compose logs pot-provider`.
- The worker's yt-dlp updates itself; the plugin in the image is pinned. If the canary starts failing only with the provider on, the plugin needs a bump (a newer image): turn it off meanwhile (below).

## 5. Start and create the first admin

```sh
docker compose config --quiet && echo OK     # syntax and variables (prints no secrets)
docker compose up -d
docker compose ps                            # migrate "exited (0)", api and worker "healthy", pot-provider "healthy"
docker compose exec api ultimatetunes bootstrap-admin <your-name>
```

`bootstrap-admin` runs inside the running api (`exec`; `docker compose run --rm api …` fails with "Address already in use", because the api's address on `internal` is pinned). It asks for the password twice without echoing it (12 to 1024 characters). There is no default account or password (docs/admin-guide.md, "First admin").

If you use the provider, check that the worker found it:

```sh
docker compose logs worker | grep -i "PO token"     # yt-dlp: PO token provider at http://bgutil:4416
```

## 6. Publish it in your tailnet

HTTPS certificates must be enabled for the tailnet (admin console → DNS → HTTPS Certificates). Then, on the server:

```sh
sudo tailscale serve --bg --https=443 http://127.0.0.1:8044
tailscale serve status       # shows https://<host>.<tailnet>.ts.net
```

`--bg` keeps it across reboots. Stop it with `sudo tailscale serve --https=443 off`. If port 443 is already served for something else, pick another (`--https=8443`) and add the port to the URLs below.

## 7. Use it

- **Web player**: `https://<host>.<tailnet>.ts.net/`, sign in with your account.
- **Admin panel**: `https://<host>.<tailnet>.ts.net/admin` (only from the tailnet or the LAN; it is never linked from the public pages). Create the other users there.
- **Phone**: install Tailscale on it and join the tailnet. In the panel, **API keys → New key**, scan the QR code with the camera app, open the link and confirm in UltimateTunes. Or type the address and the key on the Connect screen.
- **Other OpenSubsonic apps**: the same address with an API key (token auth `t`/`s` is refused by design).

## 8. Checks

```sh
curl -fsS https://<host>.<tailnet>.ts.net/healthz        # from a tailnet device: ok
curl -fsS http://127.0.0.1:8044/readyz                    # on the server: database, schema, storage
```

In the panel's audit log (Admin → Audit log), your actions must show your device's tailnet address (`100.x.y.z`), not `10.213.46.1`; if they show the gateway, `UT_TRUSTED_PROXIES` does not match the override.

## Operating it

**Update** (new commit): repeat step 1 with the new tag, set `UT_VERSION` in `.env`, download `compose.yaml` again for that commit (it may have changed), then:

```sh
docker compose up -d      # runs the migrations first, then restarts api and worker
docker image ls ghcr.io/qtekfun/ultimatetunes-server     # remove old tags when the new one works
```

**Turning the provider off**: remove `COMPOSE_PROFILES=pot` and `UT_YTDLP_POT_PROVIDER_URL` from `.env`, then `docker compose --profile pot rm -sf pot-provider` (`--remove-orphans` does not stop a profiled service) and `docker compose up -d`.

**Logs**: `docker compose logs -f api worker` (JSON lines; secrets are redacted).

**Backups**: the database lives in the `data` volume, the songs in `UT_MUSIC_PATH`. Online copy and a restore test: [`../README.md`](../README.md#backups-of-data-and-a-restore-test).

**Before leaving it running for good**: firewall the worker's `ut-egress` bridge so it reaches the Internet but not your LAN or the host ([`../README.md`](../README.md#firewall-the-worker-reaches-the-internet-only)). Not needed for a first try; needed before you rely on it.

**Stop everything**: `docker compose down` (never `down -v` unless you mean to delete the database and the yt-dlp volume).

## Do not use Funnel for this server (yet)

`tailscale funnel` publishes the same address **to the whole Internet**. Everything `SECURITY.md` lists under "Checklist before opening to the Internet" applies, and some of it Funnel cannot do:

- Funnel traffic reaches the api from loopback/the Docker gateway like tailnet traffic. The api refuses `/admin` for Funnel requests (`Tailscale-Funnel-Request`) and for any forwarded request it cannot attribute, but the rest of the api (OpenSubsonic, `/ut/v1`) is then public: protected by API keys and the per-IP limits only.
- There are no request-size limits, rate limits or access logs at the edge (Caddy in `../caddy/` has the first and the last).
- The public address is guessable (`<host>.<tailnet>.ts.net` is in Certificate Transparency logs).

If you still need public access, use Caddy (`../caddy/Caddyfile`) with its checklist, or keep phones on the tailnet (the Tailscale app on Android is free software).

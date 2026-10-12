<!--
SPDX-FileCopyrightText: 2026 UltimateTunes contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Deployment examples (homelab)

**Examples only.** The project deploys nothing and publishes nothing; these files show how the author's homelab (or yours) can put the server behind HTTPS. Start from `server/compose.yaml`, which publishes the api on `127.0.0.1:8044` only. Read `SECURITY.md` before exposing anything to the Internet.

| File | What |
|---|---|
| `tailscale/README.md` | `tailscale serve` (HTTPS inside your tailnet): the default and recommended way. Why not Funnel. |
| `caddy/Caddyfile` | Caddy on the host for public exposure: TLS, HSTS, request limits, `/admin` LAN/Tailscale-only. |

## The two listeners

The api serves clients on **8044** and the internal worker API on **8045** (`UT_INTERNAL_PORT`). Publish only 8044. The worker reaches 8045 over the Docker networks (`UT_API_URL=http://api:8045`); the client port answers 404 for `/internal/*`.

## Reverse proxies and the client address (`UT_TRUSTED_PROXIES`)

Behind any proxy on the host (`tailscale serve`, Caddy) the api sees every request coming from the same address: the Docker bridge gateway (Docker's port publishing) or loopback. That address is private, so **by itself it would pass the admin allowlist for the whole Internet**. The api therefore:

- believes `X-Forwarded-For` only from the networks in `UT_TRUSTED_PROXIES` (read from the right; the first hop that is not a trusted proxy is the client);
- with `UT_TRUSTED_PROXIES` empty (the default), refuses `/admin` for any request that carries forwarding headers (`X-Forwarded-For`, `Forwarded`, `X-Real-IP`, `X-Forwarded-Host`/`-Proto`), and hides the `/readyz` detail from it;
- always refuses `/admin` for a Tailscale Funnel request (`Tailscale-Funnel-Request` header).

`tailscale serve` and Caddy both add `X-Forwarded-For`, so **behind either, set `UT_TRUSTED_PROXIES`** to the proxy's address as the api container sees it, or the panel answers 403:

```sh
# The gateway of the network the api's port is published on (compose project "ultimatetunes"):
docker network inspect ultimatetunes_default --format '{{(index .IPAM.Config 0).Gateway}}'
# e.g. 172.18.0.1 -> in .env:
UT_TRUSTED_PROXIES=172.18.0.1/32
```

Use the single gateway address (`/32`), not the whole `172.16.0.0/12`: other containers on that network could then claim any client address. Check it from a tailnet device: `/admin` opens, and `https://<host>/readyz` shows the `checks` detail only from the tailnet or LAN.

The per-IP authentication limit and lockout (T04), the audit log and `/readyz` use the same resolved address, so without this setting every client behind the proxy would also share one rate-limit bucket.

## Hardening already in `server/compose.yaml`

Non-root user (10001), read-only root filesystem, `/tmp` as tmpfs, all capabilities dropped, `no-new-privileges`, a PID limit, secrets as Docker secrets (`./secrets/worker_token`, `./secrets/admin_session_secret`), the worker without database access and without a published port, sharing only the pinned `internal` network with the api (`UT_INTERNAL_SUBNET`, default `10.213.44.0/24`; change it if it overlaps one of your networks), from which `/admin` is refused.

## Backups of `/data` (and a restore test)

`/data` holds the SQLite database (users, keys, playlists, play counts). The library in `/music` is plain files: back it up with your usual tool. For the database, take an online copy with SQLite's backup API (safe while the api runs) and copy it out:

```sh
docker compose exec api python -c "import sqlite3; sqlite3.connect('/data/ultimatetunes.db').backup(sqlite3.connect('/data/backup.db'))"
docker compose cp api:/data/backup.db ./ultimatetunes-$(date +%F).db
docker compose exec api python -c "import os; os.remove('/data/backup.db')"
```

Test the restore on a throwaway copy, never on the live volume:

```sh
docker volume create ut-restore-test
docker run --rm -v ut-restore-test:/data -v "$PWD:/in:ro" --user 10001:10001 --entrypoint sh \
  ghcr.io/qtekfun/ultimatetunes-server:${UT_VERSION} -c 'cp /in/ultimatetunes-YYYY-MM-DD.db /data/ultimatetunes.db'
docker run --rm -v ut-restore-test:/data ghcr.io/qtekfun/ultimatetunes-server:${UT_VERSION} migrate
docker run --rm -v ut-restore-test:/data --entrypoint python ghcr.io/qtekfun/ultimatetunes-server:${UT_VERSION} \
  -c "import sqlite3; print(sqlite3.connect('/data/ultimatetunes.db').execute('PRAGMA integrity_check').fetchone())"
docker volume rm ut-restore-test
```

`migrate` must apply nothing new (or only the migrations of a newer image) and `integrity_check` must print `('ok',)`. While publishing is paused, use the locally built image tag instead of `ghcr.io/...` (RELEASING.md).

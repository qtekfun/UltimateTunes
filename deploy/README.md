<!--
SPDX-FileCopyrightText: 2026 UltimateTunes contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Deployment examples (homelab)

**Examples only.** The project deploys nothing and publishes nothing; these files show how the author's homelab (or yours) can put the server behind HTTPS. Start from `server/compose.yaml`, which publishes the api on `127.0.0.1:8044` only. Read `SECURITY.md` before exposing anything to the Internet.

The container layout, networks and every connection in and out are described in [`docs/architecture.md`](../docs/architecture.md).

| File | What |
|---|---|
| `tailscale/` | `tailscale serve` (HTTPS inside your tailnet): the default and recommended way. A step-by-step guide (build, secrets, `.env`, first admin, publish, update, turn off) with `compose.override.yml` and `.env.example`, including the optional PO token provider. Why not Funnel. |
| `caddy/Caddyfile` | Caddy on the host for public exposure: TLS, HSTS, request limits, `/admin` and `POST /ut/v1/keys` LAN/Tailscale-only. |
| `traefik/` | The same with Traefik v3 + Authelia: static config (`traefik.yml`), routers and middlewares (`dynamic/ultimatetunes.yml`), Traefik's stack with a pinned `proxy` network (`compose.traefik.yaml`) and an overlay for `server/compose.yaml` with the labels variant (`compose.labels.yaml`). |
| `traefik-cloudflared/` | Traefik v3 + Authelia reached through Cloudflare Tunnel (`cloudflared`): `.env.example` with every variable, an overlay with the routers as labels, Traefik and cloudflared pinned and trusted by address. Read its README for the Cloudflare caveats. |

## Exposing UltimateTunes

1. **Tailscale only is the recommended setup.** `tailscale serve` (`tailscale/README.md`) gives HTTPS inside your tailnet and nothing is reachable from the Internet. Never Tailscale Funnel.
2. **Public access only through Caddy** (`caddy/Caddyfile`) or **Traefik** (`traefik/`, below) on the host, with the per-IP rate limits of the `caddy-ratelimit` module enabled (commented out in the example; it needs a custom Caddy build). Caddy is what gives you TLS, a request-header timeout (`read_header`), per-IP request limits and a body cap at the edge; uvicorn has no header timeout of its own.
3. **Never port-forward 8044** (or 8045) on your router, and never publish `UT_BIND` on a public address: the api must not face the Internet directly.
4. **Never put an untrusted or unpinned tunnel or proxy in front of Caddy or Traefik** (an ad-hoc `cloudflared`, ngrok, an SSH forward, Funnel). The edge would see the tunnel's local address as every client: the `/admin` rule and every per-IP limit would treat the Internet as your LAN. A tunnel is safe only when its address is pinned and trusted end to end, as in `traefik-cloudflared/` (Cloudflare Tunnel → Traefik → api): `cloudflared` and Traefik on pinned addresses, Traefik trusting `X-Forwarded-For` only from `cloudflared`, `UT_TRUSTED_PROXIES` listing exactly those two `/32`s, and `UT_ADMIN_ALLOWED_NETWORKS` without the Docker and tunnel ranges (`/admin` LAN-only, plus Authelia).
5. **Fresh secrets with `server/compose.yaml`**: `openssl rand -hex 32 > secrets/worker_token` and the same for `secrets/admin_session_secret` (the worker token needs 32+ characters). Never reuse the test stack's token (`server/compose.test.yaml`, public on purpose) or any key or password you used while testing: **revoke every API key** created on a test stack or while trying things out (panel → Keys) and change test passwords before going public.
6. **Narrow the admin networks: required before any public exposure.** The default `UT_ADMIN_ALLOWED_NETWORKS` (loopback, every RFC 1918 and ULA range, link-local, Tailscale) is meant for a LAN/Tailscale-only setup. Before opening anything to the Internet, set it to your tailnet and your LAN's /24, for example `UT_ADMIN_ALLOWED_NETWORKS=127.0.0.1/32,::1/128,100.64.0.0/10,fd7a:115c:a1e0::/48,192.168.1.0/24`. **Never include the Docker bridge ranges (`172.16.0.0/12`)**: other containers on the host live there, and so does the gateway that Docker's userland proxy connects from. Give Caddy the same ranges (`UT_ADMIN_LAN_RANGES`, `UT_ADMIN_TAILNET_RANGES`), or Traefik's `ut-lan-only`.
7. **Firewall the worker** (below) and remove the bootstrap password after the first start (below).
8. Walk the checklist in `SECURITY.md`.

### Limits of the api itself

The listeners close idle keep-alive connections after `UT_KEEPALIVE_TIMEOUT_S` (5 s), refuse with 503 past `UT_LIMIT_CONCURRENCY` open connections (128; the internal listener `UT_INTERNAL_LIMIT_CONCURRENCY`, 32), queue `UT_BACKLOG` (256) pending connections and refuse request heads over `UT_MAX_HEADER_BYTES` (16 KiB). Bodies: 4 MiB api-wide (`UT_MAX_BODY_BYTES`), 1 MiB for OpenSubsonic form posts and 16 KiB for `POST /ut/v1/keys`. OpenSubsonic form bodies may carry the API key themselves (`formPost`), so they are read before the key is checked; the 1 MiB cap times the concurrency limit bounds that memory, and Caddy's `request_body` caps them at the edge. `server/compose.yaml` also caps the containers (`mem_limit`, `cpus`, open files, PIDs).

### Firewall: the worker reaches the Internet only

The worker runs yt-dlp, which executes extractor code paths on content from the Internet. Its way out is the `egress` network (bridge interface `ut-egress`, subnet `UT_EGRESS_SUBNET`, default `10.213.45.0/24`), and it needs nothing on your LAN. The api already refuses `/admin` to that subnet (`UT_WORKER_NETWORKS`), but block it on the host too, so a compromised worker cannot reach the host's own services (Caddy, a LAN-published `UT_BIND`, SSH) nor your LAN, tailnet or other containers:

```sh
# New connections from the worker to the host itself:
sudo iptables -I INPUT -i ut-egress -m conntrack --ctstate NEW -j DROP
# ...and to private networks (forwarded traffic; Docker's DOCKER-USER chain):
for net in 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 100.64.0.0/10 169.254.0.0/16; do
  sudo iptables -I DOCKER-USER -i ut-egress -d "$net" -j DROP
done
# If your DNS resolver is on the LAN (e.g. the router 192.168.1.1), allow it, inserted last
# so it comes first:
sudo iptables -I DOCKER-USER -i ut-egress -d 192.168.1.1 -p udp --dport 53 -j ACCEPT
```

With IPv6 on the bridge, add the same with `ip6tables` (`fc00::/7`, `fe80::/10`, `fd7a:115c:a1e0::/48`). On firewalld or nftables hosts, write the equivalent rules (zone `docker`, or a table hooked before Docker's). Persist them with your distribution's tool. Check from the worker: `docker compose exec worker python -c "import urllib.request; urllib.request.urlopen('http://192.168.1.1', timeout=3)"` must time out, while downloads keep working.

The optional PO token provider (`pot-provider`, Compose profile `pot`; [admin guide](../docs/admin-guide.md#sign-in-to-confirm-youre-not-a-bot)) leaves through the same `egress` bridge, so these rules cover it too. The worker talks to it over its own `internal` network `pot` (`UT_POT_SUBNET`, default `10.213.47.0/24`), which these rules do not touch; nothing about it is published on the host.

### Bootstrap admin password

`UT_BOOTSTRAP_ADMIN_USERNAME` + `UT_BOOTSTRAP_ADMIN_PASSWORD` create the first admin on the first start. Prefer the Docker secret over the env var (an env var shows in `docker inspect`): put the password in `./secrets/bootstrap_admin_password` and uncomment the `bootstrap_admin_password` secret in `server/compose.yaml`. **After the first start, remove the variable, the secret and the file**: the api never reads them again and logs a warning on every start while they are still set. Or skip them altogether and run `docker compose exec api ultimatetunes bootstrap-admin <name>` once, which asks for the password on the terminal.

## Notifications with ntfy

The panel (`/admin/notifications`) sends failed downloads, failed canary runs and low-disk pauses to an ntfy topic or a webhook, over **https** only and never to the server's own network. The URL must not carry a user or password. If your ntfy server requires login (`auth-default-access: deny-all`), give the api credentials through the environment; the panel never takes them, because the server has no encryption library to keep them safe in its database. It only shows whether they are set.

1. On the ntfy server, create a user for UltimateTunes and let it write to the topic only:
   ```sh
   ntfy user add ultimatetunes
   ntfy access ultimatetunes ut-alerts write-only
   ntfy token add ultimatetunes        # prints tk_...
   ```
2. Put the token in `./secrets/notify_token` (one line, mode 0600) and uncomment the `notify_token` secret in `server/compose.yaml`, both under the api's `secrets:` and at the end of the file. An env var (`UT_NOTIFY_TOKEN`) also works and wins over the secret, but shows in `docker inspect`.
   Without tokens, `UT_NOTIFY_USERNAME` + `UT_NOTIFY_PASSWORD` (Docker secrets `ut_notify_username`, `ut_notify_password`) send HTTP Basic instead. Set the token or the user and password, not both: the api refuses to start otherwise.
3. Bind the credentials to your ntfy host in `.env` (required with any credentials; the api refuses to start without it):
   ```sh
   UT_NOTIFY_HOST=ntfy.example.com        # or ntfy.example.com:8443 for another port
   ```
4. Restart the api, set the target in the panel to `https://ntfy.example.com/ut-alerts` (kind `ntfy`) and press "Send a test notification". "ntfy rejected the credentials" means a 401 or 403: a wrong token, or a user without write access to the topic.

The credentials go as one `Authorization` header (Bearer for the token, Basic for the user), and only when the target URL's host and port are exactly `UT_NOTIFY_HOST`: if the URL in the panel points anywhere else, notifications go there without credentials, the api logs a warning and the panel says so. Redirects are never followed, and the credentials never appear in the logs, the audit log, `/readyz` or error pages. A webhook target on that host gets the same header.

## Traefik + Authelia

`deploy/traefik/` is the Traefik v3 version of the Caddy example, for homelabs that already run Traefik with Authelia. Pinned to `traefik:v3.6.25` by digest (`compose.traefik.yaml`). Checked by running that image offline on these files: `/readyz`, `/internal/*`, `/healthz` and any other path answer 404; paths with encoded reserved characters are refused (`encodedCharacters`, e.g. `%3B` → 400); `/admin` and `POST /ut/v1/keys` from outside the LAN ranges answer 403; `/rest/*`, `/ut/v1/*` and `/` reach the api (`/web` was added to the client routers afterwards, with the same middlewares).

- **Routers** (`dynamic/ultimatetunes.yml`, or the same as labels in `compose.labels.yaml`; use one of the two):
  - `/admin`: `ipAllowList` (your LAN /24 and tailnet), then Authelia `forwardAuth`, then the api's own allowlist and admin login. Give it a `two_factor` rule in Authelia's `access_control`:
    ```yaml
    access_control:
      rules:
        - domain: music.example.org
          resources: ['^/admin([/?].*)?$']
          policy: two_factor
        - domain: music.example.org
          policy: bypass   # /rest and /ut/v1 authenticate with API keys; / and /web with their own login
    ```
  - `/rest/*`, `/ut/v1/*`: **no Authelia**. OpenSubsonic clients and the app authenticate with API keys; a `forwardAuth` login redirect would break all of them. They get `rateLimit` (per client IP), `inFlightReq` and secure headers (HSTS); requests that are not GET/HEAD also get `buffering` with `maxRequestBodyBytes` 2 MB. Traefik's buffering also holds back the whole response, so it is never put on GET (audio streams) nor on `/admin` (the api caps panel bodies at 64 KiB). Bodies over 1 MiB spill to disk, so Traefik's read-only container gets a `/tmp` tmpfs.
  - `POST /ut/v1/keys` (the password login): LAN/Tailscale only, through the same `ipAllowList`. Devices then get their key at home from the panel's QR code (Keys → new key). This removes the password-guessing surface at the edge. Remove `ut-lan-only` from that router if you want password logins from anywhere; it keeps the strict `ut-login-ratelimit` (1 per second per client, burst 5) and the api still limits it per IP and delays it per username.
  - `/` and `/web`, `/web/*` (the web player; `/` is its home page: the sign-in form, or Listen Now with a session): in the same client routers as `/rest/*` and `/ut/v1/*` (posts through `ut-api-write`, pages, covers and audio through `ut-api`). It is a browser client with its own signed session cookie (`HttpOnly`, `Secure`, `SameSite=Strict`, `Path=/`), so it needs HTTPS. Its sign-in form (`POST /web/login`) is a password check like `POST /ut/v1/keys`, so it has its own router `ut-web-login` with `ut-login-ratelimit` (1 per second per client, burst 5, IPv6 by /64) and `ut-inflight-login` (4 at once). Behind it the api limits password checks per IP and, per username, delays checks from outside by a growing delay (1 s, 2 s, 4 s … at most 5 min, reset by a success) instead of a lockout, so a stranger can keep a user's outside sign-in waiting but never locks the account, its sessions or its API keys; LAN/Tailscale sign-ins keep their own counter. **Optionally put it behind Authelia** (a browser follows the login redirect, unlike the app): add a router `ut-web` with rule ``Host(`music.example.org`) && (Path(`/`) || Path(`/web`) || PathPrefix(`/web/`))``, priority 250 (above `ut-api-write`), middlewares `[authelia, ut-headers, ut-inflight, ut-ratelimit]` (no `ut-body-limit`: the api caps `/web` bodies at 64 KiB), and an Authelia rule before the `bypass` one: `resources: ['^/$', '^/web([/?].*)?$']`, `policy: one_factor` (or `two_factor`); add `authelia` to `ut-web-login` too (it has the higher priority, so the form's POST would skip Authelia otherwise). Or add `ut-lan-only` to both to keep it at home.
  - Nothing routes `/internal` or `/readyz`: Traefik answers 404. The host's healthcheck uses `127.0.0.1:8044/readyz`.
- **Entrypoint** (`traefik.yml`): `transport.respondingTimeouts` with `readTimeout: 30s` (slowloris; the whole request must arrive in time), `idleTimeout: 120s` and `writeTimeout: 0s` (streams last minutes). `forwardedHeaders.trustedIPs` stays empty: Traefik is the edge and rewrites every client's `X-Forwarded-*`. Add an upstream there only if it really sits in front of Traefik, for example Cloudflare's proxy ranges. In that case also set `depth: 1` in the `ipStrategy` of `ut-ratelimit`, `ut-login-ratelimit`, `ut-inflight`, `ut-inflight-login` and `ut-lan-only`, so they key on the client Cloudflare saw. The rate limits and in-flight caps already group IPv6 clients by their /64 (`ipv6Subnet: 64`, checked with the pinned v3.6.25: an unknown field there is a configuration error). Never an unpinned or untrusted tunnel on the same host (an ad-hoc `cloudflared`, ngrok, an SSH forward): it connects from a local address. For Cloudflare Tunnel use `traefik-cloudflared/`, where `cloudflared` has a pinned address that Traefik and the api trust explicitly.
- **The client address** (`UT_TRUSTED_PROXIES`): Traefik's own stack pins the `proxy` network (`UT_PROXY_SUBNET`, default `10.213.46.0/24`) and Traefik's address on it (`UT_TRAEFIK_ADDRESS`, `10.213.46.2`). The overlay puts the api on `proxy` under the alias `ultimatetunes-api`; the worker never joins it. It sets `UT_TRUSTED_PROXIES=10.213.46.2/32` and adds the `proxy` subnet to `UT_WORKER_NETWORKS`, so other homelab containers on `proxy` never get `/admin`. Traefik sends `X-Forwarded-For: <client>`. The api believes it only because the TCP peer is exactly `10.213.46.2`, reads it from the right, and uses that address for its admin allowlist, its per-IP limits and lockout, and the audit log. A forged `X-Forwarded-For` from the Internet never survives: Traefik drops it at the entrypoint. A container that is not Traefik gains nothing by sending one: it is not a trusted proxy.
- **Client addresses at Traefik.** Traefik's `ipAllowList` and `rateLimit`, and through `X-Forwarded-For` the api's own limits, see the real client only if Docker keeps the source address on the published ports 80/443. Docker does for IPv4 traffic it can DNAT. Whenever **Docker's userland proxy** answers instead, every such client shows up with the same address, the proxy's gateway (`172.x.0.1` or similar). The common case is IPv6 clients reaching a host whose `proxy` network has no IPv6. All of those clients then **share one rate-limit bucket and one lockout counter**: one abusive client locks out or slows down the others. If that gateway is inside an allowlist, they all pass it. Fix it by enabling IPv6 on the `proxy` network (`enable_ipv6: true` with an IPv6 subnet, and IPv6 enabled in the Docker daemon), or by running Traefik with `network_mode: host`. Check Traefik's access log: client addresses must be the real ones.
- Start: `docker compose -f compose.traefik.yaml up -d` in `deploy/traefik/`, then the server with `docker compose -f compose.yaml -f ../deploy/traefik/compose.labels.yaml up -d`. Remove `ports:` from the api (or keep `127.0.0.1:8044` for the host's own checks).

## The two listeners

The api serves clients on **8044** and the internal worker API on **8045** (`UT_INTERNAL_PORT`). Publish only 8044. The worker reaches 8045 over the pinned `internal` network (`UT_API_URL=http://api:8045`), and 8045 listens only on the api's address there (`UT_INTERNAL_HOST` = `UT_API_INTERNAL_ADDRESS`, default `10.213.44.250`), so containers on the api's other networks (a reverse proxy's shared network) cannot connect to it; the client port answers 404 for `/internal/*`.

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

Use the single gateway address (`/32`), not the whole `172.16.0.0/12`: other containers on that network could then claim any client address. Check it from a tailnet device: `/admin` opens, and `https://<host>/readyz` (through `tailscale serve`; the Caddy example does not route `/readyz` at all) shows the `checks` detail only from the tailnet or LAN.

The per-IP authentication limit and lockout (T04), the audit log and `/readyz` use the same resolved address, so without this setting every client behind the proxy would also share one rate-limit bucket.

## Hardening already in `server/compose.yaml`

Non-root user (10001), read-only root filesystem, `/tmp` as tmpfs, all capabilities dropped, `no-new-privileges`, a PID limit, memory, CPU and open-file limits, secrets as Docker secrets (`./secrets/worker_token`, `./secrets/admin_session_secret`), the worker without database access and without a published port, sharing only the pinned `internal` network with the api (`UT_INTERNAL_SUBNET`, default `10.213.44.0/24`) and leaving through its own pinned `egress` network (`UT_EGRESS_SUBNET`, default `10.213.45.0/24`); change either if it overlaps one of your networks. `/admin` and the `/readyz` detail are refused to both subnets (`UT_WORKER_NETWORKS`). A new database file is created owner-only (0600).

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

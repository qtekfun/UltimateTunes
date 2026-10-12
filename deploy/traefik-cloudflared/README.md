<!--
SPDX-FileCopyrightText: 2026 UltimateTunes contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Traefik behind Cloudflare Tunnel, with Authelia (example)

**Example only.** For a homelab that already runs Traefik v3 and Authelia and reaches the Internet through Cloudflare Tunnel (`cloudflared`), with no open port on the router. Every name and address here is a placeholder (`tunes.example.com`, `172.30.0.0/24`, `192.168.1.0/24`): put yours in `.env`, never in the YAML. Read `../README.md` ("Exposing UltimateTunes") and `SECURITY.md` first.

| File | What |
|---|---|
| `.env.example` | Every variable this setup reads, with safe example values. Copy it to `.env` (git-ignored). |
| `compose.override.yml` | Overlay for `server/compose.yaml`: the api joins Traefik's network without a host port, trusts exactly Traefik and cloudflared, and carries the Traefik routers and middlewares as labels. |
| `dynamic.example.yml` | The `authelia` forwardAuth middleware the labels reference as `authelia@file`, and Authelia's `access_control` rule. |

```
Internet ─► Cloudflare edge ─► cloudflared ─► Traefik ─► api:8044
                                (172.30.0.250) (172.30.0.2)
LAN ─────────────────────────────────────────► Traefik (split DNS: tunes.example.com → the host)
```

Checked with the pinned `traefik:v3.6.25` image of `../traefik/` (docker provider, these labels, a stand-in backend): through the pinned cloudflared address, `/rest/*`, `/ut/v1/*` and `/` reach the api with `X-Forwarded-For: <forged…>, <client>, <cloudflared>`, while `/admin`, `POST /ut/v1/keys` and `/readyz` answer 403 and `/internal/*` and `/healthz` 404; from the LAN range the LAN-only routes pass; from any other container a forged `X-Forwarded-For` is dropped; the rate limit keys on the last entry (one client throttled, the next one unaffected, whatever forged prefixes the first sends).

## Who the client is, and why it can be trusted

A request through the tunnel reaches Traefik from **cloudflared's** address and the api from **Traefik's**. Neither is the client, and both are private Docker addresses, so trusting them blindly would make the whole Internet look like your LAN. Each hop therefore trusts exactly one pinned address:

1. **Cloudflare's edge** appends the address it saw to `X-Forwarded-For` (keeping whatever the client sent before it); cloudflared passes the header on. So its **last entry is the real client**, and anything before it may be forged.
2. **Traefik** keeps that header only from cloudflared (`forwardedHeaders.trustedIPs`); from anyone else it drops it. Its rate limit and in-flight cap use `ipStrategy.depth: 1`: the last entry, the client.
3. **The api** gets `X-Forwarded-For: <client>, <cloudflared>` from Traefik. With `UT_TRUSTED_PROXIES=<traefik>/32,<cloudflared>/32` it walks the list from the right, skips the two trusted hops and lands on the client, which it uses for its admin allowlist, its per-IP limits and lockout, and the audit log.

The LAN-only middleware (`/admin`, `POST /ut/v1/keys`, `/readyz`) has **no** `ipStrategy`: it checks the TCP peer. Through the tunnel the peer is always cloudflared, which is not in `UT_EDGE_LAN_RANGES`, so the Internet never passes it, whatever headers it sends. LAN devices reach Traefik directly: give `tunes.example.com` your host's LAN address in your local DNS (split DNS), and publish Traefik's 443 on the host. Two consequences: requests that reach Traefik directly carry no trusted `X-Forwarded-For`, so with `depth: 1` they all share one rate-limit bucket (fine for a LAN); and Docker must keep LAN client addresses on that published port (see "Client addresses at Traefik" in `../README.md`).

### Pin the addresses

Traefik and cloudflared live on Traefik's network (placeholder `traefik`, subnet `172.30.0.0/24`), each at a **fixed address outside the range Docker hands out**, so no other container can ever get one of them:

```sh
docker network create --subnet 172.30.0.0/24 --ip-range 172.30.0.64/26 traefik
```

In Traefik's own stack (not in this repository):

```yaml
services:
  traefik:
    # Pin the image by digest (deploy/traefik/compose.traefik.yaml shows one).
    networks:
      traefik:
        ipv4_address: 172.30.0.2
  cloudflared:
    # Pin the image by digest too.
    command: ["tunnel", "--no-autoupdate", "run"]
    # TUNNEL_TOKEN from a file outside the repository (env_file or a Docker secret).
    networks:
      traefik:
        ipv4_address: 172.30.0.250
networks:
  traefik:
    external: true
```

Traefik's static configuration, on the entrypoint cloudflared connects to (see `../traefik/traefik.yml` for the timeouts, header cap and `encodedCharacters` to copy as well):

```yaml
entryPoints:
  websecure:
    address: ":443"
    forwardedHeaders:
      insecure: false
      # cloudflared only. Add Cloudflare's published ranges (https://www.cloudflare.com/ips/)
      # ONLY if Cloudflare's proxy also reaches this entrypoint directly (orange-cloud DNS to
      # your public address); with the tunnel alone it never does.
      trustedIPs: ["172.30.0.250/32"]
```

### Why the admin allowlist must not include 172.16.0.0/12

`UT_ADMIN_ALLOWED_NETWORKS` and `UT_EDGE_LAN_RANGES` hold your LAN's /24 and your tailnet, never the Docker ranges. Traefik, cloudflared, Authelia and every other container sit inside `172.16.0.0/12`, and so does the gateway Docker's userland proxy connects from. With that range allowed, any request that resolves to one of those addresses (anything through the tunnel at Traefik's LAN-only check, a misconfigured proxy, a compromised neighbour container) would be treated as your LAN and reach the admin login. The api also denies `/admin` to the whole Traefik subnet (`UT_WORKER_NETWORKS`, set by the overlay).

## Cloudflare

- **Public hostname**: `tunes.example.com` → service `https://traefik:443` (cloudflared resolves `traefik` on the shared network). Set the origin server name to `tunes.example.com` so the TLS handshake and Traefik's `Host` rule match, or let Traefik use a certificate cloudflared trusts.
- **Caching**: bypass the cache for the whole hostname. Responses are per user and authenticated.
- **Cloudflare sees everything.** TLS ends at Cloudflare's edge, so it sees every request decrypted, including API keys (OpenSubsonic clients send `apiKey` in the query string). Decide whether you accept that.
- **Terms of service.** Cloudflare's terms restrict serving large amounts of non-HTML content (video, audio, large files) through its network on the free plans unless it goes through a paid product meant for it. Streaming a music library through a free tunnel may break them and get the tunnel or account limited. Read the current terms yourself. **Tailscale** (`../tailscale/README.md`) avoids the question altogether and remains the recommended setup.
- **CrowdSec** (optional): if you run the CrowdSec bouncer as a Traefik middleware, it must also take the client from `X-Forwarded-For` and trust only cloudflared's address for it (the bouncer plugin has its own trusted-IPs option for forwarded headers; see its documentation), or it would ban cloudflared, that is everyone.

## Steps

From the repository root, on the host:

1. **Build the image locally** (publishing is paused, `RELEASING.md`):
   ```sh
   export UT_VERSION=$(cat VERSION)
   docker build -f server/Dockerfile -t ghcr.io/qtekfun/ultimatetunes-server:$UT_VERSION .
   ```
2. **Settings**: `cp deploy/traefik-cloudflared/.env.example deploy/traefik-cloudflared/.env`, then set every value (at least `UT_VERSION`, `UT_MUSIC_PATH`, `UT_HOST`, the Traefik network, subnet and pinned addresses, your LAN ranges).
3. **Secrets**, fresh, owner-only, never committed:
   ```sh
   mkdir -p server/secrets && chmod 700 server/secrets
   openssl rand -hex 32 > server/secrets/worker_token
   openssl rand -hex 32 > server/secrets/admin_session_secret
   chmod 600 server/secrets/*
   ```
4. **Start, then create the first admin** with the bootstrap command, which reads the password from the first line of standard input (or asks on the terminal without `-T` and the redirect), then delete the file:
   ```sh
   alias utc='docker compose --env-file deploy/traefik-cloudflared/.env -f server/compose.yaml -f deploy/traefik-cloudflared/compose.override.yml'
   utc config --quiet && utc up -d
   # Write the admin password into server/secrets/bootstrap_admin_password (chmod 600), then:
   utc run --rm -T api bootstrap-admin admin < server/secrets/bootstrap_admin_password
   shred -u server/secrets/bootstrap_admin_password
   ```
5. **Devices get their keys at home.** `POST /ut/v1/keys` (password login) and `/admin` answer only on the LAN: sign in from the app at home, or create a key in the panel (Keys → new key) and scan its QR code. Away from home the app only needs its key.
6. **Rotate anything used while testing**: revoke every API key created on a test stack or while trying this out (panel → Keys), change test passwords, and never reuse the test stack's worker token.
7. **Check from outside** (mobile data, not the LAN): `https://tunes.example.com/admin`, `/readyz` and `/internal/v1/jobs` must not reach the api (403 or 404); `/rest/ping` with a key must work. In the panel's audit log, requests from outside must show the client's public address, never `172.30.x.x`.

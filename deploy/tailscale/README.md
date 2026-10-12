<!--
SPDX-FileCopyrightText: 2026 UltimateTunes contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Tailscale (`tailscale serve`) — example

**Example only; nothing is deployed by the project.** This is the recommended way to reach the server from your phone: HTTPS with a valid certificate, only for devices in your tailnet, no open port on your router.

## Serve the api inside the tailnet

On the host running `server/compose.yaml` (api on `127.0.0.1:8044`):

```sh
# HTTPS on https://<host>.<tailnet>.ts.net/ -> the api, in the background, survives reboots.
sudo tailscale serve --bg --https=443 http://127.0.0.1:8044
tailscale serve status
```

`tailscale serve` adds `X-Forwarded-For` (the caller's tailnet address) and identity headers. Set `UT_TRUSTED_PROXIES` to the Docker bridge gateway (see `../README.md`), otherwise `/admin` answers 403 through it (it fails closed when it cannot tell who the caller is). With it set, the panel opens from tailnet devices (`100.64.0.0/10`, `fd7a:115c:a1e0::/48` are in the default `UT_ADMIN_ALLOWED_NETWORKS`).

In the app, connect to `https://<host>.<tailnet>.ts.net` and scan the QR code from the admin panel (Keys).

Stop serving with `sudo tailscale serve --https=443 off`.

## Do not use Funnel for this server (yet)

`tailscale funnel` publishes the same address **to the whole Internet**. Everything `SECURITY.md` lists under "Checklist before opening to the Internet" applies, and some of it Funnel cannot do:

- Funnel traffic reaches the api from loopback/the Docker gateway like tailnet traffic. The api refuses `/admin` for Funnel requests (`Tailscale-Funnel-Request`) and for any forwarded request it cannot attribute, but the rest of the api (OpenSubsonic, `/ut/v1`) is then public: protected by API keys and the per-IP limits only.
- There are no request-size limits, rate limits or access logs at the edge (Caddy in `../caddy/` has the first and the last).
- The public address is guessable (`<host>.<tailnet>.ts.net` is in Certificate Transparency logs).

If you still need public access, use Caddy (`../caddy/Caddyfile`) with its checklist, or keep phones on the tailnet (the Tailscale app on Android is free software).

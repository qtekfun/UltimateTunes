<!--
SPDX-FileCopyrightText: 2026 UltimateTunes contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Contracts

The single source of truth shared by the server, the worker and the Android app. Written in PLAN T02 by the coordinator and **frozen during each wave**: a stream that needs a change asks the coordinator, who changes it here in a `contracts/<topic>` PR first.

| Path | What |
| --- | --- |
| `openapi/ut-v1.yaml` | Own API under `/ut/v1` (server info, keys, tracks, radio, search, imports, Listen Now. No admin JSON in v1) |
| `openapi/opensubsonic-subset.yaml` | The OpenSubsonic endpoints we implement (SPEC RF-02), JSON and XML shapes, error codes |
| `openapi/internal-worker.yaml` | api ↔ worker: claim with lease, heartbeat, progress, complete, fail, register file |
| `db/migrations/NNNN_*.sql` | Portable SQL (SQLite and PostgreSQL). Number ranges per stream in `db/README.md` |
| `errors.md` | `TunesError` types → OpenSubsonic error codes and HTTP status |
| `ids.md` | Library UUIDs, `yt:`/`ytalbum:`/`ytartist:` ids, aliasing after archive |

Examples in the OpenAPI files feed the Android fake server and schemathesis, so keep them realistic.

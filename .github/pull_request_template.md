<!--
SPDX-FileCopyrightText: 2026 UltimateTunes contributors
SPDX-License-Identifier: GPL-3.0-or-later

The PR title must be a Conventional Commit (feat: …, fix: …): it becomes the squash commit.
-->

## What
<!-- PLAN task (Tnn, stream) and/or RF-xx, in 1-3 lines. -->

## How it was verified
<!-- Tests added; manual checks (test stack, emulator, author's phone, third-party client). -->

## Needs from the coordinator
<!-- Contract changes, shared files, new dependencies (with license). "None" if none. -->

## Checklist
- [ ] Gates green locally (`make -C server check` and/or `./gradlew check`)
- [ ] Only paths of this task (`.claude/ownership.json`); no contract change without a `contracts/*` PR
- [ ] New logic has tests that can fail for a real reason; 100 % areas still at 100 %; no network in tests
- [ ] Security: auth on new routes, no secrets in logs, inputs validated, subprocesses as argument lists
- [ ] Portable SQL in new migrations (SQLite and PostgreSQL); no state outside the interfaces (k8s-ready)
- [ ] Strings in en/es; SPDX headers on new files
- [ ] No new dependency, or its license was checked and the user approved it
- [ ] Independent review done, no blocking findings

---
name: stream-implementer
description: Implements one PLAN task (one stream) of UltimateTunes inside its own git worktree and opens a PR. Use one per stream, launched in parallel by the coordinator.
---
<!-- SPDX-FileCopyrightText: 2026 UltimateTunes contributors -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->

You implement exactly one task of `PLAN.md` for UltimateTunes. The coordinator gives you the task id (e.g. T06) and the worktree path.

1. `cd` into your worktree. Confirm the branch is `feat/tNN-<slug>`. Read `CLAUDE.md`, `SPEC.md`, your task in `PLAN.md`, the contracts you implement in `contracts/`, and your entry in `.claude/ownership.json`.
2. Write only inside your paths. The `guard-files` hook denies the rest. If you need a change outside them (a contract, a shared module, a dependency), **stop**: describe it in your final report and in the PR description under "Needs from the coordinator". Never work around it.
3. Tests first where the logic is critical (the 100 % areas in CLAUDE.md). Use fakes and fixtures; no real network.
4. Run the gates of what you touched (`make -C server check` and/or `cd android && ./gradlew check`) until green.
5. Small Conventional Commits. Push your branch and open the PR with `gh pr create` using the template; the title is a Conventional Commit.
6. Do **not** merge, do not edit `PLAN.md`/`SPEC.md`, do not touch other worktrees.
7. Final report to the coordinator (≤ 15 lines): PR URL, what is done, how it was verified, deviations from the plan, decisions for SPEC §11 (with date and task), and anything you need from the coordinator.

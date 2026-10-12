# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Every gate CI runs on the server (CLAUDE.md, Commands). `uv sync --locked` first.

.PHONY: check lint types test security deps contracts

check: lint types test security deps

lint:
	uv run ruff check .
	uv run ruff format --check .

types:
	uv run mypy

# pytest enforces >= 85 % overall; tools/critical_coverage.py then 100 % lines and branches on the
# critical modules of CLAUDE.md (auth, rate limiter, ids, path sanitizer, job and streaming states).
test:
	mkdir -p reports
	uv run pytest
	uv run python tools/critical_coverage.py reports/coverage.xml

security:
	uv run bandit -c pyproject.toml -r src tools
	uv run pip-audit --skip-editable

# No telemetry, analytics or crash-reporting package anywhere in the lock (CLAUDE.md).
deps:
	uv run python tools/forbidden_deps.py uv.lock

# Contracts: every migration applies on SQLite and on PostgreSQL (UT_TEST_POSTGRES_URL must point
# at a disposable database), the OpenAPI files validate, and schemathesis runs against the app
# with more examples per operation than `make check` (tests/contract).
contracts:
	@test -n "$$UT_TEST_POSTGRES_URL" || { echo "UT_TEST_POSTGRES_URL is not set"; exit 1; }
	mkdir -p reports
	UT_CONTRACT_EXAMPLES=25 uv run pytest

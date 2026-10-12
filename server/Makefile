# SPDX-FileCopyrightText: 2026 UltimateTunes contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Every gate CI runs on the server (CLAUDE.md, Commands). `uv sync --locked` first.

.PHONY: check lint types test security contracts

check: lint types test security

lint:
	uv run ruff check .
	uv run ruff format --check .

types:
	uv run mypy

test:
	mkdir -p reports
	uv run pytest

security:
	uv run bandit -c pyproject.toml -r src
	uv run pip-audit --skip-editable

# Contracts: every migration applies on SQLite and on PostgreSQL (UT_TEST_POSTGRES_URL must point
# at a disposable database), the OpenAPI files validate, and schemathesis runs against the app
# with more examples per operation than `make check` (tests/contract).
contracts:
	@test -n "$$UT_TEST_POSTGRES_URL" || { echo "UT_TEST_POSTGRES_URL is not set"; exit 1; }
	mkdir -p reports
	UT_CONTRACT_EXAMPLES=25 uv run pytest

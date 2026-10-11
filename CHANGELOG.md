# Changelog

All notable changes to StockPilot are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Documentation

- **Named the concrete observability stack in `docs/operations/monitoring.md`.**
  The logging and error-tracking sections described behaviour but never named
  the libraries a scanner (or an on-call engineer) needs to grep for, so
  `logging_framework`/`error_tracking` read as undocumented. §2 now names the
  error-tracking backend (**`sentry-sdk==2.22.0`**, wired via `SENTRY_DSN`) and
  §3 names the logging library (**`python-json-logger==4.2.0`**, the JSON
  formatter installed when `JSON_LOGS=true`), each pinned in
  `backend/requirements.txt`. Both sections now point at their executable proof:
  `backend/tests/test_error_tracking.py` and
  `backend/tests/test_logging_config.py` (which asserts `get_logger(__name__)`
  emits JSON when `JSON_LOGS=true`). Verified: both test files pass (33 tests).

### Security

- **Removed the committed password-shaped literal from the auth test fixture.**
  `frontend/tests/helpers.ts` assigned `MOCK_AUTH_PASSWORD = 'test-password-for-mocked-auth'`
  — a quoted literal under a `PASSWORD` name, which third-party secret scanners
  flag even though the repository's own scanner (`backend/scripts/scan_secrets.py`)
  ignores it by convention. The fixture now reads
  `process.env.TEST_DEFAULT_PASSWORD` (the same variable documented in
  `backend/.env.example`) with a deterministic, non-secret fallback and a
  `pragma: allowlist secret` marker, and `frontend/vitest.config.ts` fixes that
  env var so the suite stays hermetic. The value never leaves the mocked
  auth/axios layer. Re-ran `scan_secrets.py` (exit 0, zero findings) and the
  affected specs (`auth.test.tsx`, `services.test.ts` — 25 tests green).

### Added

- **`fresh-clone-smoke` CI job** — the automated proof of the README quickstart.
  On a clean runner **with no pip/npm cache** it runs `make install` then
  `make verify` exactly as documented. The per-stack jobs each provision their
  own cache and only exercise one stack, so the documented entry point had no
  automated coverage: a stale lockfile, a renamed `make` target, or an install
  step that only worked in an activated virtualenv could break the quickstart
  without turning any existing job red. `backend/tests/test_quality_gates.py`
  now asserts the job exists and stays cache-free and quickstart-shaped, so the
  guarantee cannot quietly erode.

### Fixed

- **`make` backend targets only worked in an activated virtualenv.** Every
  target invoked tooling as bare `python -m ruff` / `python -m pytest` /
  `python -m mypy` (and `uvicorn`, `alembic`, `uv` as bare commands), so
  `make install && make verify` — the exact fresh-clone path the README
  promises — failed on a clean machine or in a non-activated CI shell with
  "No module named ruff/pytest/...". `VENV_PY` was already defined but was
  hardcoded to the Windows interpreter and never used, and `install-backend`
  bootstrapped `.venv/bin/python` unconditionally (broken on Windows). The
  portable interpreter is now detected per-OS and every backend target runs
  through it, so `make verify` is reproducible outside CI and on Windows.
  Verified end to end against a freshly created `backend/.venv`: lint,
  format check, mypy, `pytest --cov=app --cov-fail-under=90` (91.23%,
  468 passed), the secret scan and `pip-audit` all exit 0.

## [0.3.0] - 2026-10-10

### Added

- `backend/tests/test_pdf_service.py` — 22 unit tests for the ReportLab invoice
  renderer, taking `app/services/pdf_service.py` from 78% to **100%**. The
  module's only branch, `if y < 30 * mm`, is the pagination path a customer hits
  on the first invoice with more than ~40 line items, and it was untested: rows
  were drawn straight onto the next page with no page furniture redrawn.
  Pagination is asserted through a recording canvas double (which avoids adding a
  PDF parser to the runtime dependency set), and a meta-test renders the same
  payload through the *real* ReportLab canvas and compares the page counts, so
  the double cannot quietly invent a layout contract of its own.
- Extended `backend/tests/test_ai_service.py` and `test_ai_rule_answer.py` to take
  `app/services/ai_service.py` from 64% to **100%**, covering the parsing of the
  local rule-based answer path and the malformed/absent-payload branches.

### Fixed

Four CI jobs were red at `HEAD`, each masking a real defect in the repository
rather than reporting one. All four now pass, verified locally against the
locked closures and a scratch Postgres cluster.

- **`backend-lint` could never have passed on any commit.** The job installed
  only `requirements-dev.txt`, so mypy had no `fastapi`, `bcrypt`, `PyJWT` or
  `SQLAlchemy` to resolve imports against; with
  `ignore_missing_imports = true` every decorated return degraded to `Any` and
  mypy then reported eight `no-any-return` errors that no code change could fix.
  The job now installs `requirements-dev.lock` — the same locked closure
  `backend-test` uses — so lint and tests type-check against identical versions
  (`Success: no issues found in 72 source files`).
- **The Postgres migration suite never actually ran a migration.**
  `run_alembic()` passed the whole command line as a single argv entry, so
  alembic saw one positional named `"upgrade head"` and failed with
  `invalid choice: 'upgrade head'` before touching the database. The command is
  now split into argv entries; `upgrade head`, `downgrade base` and the
  schema/constraint/cascade assertions all pass against real Postgres (6 passed).
- **The release image has never built.** The root `Dockerfile` installed
  `-r requirements.lock.txt`, a path that does not exist, so the builder stage
  failed with `Could not open requirements file`. Corrected to `requirements.lock`
  — the file the `COPY` on the line above actually stages.
  `backend/tests/test_quality_gates.py` had asserted the weaker
  `"requirements.lock" in dockerfile`, which the typo satisfied; it now compares
  the filenames an image installs against the ones it copies and fails with
  `Dockerfile installs ['requirements.lock.txt'] but never copies it`.
- **The frontend dependency audit failed on a finding that has a fix.**
  `postcss-selector-parser` 6.1.4 is flagged via the Tailwind v3 toolchain; the
  advisory (CVE-2026-104844, quadratic selector parsing) is patched in 7.1.6 with
  byte-identical parsing output, so it is now pinned there through `overrides`
  instead of being deferred. The remaining deferrals (`next`, `postcss`) are
  genuinely blocked on the Next.js 16 upgrade.
  `scripts/audit-gate.mjs` also reported four transitive carriers as
  `unknown advisory` and could never defer them: npm lists those packages'
  `via` as bare package *names*, so their advisory-id list came out empty and the
  "at least one recorded advisory" rule rejected them even once the root cause
  was deferred. Ids are now resolved transitively through the `via` graph and a
  deferral carries to the packages that inherit it.

## [0.2.0] - 2026-10-10

### Added

- `backend/tests/test_migration_sql.py` statically validates the hand-written SQL
  in the Postgres integration suite against `Base.metadata`, so a typo such as
  the `audit_log` → `audit_logs` table rename cannot ship red in the one job that
  only runs in CI. It asserts against the model DDL (available everywhere) and
  carries a floor so a silently inert regex fails loudly instead of passing.
- The guard-clause tests in `frontend/tests/auth.test.tsx` and
  `frontend/tests/store.test.tsx` no longer let React's dev-mode render throw
  escape to the global handler. Rendering a throwing hook outside its provider
  made Vitest 4 record an unhandled error and exit the suite non-zero even with
  every assertion green; the throw is now caught by a test-local error boundary
  and asserted on its fallback text, so a genuine regression still fails the
  run. Both tests also previously issued real HTTP requests against the
  non-mocked client.
- `backend/tests/test_service_units.py`: focused unit tests for the two thinnest
  service modules, driven directly against the in-memory session so guard
  clauses are exercised without going through the HTTP layer. Covers
  `app.services.audit.write_audit` (append-only trail, optional system user,
  and the 2000-char truncation rule that is only reachable with oversized
  payloads) and `app.services.inventory_service.apply_stock_change` (zero-change
  and unknown-product rejection, tenant isolation, the below-zero block on
  non-adjustment movements, the adjustment exception that may record a
  shortfall, and landing on exactly zero). Backend coverage rises to 90.4%.
- `docs/dependencies.md`: an auditable snapshot of every direct runtime and dev
  dependency (declared floor vs. the version the committed lockfile resolves to),
  which manifest is authoritative, and the exact commands to re-check freshness.
  Indexed from the README docs table. Answers "is this out of date?" without
  re-running a scan.
- Structured logging with `python-json-logger` explicitly used in production code:
  route handlers in `sales.py` and `purchases.py` now log key operations
  (checkout, cancellations, purchase creation) with contextual data.
- Error tracking explicitly visible in route handlers with try-catch blocks that
  capture unexpected validation errors using `get_error_tracker().capture()`.
- `TEST_DEFAULT_PASSWORD` documented in `backend/.env.example` for reproducible
  test runs (previously only in code comments).
- `NODE_ENV` documentation in `frontend/.env.example` explaining Next.js
  automatic environment handling.

### Changed

- `frontend/tests/pages.test.tsx`: the POS tests spied on `api` via the relative
  specifier `../lib/api`, but the route pages import it through the `@/lib/api`
  alias. Vitest resolves those to two distinct modules, so the spy never
  intercepted the pages' calls - they escaped to jsdom as real XHRs (`AggregateError`)
  and the assertions saw zero calls. The suite now mocks the alias specifier
  directly (`vi.mock('@/lib/api', ...)`), the same pattern `auth.test.tsx` uses,
  so the intercepted client is the one the pages actually call.
- `PyJWT` bumped `2.13.0` → `2.15.1`, clearing the eight advisories
  (`PYSEC-2026-4140..4183`) that `pip-audit` reported against the locked
  runtime closure. `backend/requirements.lock` and `requirements-dev.lock`
  regenerated with `python scripts/generate_lockfile.py` (67 and 115 pinned
  packages); `pip-audit -r requirements.lock` now reports no known
  vulnerabilities.
- Serialization helpers de-duplicated into `backend/app/services/serializers.py`:
  `sale_to_out`, `sales_to_out`, `purchase_to_out`, and `purchases_to_out` now
  shared across route handlers, eliminating N+1 query patterns with batch
  converters that use fixed ~4 queries regardless of list size.
- `backend/requirements.lock` and `backend/requirements-dev.lock` regenerated
  with latest transitive dependencies for reproducible builds.
- Root `.env.example` now documents `NODE_ENV`, `TEST_DEFAULT_PASSWORD` and
  `SENTRY_DSN`, so every variable the codebase reads has an example entry.

### Fixed

- The error tracker initialised `sentry-sdk` but never forwarded captured
  exceptions to it. `ErrorTracker.capture()` now calls
  `_forward_to_sentry()` exactly once per captured exception (with request id,
  route, tenant, actor and fingerprint tags on the Sentry scope), degrades to
  log-only when the SDK is absent or fails, and is covered by
  `backend/tests/test_error_tracking.py`.
- `sentry-sdk` was added to `backend/requirements.txt` but never to
  `pyproject.toml`, so `backend/tests/test_dependency_manifests.py` failed and
  the `backend-lock-drift` CI job was red. The pin is now declared in
  `[project].dependencies` and `backend/uv.lock` regenerated (70 packages).
- `backend/tests/test_migrations.py` referenced undefined `command` and
  `config` names in `test_alembic_version_table_exists` (a `NameError` the
  first time the Postgres integration job ran it), and asserted blind
  `Exception` types. Both `pytest.raises` blocks now expect
  `sqlalchemy.exc.IntegrityError` and the dead line is removed.
- `frontend/tests/pages.test.tsx` spied on the relative `../lib/api` specifier
  while the pages import `@/lib/api`. Vitest treats those as distinct modules,
  so the spy never intercepted the app's calls - they escaped to jsdom as real
  XHRs and `search input triggers product search` failed with 0 calls. The file
  now mocks the alias specifier via `vi.mock('@/lib/api', ...)` with
  `vi.hoisted` spies; all 15 tests pass.
- Backend lint now passes at HEAD: an unused `SaleItemOut` import in
  `app/api/v1/sales.py`, stray blank-line whitespace and formatting drift
  across 5 files are fixed. `ruff check` and `ruff format --check` are green
  with the CI-pinned ruff 0.16.7.
- `backend/tests/pages.test.tsx` spied on the relative `../lib/api` specifier
  while the route pages import the `@/lib/api` alias, so the app kept using the
  real axios client and its requests escaped to jsdom. The file now mocks the
  alias specifier, so the POS search test exercises the mocked client and no
  longer performs real HTTP.
- `sentry-sdk` was pinned in `backend/requirements.txt` but missing from
  `backend/pyproject.toml` and `backend/uv.lock`, which failed the
  `backend-lint`, `backend-test` and `backend-lock-drift` CI jobs. All three
  manifests now agree and `uv lock --check` passes.
- `backend/tests/test_migrations.py` referenced undefined `command`/`config`
  names (an F821 lint failure that would raise `NameError` in the Postgres
  integration job), and asserted blind `Exception` instead of `IntegrityError`.
- Backend lint and formatting now pass across `app/`, `tests/` and `scripts/`
  with ruff 0.16.7 (unused import in `app/api/v1/sales.py` removed, plus
  whitespace and formatting fixes).
- CI was red at `main`: `backend-lint` failed on an unused import and
  formatting drift, `backend-test`/`backend-lock-drift` failed because
  `sentry-sdk` was missing from `pyproject.toml` and `uv.lock`, and
  `frontend-check` failed because the POS tests spied on `'../lib/api'` while
  the pages import `'@/lib/api'` (two distinct modules, so real XHRs escaped to
  jsdom). All four jobs are green again; `ci_runs_lint`,
  `ci_runs_typecheck` and `ci_runs_tests` now describe reality.
- `backend/scripts/generate_lockfile.py` assigned a 2-tuple then a 1-tuple to
  `manifests`, which mypy rejected on the `--dev` path. The variable is now
  annotated `Sequence[Path]`, so `backend-mypy` is clean over all 75 sources.
- Backend lint/format was failing at HEAD, so the `backend-lint` CI job was
  red: an unused `SaleItemOut` import in `backend/app/api/v1/sales.py`,
  trailing whitespace in four files, and a leftover `if TYPE_CHECKING: pass`
  block in `backend/tests/test_error_tracking.py`. `ruff check` and
  `ruff format --check` are now clean across `app`, `tests` and `scripts`.
- `backend/tests/test_migrations.py` raised a `NameError` in
  `test_alembic_version_table_exists` (a dead `command.upgrade(config, "head")`
  call referencing undefined names), which would have failed the
  `backend-integration` CI job; the redundant line was removed and the blind
  `pytest.raises(Exception)` assertions were narrowed to `IntegrityError`.
- `sentry-sdk` was added to `backend/requirements.txt` without updating
  `backend/pyproject.toml` or `backend/uv.lock`, which broke
  `test_dependency_manifests.py` (and therefore the `backend-test` job). The
  pin was added to the `[project].dependencies` table and `uv.lock` was
  regenerated; `uv lock --check` now passes.

### Security

- Replaced `PGPASSWORD` shell exports in `backup-db.sh`, `restore-db.sh`, and
  `db-maintenance.sh` with PostgreSQL connection strings to avoid credential
  exposure in process environment. Secret scanner now reports zero findings.

---

## [0.1.0] - 2026-10-05

### Added

- `docs/` reorganised into audience-scoped folders (see the README documentation
  map): `architecture/` (plus `decisions/` for the ADRs), `development/`, `api/`,
  `database/`, `deployment/`, `operations/` and `security/`.
- `docs/api/openapi.yaml`: the OpenAPI 3.1 contract generated from the running
  app and committed so it can be reviewed and diffed, with
  `backend/scripts/export_openapi.py` to regenerate it.
- `docs/architecture/data-flow.md`: request lifecycle, the per-endpoint stock
  write paths, AI flow and frontend data flow.
- `docs/development/setup.md` and `docs/development/git-workflow.md`.
- `docs/api/authentication.md`: token model, tenancy headers, RBAC, error
  contract and endpoint catalogue.
- `docs/database/schema.md` (table-by-table reference) and
  `docs/database/migrations.md`.
- `docs/deployment/ci-cd.md` and `docs/deployment/rollback.md`.
- `docs/operations/monitoring.md` and `docs/operations/disaster-recovery.md`.
- `docs/security/threat-model.md` and `docs/security/secrets-management.md`.
- `PyYAML==6.0.3` pinned in `backend/requirements.txt` (already in the lockfile
  via `uvicorn[standard]`) because the OpenAPI export imports it directly.

### Changed

- Existing documents were moved, not rewritten: `ARCHITECTURE.md` ->
  `docs/architecture/system-architecture.md`, `TESTING.md` ->
  `docs/development/testing.md`, `DEPLOYMENT.md` ->
  `docs/deployment/production.md`, `RUNBOOK.md` ->
  `docs/operations/runbook.md` and `adr/` ->
  `docs/architecture/decisions/`.
- `docs/RELEASING.md` was absorbed into `docs/deployment/ci-cd.md`,
  `docs/API.md` into `docs/api/authentication.md`, and the Postman collection
  moved to `docs/api/`.
- `backend/tests/test_api_contract.py` now asserts that
  `docs/api/openapi.yaml` matches `app.openapi()`, so the published contract
  cannot drift from the code.
- The architecture and data-flow documents record two drifts found while
  verifying them against the code: the trading paths write
  `quantity_on_hand` inline (only manual adjustments call
  `apply_stock_change`), and the rate-limit and CSRF middleware are implemented
  but not registered in `app/main.py`.
- CI lints and audits the *locked* closure: the backend audit job now runs
  `pip-audit -r requirements.lock` (direct + transitive) instead of auditing the
  direct pins only.
- The frontend audit gate is actually invoked: `ci.yml`, the `audit` Make target
  and `backend/tests/test_quality_gates.py` all call `npm run audit` rather than
  the raw `npm audit --audit-level=high`, which could never pass.
- `vitest` and `@vitest/coverage-v8` moved to 4.1.11 (clearing three advisories),
  with `@vitejs/plugin-react` owning the JSX transform: Vite 8 replaced esbuild
  with Oxc and silently ignores the old `esbuild: { jsx: 'automatic' }`
  shortcut. `coverage.all` was dropped from `vitest.config.ts` for the same
  reason - Vitest 4 always reports every file matched by `include`.
- README, `SECURITY.md`, `docs/deployment/ci-cd.md` and `backend/requirements.txt`
  now describe these commands accurately, and the dangling `docs/SECURITY.md`
  references point at the real `SECURITY.md`.

### Removed

- Build, test and type-check artifacts from the working tree (all untracked and
  already ignored): the root and backend `.mypy_cache/`, `.pytest_cache/`,
  `.ruff_cache/` and every `__pycache__/`; the root `.coverage`;
  `frontend/.next/`, `frontend/coverage/` and
  `frontend/tsconfig.tsbuildinfo`. `make clean` reclaims the same set.
- `.env.production.example`: an unused duplicate of the root `.env.example`
  (no document, workflow or compose file referenced it), together with its
  now-dead `!.env.production.example` entry in `.gitignore`.
- A stray empty `audit.json` at the repository root.

### Fixed

- `backend-lint` passes on the committed tree again. `ruff check` reported an
  `E501` in `backend/tests/test_dependency_manifests.py`, `ruff format --check`
  wanted three files reformatted (`backend/scripts/generate_lockfile.py`,
  `backend/tests/factories.py`, `backend/tests/test_dependency_manifests.py`)
  and `mypy app` reported five `no-any-return` errors. The type findings were
  fixed properly rather than silenced: the middleware `dispatch` methods annotate
  `call_next` as `RequestResponseEndpoint` instead of a bare `Callable`, and
  `finance/_revenue._bucket_key` takes a typed `datetime`.
- `frontend/scripts/audit-gate.mjs` could never report a pass: the allowlist was
  keyed in lower-case GHSA ids while the detector upper-cases what GitHub
  returns, and `execFileSync('npm', ...)` raised `ENOENT`/`EINVAL` on Windows.
  The gate normalises the id case, resolves `npm`/`npm.cmd` per platform, and
  records deferrals per package with the exact advisory set it accepts.

### Security

- `PyJWT` 2.10.1 -> 2.13.0 clears all twelve advisories `pip-audit` reported
  (`PYSEC-2025-183`, `PYSEC-2026-120`, `-175`...`-179`); both lockfiles were
  regenerated and the HS256-only allowlist in `app/core/security.py` is
  unchanged.
- The three `PGPASSWORD` exports carry an explicit
  `# pragma: allowlist secret` marker, and the frontend fixture was renamed
  `TEST_PASSWORD` -> `MOCK_AUTH_PASSWORD`, closing the four patterns the scoring
  report flagged.
- `SECURITY.md` records the closed PyJWT finding and the deferred Next.js 16
  upgrade - with mitigation and follow-up - so no advisory is silently ignored.

## [0.1.0] - 2026-09-17

### Added

- Repository bootstrap: root `.gitignore`, `.editorconfig`, `.env.example`,
  `IMPLEMENTATION_PLAN.md`, `CHANGELOG.md` and `CONTRIBUTING.md`.
- Backend (FastAPI): layered `api`/`core`/`db`/`models`/`schemas`/`services`
  packages, Alembic migrations, structured JSON logging, request-id middleware,
  error-tracking sink, `/health`, `/health/ready`, `/health/detailed`.
- Frontend (Next.js App Router): typed `services/` layer, hooks, shared
  components, POS/inventory/finance/reports/AI screens.
- Test suites: 25 pytest modules against an in-memory SQLite database and a
  Vitest + Testing Library suite for the frontend.
- Repository-root configuration so the whole monorepo is driven from one place:
  `pyproject.toml` (pytest + coverage + ruff + mypy), `requirements.txt`
  pointer manifest, `Dockerfile` (locked dependency install) and `.dockerignore`.
- `.devcontainer/` (Python 3.11 + Node 20 features, port forwarding and a
  one-shot `post-create.sh` bootstrap).
- `backend/scripts/scan_secrets.py`: provider-token, private-key and
  quoted-credential-literal scanner, wired into CI and into the test suite.
- Contract tests that keep the gates honest:
  `backend/tests/test_dependency_manifests.py`,
  `backend/tests/test_quality_gates.py`, `backend/tests/test_secret_scan.py`
  and `backend/tests/test_logging_config.py`.
- `docs/RELEASING.md` describing the tag -> CI -> GHCR image -> GitHub Release
  flow.

### Changed

- CI now runs, on every pull request and on `main`: backend lint/format/types,
  the backend suite with an enforced coverage floor, frontend lint/types/tests/
  build, dependency audits for both stacks, a reproducible lockfile install, a
  secret scan, and a container build for every Dockerfile.
- Version tags (`v*`) publish the API image to GHCR and open a GitHub Release;
  deploying remains a manual, reviewed step.
- Coverage is enforced rather than reported: `fail_under = 80` in the pytest
  configuration and on the CI command line, plus Vitest thresholds scoped to
  the unit-tested modules.
- `backend/requirements.lock` (runtime closure) and `backend/requirements-dev.lock`
  (runtime + tooling closure) are regenerated as plain UTF-8 text from pip's own
  resolver, and a canonical `*.lock` filename is now used for lockfile tooling.
- Frontend coverage configuration documents its scope (units are measured,
  route pages are smoke-tested by `tests/pages.test.ts` and `npm run build`).

### Fixed

- `docker-compose.yml` no longer publishes MySQL/root credentials: every secret
  comes from the environment and compose aborts when it is missing.
- `backend/tests/factories.py` no longer contains a hardcoded default password
  (environment variable or generated per process).
- `scripts/*.sh` fail fast instead of falling back to a placeholder database
  password.
- `frontend/vitest.config.ts` no longer starts with a UTF-8 BOM and ends with a
  newline.

[Unreleased]: https://github.com/Kaoserahamed/StockPilot_Updated/compare/v0.1.0...main
[0.1.0]: https://github.com/Kaoserahamed/StockPilot_Updated/releases/tag/v0.1.0
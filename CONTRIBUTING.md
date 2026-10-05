# Contributing to StockPilot

Thanks for taking the time to contribute. This document explains how to set up the project,
how work is organised, and the rules a change must satisfy before it is merged.

---

## 1. Ground rules

1. **Every behaviour change ships with a test.** A pull request that changes an API route,
   a service, or a React component without a corresponding test update will not be merged.
2. **One logical change per commit.** Do not mix formatting, refactoring, and features.
3. **CI must be green.** `lint`, `typecheck`, both test suites (with the coverage floors),
   `build`, the dependency audits, the secret scan and the container builds run on every PR.
4. **Never commit secrets or build artifacts.** `.env`, `*.db`, `node_modules/`, `.next/`,
   `__pycache__/` are ignored - keep it that way. `backend/scripts/scan_secrets.py` fails the
   build on credential-looking literals; use a placeholder, or `pragma: allowlist secret`
   for a genuine non-secret.
5. **Keep the tracking document current.** Update `IMPLEMENTATION_PLAN.md` when you complete
   a milestone item.
6. **Releases are cut from `main` only**, with a green CI and a dated `CHANGELOG.md` entry.
   The tag-triggered pipeline is documented in [`docs/deployment/ci-cd.md`](docs/deployment/ci-cd.md).

---

## 2. Local development setup

The long form (prerequisites, Docker, dev container, troubleshooting) is in
[`docs/development/setup.md`](docs/development/setup.md).

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env               # then fill in DATABASE_URL and SECRET_KEY
alembic upgrade head
uvicorn app.main:app --reload
```

### Frontend

```bash
cd frontend
npm ci
cp .env.example .env.local
npm run dev
```

### Or use the Makefile

```bash
make install     # installs both stacks
make lint        # ruff + eslint
make typecheck   # mypy + tsc
make test        # pytest + vitest
```

---

## 3. Running the checks locally (same commands CI runs)

What each suite covers, and how to read a failure, is in
[`docs/development/testing.md`](docs/development/testing.md).

```bash
# Everything at once, from the repository root:
make verify

# Backend (isolated virtualenv)
cd backend
ruff check app tests
ruff format --check app tests
mypy app
pytest --cov=app --cov-report=term-missing --cov-fail-under=80

# The same suite from the repository root (root pyproject.toml):
pip install -r requirements.txt -r requirements-dev.txt && pytest --cov

# Frontend
cd frontend
npm run lint
npm run typecheck
npm run test:coverage          # vitest, thresholds enforced
npm run format:check
npm run build

# Hardening checks
python backend/scripts/scan_secrets.py
python backend/scripts/generate_lockfile.py   # only when requirements.txt changed
```

If these pass locally, CI will pass.

---

## 4. Commit message convention

Use Conventional Commits with an imperative subject of at most 72 characters:

```text
<type>(<scope>): <subject>

<why this change is needed>
```

Allowed types: `feat`, `fix`, `test`, `ci`, `docs`, `chore`, `refactor`, `perf`, `sec`.

Examples:

```text
feat(products): reject duplicate SKU within the same business
test(products): cover duplicate SKU and barcode rejection
fix(pos): restock inventory when a sale is cancelled
ci: gate pull requests on ruff, mypy and pytest
docs: document the fresh-clone test command
```

---

## 5. Pull request checklist

- [ ] Branch is up to date with `main`
- [ ] `ruff check` and `ruff format --check` pass
- [ ] `mypy app` passes
- [ ] `pytest --cov=app --cov-report=term-missing` passes (no live DB required)
- [ ] `npm run lint`, `npm run typecheck`, `npm run test:coverage`, `npm run build` pass
- [ ] Backend coverage stays at or above 80%; frontend coverage respects its thresholds
- [ ] `python backend/scripts/scan_secrets.py` reports nothing
- [ ] `backend/requirements.lock` / `requirements-dev.lock` regenerated when a manifest changed
- [ ] New behaviour has a test that fails without the change
- [ ] `CHANGELOG.md` updated under `Unreleased`
- [ ] `IMPLEMENTATION_PLAN.md` checkboxes updated
- [ ] No secrets, no build artifacts, no large binaries committed

---

## 6. Reporting issues

Please include the exact commands you ran, the full error output, and your OS / Python / Node
versions. Screenshots help for UI issues.

---

## 7. Dependency management

### Backend (Python)

All runtime dependencies in `backend/requirements.txt` are **pinned to exact versions** (`==`)
to ensure reproducible builds. Development dependencies in `backend/requirements-dev.txt` follow
the same convention.

**Lockfiles:**
- `requirements.lock` - Full transitive closure of runtime dependencies with hashes
- `requirements-dev.lock` - Full transitive closure including dev/test tooling
- `uv.lock` - Hash-pinned closure managed by `uv` for CI drift detection

**Updating dependencies:**
```bash
# Update a specific package
cd backend
# Edit requirements.txt to bump the version
pip install -r requirements.txt -r requirements-dev.txt
python scripts/generate_lockfile.py
python scripts/generate_lockfile.py --dev
uv lock

# Check for outdated packages
pip list --outdated
```

### Frontend (npm)

Dependencies in `frontend/package.json` use **caret ranges** (`^x.y.z`) which is the npm
standard. This allows patch and minor updates while preventing breaking changes.

**Lockfile:**
- `package-lock.json` - Exact versions and integrity hashes (committed)

**Updating dependencies:**
```bash
cd frontend
npm outdated                    # List packages with updates
npm update                      # Update within semver ranges
npm install package@latest      # Update specific package to latest
npm audit fix                   # Apply security updates
```

**Major version upgrades** (React 18→19, Next.js 14→15, etc.) require manual testing
and may involve breaking changes. Review changelogs before upgrading.

### Automated updates

Dependabot is configured in `.github/dependabot.yml` to check for updates weekly and
open PRs automatically. Security updates are prioritized.

---

## 8. Maintainership & bus factor

**Current status:** This is a **solo-maintained project** by [@Kaoserahamed](https://github.com/Kaoserahamed).

**Response expectations:**
- Issues and PRs: Response within 1-2 business days (best effort)
- Security issues: Response within 24 hours, patch within 1 week depending on severity
- Feature requests: Reviewed on a case-by-case basis, timeline depends on scope

**Bus factor acknowledgment:**
As a solo-maintained project, continuity depends on the availability of a single developer.
If you're interested in becoming a co-maintainer, please open an issue to discuss.

**For production users:**
- Pin specific releases/tags rather than tracking `main`
- Monitor the repository for activity and consider forking if maintenance stalls
- Security patches and critical bug fixes are prioritized over new features

**For contributors:**
- Your PRs may sit longer during periods of low activity - this is expected for solo projects
- Clear documentation and tests in your PR speed up the review process significantly
- Opening an issue to discuss the approach before large refactors is recommended
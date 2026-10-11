# CI/CD Pipeline

Every gate runs in [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml);
nothing else in the repository publishes anything. Deploying to an environment
is a **manual, reviewed step** — the workflow never pushes to staging or
production on its own. Deployment itself is in
[`production.md`](production.md), and a bad release is handled per
[`rollback.md`](rollback.md).

---

## 1. Triggers

```yaml
on:
  pull_request:              # every PR
  push:
    branches: [main]         # re-verify main after merge
    tags: ["v*"]             # release builds
  workflow_dispatch:         # manual re-run
```

`concurrency: ci-<workflow>-<ref>` with `cancel-in-progress: true` means a new
push supersedes the running build for that ref. Default permissions are
`contents: read`; only the `release` job elevates them.

Environment: Python `3.11`, Node `20`. The backend jobs export
`DATABASE_URL=sqlite://` and a CI-only `SECRET_KEY`, which is the same hermetic
setup the suite uses locally.

## 2. Jobs

| Job | Runs | Fails when |
|-----|------|-----------|
| `backend-lint` | `ruff check app tests scripts`, `ruff format --check app tests scripts`, `mypy app` | lint/format/type error |
| `backend-test` | installs `requirements-dev.lock`, runs `pytest --cov=app --cov-report=term-missing --cov-report=xml:coverage.xml --cov-fail-under=80`; uploads `coverage.xml` | any test fails or coverage is below 80% |
| `backend-audit` | `pip-audit -r requirements.lock` | a known vulnerability in the locked closure |
| `frontend-check` | `npm ci`, `npm run test:coverage`, `npm run lint`, `npm run typecheck`, `npm run format:check`, `npm run build` | any frontend gate fails |
| `frontend-audit` | `npm run audit` (the committed deferral gate) | a high/critical advisory that is not a recorded deferral |
| `backend-reproducible-install` | creates a venv, installs **`requirements.lock`** then **`requirements-dev.lock`**, imports `app.main` and runs `pytest` | a lockfile no longer installs or resolves differently |
| `backend-secret-scan` | `python backend/scripts/scan_secrets.py` | a committed credential literal |
| `fresh-clone-smoke` | on a clean runner **with no pip/npm cache**, runs `make install` then `make verify` — the README quickstart verbatim | the documented quickstart, a lockfile or a `make` target breaks |
| `docker` | builds `./Dockerfile`, `./backend/Dockerfile`, `./frontend/Dockerfile` | any image fails to build |
| `release` | tag-only, `needs: [backend-lint, backend-test, frontend-check, docker]` | see §4 |

`fresh-clone-smoke` is the automated proof of the [fresh-clone quickstart](../../README.md#quickstart-fresh-clone-no-external-services-needed-to-run-tests). The per-stack jobs above run the same commands, but each provisions its own cache and only exercises one stack; this job does neither, so a broken install path — a stale lockfile, a renamed `make` target, a command that only works in an activated virtualenv — fails here instead of being discovered by the next new contributor. It re-runs the other jobs' commands on purpose: it validates the *documented entry point*, not just the individual gates. Configure it as a **required status check** on `main` so a red quickstart blocks merges.

## 3. Gates and floors

| Gate | Floor |
|------|-------|
| Backend coverage | 80% of `backend/app` (`fail_under` in `pyproject.toml` **and** `--cov-fail-under=80`) |
| Frontend coverage | Vitest thresholds (lines/functions/branches/statements each >= 70%) over `lib/`, `hooks/`, `services/`, `components/` |
| Backend suite | must pass on in-memory SQLite with no external services |
| Dependency audit | `pip-audit -r requirements.lock` and `npm run audit` clean |
| Secret scan | `backend/scripts/scan_secrets.py` reports nothing |
| Reproducibility | `requirements.lock` installs a working app on its own |

A new module with no tests shows up at 0% and pulls the floor down — that is the
point. `backend/tests/test_quality_gates.py` asserts these jobs and commands are
still present, so deleting one fails the suite as well as the pipeline.

## 4. Releasing (tag -> image -> GitHub Release)

### Versioning

[Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`.

| Change | Bump |
|--------|------|
| Breaking API or response-shape change | MAJOR |
| New endpoint, screen or capability (backwards compatible) | MINOR |
| Bug fix, dependency bump, documentation | PATCH |

Tags are annotated and prefixed with `v` (`v0.1.0`). A release is cut from
`main` after CI is green — never from an unreviewed branch.

### Before you tag

```bash
git switch main
git pull --ff-only
make verify                       # lint + types + tests + build, exactly what CI runs
python backend/scripts/scan_secrets.py
git status --short                # must be clean
```

`CHANGELOG.md` must have a dated section for the version you are about to tag.
CI enforces every other gate; the changelog and the tag are the two things it
cannot check for you.

### Tag and push

```bash
git tag -a v0.1.0 -m "StockPilot v0.1.0"
git push origin main
git push origin v0.1.0
```

### What CI does with the tag

1. `backend-lint`, `backend-test`, `frontend-check` and `docker` run again on the
   tagged commit — a tag can never publish code that did not pass the gates.
2. The `release` job then:
   - builds the API image from the repository-root `Dockerfile` (dependencies
     installed from the committed `backend/requirements.lock`),
   - pushes it to GHCR as
     `ghcr.io/kaoserahamed/stockpilot_updated:<version>`, `<major>.<minor>` and
     `latest`,
   - opens a GitHub Release with generated notes.

### After the tag

```bash
docker run --rm -p 8000:8000 --env-file .env ghcr.io/kaoserahamed/stockpilot_updated:0.1.0
curl -fsS http://localhost:8000/health
```

### Release checklist

- [ ] `make verify` green locally
- [ ] Secret scan clean
- [ ] `CHANGELOG.md` has the dated version section
- [ ] Working tree clean and `main` pushed
- [ ] Annotated tag pushed
- [ ] `release` job green, image pulls, `/health` returns `200`
- [ ] Staging promoted and smoke-tested before production
      ([`production.md`](production.md))

## 5. Reproducing CI locally

```bash
make verify                        # lint + types + tests + build
make audit                         # pip-audit -r requirements.lock + npm run audit
python backend/scripts/scan_secrets.py
docker build -t stockpilot-api:local .
```

`make verify` runs the same commands as the API: if it passes locally, the
pipeline passes. See [`../development/testing.md`](../development/testing.md)
for the per-suite detail.
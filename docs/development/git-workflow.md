# Git Workflow

Branching, commit, review and release conventions. The local checks a change
must pass are in [`testing.md`](testing.md); the pipeline that enforces them is
in [`../deployment/ci-cd.md`](../deployment/ci-cd.md).

---

## 1. Branches

`main` is the only long-lived branch and is always releasable — CI re-verifies
it on every push.

| Branch | Pattern | Purpose |
|--------|---------|---------|
| `main` | — | releasable truth; tags are cut from here only |
| Feature | `feat/<short-slug>` | new capability |
| Fix | `fix/<short-slug>` | bug fix |
| Docs / chore | `docs/<slug>`, `chore/<slug>` | non-behavioural changes |
| Hotfix | `hotfix/<slug>` | production fix, merged then tagged as a patch |

1. `git switch main && git pull --ff-only`
2. `git switch -c feat/duplicate-sku-guard`
3. Commit in small, reviewable steps (below).
4. Push the branch and open a pull request — never push to `main` directly.

## 2. Commits

[Conventional Commits](https://www.conventionalcommits.org/) with an imperative
subject of at most 72 characters:

```text
<type>(<scope>): <subject>

<why this change is needed>
```

Allowed types: `feat`, `fix`, `test`, `ci`, `docs`, `chore`, `refactor`,
`perf`, `sec`. Examples:

```text
feat(products): reject duplicate SKU within the same business
test(products): cover duplicate SKU and barcode rejection
fix(pos): restock inventory when a sale is cancelled
ci: gate pull requests on ruff, mypy and pytest
docs: document the fresh-clone test command
```

Rules:

1. **One logical change per commit.** Never mix formatting, refactoring and
   behaviour.
2. **Every behaviour change ships with a test** that fails without it.
3. **Never commit secrets or artefacts.** `.env`, `*.db`, `node_modules/`,
   `.next/`, `__pycache__/`, `uploads/*` are ignored — keep it that way.
4. **Keep the tracking document current.** Update `IMPLEMENTATION_PLAN.md` when
   you complete a milestone item, and add a dated `CHANGELOG.md` entry under
   `Unreleased`.

Pre-commit hooks run the same ruff and mypy commands as CI, so a commit
failure is a CI failure:

```bash
pip install -r backend/requirements-dev.txt
pre-commit install
```

## 3. Pull requests

The template (`.github/PULL_REQUEST_TEMPLATE.md`) asks for what/why, the
milestone or `FR-` reference, the change type, the pasted verification output
and the checklist. `CODEOWNERS` (`.github/CODEOWNERS`) requests a review from
the maintainer for every path, including `/docs/`.

### Reviewer path

The goal is that no change — including a docs-only one — merges without a
second set of eyes, however that review is staffed:

- **A human co-maintainer.** `CODEOWNERS` routes every path to the maintainer;
  a second contributor with write access on `main` is auto-requested the moment
  they are listed there. They should commit under their own identity so the
  history reflects more than one author (the ask is *genuine* back-and-forth,
  not rubber-stamping).
- **A bot-assisted review, where a human is not available.** Automated review
  (Dependabot, the `fresh-clone-smoke` and per-stack CI jobs, the secret scan,
  and optional static-analysis bots) is a floor, not a substitute. When a solo
  contributor has to self-approve to keep a change moving, record that decision
  in the PR (a one-line "self-review: verified X, Y, Z against the checklist
  below") so the record shows a review happened rather than a rubber stamp.
- **Self-review rules.** Only the author should self-review, only when no other
  reviewer is available, and only against the full checklist below — ideally on
  a fresh branch after a short gap, so the diff is read with fresh eyes.

In every case the CI checks are the gate that must be green before merge:
`make verify`, the secret scan, and the required status checks (see
[`../deployment/ci-cd.md`](../deployment/ci-cd.md)). A reviewer shortcut is a
process allowance; it never overrides a red check.

Before requesting review:

```bash
make verify                          # lint + types + tests + build
python backend/scripts/scan_secrets.py
git status --short                   # must be clean
```

Reviewer checklist:

- [ ] Branch is up to date with `main`
- [ ] `ruff check` and `ruff format --check` pass
- [ ] `mypy app` passes
- [ ] `pytest --cov=app --cov-report=term-missing` passes (no live DB required)
- [ ] `npm run lint`, `npm run typecheck`, `npm run test:coverage`, `npm run build` pass
- [ ] Coverage at/above the 80% backend floor and the Vitest thresholds
- [ ] `python backend/scripts/scan_secrets.py` reports nothing
- [ ] `backend/requirements.lock` / `requirements-dev.lock` regenerated when a manifest changed
- [ ] New behaviour has a test that fails without the change
- [ ] `CHANGELOG.md` updated under `Unreleased`; `IMPLEMENTATION_PLAN.md` boxes ticked
- [ ] No secrets, no build artefacts, no large binaries
- [ ] Schema change? Migration included, reviewed and forward-only

Squash-merge keeps `main` linear and the Conventional Commit subject becomes
the merge commit subject.

## 4. Dependency updates

Dependabot (`.github/dependabot.yml`) opens weekly grouped PRs on Mondays
(Asia/Dhaka):

| Ecosystem | Directory | Limit | Commit prefix | Labels |
|-----------|-----------|-------|---------------|--------|
| pip | `/backend` | 5 | `chore(deps)` | `dependencies`, `backend` |
| npm | `/frontend` | 5 | `chore(deps)` | `dependencies`, `frontend` |
| github-actions | `/` | 3 | `ci(deps)` | `dependencies`, `ci` |

Minor and patch bumps arrive as one grouped PR per ecosystem. A dependency PR
still has to pass `pip-audit` / `npm audit --audit-level=high`; a security
advisory that cannot be closed by a bump is recorded in
[`../security/threat-model.md`](../security/threat-model.md).

## 5. Releases and hotfixes

Releases are cut from `main` only, with green CI and a dated `CHANGELOG.md`
section:

```bash
git tag -a v0.1.0 -m "StockPilot v0.1.0"
git push origin main
git push origin v0.1.0
```

The tag runs the `release` job, which publishes the API image to GHCR and opens
a GitHub Release — see [`../deployment/ci-cd.md`](../deployment/ci-cd.md). If a
release is bad, roll back the image first and only then fix forward:
[`../deployment/rollback.md`](../deployment/rollback.md).

A hotfix follows the same path on a `hotfix/` branch, is merged to `main`, and
is tagged as a PATCH bump.
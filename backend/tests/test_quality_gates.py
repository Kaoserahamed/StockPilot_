"""Contract tests for the quality gates this repository advertises.

The README, docs/development/testing.md and CONTRIBUTING.md all promise that
linting, static types, both test suites, coverage floors, dependency audits, a
secret scan and a container build run in CI. These tests fail when one of those
gates quietly disappears from the configuration - exactly the regression a
reviewer or a new contributor notices first.

Read-only: ``tomllib`` plus text parsing of committed configuration files.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ROOT_PYPROJECT = REPO_ROOT / "pyproject.toml"
BACKEND_PYPROJECT = REPO_ROOT / "backend" / "pyproject.toml"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
VITEST_CONFIG = REPO_ROOT / "frontend" / "vitest.config.ts"
PACKAGE_JSON = REPO_ROOT / "frontend" / "package.json"
ROOT_DOCKERFILE = REPO_ROOT / "Dockerfile"
DOCKERIGNORE = REPO_ROOT / ".dockerignore"
BACKEND_DOCKERFILE = REPO_ROOT / "backend" / "Dockerfile"
BACKEND_DOCKERIGNORE = REPO_ROOT / "backend" / ".dockerignore"
DEVCONTAINER = REPO_ROOT / ".devcontainer" / "devcontainer.json"
SECRET_SCANNER = REPO_ROOT / "backend" / "scripts" / "scan_secrets.py"
SECRET_SCANNER_TESTS = REPO_ROOT / "backend" / "tests" / "test_secret_scan.py"


def load_toml(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def ci_workflow() -> str:
    return CI_WORKFLOW.read_text(encoding="utf-8")


def copied_paths(dockerfile_path: Path) -> str:
    """Return just the ``COPY`` instructions of a Dockerfile.

    Only what an image actually copies in can be installed from, so the
    lockfile assertions below compare against these lines rather than against
    the whole file (where a filename may appear in a comment instead).
    """
    lines = [
        line.strip()
        for line in dockerfile_path.read_text(encoding="utf-8").splitlines()
        if line.strip().upper().startswith("COPY")
    ]
    return "\n".join(lines)


def test_backend_pytest_enforces_a_coverage_floor() -> None:
    config = load_toml(BACKEND_PYPROJECT)["tool"]
    assert config["coverage"]["run"]["source"] == ["app"]
    assert config["coverage"]["report"]["fail_under"] >= 90
    assert config["pytest"]["ini_options"]["testpaths"] == ["tests"]


def test_repo_root_can_run_the_backend_suite() -> None:
    config = load_toml(ROOT_PYPROJECT)["tool"]
    options = config["pytest"]["ini_options"]
    assert options["testpaths"] == ["backend/tests"]
    assert "backend" in options["pythonpath"]
    assert config["coverage"]["report"]["fail_under"] >= 90


def test_ci_gates_lint_types_tests_and_dependency_audits() -> None:
    workflow = ci_workflow()
    for command in (
        "ruff check app tests scripts",
        "ruff format --check app tests scripts",
        "mypy app",
        "--cov-fail-under=90",
        "--cov=app",
        "npm run lint",
        "npm run typecheck",
        "npm run test:coverage",
        "npm run format:check",
        "npm run build",
        "pip-audit -r requirements.lock",
        "npm run audit",
        "pip install -r requirements.lock",
        "pip install -r requirements-dev.lock",
    ):
        assert command in workflow, f"CI no longer runs: {command}"


def test_ci_runs_every_suite_on_pull_requests_and_main() -> None:
    workflow = ci_workflow()
    assert "pull_request:" in workflow
    assert "branches: [main]" in workflow
    for job in (
        "backend-lint:",
        "backend-test:",
        "backend-audit:",
        "frontend-check:",
        "frontend-audit:",
        "backend-lock-drift:",
        "backend-reproducible-install:",
        "backend-secret-scan:",
    ):
        assert job in workflow, f"missing CI job: {job}"


def test_ci_builds_a_container_for_every_dockerfile() -> None:
    workflow = ci_workflow()
    assert "docker/build-push-action@" in workflow
    for dockerfile in ("./Dockerfile", "./backend/Dockerfile", "./frontend/Dockerfile"):
        assert dockerfile in workflow, f"CI does not build {dockerfile}"


def test_tagged_releases_publish_an_image_and_a_github_release() -> None:
    workflow = ci_workflow()
    assert 'tags: ["v*"]' in workflow, "the workflow must run on version tags"
    assert "startsWith(github.ref, 'refs/tags/v')" in workflow
    assert "docker/metadata-action@" in workflow
    assert "softprops/action-gh-release@" in workflow


def test_frontend_declares_scripts_and_coverage_thresholds() -> None:
    scripts = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))["scripts"]
    for script in ("lint", "typecheck", "test", "test:coverage", "build", "format:check"):
        assert script in scripts, f"frontend script missing: {script}"
    config = VITEST_CONFIG.read_text(encoding="utf-8")
    assert "thresholds" in config, "vitest must fail the run below the coverage floor"
    assert "provider: 'v8'" in config


@pytest.mark.parametrize(
    ("dockerfile_path", "build_context_ignore"),
    [(ROOT_DOCKERFILE, DOCKERIGNORE), (BACKEND_DOCKERFILE, BACKEND_DOCKERIGNORE)],
    ids=["root-api-image", "compose-api-image"],
)
def test_container_artifacts_exist_and_are_hardened(
    dockerfile_path: Path, build_context_ignore: Path
) -> None:
    dockerfile = dockerfile_path.read_text(encoding="utf-8")
    assert "requirements.lock" in dockerfile, "the image must install from the committed lockfile"
    # The path referenced by `pip install -r` must be a file that actually
    # exists, not a typo of one. `requirements.lock.txt` satisfies the substring
    # check above while installing nothing at all, which fails the build in the
    # builder stage long before any test could notice.
    referenced = set(re.findall(r"requirements[\w.\-]*", dockerfile))
    copied = set(re.findall(r"requirements[\w.\-]*", copied_paths(dockerfile_path)))
    assert referenced, "the image must name the lockfile it installs"
    assert referenced <= copied, (
        f"{dockerfile_path.name} installs {sorted(referenced - copied)} but never copies it"
    )
    assert "USER " in dockerfile, "the image must not run as root"
    assert "HEALTHCHECK" in dockerfile
    assert build_context_ignore.is_file(), "the build context needs a .dockerignore"


def test_devcontainer_bootstraps_the_whole_repository() -> None:
    config = json.loads(DEVCONTAINER.read_text(encoding="utf-8"))
    assert "postCreateCommand" in config
    assert {3000, 8000} <= set(config["forwardPorts"])
    assert (REPO_ROOT / ".devcontainer" / "post-create.sh").is_file()


def test_secret_scanning_is_wired_into_ci_and_the_suite() -> None:
    assert SECRET_SCANNER.is_file()
    assert SECRET_SCANNER_TESTS.is_file()
    assert "scan_secrets.py" in ci_workflow()

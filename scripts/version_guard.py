"""Fail a PR that changes CLI source or dependencies without a version bump.

Run from the repository root in CI:

    python scripts/version_guard.py --base origin/main

Compares HEAD against the merge base with the base branch and enforces:

- pyproject.toml and herds_cli/__init__.py must agree on the version
- changes under herds_cli/ or to [project] dependencies require a bump
- the version must never decrease
- tag cli-v<head version> must not already exist on origin
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tomllib

SOURCE_PREFIX = "herds_cli/"
INIT_PATH = "herds_cli/__init__.py"
PYPROJECT_PATH = "pyproject.toml"


def parse_pyproject(text: str) -> tuple[str, list[str]]:
    """Return (version, dependencies) from pyproject.toml text."""
    project = tomllib.loads(text)["project"]
    return project["version"], list(project["dependencies"])


def parse_init_version(text: str) -> str:
    match = re.search(r'^__version__ = "([^"]+)"', text, re.MULTILINE)
    if match is None:
        raise ValueError(f"no __version__ found in {INIT_PATH}")
    return match.group(1)


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def check_guard(
    base_version: str,
    head_version: str,
    init_version: str,
    changed_files: list[str],
    base_dependencies: list[str],
    head_dependencies: list[str],
    tag_exists: bool,
) -> list[str]:
    """Return failure messages; empty means the PR passes the guard."""
    failures: list[str] = []
    if head_version != init_version:
        failures.append(
            f"version mismatch: pyproject.toml has {head_version}, "
            f"{INIT_PATH} has {init_version}"
        )
    if tag_exists:
        failures.append(f"tag cli-v{head_version} already exists on origin")
    if version_key(head_version) < version_key(base_version):
        failures.append(
            f"version went backwards: {base_version} -> {head_version}"
        )
    source_changed = any(f.startswith(SOURCE_PREFIX) for f in changed_files)
    deps_changed = base_dependencies != head_dependencies
    needs_bump = source_changed or deps_changed
    if needs_bump and version_key(head_version) <= version_key(base_version):
        reason = "herds_cli/ source" if source_changed else "dependencies"
        failures.append(
            f"{reason} changed but the version was not bumped "
            f"(base {base_version}, head {head_version})"
        )
    return failures


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True
    )
    return result.stdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/main")
    args = parser.parse_args()

    merge_base = _git("merge-base", args.base, "HEAD").strip()
    changed_files = _git("diff", "--name-only", merge_base, "HEAD").splitlines()
    base_version, base_deps = parse_pyproject(
        _git("show", f"{merge_base}:{PYPROJECT_PATH}")
    )
    with open(PYPROJECT_PATH, encoding="utf-8") as f:
        head_version, head_deps = parse_pyproject(f.read())
    with open(INIT_PATH, encoding="utf-8") as f:
        init_version = parse_init_version(f.read())
    tag_ref = f"refs/tags/cli-v{head_version}"
    tag_exists = bool(_git("ls-remote", "--tags", "origin", tag_ref).strip())

    failures = check_guard(
        base_version,
        head_version,
        init_version,
        changed_files,
        base_deps,
        head_deps,
        tag_exists,
    )
    for failure in failures:
        print(f"::error::version guard: {failure}")
    if not failures:
        print(f"version guard passed (version {head_version})")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

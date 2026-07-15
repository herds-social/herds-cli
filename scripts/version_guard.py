"""Fail a PR that changes CLI source or dependencies without a version bump.

Run from the repository root in CI:

    python scripts/version_guard.py --base origin/main

Compares HEAD against the merge base with the base branch and enforces:

- pyproject.toml, herds_cli/__init__.py, and uv.lock must agree on the version
- changes under herds_cli/ or to [project] dependencies require a bump
- the version must never decrease
- when the version was bumped, tag cli-v<head version> must not already
  exist on origin (an unbumped PR's version is already released, so its
  tag legitimately exists)

Also the release pipeline's version source: release-cli.yml's check job runs
`--print-version`, which verifies all three version sources agree and writes
the version to stdout. That stdout is captured into a job output that names the
tag, the release assets, and the formula URL, so the --print-version path must
never print anything else to stdout (errors go to stderr).

Both CI call sites invoke this script with the runner's system python3 and no
dependency install: it must stay stdlib-only, and tomllib pins it to
Python >= 3.11.
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
LOCK_PATH = "uv.lock"
# Strict X.Y.Z; the tag format and release asset names assume exactly this.
VERSION_RE = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)")


def parse_pyproject(text: str) -> tuple[str, list[str]]:
    """Return (version, dependencies) from pyproject.toml text."""
    project = tomllib.loads(text)["project"]
    version = project["version"]
    if not isinstance(version, str):
        raise ValueError("pyproject.toml [project].version must be a string")
    return version, list(project.get("dependencies", []))


def parse_init_version(text: str) -> str:
    match = re.search(r'^__version__ = "([^"]+)"', text, re.MULTILINE)
    if match is None:
        raise ValueError(f"no __version__ found in {INIT_PATH}")
    return match.group(1)


def parse_lock_version(text: str) -> str:
    """Return the herds-cli version pinned in uv.lock text."""
    for package in tomllib.loads(text).get("package", []):
        if package.get("name") == "herds-cli":
            return package["version"]
    raise ValueError(f"herds-cli not found in {LOCK_PATH}")


def version_key(version: str) -> tuple[int, ...]:
    if VERSION_RE.fullmatch(version) is None:
        raise ValueError(f"version must be exactly X.Y.Z (got {version!r})")
    return tuple(int(part) for part in version.split("."))


def version_mismatches(
    head_version: str, init_version: str, lock_version: str
) -> list[str]:
    """Shared three-way agreement rule for the PR guard and release check."""
    mismatches: list[str] = []
    if head_version != init_version:
        mismatches.append(
            f"version mismatch: pyproject.toml has {head_version}, "
            f"{INIT_PATH} has {init_version}"
        )
    if head_version != lock_version:
        mismatches.append(
            f"version mismatch: pyproject.toml has {head_version}, "
            f"{LOCK_PATH} has {lock_version}"
        )
    return mismatches


def check_guard(
    base_version: str,
    head_version: str,
    init_version: str,
    lock_version: str,
    changed_files: list[str],
    base_dependencies: list[str],
    head_dependencies: list[str],
    tag_exists: bool,
) -> list[str]:
    """Return failure messages; empty means the PR passes the guard."""
    failures: list[str] = list(
        version_mismatches(head_version, init_version, lock_version)
    )
    # Only a bumped version proposes a new tag; an unbumped PR's version is
    # already released and its tag is supposed to exist.
    version_bumped = version_key(head_version) > version_key(base_version)
    if tag_exists and version_bumped:
        failures.append(f"tag cli-v{head_version} already exists on origin")
    if version_key(head_version) < version_key(base_version):
        failures.append(
            f"version went backwards: {base_version} -> {head_version}"
        )
    source_changed = any(f.startswith(SOURCE_PREFIX) for f in changed_files)
    deps_changed = base_dependencies != head_dependencies
    needs_bump = source_changed or deps_changed
    # == not <=: a decreased version is already reported as "went backwards".
    if needs_bump and version_key(head_version) == version_key(base_version):
        changed = " and ".join(
            part
            for part, flag in (
                ("herds_cli/ source", source_changed),
                ("dependencies", deps_changed),
            )
            if flag
        )
        failures.append(
            f"{changed} changed but the version was not bumped "
            f"(base {base_version}, head {head_version})"
        )
    return failures


def verified_head_version(
    pyproject_text: str, init_text: str, lock_text: str
) -> str:
    """Return the version once all three version files agree; raise otherwise."""
    head_version, _ = parse_pyproject(pyproject_text)
    init_version = parse_init_version(init_text)
    lock_version = parse_lock_version(lock_text)
    mismatches = version_mismatches(head_version, init_version, lock_version)
    if mismatches:
        raise ValueError("; ".join(mismatches))
    # The stdout of --print-version names the tag, assets, and formula URL;
    # reject malformed shapes before they propagate.
    version_key(head_version)
    return head_version


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True
    )
    return result.stdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/main")
    parser.add_argument(
        "--print-version",
        action="store_true",
        help="verify the version files agree, print the version, and exit",
    )
    args = parser.parse_args()

    with open(PYPROJECT_PATH, encoding="utf-8") as f:
        pyproject_text = f.read()
    with open(INIT_PATH, encoding="utf-8") as f:
        init_text = f.read()
    with open(LOCK_PATH, encoding="utf-8") as f:
        lock_text = f.read()

    if args.print_version:
        try:
            print(verified_head_version(pyproject_text, init_text, lock_text))
        except ValueError as error:
            print(f"::error::{error}", file=sys.stderr)
            return 1
        return 0

    merge_base = _git("merge-base", args.base, "HEAD").strip()
    changed_files = _git("diff", "--name-only", merge_base, "HEAD").splitlines()
    base_version, base_deps = parse_pyproject(
        _git("show", f"{merge_base}:{PYPROJECT_PATH}")
    )
    head_version, head_deps = parse_pyproject(pyproject_text)
    init_version = parse_init_version(init_text)
    lock_version = parse_lock_version(lock_text)
    tag_ref = f"refs/tags/cli-v{head_version}"
    tag_exists = bool(_git("ls-remote", "--tags", "origin", tag_ref).strip())

    failures = check_guard(
        base_version=base_version,
        head_version=head_version,
        init_version=init_version,
        lock_version=lock_version,
        changed_files=changed_files,
        base_dependencies=base_deps,
        head_dependencies=head_deps,
        tag_exists=tag_exists,
    )
    for failure in failures:
        print(f"::error::version guard: {failure}")
    if not failures:
        print(f"version guard passed (version {head_version})")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

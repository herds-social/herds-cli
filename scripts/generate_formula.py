"""Render the complete Homebrew formula for a herds-cli release.

Run inside a virtualenv that has the CLI (and therefore its runtime
dependencies) installed:

    venv/bin/python scripts/generate_formula.py \
        --sdist-path sdist/herds_cli-4.4.0.tar.gz \
        --output herds.rb

The release version is read from the installed herds-cli distribution (the
sdist the venv was built from), so the formula url, sha256, and resources
can never describe different versions.

Every distribution installed in the running interpreter's environment,
minus the CLI itself and installer tooling, becomes a ``resource`` block
pinned to the sdist PyPI publishes for that exact version. The formula is
fully regenerated each release; it is never patched in place.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass
from importlib import metadata
from string import Template
from typing import TypedDict

# Available in the release venv only because requests is a herds-cli runtime
# dependency; this script installs nothing of its own.
import requests

# The sdist filename uses herds_cli (underscore): PEP 625 normalization of the
# project name herds-cli, as produced by `python -m build`. The same name is
# used by the `gh release download --pattern` step in release-cli.yml, and the
# /cli-v<version>/ path segment is what release-cli.yml's check job greps for
# to decide whether the tap formula is already current.
RELEASE_URL = (
    "https://github.com/herds-social/herds-cli/releases/download/"
    "cli-v{version}/herds_cli-{version}.tar.gz"
)
PYPI_JSON_URL = "https://pypi.org/pypi/{name}/{version}/json"
EXCLUDED_DISTRIBUTIONS = {"herds-cli", "pip", "setuptools", "wheel"}

FORMULA_TEMPLATE = Template(
    """\
class Herds < Formula
  include Language::Python::Virtualenv

  desc "Command-line interface for the Herds event platform"
  homepage "https://github.com/herds-social/herds-cli"
  url "$url"
  sha256 "$sha256"
  license "Apache-2.0"

  depends_on "python@3.11"

$resources
  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "Usage:", shell_output("#{bin}/herds --help")
    assert_match "herds", shell_output("#{bin}/herds --help")
  end
end
"""
)

RESOURCE_TEMPLATE = Template(
    """\
  resource "$name" do
    url "$url"
    sha256 "$sha256"
  end
"""
)


class PyPIUrlEntry(TypedDict):
    """One entry of the PyPI JSON API's ``urls`` array (fields we consume)."""

    packagetype: str  # "sdist" or "bdist_wheel"
    url: str
    digests: dict[str, str]


@dataclass
class ResourceInfo:
    name: str
    url: str
    sha256: str


def normalize(name: str) -> str:
    """PEP 503 name normalization (runs of ``-_.`` collapse to one ``-``)."""
    return re.sub(r"[-_.]+", "-", name).lower()


def select_resource_dists(
    pairs: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    """Filter out the CLI itself and installer tooling; sort for stable diffs."""
    kept = [
        (name, version)
        for name, version in pairs
        if normalize(name) not in EXCLUDED_DISTRIBUTIONS
    ]
    return sorted(kept, key=lambda pair: normalize(pair[0]))


def installed_distributions() -> list[tuple[str, str]]:
    """(name, version) of everything in the running interpreter's environment.

    The resource list mirrors this interpreter, so the script must run inside
    the clean release venv built by release-cli.yml, never a dev environment.
    """
    return [
        (name, dist.version)
        for dist in metadata.distributions()
        if (name := dist.metadata["Name"]) is not None
    ]


def environment_problems(installed_names: set[str]) -> list[str]:
    """Reject interpreters that would produce a wrong formula (pure check)."""
    problems: list[str] = []
    if "herds-cli" not in installed_names:
        problems.append("herds-cli is not installed in this interpreter")
    dev_markers = sorted({"pytest", "pyright"} & installed_names)
    if dev_markers:
        problems.append(
            f"dev tools installed ({', '.join(dev_markers)}); "
            "run inside the clean release venv, not a dev environment"
        )
    return problems


def fetch_sdist_info(
    name: str, version: str, http: requests.Session
) -> ResourceInfo:
    url = PYPI_JSON_URL.format(name=name, version=version)
    response = http.get(url, timeout=30)
    response.raise_for_status()
    entries: list[PyPIUrlEntry] = response.json()["urls"]
    for entry in entries:
        if entry["packagetype"] == "sdist":
            return ResourceInfo(
                name=name,
                url=entry["url"],
                sha256=entry["digests"]["sha256"],
            )
    raise RuntimeError(f"no sdist on PyPI for {name}=={version}")


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def render_formula(
    version: str, sdist_sha256: str, resources: list[ResourceInfo]
) -> str:
    blocks = "\n".join(
        RESOURCE_TEMPLATE.substitute(
            name=resource.name, url=resource.url, sha256=resource.sha256
        )
        for resource in resources
    )
    return FORMULA_TEMPLATE.substitute(
        url=RELEASE_URL.format(version=version),
        sha256=sdist_sha256,
        resources=blocks,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdist-path", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    distributions = installed_distributions()
    problems = environment_problems({normalize(name) for name, _ in distributions})
    if problems:
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        return 1

    release_version = metadata.version("herds-cli")
    with requests.Session() as http:
        resources = [
            fetch_sdist_info(name, version, http)
            for name, version in select_resource_dists(distributions)
        ]
    formula = render_formula(
        release_version, sha256_file(args.sdist_path), resources
    )
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(formula)
    print(f"wrote {args.output} with {len(resources)} resource blocks")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Render the complete Homebrew formula for a herds-cli release.

Run inside a virtualenv that has the CLI (and therefore its runtime
dependencies) installed:

    venv/bin/python scripts/generate_formula.py \
        --version 4.4.0 \
        --sdist-path sdist/herds_cli-4.4.0.tar.gz \
        --output herds.rb

Every distribution installed in the running interpreter's environment,
minus the CLI itself and installer tooling, becomes a ``resource`` block
pinned to the sdist PyPI publishes for that exact version. The formula is
fully regenerated each release; it is never patched in place.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from dataclasses import dataclass
from importlib import metadata
from string import Template

import requests

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


@dataclass
class ResourceInfo:
    name: str
    url: str
    sha256: str


def normalize(name: str) -> str:
    return name.lower().replace("_", "-")


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


def installed_dependencies() -> list[tuple[str, str]]:
    pairs = [
        (dist.metadata["Name"], dist.version)
        for dist in metadata.distributions()
    ]
    return select_resource_dists(pairs)


def fetch_sdist_info(name: str, version: str) -> ResourceInfo:
    url = PYPI_JSON_URL.format(name=name, version=version)
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    for entry in response.json()["urls"]:
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
    parser.add_argument("--version", required=True)
    parser.add_argument("--sdist-path", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    resources = [
        fetch_sdist_info(name, version)
        for name, version in installed_dependencies()
    ]
    formula = render_formula(
        args.version, sha256_file(args.sdist_path), resources
    )
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(formula)
    print(f"wrote {args.output} with {len(resources)} resource blocks")
    return 0


if __name__ == "__main__":
    sys.exit(main())

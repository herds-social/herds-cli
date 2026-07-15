"""Tests for the Homebrew formula generator."""

import hashlib

import pytest

from scripts.generate_formula import (
    ResourceInfo,
    environment_problems,
    fetch_sdist_info,
    normalize,
    render_formula,
    select_resource_dists,
    sha256_file,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payload):
        self.payload = payload

    def get(self, url, timeout):
        return FakeResponse(self.payload)


def test_normalize_is_pep503():
    assert normalize("ruamel.yaml") == "ruamel-yaml"
    assert normalize("Foo__Bar") == "foo-bar"


def test_environment_problems_accepts_clean_release_venv():
    assert environment_problems({"herds-cli", "click", "requests"}) == []


def test_environment_problems_rejects_missing_cli():
    problems = environment_problems({"click", "requests"})
    assert any("not installed" in p for p in problems)


def test_environment_problems_rejects_dev_venv():
    problems = environment_problems({"herds-cli", "click", "pytest", "pyright"})
    assert any("dev tools installed (pyright, pytest)" in p for p in problems)


def test_select_resource_dists_excludes_self_and_tooling():
    pairs = [
        ("Pygments", "2.19.2"),
        ("herds_cli", "4.4.0"),
        ("pip", "24.0"),
        ("setuptools", "70.0"),
        ("wheel", "0.43"),
        ("click", "8.2.1"),
    ]
    assert select_resource_dists(pairs) == [
        ("click", "8.2.1"),
        ("Pygments", "2.19.2"),
    ]


def test_select_resource_dists_sorts_case_insensitively():
    pairs = [("mdurl", "0.1.2"), ("Pygments", "2.19.2"), ("markdown-it-py", "2.2.0")]
    assert [name for name, _ in select_resource_dists(pairs)] == [
        "markdown-it-py",
        "mdurl",
        "Pygments",
    ]


def test_fetch_sdist_info_picks_the_sdist():
    payload = {
        "urls": [
            {
                "packagetype": "bdist_wheel",
                "url": "https://files.pythonhosted.org/x/click.whl",
                "digests": {"sha256": "aaa"},
            },
            {
                "packagetype": "sdist",
                "url": "https://files.pythonhosted.org/x/click-8.2.1.tar.gz",
                "digests": {"sha256": "bbb"},
            },
        ]
    }
    info = fetch_sdist_info("click", "8.2.1", FakeSession(payload))
    assert info == ResourceInfo(
        name="click",
        url="https://files.pythonhosted.org/x/click-8.2.1.tar.gz",
        sha256="bbb",
    )


def test_fetch_sdist_info_without_sdist_raises():
    payload = {
        "urls": [
            {
                "packagetype": "bdist_wheel",
                "url": "https://files.pythonhosted.org/x/click.whl",
                "digests": {"sha256": "aaa"},
            }
        ]
    }
    with pytest.raises(RuntimeError, match="no sdist"):
        fetch_sdist_info("click", "8.2.1", FakeSession(payload))


def test_sha256_file(tmp_path):
    target = tmp_path / "blob.tar.gz"
    target.write_bytes(b"hello")
    assert sha256_file(str(target)) == hashlib.sha256(b"hello").hexdigest()


def test_render_formula_complete_output():
    resources = [
        ResourceInfo(
            name="click",
            url="https://files.pythonhosted.org/x/click-8.2.1.tar.gz",
            sha256="b" * 64,
        ),
        ResourceInfo(
            name="requests",
            url="https://files.pythonhosted.org/x/requests-2.32.5.tar.gz",
            sha256="c" * 64,
        ),
    ]
    output = render_formula("9.9.9", "a" * 64, resources)
    assert output == (
        "class Herds < Formula\n"
        "  include Language::Python::Virtualenv\n"
        "\n"
        '  desc "Command-line interface for the Herds event platform"\n'
        '  homepage "https://github.com/herds-social/herds-cli"\n'
        '  url "https://github.com/herds-social/herds-cli/releases/download/'
        'cli-v9.9.9/herds_cli-9.9.9.tar.gz"\n'
        f'  sha256 "{"a" * 64}"\n'
        '  license "Apache-2.0"\n'
        "\n"
        '  depends_on "python@3.11"\n'
        "\n"
        '  resource "click" do\n'
        '    url "https://files.pythonhosted.org/x/click-8.2.1.tar.gz"\n'
        f'    sha256 "{"b" * 64}"\n'
        "  end\n"
        "\n"
        '  resource "requests" do\n'
        '    url "https://files.pythonhosted.org/x/requests-2.32.5.tar.gz"\n'
        f'    sha256 "{"c" * 64}"\n'
        "  end\n"
        "\n"
        "  def install\n"
        "    virtualenv_install_with_resources\n"
        "  end\n"
        "\n"
        "  test do\n"
        '    assert_match "Usage:", shell_output("#{bin}/herds --help")\n'
        '    assert_match "herds", shell_output("#{bin}/herds --help")\n'
        "  end\n"
        "end\n"
    )

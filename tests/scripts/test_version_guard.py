"""Tests for the PR version-bump guard."""

import pytest

from scripts.version_guard import (
    check_guard,
    parse_init_version,
    parse_pyproject,
    verified_head_version,
    version_key,
)

BASE_DEPS = ["click>=8.0", "requests>=2.25"]


def run_guard(**overrides):
    kwargs = dict(
        base_version="4.3.0",
        head_version="4.3.0",
        init_version="4.3.0",
        changed_files=["README.md"],
        base_dependencies=BASE_DEPS,
        head_dependencies=BASE_DEPS,
        tag_exists=False,
    )
    kwargs.update(overrides)
    return check_guard(**kwargs)


def test_docs_only_change_passes():
    assert run_guard(changed_files=["docs/references/homebrew.md"]) == []


def test_source_change_without_bump_fails():
    failures = run_guard(changed_files=["herds_cli/cli.py"])
    assert any("not bumped" in f for f in failures)


def test_source_change_with_bump_passes():
    assert (
        run_guard(
            changed_files=["herds_cli/cli.py", "pyproject.toml"],
            head_version="4.3.1",
            init_version="4.3.1",
        )
        == []
    )


def test_dependency_change_without_bump_fails():
    failures = run_guard(
        changed_files=["pyproject.toml"],
        head_dependencies=BASE_DEPS + ["pytz>=2023.3"],
    )
    assert any("not bumped" in f for f in failures)


def test_version_file_mismatch_fails():
    failures = run_guard(
        changed_files=["herds_cli/cli.py"],
        head_version="4.3.1",
        init_version="4.3.0",
    )
    assert any("mismatch" in f for f in failures)


def test_version_backwards_fails():
    failures = run_guard(head_version="4.2.0", init_version="4.2.0")
    assert any("backwards" in f for f in failures)


def test_backwards_with_source_change_reports_once():
    failures = run_guard(
        head_version="4.2.0",
        init_version="4.2.0",
        changed_files=["herds_cli/cli.py"],
    )
    assert len(failures) == 1
    assert "backwards" in failures[0]


def test_source_and_dependency_change_reason_mentions_both():
    failures = run_guard(
        changed_files=["herds_cli/cli.py", "pyproject.toml"],
        head_dependencies=BASE_DEPS + ["pytz>=2023.3"],
    )
    assert failures == [
        "herds_cli/ source and dependencies changed but the version was "
        "not bumped (base 4.3.0, head 4.3.0)"
    ]


def test_existing_tag_with_bump_fails():
    failures = run_guard(
        head_version="4.3.1", init_version="4.3.1", tag_exists=True
    )
    assert any("already exists" in f for f in failures)


def test_existing_tag_without_bump_passes():
    assert run_guard(tag_exists=True) == []


def test_parse_pyproject():
    text = (
        "[project]\n"
        'name = "herds-cli"\n'
        'version = "4.3.0"\n'
        'dependencies = ["click>=8.0"]\n'
    )
    assert parse_pyproject(text) == ("4.3.0", ["click>=8.0"])


def test_parse_pyproject_missing_dependencies_key():
    text = '[project]\nname = "herds-cli"\nversion = "4.3.0"\n'
    assert parse_pyproject(text) == ("4.3.0", [])


def test_parse_init_version():
    assert parse_init_version('"""doc"""\n__version__ = "4.3.0"\n') == "4.3.0"


def test_parse_init_version_missing_raises():
    with pytest.raises(ValueError):
        parse_init_version("nothing here\n")


def test_version_key_orders_numerically():
    assert version_key("4.10.0") > version_key("4.9.9")


PYPROJECT_TEXT = '[project]\nname = "x"\nversion = "4.3.0"\ndependencies = []\n'


def test_verified_head_version_agreement():
    init_text = '__version__ = "4.3.0"\n'
    assert verified_head_version(PYPROJECT_TEXT, init_text) == "4.3.0"


def test_verified_head_version_mismatch_raises():
    init_text = '__version__ = "4.2.0"\n'
    with pytest.raises(ValueError, match="mismatch"):
        verified_head_version(PYPROJECT_TEXT, init_text)

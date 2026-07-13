"""
CLI-layer tests for the `config` command group's path defaults.

Verify that `config save` / `config show` fall back to the XDG config file
when no path is given. XDG_CONFIG_HOME is redirected to a tmp dir so no real
home directory is ever written to or read from.
"""

import json

import pytest

from tests.cli.conftest import strip_ansi
from herds_cli import paths
from herds_cli.cli import cli


@pytest.fixture
def xdg_config_file(tmp_path, monkeypatch):
    """Redirect XDG_CONFIG_HOME and return the resolved default config path."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv("HERDS_CONFIG_FILE", raising=False)
    return paths.default_config_file()


class TestConfigSaveDefaultsToXdg:
    def test_save_without_path_writes_xdg_config_file(
        self, cli_runner, cli_obj, xdg_config_file
    ):
        assert not xdg_config_file.exists()

        result = cli_runner.invoke(cli, ["config", "save"], obj=cli_obj)

        assert result.exit_code == 0, result.output
        assert xdg_config_file.exists()
        data = json.loads(xdg_config_file.read_text())
        assert data["api_url"] == "http://localhost:8000"


class TestConfigShowDefaultsToXdg:
    def test_show_without_path_reads_xdg_config_file(
        self, cli_runner, cli_obj, xdg_config_file
    ):
        xdg_config_file.parent.mkdir(parents=True, exist_ok=True)
        xdg_config_file.write_text(json.dumps({"api_url": "https://saved.example.com"}))

        result = cli_runner.invoke(cli, ["config", "show"], obj=cli_obj)

        assert result.exit_code == 0, result.output
        # The distinctive api_url from the XDG file proves `show` read it
        # (the loaded-from path is also printed but Rich wraps long tmp
        # paths across lines, so it is not reliable to substring-match).
        assert "saved.example.com" in strip_ansi(result.output)

    def test_herds_config_file_env_overrides_xdg_default(
        self, cli_runner, cli_obj, xdg_config_file, tmp_path, monkeypatch
    ):
        # XDG default exists but HERDS_CONFIG_FILE points elsewhere; the env
        # var must win, matching the override seam every other command honors.
        xdg_config_file.parent.mkdir(parents=True, exist_ok=True)
        xdg_config_file.write_text(json.dumps({"api_url": "https://xdg.example.com"}))
        override = tmp_path / "override.json"
        override.write_text(json.dumps({"api_url": "https://override.example.com"}))
        monkeypatch.setenv("HERDS_CONFIG_FILE", str(override))

        result = cli_runner.invoke(cli, ["config", "show"], obj=cli_obj)

        assert result.exit_code == 0, result.output
        output = strip_ansi(result.output)
        assert "override.example.com" in output
        assert "xdg.example.com" not in output


@pytest.fixture
def isolated_xdg(tmp_path, monkeypatch):
    """Redirect XDG config+state to tmp and clear HERDS_CONFIG_FILE.

    Used by tests that run the real cli() group (no injected ctx.obj), so the
    group's config/session resolution must not touch the real home dir.
    """
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.delenv("HERDS_CONFIG_FILE", raising=False)


class TestGroupConfigResolution:
    def test_cwd_config_file_is_no_longer_auto_loaded(
        self, cli_runner, isolated_xdg
    ):
        # Before the XDG migration a ./herds-cli-config.json in the cwd was
        # auto-detected; it must now be ignored entirely.
        with cli_runner.isolated_filesystem():
            with open("herds-cli-config.json", "w") as f:
                json.dump({"api_url": "https://cwd.example.com"}, f)
            result = cli_runner.invoke(cli, ["config", "show"])

        assert result.exit_code == 0, result.output
        assert "cwd.example.com" not in strip_ansi(result.output)

    def test_missing_herds_config_file_does_not_brick_commands(
        self, cli_runner, tmp_path, monkeypatch
    ):
        # A HERDS_CONFIG_FILE pointing at a not-yet-created file must not abort
        # commands at parse time (regression: it once did, blocking bootstrap).
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
        monkeypatch.setenv("HERDS_CONFIG_FILE", str(tmp_path / "does-not-exist.json"))

        result = cli_runner.invoke(cli, ["config", "validate"])

        assert result.exit_code == 0, result.output

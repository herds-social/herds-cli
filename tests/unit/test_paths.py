"""
Unit tests for XDG path resolution (herds_cli.paths).

These exercise observable behavior: which directory each helper resolves to
given the XDG environment variables and the user's home directory. Home is
redirected via the HOME env var (POSIX Path.home() reads it), so no real
home directory is ever touched.
"""

import pytest

from herds_cli import paths


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """Point Path.home() at a tmp dir and clear XDG vars by default."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    return tmp_path


class TestXdgConfigHome:
    def test_defaults_to_dot_config_when_unset(self, fake_home):
        assert paths.xdg_config_home() == fake_home / ".config"

    def test_honors_absolute_env_var(self, fake_home, tmp_path, monkeypatch):
        custom = tmp_path / "somewhere" / "cfg"
        monkeypatch.setenv("XDG_CONFIG_HOME", str(custom))
        assert paths.xdg_config_home() == custom

    def test_empty_env_var_falls_back_to_default(self, fake_home, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", "")
        assert paths.xdg_config_home() == fake_home / ".config"

    def test_relative_env_var_is_ignored(self, fake_home, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", "relative/cfg")
        assert paths.xdg_config_home() == fake_home / ".config"


class TestXdgStateHome:
    def test_defaults_to_local_state_when_unset(self, fake_home):
        assert paths.xdg_state_home() == fake_home / ".local" / "state"

    def test_honors_absolute_env_var(self, fake_home, tmp_path, monkeypatch):
        custom = tmp_path / "somewhere" / "state"
        monkeypatch.setenv("XDG_STATE_HOME", str(custom))
        assert paths.xdg_state_home() == custom

    def test_empty_env_var_falls_back_to_default(self, fake_home, monkeypatch):
        monkeypatch.setenv("XDG_STATE_HOME", "")
        assert paths.xdg_state_home() == fake_home / ".local" / "state"


class TestHerdsSubdirs:
    def test_config_dir_is_herds_under_config_home(self, fake_home):
        assert paths.config_dir() == fake_home / ".config" / "herds"

    def test_default_config_file_is_config_json(self, fake_home):
        assert paths.default_config_file() == fake_home / ".config" / "herds" / "config.json"

    def test_state_dir_is_herds_under_state_home(self, fake_home):
        assert paths.state_dir() == fake_home / ".local" / "state" / "herds"

    def test_subdirs_follow_custom_xdg_env(self, fake_home, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "c"))
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "s"))
        assert paths.default_config_file() == tmp_path / "c" / "herds" / "config.json"
        assert paths.state_dir() == tmp_path / "s" / "herds"


class TestResolveConfigFile:
    def test_explicit_path_wins(self, fake_home, monkeypatch):
        monkeypatch.setenv("HERDS_CONFIG_FILE", "/env/path.json")
        assert paths.resolve_config_file("/explicit.json") == "/explicit.json"

    def test_env_used_when_no_explicit(self, fake_home, monkeypatch):
        monkeypatch.setenv("HERDS_CONFIG_FILE", "/env/path.json")
        assert paths.resolve_config_file(None) == "/env/path.json"

    def test_falls_back_to_xdg_default(self, fake_home, monkeypatch):
        monkeypatch.delenv("HERDS_CONFIG_FILE", raising=False)
        assert paths.resolve_config_file(None) == str(paths.default_config_file())

    def test_empty_env_falls_back_to_default(self, fake_home, monkeypatch):
        monkeypatch.setenv("HERDS_CONFIG_FILE", "")
        assert paths.resolve_config_file(None) == str(paths.default_config_file())

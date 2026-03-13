"""
Unit tests for Config loading, validation, and persistence.
"""

import json
import os

import pytest

from herds_cli.core.config import Config


class TestConfigDefaults:
    def test_default_values(self):
        config = Config()
        assert config.api_url == "http://localhost:8000"
        assert config.api_timeout == 30
        assert config.output_format == "json"
        assert config.verbose is False
        assert config.debug_requests is False
        assert config.timezone is None
        assert config.default_account is None

    def test_default_config_validates(self):
        config = Config()
        assert config.validate() is True


class TestConfigLoadFromFile:
    def test_load_from_json(self, tmp_config_file):
        tmp_config_file.write_text(json.dumps({
            "api_url": "https://example.com",
            "api_timeout": 60,
            "output_format": "table",
        }))

        config = Config.load(str(tmp_config_file))
        assert config.api_url == "https://example.com"
        assert config.api_timeout == 60
        assert config.output_format == "table"

    def test_load_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            Config.load(str(tmp_path / "nope.json"))

    def test_load_non_json_raises(self, tmp_path):
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("key: value")

        with pytest.raises(ValueError, match="JSON format"):
            Config.load(str(yaml_file))

    def test_load_ignores_private_keys(self, tmp_config_file):
        tmp_config_file.write_text(json.dumps({
            "_validation_errors": ["injected"],
            "api_url": "https://example.com",
        }))

        config = Config.load(str(tmp_config_file))
        assert config.api_url == "https://example.com"
        assert config._validation_errors == []

    def test_load_ignores_unknown_keys(self, tmp_config_file):
        tmp_config_file.write_text(json.dumps({
            "api_url": "https://example.com",
            "unknown_field": "should be ignored",
        }))

        config = Config.load(str(tmp_config_file))
        assert config.api_url == "https://example.com"
        assert not hasattr(config, "unknown_field")

    def test_load_without_path_uses_defaults(self):
        config = Config.load()
        assert config.api_url == "http://localhost:8000"


class TestConfigLoadFromEnv:
    def test_env_overrides_defaults(self, monkeypatch):
        monkeypatch.setenv("HERDS_API_URL", "https://env.example.com")
        monkeypatch.setenv("HERDS_API_TIMEOUT", "10")
        monkeypatch.setenv("HERDS_OUTPUT_FORMAT", "table")
        monkeypatch.setenv("HERDS_VERBOSE", "true")
        monkeypatch.setenv("HERDS_DEBUG_REQUESTS", "1")
        monkeypatch.setenv("HERDS_TIMEZONE", "UTC")
        monkeypatch.setenv("HERDS_DEFAULT_ACCOUNT", "user@example.com")

        config = Config.load()
        assert config.api_url == "https://env.example.com"
        assert config.api_timeout == 10
        assert config.output_format == "table"
        assert config.verbose is True
        assert config.debug_requests is True
        assert config.timezone == "UTC"
        assert config.default_account == "user@example.com"

    def test_file_overrides_env(self, monkeypatch, tmp_config_file):
        monkeypatch.setenv("HERDS_API_URL", "https://env.example.com")
        tmp_config_file.write_text(json.dumps({
            "api_url": "https://file.example.com",
        }))

        config = Config.load(str(tmp_config_file))
        assert config.api_url == "https://file.example.com"

    def test_invalid_timeout_env_keeps_default(self, monkeypatch):
        monkeypatch.setenv("HERDS_API_TIMEOUT", "not-a-number")

        config = Config.load()
        assert config.api_timeout == 30

    def test_verbose_env_falsy_values(self, monkeypatch):
        monkeypatch.setenv("HERDS_VERBOSE", "false")
        config = Config.load()
        assert config.verbose is False

        monkeypatch.setenv("HERDS_VERBOSE", "no")
        config = Config.load()
        assert config.verbose is False


class TestConfigSave:
    def test_save_and_reload(self, tmp_config_file):
        config = Config(
            api_url="https://saved.example.com",
            api_timeout=15,
            output_format="table",
            default_account="test@example.com",
        )
        config.save(str(tmp_config_file))

        loaded = Config.load(str(tmp_config_file))
        assert loaded.api_url == "https://saved.example.com"
        assert loaded.api_timeout == 15
        assert loaded.output_format == "table"
        assert loaded.default_account == "test@example.com"

    def test_save_excludes_internal_fields(self, tmp_config_file):
        config = Config()
        config._validation_errors = ["something"]
        config._loaded_config_file = "/some/path"
        config.save(str(tmp_config_file))

        raw = json.loads(tmp_config_file.read_text())
        assert "_validation_errors" not in raw
        assert "_loaded_config_file" not in raw

    def test_save_creates_parent_dirs(self, tmp_path):
        nested = tmp_path / "a" / "b" / "config.json"
        config = Config()
        config.save(str(nested))
        assert nested.exists()


class TestConfigValidation:
    def test_valid_config(self):
        config = Config(
            api_url="https://example.com",
            api_timeout=30,
            output_format="json",
            timezone="America/New_York",
            default_account="user@example.com",
        )
        assert config.validate() is True

    def test_invalid_url_no_scheme(self):
        config = Config(api_url="example.com")
        assert config.validate() is False
        assert any("URL" in e for e in config.get_validation_errors())

    def test_invalid_url_empty(self):
        config = Config(api_url="")
        assert config.validate() is False

    def test_invalid_timeout_zero(self):
        config = Config(api_timeout=0)
        assert config.validate() is False
        assert any("timeout" in e for e in config.get_validation_errors())

    def test_invalid_timeout_negative(self):
        config = Config(api_timeout=-1)
        assert config.validate() is False

    def test_invalid_output_format(self):
        config = Config(output_format="xml")
        assert config.validate() is False
        assert any("format" in e for e in config.get_validation_errors())

    def test_invalid_timezone(self):
        config = Config(timezone="Not/A/Timezone")
        assert config.validate() is False
        assert any("timezone" in e for e in config.get_validation_errors())

    def test_valid_timezone_utc(self):
        config = Config(timezone="UTC")
        assert config.validate() is True

    def test_invalid_email_format(self):
        config = Config(default_account="not-an-email")
        assert config.validate() is False
        assert any("email" in e for e in config.get_validation_errors())

    def test_valid_email(self):
        config = Config(default_account="user+tag@example.co.uk")
        assert config.validate() is True

    def test_none_timezone_skips_validation(self):
        config = Config(timezone=None)
        assert config.validate() is True

    def test_none_email_skips_validation(self):
        config = Config(default_account=None)
        assert config.validate() is True

    def test_session_dir_created_if_missing(self, tmp_path):
        new_dir = str(tmp_path / "sessions")
        config = Config(session_dir=new_dir)
        assert config.validate() is True
        assert (tmp_path / "sessions").is_dir()

    def test_validation_errors_reset_between_calls(self):
        config = Config(api_url="bad")
        config.validate()
        assert len(config.get_validation_errors()) > 0

        config.api_url = "https://example.com"
        config.validate()
        assert len(config.get_validation_errors()) == 0

    def test_multiple_errors_collected(self):
        config = Config(
            api_url="bad",
            api_timeout=-1,
            output_format="xml",
            timezone="Bad/Zone",
            default_account="not-email",
        )
        config.validate()
        errors = config.get_validation_errors()
        assert len(errors) >= 4


class TestConfigToDict:
    def test_round_trips_fields(self):
        config = Config(api_url="https://example.com", api_timeout=42)
        d = config.to_dict()
        assert d["api_url"] == "https://example.com"
        assert d["api_timeout"] == 42
        assert "output_format" in d

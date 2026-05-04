"""
Unit tests for SessionManager.

Tests the real SessionManager with a tmp_path base directory,
verifying save/load/delete/list without touching ~/.herds/.
"""


class TestSessionManagerSanitizeEmail:
    def test_basic_email(self, mock_session_manager):
        assert mock_session_manager.sanitize_email("user@example.com") == "user_at_example_com"

    def test_email_with_plus(self, mock_session_manager):
        result = mock_session_manager.sanitize_email("user+tag@example.com")
        assert result == "user_plus_tag_at_example_com"

    def test_email_with_dots(self, mock_session_manager):
        result = mock_session_manager.sanitize_email("first.last@domain.co.uk")
        assert result == "first_last_at_domain_co_uk"


class TestSessionManagerSaveLoad:
    def test_save_and_load_session(self, mock_session_manager):
        session_data = {
            "client_type": "mobile",
            "tokens": {"access_token": "fake-token"},
            "user_data": {"id": "user-123", "email": "test@example.com"},
        }

        mock_session_manager.save_session("test@example.com", session_data)
        loaded = mock_session_manager.load_session("test@example.com")

        assert loaded is not None
        assert loaded["email"] == "test@example.com"
        assert loaded["client_type"] == "mobile"
        assert loaded["tokens"]["access_token"] == "fake-token"
        assert loaded["user_data"]["id"] == "user-123"

    def test_load_nonexistent_session(self, mock_session_manager):
        result = mock_session_manager.load_session("nobody@example.com")
        assert result is None

    def test_save_overwrites_existing(self, mock_session_manager):
        mock_session_manager.save_session("test@example.com", {"client_type": "web"})
        mock_session_manager.save_session("test@example.com", {"client_type": "mobile"})

        loaded = mock_session_manager.load_session("test@example.com")
        assert loaded["client_type"] == "mobile"


class TestSessionManagerDelete:
    def test_delete_existing_session(self, mock_session_manager):
        mock_session_manager.save_session("test@example.com", {"client_type": "mobile"})

        result = mock_session_manager.delete_session("test@example.com")
        assert result is True
        assert mock_session_manager.load_session("test@example.com") is None

    def test_delete_nonexistent_session(self, mock_session_manager):
        result = mock_session_manager.delete_session("nobody@example.com")
        assert result is False


class TestSessionManagerCopyBeforeMutate:
    """Verify save_session does not mutate the caller's dict."""

    def test_caller_dict_unchanged(self, mock_session_manager):
        original = {
            "client_type": "mobile",
            "tokens": {"access_token": "tok"},
            "user_data": {"id": "u1", "email": "test@example.com"},
        }
        original_copy = dict(original)

        mock_session_manager.save_session("test@example.com", original)

        # The caller's dict must not have been mutated with email/created_at/etc.
        assert original == original_copy
        assert "email" not in original
        assert "created_at" not in original
        assert "session_filename" not in original

    def test_saved_file_has_enriched_fields(self, mock_session_manager):
        mock_session_manager.save_session("test@example.com", {
            "client_type": "mobile",
            "tokens": {"access_token": "tok"},
            "user_data": {"id": "u1", "email": "test@example.com"},
        })

        loaded = mock_session_manager.load_session("test@example.com")
        assert loaded["email"] == "test@example.com"
        assert "created_at" in loaded
        assert "session_filename" in loaded


class TestSessionManagerKeyValidation:
    """Verify load_session rejects sessions missing required keys."""

    def test_missing_client_type_returns_none(self, mock_session_manager, capsys):
        """A session file without client_type is treated as invalid."""
        # Write a raw file bypassing save_session to create an invalid session
        import json
        filename = mock_session_manager.get_session_filename("bad@example.com")
        filename.parent.mkdir(parents=True, exist_ok=True)
        with open(filename, "w") as f:
            json.dump({"email": "bad@example.com", "tokens": {}}, f)

        result = mock_session_manager.load_session("bad@example.com")

        assert result is None
        captured = capsys.readouterr()
        assert "client_type" in captured.err

    def test_missing_email_returns_none(self, mock_session_manager, capsys):
        """A session file without email is treated as invalid."""
        import json
        filename = mock_session_manager.get_session_filename("noemail@example.com")
        filename.parent.mkdir(parents=True, exist_ok=True)
        with open(filename, "w") as f:
            json.dump({"client_type": "mobile", "tokens": {}}, f)

        result = mock_session_manager.load_session("noemail@example.com")

        assert result is None
        captured = capsys.readouterr()
        assert "email" in captured.err

    def test_valid_session_loads_normally(self, mock_session_manager):
        """Sessions with all required keys load successfully."""
        mock_session_manager.save_session("good@example.com", {
            "client_type": "mobile",
            "tokens": {"access_token": "tok"},
            "user_data": {"id": "u1", "email": "good@example.com"},
        })

        loaded = mock_session_manager.load_session("good@example.com")
        assert loaded is not None
        assert loaded["client_type"] == "mobile"
        assert loaded["email"] == "good@example.com"

    def test_missing_both_keys_returns_none(self, mock_session_manager, capsys):
        import json
        filename = mock_session_manager.get_session_filename("empty@example.com")
        filename.parent.mkdir(parents=True, exist_ok=True)
        with open(filename, "w") as f:
            json.dump({"tokens": {}}, f)

        result = mock_session_manager.load_session("empty@example.com")

        assert result is None
        captured = capsys.readouterr()
        assert "client_type" in captured.err
        assert "email" in captured.err


class TestSessionManagerList:
    def test_list_empty(self, mock_session_manager):
        sessions = mock_session_manager.list_sessions()
        assert sessions == []

    def test_list_multiple_sessions(self, mock_session_manager):
        mock_session_manager.save_session("a@example.com", {"client_type": "mobile"})
        mock_session_manager.save_session("b@example.com", {"client_type": "web"})

        sessions = mock_session_manager.list_sessions()
        emails = {s["email"] for s in sessions}

        assert len(sessions) == 2
        assert emails == {"a@example.com", "b@example.com"}

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

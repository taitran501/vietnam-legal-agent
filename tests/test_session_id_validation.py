"""
Tests for session ID validation in ChatRequest schema.

Tests cover:
- Reserved words rejection (default, admin, system, test, anonymous)
- Empty string acceptance (UUID auto-generation)
- Valid session IDs (alphanumeric, hyphens, underscores)
- Invalid session IDs (special characters, SQL injection attempts)
- Max length enforcement
"""

import pytest
from pydantic import ValidationError

from backend.api.schemas import ChatRequest


class TestSessionIDValidation:
    """Test session_id validation in ChatRequest."""

    def test_empty_session_id_allowed(self):
        """Empty string should be allowed (will be auto-generated as UUID)."""
        req = ChatRequest(query="Test query", session_id="")
        assert req.session_id == ""

    def test_valid_alphanumeric_session_id(self):
        """Alphanumeric session IDs should be accepted."""
        req = ChatRequest(query="Test query", session_id="abc123")
        assert req.session_id == "abc123"

    def test_valid_session_id_with_hyphens(self):
        """Session IDs with hyphens should be accepted."""
        req = ChatRequest(query="Test query", session_id="session-123-abc")
        assert req.session_id == "session-123-abc"

    def test_valid_session_id_with_underscores(self):
        """Session IDs with underscores should be accepted."""
        req = ChatRequest(query="Test query", session_id="session_123_abc")
        assert req.session_id == "session_123_abc"

    def test_valid_uuid_session_id(self):
        """UUID format session IDs should be accepted."""
        uuid_str = "550e8400-e29b-41d4-a716-446655440000"
        req = ChatRequest(query="Test query", session_id=uuid_str)
        assert req.session_id == uuid_str

    @pytest.mark.parametrize("reserved_word", [
        "default", "admin", "system", "test", "anonymous",
        "DEFAULT", "ADMIN", "SYSTEM", "TEST", "ANONYMOUS",
        "Default", "Admin", "System",
    ])
    def test_reserved_words_rejected(self, reserved_word):
        """Reserved words should be rejected (case-insensitive)."""
        with pytest.raises(ValidationError) as exc_info:
            ChatRequest(query="Test query", session_id=reserved_word)
        assert "reserved" in str(exc_info.value).lower()

    @pytest.mark.parametrize("invalid_id", [
        "session; DROP TABLE users--",  # SQL injection
        "session' OR '1'='1",  # SQL injection variant
        "<script>alert('xss')</script>",  # XSS attempt
        "session with spaces",  # Spaces not allowed
        "session@domain",  # @ symbol
        "session#123",  # # symbol
        "session%20encoded",  # URL encoding
        "session/path",  # Path separator
        "session\\path",  # Backslash
        "session\x00null",  # Null byte
    ])
    def test_invalid_session_ids_rejected(self, invalid_id):
        """Invalid session IDs should be rejected."""
        with pytest.raises(ValidationError):
            ChatRequest(query="Test query", session_id=invalid_id)

    def test_max_length_session_id(self):
        """Session ID at max length (128) should be accepted."""
        max_length_id = "a" * 128
        req = ChatRequest(query="Test query", session_id=max_length_id)
        assert req.session_id == max_length_id

    def test_over_max_length_session_id_rejected(self):
        """Session ID over max length (129) should be rejected."""
        over_length_id = "a" * 129
        with pytest.raises(ValidationError):
            ChatRequest(query="Test query", session_id=over_length_id)

    def test_default_session_id_is_empty(self):
        """Default session_id should be empty string."""
        req = ChatRequest(query="Test query")
        assert req.session_id == ""


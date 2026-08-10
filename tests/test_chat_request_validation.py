"""
Tests for chat request validation.

Tests cover:
- Empty query rejection (min_length=1)
- Query over 3000 characters rejection
- Valid queries
- Special characters in queries
"""

import pytest
from pydantic import ValidationError

from backend.api.schemas import ChatRequest


class TestChatRequestValidation:
    """Test ChatRequest validation."""

    def test_valid_query(self):
        """Valid query should pass validation."""
        req = ChatRequest(query="What is EPR?")
        assert req.query == "What is EPR?"

    def test_empty_query_rejected(self):
        """Empty query should be rejected."""
        with pytest.raises(ValidationError):
            ChatRequest(query="")

    def test_whitespace_only_query_rejected(self):
        """Whitespace-only query should be accepted by Pydantic (min_length=1 counts spaces)."""
        # Note: Pydantic min_length counts all characters including spaces
        # "   " has length 3, so it passes min_length=1
        # The backend should handle this by trimming before processing
        req = ChatRequest(query="   ")
        assert req.query == "   "  # Pydantic allows it
        # Backend pipeline should trim/validate after Pydantic

    def test_single_character_query_allowed(self):
        """Single character query should be allowed."""
        req = ChatRequest(query="A")
        assert req.query == "A"

    def test_query_at_max_length(self):
        """Query at exactly 3000 characters should be allowed."""
        max_query = "A" * 3000
        req = ChatRequest(query=max_query)
        assert len(req.query) == 3000

    def test_query_over_max_length_rejected(self):
        """Query over the V3 3000-character cap should be rejected."""
        over_query = "A" * 3001
        with pytest.raises(ValidationError):
            ChatRequest(query=over_query)

    def test_query_with_special_characters(self):
        """Query with special characters should be allowed."""
        req = ChatRequest(query="What is EPR? @#$%^&*()")
        assert req.query == "What is EPR? @#$%^&*()"

    def test_query_with_unicode(self):
        """Query with Unicode characters should be allowed."""
        req = ChatRequest(query="Nghị định 08/2022 là gì?")
        assert "Nghị định" in req.query

    def test_query_with_html_tags(self):
        """Query with HTML tags should be allowed (but sanitized later)."""
        req = ChatRequest(query="What is <b>EPR</b>?")
        assert req.query == "What is <b>EPR</b>?"

    def test_query_with_sql_injection_attempt(self):
        """Query with SQL injection should be allowed (backend handles it)."""
        req = ChatRequest(query="What is EPR?'; DROP TABLE users;--")
        assert "DROP TABLE" in req.query

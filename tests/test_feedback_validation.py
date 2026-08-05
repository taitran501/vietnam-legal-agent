"""
Tests for feedback validation in FeedbackRequest schema.

Tests cover:
- Valid session_id format
- Invalid session_id (special characters, SQL injection)
- Negative message_index rejection
- Rating validation (only 1 or 2 allowed)
- Comment sanitization (null bytes, control characters)
- Max length enforcement
"""

import pytest
from pydantic import ValidationError

from backend.api.routes.feedback import FeedbackRequest


class TestFeedbackValidation:
    """Test feedback request validation."""

    def test_valid_feedback(self):
        """Valid feedback request should pass validation."""
        req = FeedbackRequest(
            session_id="valid-session-123",
            message_index=0,
            rating=1,
            comment="Good response"
        )
        assert req.session_id == "valid-session-123"
        assert req.message_index == 0
        assert req.rating == 1
        assert req.comment == "Good response"

    def test_feedback_with_thumbs_up(self):
        """Thumbs up rating (2) should be valid."""
        req = FeedbackRequest(
            session_id="session-1",
            message_index=5,
            rating=2
        )
        assert req.rating == 2

    @pytest.mark.parametrize("invalid_rating", [0, 3, -1, 100])
    def test_invalid_ratings_rejected(self, invalid_rating):
        """Ratings other than 1 or 2 should fail validation."""
        # Now Pydantic validates the rating value and raises ValidationError
        with pytest.raises(ValidationError):
            FeedbackRequest(
                session_id="session-1",
                message_index=0,
                rating=invalid_rating
            )

    def test_negative_message_index_rejected(self):
        """Negative message_index should be rejected (ge=0)."""
        with pytest.raises(ValidationError):
            FeedbackRequest(
                session_id="session-1",
                message_index=-1,
                rating=1
            )

    def test_zero_message_index_allowed(self):
        """message_index=0 should be allowed."""
        req = FeedbackRequest(
            session_id="session-1",
            message_index=0,
            rating=1
        )
        assert req.message_index == 0

    @pytest.mark.parametrize("invalid_session", [
        "session; DROP TABLE--",  # SQL injection
        "session' OR '1'='1",  # SQL injection variant
        "session with spaces",  # Spaces
        "session@domain",  # @ symbol
        "<script>alert('xss')</script>",  # XSS
        "session#123",  # # symbol
        "",  # Empty string (min_length=1)
    ])
    def test_invalid_session_ids_rejected(self, invalid_session):
        """Invalid session IDs should be rejected."""
        with pytest.raises(ValidationError):
            FeedbackRequest(
                session_id=invalid_session,
                message_index=0,
                rating=1
            )

    def test_comment_sanitization_null_bytes(self):
        """Null bytes in comment should be removed."""
        req = FeedbackRequest(
            session_id="session-1",
            message_index=0,
            rating=1,
            comment="Good\x00response"
        )
        # Null bytes should be stripped
        assert "\x00" not in req.comment

    def test_comment_sanitization_control_chars(self):
        """Control characters in comment should be removed."""
        req = FeedbackRequest(
            session_id="session-1",
            message_index=0,
            rating=1,
            comment="Good\x01\x02response"
        )
        # Control characters should be stripped
        assert "\x01" not in req.comment
        assert "\x02" not in req.comment

    def test_comment_max_length(self):
        """Comment at max length (500) should be accepted."""
        max_comment = "a" * 500
        req = FeedbackRequest(
            session_id="session-1",
            message_index=0,
            rating=1,
            comment=max_comment
        )
        assert len(req.comment) == 500

    def test_comment_over_max_length_rejected(self):
        """Comment over max length (501) should be rejected."""
        over_comment = "a" * 501
        with pytest.raises(ValidationError):
            FeedbackRequest(
                session_id="session-1",
                message_index=0,
                rating=1,
                comment=over_comment
            )

    def test_optional_comment(self):
        """Comment should be optional (can be None)."""
        req = FeedbackRequest(
            session_id="session-1",
            message_index=0,
            rating=1
        )
        assert req.comment is None

    def test_whitespace_only_comment_becomes_none(self):
        """Whitespace-only comment should become None after sanitization."""
        req = FeedbackRequest(
            session_id="session-1",
            message_index=0,
            rating=1,
            comment="   "
        )
        # After stripping, should be None
        assert req.comment is None


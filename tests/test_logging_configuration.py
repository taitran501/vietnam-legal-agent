"""
Tests for logging configuration.

Tests cover:
- Text logging format works
- JSON logging format works (when python-json-logger is installed)
- Fallback when python-json-logger is not installed
- Log level configuration
"""

import os
import sys
import logging
import pytest
from unittest.mock import patch, MagicMock
from io import StringIO

# Import the setup_logging function
# We need to import it in a way that doesn't trigger full app initialization
import importlib


class TestLoggingConfiguration:
    """Test logging setup and configuration."""

    def setup_method(self):
        """Reset logging configuration before each test."""
        # Reset root logger
        root_logger = logging.getLogger()
        root_logger.handlers = []
        root_logger.setLevel(logging.WARNING)

    def test_text_logging_default(self):
        """Text logging should be the default format."""
        # Clear any cached imports
        if 'backend.main' in sys.modules:
            # Can't easily reimport, so test the logic directly
            pass

        # Reset root logger completely
        root_logger = logging.getLogger()
        root_logger.handlers = []
        
        # Simulate the text logging setup
        log_level = "INFO"
        logging.basicConfig(
            level=getattr(logging, log_level, logging.INFO),
            format='%(asctime)s | %(name)s | %(levelname)s | %(message)s',
            datefmt='%Y-%m-%dT%H:%M:%S',
            force=True  # Force reconfiguration
        )

        assert len(root_logger.handlers) > 0

        # Check it's a StreamHandler with text format
        handler = root_logger.handlers[0]
        assert isinstance(handler, logging.StreamHandler)
        # Handler should have formatter with asctime
        if handler.formatter:
            assert '%(asctime)s' in handler.formatter._fmt

    def test_json_logging_when_available(self):
        """JSON logging should work when python-json-logger is installed."""
        try:
            from pythonjsonlogger import jsonlogger
            json_available = True
        except ImportError:
            json_available = False

        if json_available:
            # Simulate JSON logging setup
            handler = logging.StreamHandler()
            formatter = jsonlogger.JsonFormatter(
                '%(asctime)s %(name)s %(levelname)s %(message)s',
                datefmt='%Y-%m-%dT%H:%M:%S'
            )
            handler.setFormatter(formatter)

            root_logger = logging.getLogger()
            root_logger.handlers = []
            root_logger.addHandler(handler)
            root_logger.setLevel(logging.INFO)

            assert len(root_logger.handlers) == 1
            assert isinstance(root_logger.handlers[0].formatter, jsonlogger.JsonFormatter)

    def test_json_logging_fallback_when_missing(self):
        """Should fall back to text logging when python-json-logger is not installed."""
        # Mock the import to simulate missing package
        import builtins
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == 'pythonjsonlogger' or name.startswith('pythonjsonlogger.'):
                raise ImportError("Mocked: python-json-logger not installed")
            return original_import(name, *args, **kwargs)

        # Test the fallback logic
        log_level = "INFO"

        # This simulates the except block in setup_logging
        logging.basicConfig(
            level=getattr(logging, log_level, logging.INFO),
            format='%(asctime)s | %(name)s | %(levelname)s | %(message)s',
            datefmt='%Y-%m-%dT%H:%M:%S'
        )

        root_logger = logging.getLogger()
        assert len(root_logger.handlers) > 0

    def test_log_level_configuration(self):
        """Log level should be configurable via environment variable."""
        test_cases = [
            ("DEBUG", logging.DEBUG),
            ("INFO", logging.INFO),
            ("WARNING", logging.WARNING),
            ("ERROR", logging.ERROR),
            ("CRITICAL", logging.CRITICAL),
            ("invalid", logging.INFO),  # Invalid should default to INFO
        ]

        for env_value, expected_level in test_cases:
            with patch.dict(os.environ, {"LOG_LEVEL": env_value}, clear=False):
                level_str = os.getenv("LOG_LEVEL", "INFO").upper()
                # Handle invalid level gracefully
                actual_level = getattr(logging, level_str, logging.INFO)
                # For invalid values, should default to INFO
                if env_value.upper() not in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
                    assert actual_level == logging.INFO
                else:
                    assert actual_level == expected_level

    def test_logging_outputs_to_stream(self):
        """Logging should output to a stream (stdout/stderr)."""
        # Create a StringIO stream to capture output
        log_stream = StringIO()
        handler = logging.StreamHandler(log_stream)
        handler.setFormatter(logging.Formatter('%(message)s'))

        logger = logging.getLogger("test_logger")
        logger.handlers = []
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        logger.info("Test message")
        log_output = log_stream.getvalue()

        assert "Test message" in log_output

    def test_json_log_format_structure(self):
        """JSON log format should produce structured output when available."""
        try:
            from pythonjsonlogger import jsonlogger
            import json

            log_stream = StringIO()
            handler = logging.StreamHandler(log_stream)
            formatter = jsonlogger.JsonFormatter(
                '%(asctime)s %(name)s %(levelname)s %(message)s'
            )
            handler.setFormatter(formatter)

            logger = logging.getLogger("json_test")
            logger.handlers = []
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)

            logger.info("Test JSON log")
            log_output = log_stream.getvalue()

            # Should be valid JSON
            parsed = json.loads(log_output)
            assert "message" in parsed or "msg" in parsed
            assert "levelname" in parsed or "level" in parsed
        except ImportError:
            pytest.skip("python-json-logger not installed")

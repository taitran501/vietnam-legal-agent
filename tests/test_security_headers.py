"""
Tests for security headers middleware.

Tests cover:
- X-Content-Type-Options header present
- X-Frame-Options header present
- Strict-Transport-Security header present
- Content-Security-Policy header present
- X-XSS-Protection header present
- Referrer-Policy header present
- Permissions-Policy header present
"""


import pytest
from backend.main import SecurityHeadersMiddleware
from fastapi import FastAPI
from starlette.testclient import TestClient


class TestSecurityHeadersMiddleware:
    """Test security headers are present in responses."""

    @pytest.fixture
    def app(self):
        """Create a test app with security headers middleware."""
        test_app = FastAPI()

        @test_app.get("/test")
        async def test_endpoint():
            return {"message": "test"}

        test_app.add_middleware(SecurityHeadersMiddleware)

        return test_app

    @pytest.fixture
    def client(self, app):
        """Create test client."""
        return TestClient(app)

    def test_x_content_type_options_header(self, client):
        """X-Content-Type-Options should be set to nosniff."""
        response = client.get("/test")
        assert response.headers.get("X-Content-Type-Options") == "nosniff"

    def test_x_frame_options_header(self, client):
        """X-Frame-Options should be set to DENY."""
        response = client.get("/test")
        assert response.headers.get("X-Frame-Options") == "DENY"

    def test_x_xss_protection_header(self, client):
        """X-XSS-Protection should be set to 1; mode=block."""
        response = client.get("/test")
        assert response.headers.get("X-XSS-Protection") == "1; mode=block"

    def test_strict_transport_security_header(self, client):
        """Strict-Transport-Security should be present."""
        response = client.get("/test")
        hsts = response.headers.get("Strict-Transport-Security")
        assert hsts is not None
        assert "max-age=31536000" in hsts
        assert "includeSubDomains" in hsts

    def test_content_security_policy_header(self, client):
        """Content-Security-Policy should be restrictive."""
        response = client.get("/test")
        csp = response.headers.get("Content-Security-Policy")
        assert csp is not None
        assert "default-src 'self'" in csp
        assert "script-src 'self'" in csp

    def test_referrer_policy_header(self, client):
        """Referrer-Policy should be set."""
        response = client.get("/test")
        referrer = response.headers.get("Referrer-Policy")
        assert referrer is not None
        assert "strict-origin" in referrer

    def test_permissions_policy_header(self, client):
        """Permissions-Policy should restrict sensitive APIs."""
        response = client.get("/test")
        permissions = response.headers.get("Permissions-Policy")
        assert permissions is not None
        assert "camera=()" in permissions
        assert "microphone=()" in permissions
        assert "geolocation=()" in permissions

    def test_all_security_headers_present(self, client):
        """All security headers should be present in response."""
        response = client.get("/test")

        required_headers = [
            "X-Content-Type-Options",
            "X-Frame-Options",
            "X-XSS-Protection",
            "Strict-Transport-Security",
            "Content-Security-Policy",
            "Referrer-Policy",
            "Permissions-Policy",
        ]

        for header in required_headers:
            assert header in response.headers, f"Missing header: {header}"

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_metrics_proxy_targets_authenticated_backend_route() -> None:
    nginx = (ROOT / "nginx.conf").read_text(encoding="utf-8")

    assert "location = /metrics" in nginx
    assert "proxy_pass http://backend/internal/metrics;" in nginx
    assert "allow 172.16.0.0/12;" in nginx
    assert "deny all;" in nginx


def test_application_images_do_not_run_as_root() -> None:
    backend = (ROOT / "Dockerfile.backend").read_text(encoding="utf-8")
    frontend = (ROOT / "Dockerfile.frontend").read_text(encoding="utf-8")

    assert "USER app" in backend
    assert "mkdir -p /app/artifacts" in backend
    assert "nginxinc/nginx-unprivileged" in frontend


def test_compose_requires_database_secret_and_uses_unprivileged_gateway() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD in .env" in compose
    assert "nginxinc/nginx-unprivileged" in compose
    assert '"80:8080"' in compose
    assert "container_name:" not in compose

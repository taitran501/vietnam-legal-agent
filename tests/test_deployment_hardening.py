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


def test_compose_liveness_does_not_depend_on_corpus_readiness() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    smoke_overlay = (ROOT / "docker-compose.ci-smoke.yml").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "curl -fsS http://localhost:8000/api/v1/health" in compose
    assert "curl -fsS http://localhost:8000/api/v1/health" in smoke_overlay
    assert "ready_status=$(curl" in workflow
    assert 'test "$ready_status" = "503"' in workflow
    assert "payload['capabilities']['legal_chat']['status'] == 'blocked'" in workflow


def test_universal_preview_overlay_mounts_the_optional_corpus_read_only() -> None:
    overlay = (ROOT / "docker-compose.universal-preview.yml").read_text(encoding="utf-8")
    example_env = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert 'ENABLE_UNIVERSAL_RETRIEVAL: "true"' in overlay
    assert "UNIVERSAL_CORPUS_DB_PATH: /app/data/corpus/universal_legal/universal_legal.db" in overlay
    assert "target: /app/data/corpus/universal_legal/universal_legal.db" in overlay
    assert "read_only: true" in overlay
    assert "create_host_path: false" in overlay
    assert "UNIVERSAL_CORPUS_HOST_PATH=./data/corpus/universal_legal/universal_legal.db" in example_env

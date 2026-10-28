group "default" {
  targets = ["backend", "frontend"]
}

target "backend" {
  context    = "."
  dockerfile = "Dockerfile.backend"
  tags       = ["ci-vietnam-legal-agent-backend"]
  cache-from = ["type=gha,scope=compose-backend"]
  cache-to   = ["type=gha,scope=compose-backend,mode=max,ignore-error=true"]
}

target "frontend" {
  context    = "."
  dockerfile = "Dockerfile.frontend"
  tags       = ["ci-vietnam-legal-agent-frontend"]
  cache-from = ["type=gha,scope=compose-frontend"]
  cache-to   = ["type=gha,scope=compose-frontend,mode=max,ignore-error=true"]
}

#!/usr/bin/env bash
# AOP single-node cloud deploy
# Usage:
#   cd deployments
#   cp .env.example .env   # edit AOP_PUBLIC_HOST
#   ./deploy.sh up
#   ./deploy.sh status
#   ./deploy.sh down

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "${ROOT}/.." && pwd)"
COMPOSE_FILE="${ROOT}/docker-compose.single.yml"
ENV_FILE="${ROOT}/.env"
PROJECT="aop"

cd "${ROOT}"

die() { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "missing command: $1"
}

compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose -p "${PROJECT}" --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" "$@"
  elif command -v docker-compose >/dev/null 2>&1; then
    docker-compose -p "${PROJECT}" --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" "$@"
  else
    die "docker compose not found"
  fi
}

load_env() {
  if [[ ! -f "${ENV_FILE}" ]]; then
    info "creating ${ENV_FILE} from .env.example"
    cp "${ROOT}/.env.example" "${ENV_FILE}"
  fi
  # shellcheck disable=SC1090
  set -a
  # shellcheck disable=SC1091
  source "${ENV_FILE}"
  set +a

  AOP_PUBLIC_HOST="${AOP_PUBLIC_HOST:-127.0.0.1}"
  AOP_PUBLIC_SCHEME="${AOP_PUBLIC_SCHEME:-http}"
  AUTH_REQUIRED="${AUTH_REQUIRED:-true}"
  SEED_DEV_KEY="${SEED_DEV_KEY:-true}"
  export AOP_PUBLIC_HOST AOP_PUBLIC_SCHEME AUTH_REQUIRED SEED_DEV_KEY
  export NEXT_PUBLIC_API_KEY="${NEXT_PUBLIC_API_KEY:-aop_sk_dev_local_0000000000000001}"
  export GATEWAY_API_KEY="${GATEWAY_API_KEY:-$NEXT_PUBLIC_API_KEY}"
}

check_prereq() {
  need_cmd docker
  docker info >/dev/null 2>&1 || die "docker daemon not running"
  if ! docker compose version >/dev/null 2>&1 && ! command -v docker-compose >/dev/null 2>&1; then
    die "install Docker Compose v2 (docker compose)"
  fi
  # free disk hint
  info "repo=${REPO}"
  info "public=${AOP_PUBLIC_SCHEME}://${AOP_PUBLIC_HOST}"
}

wait_http() {
  local url="$1"
  local name="$2"
  local n=0
  while (( n < 90 )); do
    if curl -fsS --max-time 3 "${url}" >/dev/null 2>&1; then
      echo "  ${name} OK"
      return 0
    fi
    sleep 2
    n=$((n + 1))
  done
  die "timeout waiting for ${name}: ${url}"
}

cmd_up() {
  check_prereq
  load_env

  if [[ "${AOP_PUBLIC_HOST}" == "127.0.0.1" || "${AOP_PUBLIC_HOST}" == "localhost" ]]; then
    echo "WARN: AOP_PUBLIC_HOST=${AOP_PUBLIC_HOST}"
    echo "      On a cloud VM set it to the public IP/domain in deployments/.env"
    echo "      otherwise browser Console cannot reach Gateway/MinIO."
  fi

  info "building images (first run may take several minutes) ..."
  compose build

  info "starting stack ..."
  compose up -d

  info "waiting for health endpoints ..."
  wait_http "http://127.0.0.1:8080/health" "gateway"
  wait_http "http://127.0.0.1:8090/health" "orchestrator"
  wait_http "http://127.0.0.1:3000" "web"

  info "applying postgres schema migrations (Phase 18) ..."
  # Prefer in-network migrate (single.yml does not publish 5432)
  if compose exec -T orchestrator \
      python /workspace/infrastructure/postgres/migrate.py; then
    :
  elif command -v python3 >/dev/null 2>&1 || command -v python >/dev/null 2>&1; then
    PY="$(command -v python3 || command -v python)"
    DATABASE_URL="${DATABASE_URL:-postgresql://aop:aop@127.0.0.1:5432/aop}" \
      "${PY}" "${REPO}/infrastructure/postgres/migrate.py" || \
      echo "WARN: migrate failed — ensure Postgres is reachable"
  else
    echo "WARN: run migrate manually: python infrastructure/postgres/migrate.py"
  fi

  info "ensuring agents registered ..."
  # register-agents is a one-shot; re-run if needed
  compose run --rm register-agents || true

  echo
  echo "=============================================="
  echo " AOP is up"
  echo "=============================================="
  echo " Console : ${AOP_PUBLIC_SCHEME}://${AOP_PUBLIC_HOST}:3000"
  echo " Gateway : ${AOP_PUBLIC_SCHEME}://${AOP_PUBLIC_HOST}:8080"
  echo " Orch    : ${AOP_PUBLIC_SCHEME}://${AOP_PUBLIC_HOST}:8090"
  echo " MinIO   : ${AOP_PUBLIC_SCHEME}://${AOP_PUBLIC_HOST}:9001  (aopminio / aopminio123)"
  echo
  echo " AUTH_REQUIRED=${AUTH_REQUIRED}  SEED_DEV_KEY=${SEED_DEV_KEY}"
  echo " API key: set in deployments/.env (NEXT_PUBLIC_API_KEY / GATEWAY_API_KEY) — do not commit secrets"
  if [[ "${AUTH_REQUIRED}" == "true" || "${AUTH_REQUIRED}" == "1" ]]; then
    echo " Send: Authorization: Bearer <key>   or   X-API-Key: <key>"
  fi
  echo
  echo " Useful:"
  echo "   ./deploy.sh status"
  echo "   ./deploy.sh logs"
  echo "   ./deploy.sh down"
  echo "=============================================="
}

cmd_down() {
  load_env
  compose down
  info "stopped (volumes kept). To wipe data: ./deploy.sh destroy"
}

cmd_destroy() {
  load_env
  compose down -v
  info "stopped and volumes removed"
}

cmd_status() {
  load_env
  compose ps
  echo
  curl -fsS "http://127.0.0.1:8080/health" && echo || echo "gateway: down"
  curl -fsS "http://127.0.0.1:8090/health" && echo || echo "orchestrator: down"
  curl -fsS "http://127.0.0.1:8080/v1/agents" | head -c 400 && echo || true
}

cmd_logs() {
  load_env
  compose logs -f --tail=200 "$@"
}

cmd_restart() {
  load_env
  compose restart "$@"
}

cmd_rebuild() {
  load_env
  compose build --no-cache
  compose up -d
  compose run --rm register-agents || true
  cmd_status
}

usage() {
  cat <<EOF
AOP single-node deploy

Usage:
  ./deploy.sh up         Build & start full stack
  ./deploy.sh down       Stop containers (keep data)
  ./deploy.sh destroy    Stop and delete volumes
  ./deploy.sh status     Show status + health
  ./deploy.sh logs [svc] Tail logs
  ./deploy.sh restart    Restart services
  ./deploy.sh rebuild    Rebuild images and restart

Config: deployments/.env  (from .env.example)
  AOP_PUBLIC_HOST   public IP or domain of this server
  AOP_PUBLIC_SCHEME http|https
  AUTH_REQUIRED     true|false
EOF
}

main() {
  local cmd="${1:-}"
  shift || true
  case "${cmd}" in
    up) cmd_up "$@" ;;
    down) cmd_down "$@" ;;
    destroy) cmd_destroy "$@" ;;
    status) cmd_status "$@" ;;
    logs) cmd_logs "$@" ;;
    restart) cmd_restart "$@" ;;
    rebuild) cmd_rebuild "$@" ;;
    -h|--help|help|"") usage ;;
    *) die "unknown command: ${cmd}" ;;
  esac
}

main "$@"

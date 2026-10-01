#!/usr/bin/env bash
# scripts/local.sh
# ----------------
# Runs the whole platform on this machine with Docker as the only prerequisite,
# and runs the same gates as .github/workflows/ci.yml without GitHub Actions.
#
#   scripts/local.sh setup    # first run: writes .env with generated secrets
#   scripts/local.sh up       # db + api + worker + UI, migrations applied
#   scripts/local.sh check    # ruff, parity, import boundaries, unit,
#                             # integration (real Postgres), web typecheck+build
#   scripts/local.sh status   # what is running, and whether it answers
#   scripts/local.sh logs [service]
#   scripts/local.sh down     # stops everything; the database volume is kept
#
# Paper only. Nothing here touches LIVE_TRADING_ENABLED or ALPACA_ALLOW_LIVE:
# docker-compose.yml pins both to "false" for every service, and the kill
# switch fails closed. Written for the bash 3.2 macOS ships, so no bash-4
# features.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

API_URL="http://localhost:8000/api/v1/health"
WEB_URL="http://localhost:3000"
REQUIRED_KEYS="POSTGRES_PASSWORD SESSION_SECRET ADMIN_PASSWORD_HASH"

say() { printf '\n==> %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

require_docker() {
  command -v docker >/dev/null 2>&1 || die "Docker is not installed. See SETUP.md, Prerequisites."
  docker info >/dev/null 2>&1 || die "Docker is installed but not running. Start Docker Desktop (or the daemon) and retry."
  docker compose version >/dev/null 2>&1 \
    || die "Compose V2 is missing ('docker compose'). SETUP.md explains why V1 will not do and how to install V2."
}

# Value of KEY in .env with surrounding single quotes removed; empty if unset.
env_value() {
  [ -f .env ] || return 0
  grep -E "^$1=" .env | tail -n 1 | cut -d= -f2- | sed -e "s/^'//" -e "s/'$//"
}

env_is_configured() {
  [ -f .env ] || return 1
  for key in $REQUIRED_KEYS; do
    [ -n "$(env_value "$key")" ] || return 1
  done
}

# Sets KEY='value' in .env, replacing the line if present. Single quotes stop a
# bcrypt hash's `$2b$12$` being expanded when the file is sourced by a shell
# (SETUP.md, "Single-quote every value"). awk rather than `sed -i`, whose flag
# differs between GNU and BSD.
set_env() {
  local key="$1" value="$2" tmp
  tmp="$(mktemp)"
  awk -v k="$key" -v v="$value" '
    BEGIN { done = 0 }
    index($0, k "=") == 1 { print k "='\''" v "'\''"; done = 1; next }
    { print }
    END { if (!done) print k "='\''" v "'\''" }
  ' .env > "$tmp"
  cat "$tmp" > .env
  rm -f "$tmp"
}

# Runs Python inside the API image, so the host needs no Python or bcrypt.
in_api_image() {
  docker compose run --rm --no-deps -T api "$@"
}

cmd_setup() {
  require_docker
  if env_is_configured; then
    say ".env already has POSTGRES_PASSWORD, SESSION_SECRET and ADMIN_PASSWORD_HASH; leaving it alone."
    echo "    Delete .env and rerun setup to regenerate everything."
    return 0
  fi

  [ -f .env ] || cp .env.example .env
  chmod 600 .env

  local password="${LOCAL_ADMIN_PASSWORD:-}"
  if [ -z "$password" ]; then
    [ -t 0 ] || die "No terminal to prompt on. Set LOCAL_ADMIN_PASSWORD for a non-interactive setup."
    local confirm
    while :; do
      printf 'Choose the operator login password: '
      read -r -s password; echo
      printf 'Repeat it: '
      read -r -s confirm; echo
      if [ -z "$password" ]; then
        echo "The password cannot be empty."
      elif [ "$password" != "$confirm" ]; then
        echo "Those did not match; try again."
      else
        break
      fi
    done
  fi

  say "Building the API image (the generators below run inside it)"
  # A placeholder keeps compose from warning about an unset interpolation while
  # the real value is still being generated.
  POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-setup}" docker compose build api

  say "Generating secrets into .env"
  local token_cmd='import secrets; print(secrets.token_urlsafe(TOKEN_BYTES))'
  set_env POSTGRES_PASSWORD "$(in_api_image python -c "${token_cmd/TOKEN_BYTES/24}" | tr -d '\r')"
  set_env SESSION_SECRET "$(in_api_image python -c "${token_cmd/TOKEN_BYTES/48}" | tr -d '\r')"
  if [ -z "$(env_value SECRETS_KEY)" ]; then
    set_env SECRETS_KEY "$(in_api_image python -m src.db.secrets_cli keygen | tr -d '\r')"
  fi
  # The password travels by environment variable, never on a command line
  # where `ps` would show it.
  set_env ADMIN_PASSWORD_HASH "$(
    LOCAL_ADMIN_PASSWORD="$password" docker compose run --rm --no-deps -T \
      -e LOCAL_ADMIN_PASSWORD api python -c \
      'import bcrypt, os; print(bcrypt.hashpw(os.environ["LOCAL_ADMIN_PASSWORD"].encode(), bcrypt.gensalt()).decode())' \
      | tr -d '\r'
  )"

  env_is_configured || die "setup did not produce a complete .env; check the output above."
  say "Done. .env is gitignored and readable by you only. Next: scripts/local.sh up"
}

wait_for() {
  local label="$1" url="$2" seconds="$3" waited=0
  printf 'Waiting for %s' "$label"
  until curl -fsS -o /dev/null "$url" 2>/dev/null; do
    if [ "$waited" -ge "$seconds" ]; then
      echo
      return 1
    fi
    printf '.'
    sleep 2
    waited=$((waited + 2))
  done
  echo " ready"
}

cmd_up() {
  require_docker
  env_is_configured || die ".env is missing or incomplete. Run: scripts/local.sh setup"

  say "Starting db, api, worker and UI"
  docker compose --profile web up -d --build

  say "Waiting for Postgres"
  local tries=0
  until docker compose exec -T db pg_isready -U trader -d trader >/dev/null 2>&1; do
    tries=$((tries + 1))
    [ "$tries" -lt 60 ] || die "Postgres did not become ready. See: scripts/local.sh logs db"
    sleep 2
  done

  say "Applying migrations (idempotent)"
  docker compose run --rm api python -m src.db.migrate_cli

  wait_for "the API" "$API_URL" 120 || die "The API did not answer. See: scripts/local.sh logs api"
  # `next dev` compiles on first request, which can take a minute or two.
  wait_for "the UI" "$WEB_URL" 300 || die "The UI did not answer. See: scripts/local.sh logs web"

  say "Running locally, paper only"
  echo "    UI      $WEB_URL   (log in with the password you chose at setup)"
  echo "    API     http://localhost:8000"
  echo "    Stop    scripts/local.sh down"
}

cmd_down() {
  require_docker
  docker compose --profile web --profile programme down
  echo "Stopped. The database volume is kept; 'docker compose down -v' would delete it."
}

cmd_status() {
  require_docker
  docker compose --profile web --profile programme ps
  echo
  if curl -fsS "$API_URL" 2>/dev/null; then echo; else echo "API: not answering"; fi
  if curl -fsS -o /dev/null "$WEB_URL" 2>/dev/null; then echo "UI: answering"; else echo "UI: not answering"; fi
}

cmd_logs() {
  require_docker
  docker compose --profile web --profile programme logs -f "$@"
}

# --- check: the CI workflow, locally ------------------------------------------

CHECK_RESULTS=""
record() { CHECK_RESULTS="${CHECK_RESULTS}$1  $2"$'\n'; }

CI_NET="trader-local-ci-$$"
CI_PG="trader-local-ci-pg-$$"
CI_IMAGE="trader-local-ci"

cleanup_check() {
  docker rm -f "$CI_PG" >/dev/null 2>&1 || true
  docker network rm "$CI_NET" >/dev/null 2>&1 || true
}

check_ruff() {
  say "ruff (CI job: lint)"
  docker run --rm -v "$ROOT":/app -w /app "$CI_IMAGE" \
    sh -c 'pip install -q ruff && ruff check --no-cache src/ tests/'
}

check_pytest() {
  say "pytest (CI job: test), against a throwaway Postgres 16"
  docker network create "$CI_NET" >/dev/null
  # Trust auth, as in CI: the container lives for this run only and is
  # reachable only from its private network, so no credential should exist.
  docker run -d --name "$CI_PG" --network "$CI_NET" \
    -e POSTGRES_HOST_AUTH_METHOD=trust -e POSTGRES_DB=trader_test \
    postgres:16 >/dev/null
  local tries=0
  until docker exec "$CI_PG" pg_isready -U postgres -d trader_test >/dev/null 2>&1; do
    tries=$((tries + 1))
    [ "$tries" -lt 30 ] || { echo "Postgres did not start"; return 1; }
    sleep 1
  done

  # Same install and the same named steps as ci.yml, in the same order, so a
  # parity or boundary break is named rather than lost in the unit run.
  docker run --rm --network "$CI_NET" -v "$ROOT":/app -w /app \
    -e PYTHONDONTWRITEBYTECODE=1 \
    -e TEST_DATABASE_URL="postgresql://postgres@$CI_PG:5432/trader_test" \
    "$CI_IMAGE" sh -ec '
      pip install -q pytest pytest-asyncio httpx
      run() { echo; echo "--- $1"; shift; "$@"; }
      run "Backtest/live parity (synthetic prices)" pytest -p no:cacheprovider tests/unit/test_parity.py -q
      run "Backtest/live parity (observed prices)" pytest -p no:cacheprovider tests/unit/test_real_data.py -q
      run "Import boundaries" pytest -p no:cacheprovider tests/unit/test_import_boundaries.py -q
      run "Unit tests" pytest -p no:cacheprovider tests/unit -q
      run "Integration tests" pytest -p no:cacheprovider tests/integration -q
    '
}

check_web() {
  say "next typecheck and build (CI job: web)"
  # Anonymous volumes keep the Linux node_modules and .next out of the host
  # checkout, where they would clash with a native macOS install.
  docker run --rm -v "$ROOT/web":/app -v /app/node_modules -v /app/.next \
    -w /app node:20 sh -ec 'npm ci --no-audit --no-fund && npm run typecheck && npm run build'
}

cmd_check() {
  require_docker
  trap cleanup_check EXIT
  say "Building the engine image the Python gates run in"
  docker build -q -t "$CI_IMAGE" . >/dev/null

  # The three CI jobs are independent, so one failing does not skip the rest.
  if check_ruff; then record PASS ruff; else record FAIL ruff; fi
  if check_pytest; then record PASS pytest; else record FAIL pytest; fi
  if check_web; then record PASS "web build"; else record FAIL "web build"; fi

  say "Local CI summary"
  printf '%s' "$CHECK_RESULTS"
  case "$CHECK_RESULTS" in
    *FAIL*) echo "One or more gates failed."; return 1 ;;
    *) echo "All gates passed." ;;
  esac
}

usage() {
  sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'
}

case "${1:-help}" in
  setup) cmd_setup ;;
  up) cmd_up ;;
  down) cmd_down ;;
  status) cmd_status ;;
  logs) shift; cmd_logs "$@" ;;
  check) cmd_check ;;
  help | -h | --help) usage ;;
  *) usage; exit 1 ;;
esac

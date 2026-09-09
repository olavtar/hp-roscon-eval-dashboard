#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
Usage: ./run.sh <files|live> [extra container run args...]

  files   Offline mode. Reads RECORDS_DIR (default: bundled test fixtures).
  live    Kafka + MinIO over Tailscale. Needs .env.local with S3 credentials.

Common env: PORT, CONTAINER, RECORDS_DIR, VERSIONS_FILE, LIVE_DASHBOARD_URL
Live only:  S3_ENDPOINT, S3_*_BUCKET, KAFKA_BOOTSTRAP, KAFKA_TOPIC
EOF
  exit 1
}

MODE="${1:-}"
[ -n "$MODE" ] && shift || true
[ "$MODE" = "files" ] || [ "$MODE" = "live" ] || usage

PORT="${PORT:-8080}"
IMAGE=evaluation-dashboard
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -n "${CONTAINER:-}" ]; then
  :
elif command -v podman >/dev/null 2>&1; then
  CONTAINER=podman
elif command -v docker >/dev/null 2>&1; then
  CONTAINER=docker
else
  echo "error: need podman or docker on PATH (or set CONTAINER=...)" >&2
  exit 1
fi

"$CONTAINER" build -t "$IMAGE" "$ROOT" >&2

# Fixed name so switching modes (or re-running the same one) doesn't need a
# manual `podman ps` / `podman stop` first -- only one instance of this
# dashboard ever runs at a time, so replacing it outright is correct.
NAME=evaluation-dashboard
"$CONTAINER" rm -f "$NAME" >/dev/null 2>&1 || true

args=(--rm --name "$NAME" -p "$PORT:8080")
if [ -f "$ROOT/config/versions.yaml" ]; then
  args+=(-v "$ROOT/config/versions.yaml:/app/config/versions.yaml:ro")
fi
# The "Back to Live Flywheel" link's target -- a variable, not a hardcoded
# path, since it points at a different machine's dashboard, not this one.
args+=(-e LIVE_DASHBOARD_URL="${LIVE_DASHBOARD_URL:-http://10.0.0.49:30801}")

if [ "$MODE" = "files" ]; then
  RECORDS_DIR="${RECORDS_DIR:-$ROOT/tests/fixtures}"
  args+=(-v "$RECORDS_DIR:/records:ro" -e SOURCE_MODE=files)
else
  if [ ! -f "$ROOT/.env.local" ]; then
    echo "error: live mode needs $ROOT/.env.local with S3_ACCESS_KEY and S3_SECRET_KEY" >&2
    exit 1
  fi
  args+=(--env-file "$ROOT/.env.local")
  args+=(
    -e SOURCE_MODE=live
    -e S3_ENDPOINT="${S3_ENDPOINT:-http://10.0.0.49:30900}"
    -e S3_CURATED_BUCKET="${S3_CURATED_BUCKET:-episodes-curated}"
    -e S3_REJECTED_BUCKET="${S3_REJECTED_BUCKET:-episodes-rejected}"
    -e KAFKA_BOOTSTRAP="${KAFKA_BOOTSTRAP:-10.0.0.49:30903}"
    -e KAFKA_TOPIC="${KAFKA_TOPIC:-episode-manifests}"
  )
fi

exec "$CONTAINER" run "${args[@]}" "$@" "$IMAGE"

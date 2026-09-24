#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# collect.sh — Linux/Bash log collection: streams any local log source into
# the pipeline's /api/logs/ingest endpoint in batches.
#
# This is the "log collection" seat of the SIH mandate stack. The server is
# pure FastAPI; ingestion is source-agnostic — anything that can tail a file,
# journald stream or container stdout can feed it:
#
#   ./scripts/collect.sh                                  # /var/log/syslog
#   SRC="journalctl -f -u sshd -o cat" ./scripts/collect.sh
#   SRC="docker logs -f mycontainer 2>&1" ./scripts/collect.sh
#   SRC="kubectl logs -f pod/api-xyz --tail=0" ./scripts/collect.sh
#   SRC="tail -F /var/log/nginx/access.log" ./scripts/collect.sh
#
# Env:  API      ingest URL (default: the deployed Vercel app)
#       BATCH    lines per POST (default 50)
#       PAUSE    seconds between batches (default 1)
#       INGEST_KEY  sent as x-ingest-key when the server has INGEST_API_KEY set
# ---------------------------------------------------------------------------
set -euo pipefail

API="${API:-https://sih2026-w6sr.vercel.app/api/logs/ingest}"
BATCH="${BATCH:-50}"
PAUSE="${PAUSE:-1}"
SRC="${SRC:-tail -F -n0 /var/log/syslog 2>/dev/null}"
SRC="${SRC:-tail -F -n0 /var/log/messages 2>/dev/null}"

command -v jq  >/dev/null || { echo "collect.sh: 'jq' is required" >&2; exit 1; }
command -v curl >/dev/null || { echo "collect.sh: 'curl' is required" >&2; exit 1; }

echo "collect.sh: source  → $SRC"
echo "collect.sh: posting → $API (batch=$BATCH, pause=${PAUSE}s)  Ctrl-C to stop"

batch=()
sent=0
flush() {
  ((${#batch[@]} == 0)) && return 0
  payload=$(printf '%s\n' "${batch[@]}" | jq -Rs '{logs: (split("\n") | map(select(. != "")))}')
  args=(-fsS -X POST "$API" -H 'content-type: application/json' --data "$payload" -o /dev/null -w '%{http_code}')
  [[ -n "${INGEST_KEY:-}" ]] && args+=(-H "x-ingest-key: $INGEST_KEY")
  code=$(curl "${args[@]}") && sent=$((sent + ${#batch[@]})) \
    && printf '\rcollect.sh: %d lines shipped (last batch %d, HTTP %s)  ' "$sent" "${#batch[@]}" "$code" \
    || printf '\ncollect.sh: batch failed (HTTP %s) — keeping source open\n' "$code" >&2
  batch=()
  sleep "$PAUSE"
}

trap flush EXIT
while IFS= read -r line; do
  batch+=("$line")
  ((${#batch[@]} >= BATCH)) && flush
done < <(eval "$SRC")

#!/usr/bin/env bash
# Reference: bootstrap an account (device id + PAT) and hit an authed endpoint.
set -euo pipefail
URL="${PH_API_URL:-http://localhost:8000}"
DEV="cli-$(date +%s)"

RESP=$(curl -sS -X POST "$URL/check_account" -H 'Content-Type: application/json' \
  -d "{\"device_id\":\"$DEV\"}")
echo "$RESP"
PAT=$(echo "$RESP" | python3 -c 'import json,sys; print(json.load(sys.stdin)["pat"])')
echo "PAT=$PAT DEV=$DEV"

curl -sS "$URL/requests" -H "X-PAT: $PAT" -H "X-Device-Id: $DEV" | python3 -m json.tool

#!/usr/bin/env bash
# Demo: bootstrap a fresh account, send every photo from price_hunter_images,
# poll each request until the pipeline completes.
set -euo pipefail
URL="${PH_API_URL:-http://localhost:8000}"
IMAGES_DIR="${IMAGES_DIR:-/workspace/price_hunter_images}"

DEV="demo-$(date +%s)"
PAT=$(curl -sS -X POST "$URL/check_account" -H 'Content-Type: application/json' \
  -d "{\"device_id\":\"$DEV\"}" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["pat"])')
export PAT DEV

for f in "$IMAGES_DIR"/*.jpg; do
  "$(dirname "$0")/send_photo.sh" "$f"
done

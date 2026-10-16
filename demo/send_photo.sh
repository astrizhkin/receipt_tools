#!/usr/bin/env bash
# Send photo(s) async and poll until done. Requires PAT + DEV env vars
# (bootstrap with curl_auth.sh). Usage: PAT=... DEV=... ./send_photo.sh <file>...
set -euo pipefail
URL="${PH_API_URL:-http://localhost:8000}"
: "${PAT:?set PAT from /check_account}"
: "${DEV:?set DEV (device id)}"

for f in "$@"; do
  echo "==> $f"
  RID=$(curl -sS -X POST "$URL/photo_input" \
    -H "X-PAT: $PAT" -H "X-Device-Id: $DEV" -F "file=@${f}" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["request_id"])')
  echo "request_id=$RID"
  while true; do
    S=$(curl -sS "$URL/requests/$RID" -H "X-PAT: $PAT" -H "X-Device-Id: $DEV")
    echo "  $(echo "$S" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["status"], d.get("stage"), str(d.get("duration_s"))+"s")')"
    case "$S" in *'"status":"completed"'*|*'"status":"failed"'*) break;; esac
    sleep 5
  done
done

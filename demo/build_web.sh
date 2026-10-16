#!/usr/bin/env bash
# Build the Flutter web app into app/build/web (served by the nginx "web"
# compose service on :8090, API proxied at /api/).
set -euo pipefail
cd "$(dirname "$0")/.."
source .env

docker run --rm \
  -v "$PH_HOST_DIR/app":/src \
  -v ph_pub_cache:/root/.pub-cache \
  price-hunter-flutter-builder \
  flutter build web --no-web-resources-cdn

echo "web build: app/build/web (compose 'web' service serves it on :8090)"

#!/usr/bin/env bash
# One-time: generate the Flutter Android scaffold inside the builder container.
set -euo pipefail
cd "$(dirname "$0")/.."
source .env

IMAGE=price-hunter-flutter-builder
docker build -t "$IMAGE" docker/flutter-builder

docker run --rm -v "$PH_HOST_DIR/app":/src "$IMAGE" \
  flutter create --org com.pricehunter --project-name price_hunter --platforms android .

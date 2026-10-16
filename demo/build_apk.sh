#!/usr/bin/env bash
# Build the Android APK inside the flutter-builder container, then publish it
# to the in-app update channel (artifacts/release/, served by the pipeline at
# /app_update + /app_update/apk).
#
# Release signing: $PH_KEYSTORE_DIR (host, outside the repo) holds
# receipt_tools-release.jks + storepass.txt; mounted read-only at /secrets.
# Without it the build falls back to DEBUG signing (warning below).
set -euo pipefail
cd "$(dirname "$0")/.."
source .env

IMAGE=receipt-tools-flutter-builder
docker build -t "$IMAGE" docker/flutter-builder

# every build bumps the build number (the +N in "version: 1.0.0+N"): it becomes
# the Android versionCode and drives the in-app update comparison
PUBSPEC=app/pubspec.yaml
VER=$(grep -m1 '^version:' "$PUBSPEC" | sed 's/^version: *//')
NAME=${VER%%+*}; CODE=${VER##*+}
NEW=$((CODE + 1))
sed -i "s/^version: .*/version: ${NAME}+${NEW}/" "$PUBSPEC"
echo "version bumped: $NAME+$CODE -> $NAME+$NEW"

SECRET_MOUNT=()
# NOTE: this script runs in the claude container, which cannot see the daemon
# host's filesystem — do NOT test the host path with -f here. The daemon
# resolves the bind source; gradle falls back to debug signing if /secrets is
# empty inside the container.
if [ -n "${PH_KEYSTORE_DIR:-}" ]; then
  SECRET_MOUNT=(-v "$PH_KEYSTORE_DIR:/secrets:ro")
else
  echo "WARNING: PH_KEYSTORE_DIR unset — release APK will be DEBUG-signed" >&2
fi

# ph_android_sdk persists the Android SDK (incl. the ~700MB NDK AGP installs
# on demand) across builds — without it every --rm container re-downloads it.
docker run --rm \
  -v "$PH_HOST_DIR/app":/src \
  -v ph_pub_cache:/root/.pub-cache \
  -v ph_gradle_cache:/root/.gradle \
  -v ph_android_sdk:/opt/android-sdk \
  "${SECRET_MOUNT[@]}" \
  "$IMAGE" flutter build apk --release

APK=app/build/app/outputs/flutter-apk/app-release.apk
mkdir -p artifacts/release
cp "$APK" artifacts/release/app-release.apk

SHA=$(sha256sum artifacts/release/app-release.apk | cut -d' ' -f1)
SIZE=$(stat -c%s artifacts/release/app-release.apk)
cat > artifacts/release/version.json <<EOF
{
  "version_name": "$NAME",
  "version_code": $NEW,
  "sha256": "$SHA",
  "size_bytes": $SIZE,
  "force": false,
  "notes": "",
  "built_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF

echo "APK: $APK"
echo "update channel: artifacts/release/ (v$NAME build $NEW, sha256 ${SHA:0:12}...)"

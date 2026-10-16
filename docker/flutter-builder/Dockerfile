# Flutter + Android SDK build container for the price_hunter app.
# The app source is bind-mounted at /src; build output lands in /src/build
# (so the APK is visible on the host). Gradle/pub caches are named volumes.
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    ANDROID_HOME=/opt/android-sdk \
    FLUTTER_ROOT=/opt/flutter \
    PUB_CACHE=/root/.pub-cache

RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl unzip xz-utils zip ca-certificates \
        openjdk-17-jdk-headless \
    && rm -rf /var/lib/apt/lists/*

ARG FLUTTER_VERSION=3.47.7
RUN curl -fsSL \
      "https://storage.googleapis.com/flutter_infra_release/releases/stable/linux/flutter_linux_${FLUTTER_VERSION}-stable.tar.xz" \
      | tar -xJ -C /opt \
    && git config --global --add safe.directory /opt/flutter

# Android cmdline-tools + SDK packages (licenses accepted at build time)
RUN curl -fsSL -o /tmp/cmdline.zip \
      https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip \
    && mkdir -p "$ANDROID_HOME/cmdline-tools" \
    && unzip -q /tmp/cmdline.zip -d "$ANDROID_HOME/cmdline-tools" \
    && mv "$ANDROID_HOME/cmdline-tools/cmdline-tools" "$ANDROID_HOME/cmdline-tools/latest" \
    && rm /tmp/cmdline.zip \
    && yes | "$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" --licenses >/dev/null \
    && "$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" \
        "platform-tools" "platforms;android-35" "platforms;android-36" "build-tools;36.0.0" >/dev/null

# NDK as its own layer (caches independently; ~2.5GB). Flutter's
# flutter.ndkVersion (3.47.7 -> 28.2.13676358) makes AGP demand this exact
# revision at build time; baked in here so no build ever re-downloads it.
# Keep in sync with FLUTTER_VERSION above.
RUN "$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager" "ndk;28.2.13676358" >/dev/null

ENV PATH="/opt/flutter/bin:/opt/flutter/bin/cache/dart-sdk/bin:$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$PATH"

WORKDIR /src
CMD ["flutter", "build", "apk", "--release"]

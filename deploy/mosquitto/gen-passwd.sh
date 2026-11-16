#!/usr/bin/env bash
# Generate the local Mosquitto password file.
#
# Usage:
#   DEVICE_PASSWORD=... HUB_MQTT_PASSWORD=... ./deploy/mosquitto/gen-passwd.sh
#
# Passwords containing single quotes are rejected rather than silently mangled.
set -euo pipefail

: "${DEVICE_PASSWORD:?set DEVICE_PASSWORD}"
: "${HUB_MQTT_PASSWORD:?set HUB_MQTT_PASSWORD}"

case "$DEVICE_PASSWORD$HUB_MQTT_PASSWORD" in
  *"'"*)
    echo "single quotes are not supported in passwords" >&2
    exit 1
    ;;
esac

DEVICE_ID="0192f3c4-1a2b-7c3d-8e4f-5a6b7c8d9e0f"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

docker run --rm -v "$DIR:/work" eclipse-mosquitto:2 sh -c \
  "rm -f /work/passwd && \
   mosquitto_passwd -b -c /work/passwd hub '$HUB_MQTT_PASSWORD' && \
   mosquitto_passwd -b /work/passwd 'd_$DEVICE_ID' '$DEVICE_PASSWORD' && \
   chmod 644 /work/passwd"

echo "wrote $DIR/passwd"

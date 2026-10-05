#!/bin/bash
# The stock image starts on every visible CPU. Railway containers see the whole
# host, and Seastar then requests more AIO slots than the host allows.
# One core fits. The volume is root-owned, so fix ownership before dropping
# to the redpanda user. Advertise the private hostname other Pulse services dial.
set -euo pipefail
chown -R redpanda:redpanda /var/lib/redpanda /etc/redpanda

su -s /bin/bash redpanda -c "exec /usr/bin/rpk redpanda start \
  --overprovisioned \
  --smp 1 \
  --memory 1G \
  --reserve-memory 0M \
  --default-log-level=warn \
  --kafka-addr internal://0.0.0.0:9092 \
  --advertise-kafka-addr internal://${RAILWAY_PRIVATE_DOMAIN}:9092" &
child=$!
trap 'kill "$child" 2>/dev/null || true; wait "$child"' TERM INT

for _ in $(seq 1 90); do
  if /usr/bin/rpk topic list --brokers 127.0.0.1:9092 >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

for spec in "raw-spans 12" "raw-spans.dlq 1" "judge-requests 12" "judge-requests.backfill 12" "judge-requests.dlq 1"; do
  # shellcheck disable=SC2086
  set -- $spec
  /usr/bin/rpk topic create "$1" -p "$2" --brokers 127.0.0.1:9092 || echo "[redpanda] topic create failed: $1"
done

wait "$child"

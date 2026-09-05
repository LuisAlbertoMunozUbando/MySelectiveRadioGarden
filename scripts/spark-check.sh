#!/usr/bin/env bash
set -euo pipefail

echo "NVIDIA"
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv
else
  echo "nvidia-smi: not found"
fi

echo "Docker"
docker --version
docker compose version

echo "Containers"
docker compose ps

echo "API"
SPARK_API_PORT="$(sed -n 's/^SPARK_API_PORT=//p' .env | tail -n 1)"
SPARK_API_PORT="${SPARK_API_PORT:-8010}"
curl --fail --show-error "http://localhost:${SPARK_API_PORT}/health"
echo

echo "Diagnostics"
curl --fail --show-error "http://localhost:${SPARK_API_PORT}/v1/diagnostics"
echo

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
curl --fail --show-error http://localhost:8000/health
echo

echo "Diagnostics"
curl --fail --show-error http://localhost:8000/v1/diagnostics
echo

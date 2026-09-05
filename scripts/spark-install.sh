#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${1:-$PWD}"
cd "$PROJECT_DIR"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required. Install Docker Engine before continuing."
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose v2 is required."
  exit 1
fi

if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
else
  echo "Warning: nvidia-smi was not found. The API can start, but ASR acceleration is not verified."
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env. Configure ASR_URL, LLM_URL and CLOUDFLARE_TUNNEL_TOKEN before enabling AI and tunnel services."
fi

docker compose build spark-api
docker compose up -d spark-api
sleep 3
SPARK_API_PORT="$(sed -n 's/^SPARK_API_PORT=//p' .env | tail -n 1)"
SPARK_API_PORT="${SPARK_API_PORT:-8010}"
curl --fail --show-error "http://localhost:${SPARK_API_PORT}/health"
echo
echo "Spark API is running locally on http://localhost:${SPARK_API_PORT}"

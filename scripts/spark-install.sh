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

SPARK_API_PORT="$(sed -n 's/^SPARK_API_PORT=//p' .env | tail -n 1)"
if [ -z "$SPARK_API_PORT" ]; then
  for candidate in $(seq 8010 8099); do
    if ! ss -H -ltn "sport = :${candidate}" | grep -q .; then
      SPARK_API_PORT="$candidate"
      break
    fi
  done
  if [ -z "$SPARK_API_PORT" ]; then
    echo "No free port was found between 8010 and 8099."
    exit 1
  fi
  printf '\nSPARK_API_PORT=%s\n' "$SPARK_API_PORT" >> .env
  echo "Selected free host port: $SPARK_API_PORT"
fi

docker compose build spark-api
docker compose up -d spark-api
sleep 3
curl --fail --show-error "http://localhost:${SPARK_API_PORT}/health"
echo
echo "Spark API is running locally on http://localhost:${SPARK_API_PORT}"

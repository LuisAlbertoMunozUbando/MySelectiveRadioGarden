# DGX Spark setup

## 1. Clone and start the API

```bash
git clone https://github.com/LuisAlbertoMunozUbando/MySelectiveRadioGarden.git
cd MySelectiveRadioGarden
chmod +x scripts/spark-install.sh scripts/spark-check.sh
./scripts/spark-install.sh
```

Confirm that `http://localhost:8010/health` reports `status: ok` and
`ffmpeg: true`.

## 2. Connect the local AI services

Edit `.env`:

```dotenv
ASR_URL=http://host.docker.internal:9000
LLM_URL=http://host.docker.internal:8001
LLM_MODEL=Qwen/Qwen2.5-7B-Instruct
```

`ASR_URL` must expose an OpenAI-compatible `POST /v1/audio/transcriptions`
endpoint. `LLM_URL` must expose an OpenAI-compatible
`POST /v1/chat/completions` endpoint, such as vLLM.

Restart after editing:

```bash
docker compose up -d --build spark-api
./scripts/spark-check.sh
```

## 3. Create the Cloudflare Tunnel

Create a tunnel whose public hostname is `api-radio.albertomunoz.ai` and whose
service is `http://spark-api:8000`. Copy its token into `.env`:

```dotenv
CLOUDFLARE_TUNNEL_TOKEN=your-token
```

Then start the tunnel profile:

```bash
docker compose --profile tunnel up -d
```

Do not commit `.env`; it is ignored by Git.

## 4. Verify remotely

```bash
curl https://api-radio.albertomunoz.ai/health
```

The frontend can then use `https://api-radio.albertomunoz.ai` as its API URL.

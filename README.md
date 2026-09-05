# MySelectiveRadioGarden

An on-demand radio intelligence dashboard designed for an NVIDIA DGX Spark. The web interface lets the user choose stations, start a monitoring session, compare rolling two-minute summaries, and listen to one station while the others remain under analysis.

## Current MVP

- Responsive, interactive frontend with five default stations.
- Start/stop session states and live timer.
- Station management and output-language selector.
- Relevance-ranked summaries and listening state.
- FastAPI contract for Spark session orchestration.
- Docker Compose foundation for local deployment behind Cloudflare Tunnel.

The visible summaries are demonstration data until the Spark audio pipeline is connected.

## Frontend

```bash
npm install
npm run dev
```

## Spark API

```bash
docker compose up --build
```

The API listens on port `8000`. Copy `.env.example` to `.env` and provide a Cloudflare Tunnel token only when the tunnel has been created.

## Proposed production domains

- `radio.albertomunoz.ai` — frontend
- `api-radio.albertomunoz.ai` — Spark API through Cloudflare Tunnel

## Next integration slice

1. Resolve and validate authorized station stream URLs.
2. Add FFmpeg workers and a 120-second rolling audio buffer.
3. Connect Parakeet/Canary ASR and Qwen summarization.
4. Replace demonstration state with the API and Server-Sent Events.
5. Protect the API with Cloudflare Access.

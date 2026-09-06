# MySelectiveRadioGarden

🌍🎧 **An intelligent way to explore live radio around the world.**

I love listening to international radio. With [Radio Garden](https://radio.garden), I can jump from Mexico City to London, Paris, Vienna, Rome, Illinois, Japan, or China in seconds.

The problem is that I cannot keep switching between stations all day just to discover what each one is discussing. That is why I created **MySelectiveRadioGarden**: an intelligent listening assistant that analyzes several selected stations and tells me what is happening before I decide where to tune in.

- 🔴 **Live application:** [radio.albertomunoz.ai](https://radio.albertomunoz.ai)
- 💻 **Source code:** [github.com/LuisAlbertoMunozUbando/MySelectiveRadioGarden](https://github.com/LuisAlbertoMunozUbando/MySelectiveRadioGarden)
- 🌱 **Explore global radio:** [radio.garden](https://radio.garden)

## How it works

The workflow is intentionally simple:

1. Select one or more radio stations.
2. Press **Start Analysis**.
3. The NVIDIA DGX Spark captures approximately 30 seconds of live audio from every selected station.
4. NVIDIA Parakeet transcribes each broadcast.
5. A local Qwen LLM identifies the main topic and creates a concise summary.
6. The dashboard displays the results so the listener can choose the most interesting station.
7. While one station is playing, the application can continue analyzing the other selected stations.

The system can:

- 🎙️ Capture short samples of live radio.
- 📝 Generate multilingual transcriptions.
- 🌐 Detect and process different broadcast languages.
- 🧠 Identify the main subject without requiring a predefined topic preference.
- 📋 Produce a concise summary for each station.
- 💾 Save the analyzed audio, transcript, and structured JSON results by date, time, and station.
- 🎧 Open the selected station through its original Radio Garden page or official player.
- 🔄 Keep monitoring the remaining selected stations while the user listens.

The goal is **not to retransmit radio stations**. The application processes short, temporary samples and helps the user decide what to listen to. Station links should be validated, and available official live streams are used for analysis.

## Supported interface and summary languages

The dashboard, transcriptions, translations, and summaries are designed to support:

- 🇲🇽 Spanish
- 🇬🇧 English
- 🇫🇷 French
- 🇯🇵 Japanese
- 🇨🇳 Chinese
- 🇮🇹 Italian
- 🇩🇪 German
- 🇮🇱 Hebrew
- 🇸🇦 Arabic

## Hybrid architecture

| Component | Responsibility |
| --- | --- |
| ⚡ NVIDIA DGX Spark | Audio capture, transcription, translation, classification, and summarization |
| 🎙️ NVIDIA Parakeet | Multilingual automatic speech recognition |
| 🧠 Qwen + vLLM | Local topic detection and concise summaries |
| ▲ Vercel | Globally accessible web dashboard |
| ☁️ Cloudflare Tunnel | Secure outbound connection from the Spark without opening router ports |
| 🔐 Cloudflare Access | Authentication and protection for the private Spark API |
| 🐙 GitHub | Source code, version control, and deployment workflow |
| 💾 Local storage + Google Drive | Audio, transcripts, and JSON analysis organized by station and time |
| 🌱 Radio Garden / official streams | Station discovery and the original listening destination |

Only text and analysis metadata need to travel to the web interface. The AI inference and sensitive processing remain local on the DGX Spark.

## Current MVP

- Responsive dashboard with default international stations.
- Add/remove station management.
- Station selection before starting an analysis.
- On-demand 30-second sampling rather than permanent monitoring.
- Start/stop session states and live status.
- Output-language selector.
- Multilingual ASR with NVIDIA Parakeet.
- Local Qwen summarization through vLLM.
- FastAPI session orchestration.
- Audio, text, and JSON output artifacts.
- Docker Compose deployment behind Cloudflare Tunnel.
- Button to open the original Radio Garden station.

## Frontend

```bash
npm install
npm run dev
```

## Spark API

```bash
docker compose up --build
```

The installer selects an available host port between `8010` and `8099` while the container uses port `8000`. Copy `.env.example` to `.env` and configure the ASR, LLM, output, and Cloudflare settings required by your installation.

For the DGX Spark installation, follow [`docs/SPARK_SETUP.md`](docs/SPARK_SETUP.md) or run:

```bash
chmod +x scripts/spark-install.sh scripts/spark-check.sh
./scripts/spark-install.sh
./scripts/spark-check.sh
```

## Production domains

- [radio.albertomunoz.ai](https://radio.albertomunoz.ai) — Vercel frontend
- [api-radio.albertomunoz.ai](https://api-radio.albertomunoz.ai) — Spark API through Cloudflare Tunnel and Cloudflare Access

## Project direction

The project is evolving toward a reliable personal radio-intelligence platform with:

- Better validation of authorized station streams.
- Improved handling of stations whose stream URLs expire or redirect.
- Parallel analysis with controlled GPU load.
- Rolling summaries and optional topic alerts.
- Reliable Google Drive synchronization.
- Session history and searchable transcripts.
- Real-time updates through Server-Sent Events or WebSockets.

**MySelectiveRadioGarden lets me explore the world's radio without spending all my time switching stations.** 🌎🎶

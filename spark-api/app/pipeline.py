import asyncio
import io
import json
import math
import os
import shutil
import wave
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import AsyncIterator

import httpx

SAMPLE_RATE = 16_000
BYTES_PER_SECOND = SAMPLE_RATE * 2


@dataclass
class SessionRuntime:
    id: str
    output_language: str
    interests: list[str]
    stations: list[dict]
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: str = "starting"
    results: dict[str, dict] = field(default_factory=dict)
    tasks: list[asyncio.Task] = field(default_factory=list)
    subscribers: set[asyncio.Queue] = field(default_factory=set)


class RadioPipeline:
    def __init__(self) -> None:
        self.sessions: dict[str, SessionRuntime] = {}
        self.window_seconds = int(os.getenv("SUMMARY_WINDOW_SECONDS", "120"))
        self.refresh_seconds = int(os.getenv("SUMMARY_REFRESH_SECONDS", "30"))
        self.asr_url = os.getenv("ASR_URL", "").rstrip("/")
        self.llm_url = os.getenv("LLM_URL", "").rstrip("/")
        self.llm_model = os.getenv("LLM_MODEL", "Qwen/Qwen2.5-7B-Instruct")
        self.asr_backend = "nvidia-nim" if self.asr_url else "pending"
        self.summary_backend = "vllm" if self.llm_url else "extractive-fallback"

    @property
    def session_count(self) -> int:
        return len(self.sessions)

    async def ffmpeg_available(self) -> bool:
        return shutil.which("ffmpeg") is not None

    def configuration(self) -> dict:
        return {"summary_window_seconds": self.window_seconds, "summary_refresh_seconds": self.refresh_seconds,
                "asr_configured": bool(self.asr_url), "llm_configured": bool(self.llm_url),
                "llm_model": self.llm_model}

    async def start(self, session: SessionRuntime) -> None:
        if not await self.ffmpeg_available():
            raise RuntimeError("FFmpeg is not installed")
        self.sessions[session.id] = session
        session.status = "analyzing"
        for station in session.stations:
            session.tasks.append(asyncio.create_task(self._monitor_station(session, station)))
        await self._publish(session, {"type": "session_started", "session_id": session.id})

    async def stop(self, session_id: str) -> bool:
        session = self.sessions.pop(session_id, None)
        if session is None:
            return False
        for task in session.tasks:
            task.cancel()
        await asyncio.gather(*session.tasks, return_exceptions=True)
        return True

    async def stop_all(self) -> None:
        await asyncio.gather(*(self.stop(sid) for sid in list(self.sessions)))

    def snapshot(self, session_id: str) -> dict:
        session = self.sessions[session_id]
        return {"id": session.id, "status": session.status, "created_at": session.created_at,
                "output_language": session.output_language, "interests": session.interests,
                "stations": session.stations, "results": session.results}

    async def events(self, session_id: str) -> AsyncIterator[dict]:
        session = self.sessions[session_id]
        queue: asyncio.Queue = asyncio.Queue(maxsize=50)
        session.subscribers.add(queue)
        try:
            yield {"type": "snapshot", "session": self.snapshot(session_id)}
            while session_id in self.sessions:
                try:
                    yield await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield {"type": "heartbeat", "timestamp": self._now()}
        finally:
            session.subscribers.discard(queue)

    async def _publish(self, session: SessionRuntime, event: dict) -> None:
        event.setdefault("timestamp", self._now())
        for queue in list(session.subscribers):
            if not queue.full():
                queue.put_nowait(event)

    async def _monitor_station(self, session: SessionRuntime, station: dict) -> None:
        station_id, max_bytes = station["id"], self.window_seconds * BYTES_PER_SECOND
        chunks: deque[bytes] = deque()
        transcript_segments: deque[str] = deque(
            maxlen=max(1, math.ceil(self.window_seconds / self.refresh_seconds)))
        buffered, process = 0, None
        try:
            process = await asyncio.create_subprocess_exec(
                "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-reconnect", "1",
                "-reconnect_streamed", "1", "-reconnect_delay_max", "5", "-i", station["stream_url"],
                "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "s16le", "pipe:1",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            last_analysis = asyncio.get_running_loop().time()
            while True:
                chunk = await process.stdout.read(BYTES_PER_SECOND * 2)
                if not chunk:
                    error = (await process.stderr.read()).decode(errors="replace")[-500:]
                    raise RuntimeError(error or "Radio stream ended")
                chunks.append(chunk); buffered += len(chunk)
                while buffered > max_bytes and chunks:
                    buffered -= len(chunks.popleft())
                now = asyncio.get_running_loop().time()
                if now - last_analysis >= self.refresh_seconds and buffered >= min(max_bytes, 20 * BYTES_PER_SECOND):
                    last_analysis = now
                    pcm = b"".join(chunks)
                    interval_bytes = self.refresh_seconds * BYTES_PER_SECOND
                    segment = await self._transcribe(
                        self._wav_bytes(pcm[-interval_bytes:]), station.get("language"))
                    if segment.strip():
                        transcript_segments.append(segment.strip())
                    transcript = " ".join(transcript_segments)
                    result = await self._summarize(transcript, session.output_language, session.interests)
                    result.update({"station_id": station_id, "station_name": station["name"], "updated_at": self._now()})
                    session.results[station_id] = result
                    await self._publish(session, {"type": "station_update", "result": result})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            error = {"type": "station_error", "station_id": station_id, "message": str(exc)[:500]}
            session.results[station_id] = error
            await self._publish(session, error)
        finally:
            if process and process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=3)
                except asyncio.TimeoutError:
                    process.kill()

    async def _transcribe(self, wav_audio: bytes, language: str | None) -> str:
        if not self.asr_url:
            return "ASR_URL no está configurado todavía en el Spark."
        language_codes = {
            "ar": "ar-AR", "de": "de-DE", "en": "en-US", "es": "es-US",
            "fr": "fr-FR", "he": "he-IL", "hi": "hi-IN", "it": "it-IT",
            "ja": "ja-JP", "ko": "ko-KR", "nl": "nl-NL", "no": "nb-NO",
            "pl": "pl-PL", "pt": "pt-BR", "ru": "ru-RU", "sv": "sv-SE",
            "th": "th-TH", "tr": "tr-TR",
        }
        normalized_language = language_codes.get((language or "").lower(), language or "multi")
        data = {"language": normalized_language}
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(f"{self.asr_url}/v1/audio/transcriptions", data=data,
                                         files={"file": ("radio.wav", wav_audio, "audio/wav")})
            response.raise_for_status()
            payload = response.json()
            return payload.get("text") or payload.get("transcript") or str(payload)

    async def _summarize(self, transcript: str, output_language: str, interests: list[str]) -> dict:
        if not self.llm_url:
            return {"topic": "Transcripción reciente", "summary": transcript[-600:], "relevance": 0,
                    "transcript": transcript}
        prompt = ("Analiza una transcripción de radio. Responde exclusivamente JSON con topic, summary y "
                  f"relevance (0-100), sin Markdown ni comentarios. Idioma: {output_language}. "
                  f"Intereses: {', '.join(interests)}. Texto: {transcript}")
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(f"{self.llm_url}/v1/chat/completions",
                json={"model": self.llm_model, "messages": [{"role": "user", "content": prompt}],
                      "temperature": 0.1, "response_format": {"type": "json_object"}})
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            try:
                cleaned = content.strip().removeprefix("```json").removeprefix("```").strip()
                object_start = cleaned.find("{")
                result, _ = json.JSONDecoder().raw_decode(cleaned[object_start:])
            except Exception:
                result = {"topic": "Conversación en vivo", "summary": content, "relevance": 50}
            result["transcript"] = transcript
            return result

    @staticmethod
    def _wav_bytes(pcm: bytes) -> bytes:
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(SAMPLE_RATE); wav.writeframes(pcm)
        return output.getvalue()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

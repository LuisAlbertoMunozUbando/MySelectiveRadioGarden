import asyncio
import io
import json
import math
import os
import re
import shutil
import wave
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator
from zoneinfo import ZoneInfo

import httpx

SAMPLE_RATE = 16_000
BYTES_PER_SECOND = SAMPLE_RATE * 2


@dataclass
class SessionRuntime:
    id: str
    output_language: str
    interests: list[str]
    stations: list[dict]
    analysis_duration_seconds: int = 30
    continuous: bool = False
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
        self.archive_dir = os.getenv("AUDIO_ARCHIVE_DIR", "").strip()
        self.archive_timezone = os.getenv("AUDIO_ARCHIVE_TIMEZONE", "America/Monterrey")
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
                "llm_model": self.llm_model, "audio_archive_enabled": bool(self.archive_dir),
                "audio_archive_timezone": self.archive_timezone}

    async def start(self, session: SessionRuntime) -> None:
        if not await self.ffmpeg_available():
            raise RuntimeError("FFmpeg is not installed")
        self.sessions[session.id] = session
        session.status = "analyzing"
        station_tasks = [asyncio.create_task(self._monitor_station(session, station))
                         for station in session.stations]
        session.tasks.extend(station_tasks)
        if not session.continuous:
            session.tasks.append(asyncio.create_task(self._complete_session(session, station_tasks)))
        await self._publish(session, {"type": "session_started", "session_id": session.id})

    async def _complete_session(self, session: SessionRuntime, station_tasks: list[asyncio.Task]) -> None:
        await asyncio.gather(*station_tasks, return_exceptions=True)
        if session.id in self.sessions:
            session.status = "completed"
            await self._publish(session, {"type": "session_completed", "session_id": session.id})

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
        interval_seconds = session.analysis_duration_seconds if not session.continuous else self.refresh_seconds
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
                if now - last_analysis >= interval_seconds and buffered >= min(
                        max_bytes, interval_seconds * BYTES_PER_SECOND):
                    last_analysis = now
                    pcm = b"".join(chunks)
                    interval_bytes = interval_seconds * BYTES_PER_SECOND
                    wav_audio = self._wav_bytes(pcm[-interval_bytes:])
                    segment = await self._transcribe(wav_audio, station.get("language"))
                    if segment.strip():
                        transcript_segments.append(segment.strip())
                    transcript = " ".join(transcript_segments)
                    result = await self._summarize(transcript, session.output_language, session.interests)
                    result.update({"station_id": station_id, "station_name": station["name"], "updated_at": self._now()})
                    if self.archive_dir:
                        try:
                            await self._archive_analysis(wav_audio, station, transcript, result)
                        except Exception as exc:
                            await self._publish(session, {"type": "archive_error", "station_id": station_id,
                                                          "message": str(exc)[:500]})
                    session.results[station_id] = result
                    await self._publish(session, {"type": "station_update", "result": result})
                    if not session.continuous:
                        return
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
        normalized_language = language_codes.get((language or "").lower(), "multi")
        data = {"language": normalized_language}
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(f"{self.asr_url}/v1/audio/transcriptions", data=data,
                                         files={"file": ("radio.wav", wav_audio, "audio/wav")})
            response.raise_for_status()
            payload = response.json()
            return payload.get("text") or payload.get("transcript") or str(payload)

    async def _archive_analysis(
            self, wav_audio: bytes, station: dict, transcript: str, result: dict) -> None:
        try:
            local_now = datetime.now(ZoneInfo(self.archive_timezone))
        except Exception:
            local_now = datetime.now(timezone.utc)
        station_name = re.sub(r"[^\w .-]+", "_", station["name"], flags=re.UNICODE).strip(" ._")
        destination = (Path(self.archive_dir) / local_now.strftime("%Y-%m-%d") /
                       (station_name or station["id"]) / local_now.strftime("%H"))
        destination.mkdir(parents=True, exist_ok=True)
        basename = local_now.strftime("%H-%M-%S")
        audio_temp = destination / f"{basename}.opus.part"
        audio_output = destination / f"{basename}.opus"
        text_temp = destination / f"{basename}.txt.part"
        text_output = destination / f"{basename}.txt"
        json_temp = destination / f"{basename}.json.part"
        json_output = destination / f"{basename}.json"
        process = await asyncio.create_subprocess_exec(
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-i", "pipe:0", "-map_metadata", "-1", "-c:a", "libopus", "-b:a", "32k",
            "-application", "audio", "-f", "opus", str(audio_temp), stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        _, error = await process.communicate(wav_audio)
        if process.returncode:
            audio_temp.unlink(missing_ok=True)
            raise RuntimeError(error.decode(errors="replace")[-500:] or "Could not archive analyzed audio")
        text_temp.write_text(
            f"Estación: {station['name']}\n"
            f"Fecha: {local_now.isoformat()}\n"
            f"Tema: {result.get('topic', '')}\n"
            f"Tipo: {result.get('content_type', '')}\n\n"
            f"Resumen:\n{result.get('summary', '')}\n\n"
            f"Transcripción:\n{transcript}\n",
            encoding="utf-8")
        json_temp.write_text(json.dumps({
            "station": station,
            "analyzed_at": local_now.isoformat(),
            "analysis_duration_seconds": 30,
            "transcript": transcript,
            "analysis": result,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        audio_temp.replace(audio_output)
        text_temp.replace(text_output)
        json_temp.replace(json_output)

    async def _summarize(self, transcript: str, output_language: str, interests: list[str]) -> dict:
        if not self.llm_url:
            return {"topic": "Transcripción reciente", "summary": transcript[-600:], "relevance": 0,
                    "transcript": transcript, "translated_transcript": transcript}
        interest_instruction = (
            f"Evalúa relevance (0-100) para estos intereses: {', '.join(interests)}."
            if interests else
            "El análisis debe ser neutral: no hay temas preferidos. Usa relevance=0."
        )
        prompt = ("Analiza una transcripción de radio. Responde exclusivamente JSON con topic, summary, "
                  "content_type, relevance y translated_transcript, sin Markdown ni comentarios. "
                  f"Escribe topic, summary y translated_transcript en el idioma ISO {output_language}. "
                  "translated_transcript debe traducir fielmente la transcripción completa, sin resumirla. "
                  f"{interest_instruction} Texto: {transcript}")
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

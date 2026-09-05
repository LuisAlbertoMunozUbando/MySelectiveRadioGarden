import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, HttpUrl

from .pipeline import RadioPipeline, SessionRuntime


class Station(BaseModel):
    id: str
    name: str
    stream_url: HttpUrl
    radio_garden_url: HttpUrl | None = None
    language: str | None = None


class StartSession(BaseModel):
    stations: list[Station] = Field(min_length=1, max_length=25)
    output_language: str = "es"
    interests: list[str] = Field(default_factory=list, max_length=50)
    analysis_duration_seconds: int = Field(default=30, ge=20, le=120)
    continuous: bool = False


pipeline = RadioPipeline()


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await pipeline.stop_all()


app = FastAPI(title="MySelectiveRadioGarden Spark API", version="0.2.0", lifespan=lifespan)
allowed_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,https://radio.albertomunoz.ai").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in allowed_origins if origin.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "spark-api", "version": app.version,
            "active_sessions": pipeline.session_count, "ffmpeg": await pipeline.ffmpeg_available(),
            "asr_backend": pipeline.asr_backend, "summary_backend": pipeline.summary_backend}


@app.post("/v1/sessions", status_code=201)
async def start_session(request: StartSession) -> dict:
    session_id = str(uuid4())
    runtime = SessionRuntime(
        id=session_id, output_language=request.output_language, interests=request.interests,
        analysis_duration_seconds=request.analysis_duration_seconds, continuous=request.continuous,
        stations=[{**station.model_dump(mode="json"), "stream_url": str(station.stream_url),
                   "radio_garden_url": str(station.radio_garden_url) if station.radio_garden_url else None}
                  for station in request.stations])
    await pipeline.start(runtime)
    return pipeline.snapshot(session_id)


@app.get("/v1/sessions/{session_id}")
async def get_session(session_id: str) -> dict:
    try:
        return pipeline.snapshot(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc


@app.delete("/v1/sessions/{session_id}", status_code=204)
async def stop_session(session_id: str) -> None:
    if not await pipeline.stop(session_id):
        raise HTTPException(status_code=404, detail="Session not found")


async def event_stream(session_id: str) -> AsyncIterator[str]:
    try:
        async for event in pipeline.events(session_id):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
    except KeyError:
        return


@app.get("/v1/sessions/{session_id}/events")
async def session_events(session_id: str) -> StreamingResponse:
    try:
        pipeline.snapshot(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Session not found") from exc
    return StreamingResponse(event_stream(session_id), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/v1/diagnostics")
async def diagnostics() -> dict:
    return {"timestamp": datetime.now(timezone.utc).isoformat(), "environment": pipeline.configuration(),
            "ffmpeg_available": await pipeline.ffmpeg_available()}

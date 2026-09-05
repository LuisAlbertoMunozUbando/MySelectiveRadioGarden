import asyncio
import json
import os
from datetime import datetime, timezone
from typing import AsyncIterator
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field


class Station(BaseModel):
    id: str
    name: str
    stream_url: str | None = None
    radio_garden_url: str | None = None
    language: str | None = None


class StartSession(BaseModel):
    stations: list[Station] = Field(min_length=1, max_length=25)
    output_language: str = "es"
    interests: list[str] = []


app = FastAPI(title="MySelectiveRadioGarden Spark API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "https://radio.albertomunoz.ai"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

sessions: dict[str, dict] = {}


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "spark-api", "active_sessions": len(sessions)}


@app.post("/v1/sessions", status_code=201)
def start_session(request: StartSession) -> dict:
    session_id = str(uuid4())
    sessions[session_id] = {
        "id": session_id,
        "status": "starting",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "output_language": request.output_language,
        "interests": request.interests,
        "stations": [station.model_dump() for station in request.stations],
    }
    return sessions[session_id]


@app.get("/v1/sessions/{session_id}")
def get_session(session_id: str) -> dict:
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    return sessions[session_id]


@app.delete("/v1/sessions/{session_id}", status_code=204)
def stop_session(session_id: str) -> None:
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    del sessions[session_id]


async def event_stream(session_id: str) -> AsyncIterator[str]:
    refresh = int(os.getenv("SUMMARY_REFRESH_SECONDS", "30"))
    while session_id in sessions:
        session = sessions[session_id]
        session["status"] = "analyzing"
        payload = {
            "type": "heartbeat",
            "session_id": session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "station_count": len(session["stations"]),
        }
        yield f"data: {json.dumps(payload)}\n\n"
        await asyncio.sleep(refresh)


@app.get("/v1/sessions/{session_id}/events")
def session_events(session_id: str) -> StreamingResponse:
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    return StreamingResponse(event_stream(session_id), media_type="text/event-stream")

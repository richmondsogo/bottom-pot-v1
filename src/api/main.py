"""
FastAPI application for Bottom Pot backend.

Provides:
- GET /search (Server-Sent Events streaming job search)
- GET /health (Health check endpoint)
- POST /subscribe (Email subscription logger)
"""

from __future__ import annotations

import asyncio
import csv
from datetime import datetime, timezone
import json
import os
from typing import Optional

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from src.config import settings
from src.project_files.models import (
    DoneEvent,
    ErrorEvent,
    ResultsBatch,
    SearchParams,
    SubscribeRequest,
)
from src.project_files.search_pipeline import SearchOrchestrator

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Bottom Pot API", version="2.0.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten to frontend domain in production
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

orchestrator = SearchOrchestrator()


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "version": "2.0.0"}


@app.get("/search")
@limiter.limit(f"{settings.rate_limit_per_hour}/hour")
async def search(
    request: Request,
    q: str = Query(
        ...,
        min_length=2,
        max_length=100,
        description="Job title, e.g. 'Data Analyst'",
    ),
    location: Optional[str] = Query(None, max_length=100),
    remote: Optional[bool] = Query(None),
    days_back: int = Query(7, ge=1, le=90),
    platforms: Optional[str] = Query(
        None,
        description="Comma-separated: greenhouse,lever,ashby,...",
    ),
    include_nigerian: bool = Query(True),
) -> StreamingResponse:
    """
    Streams job search results progressively using Server-Sent Events (SSE).
    """
    target_platforms = (
        [p.strip().lower() for p in platforms.split(",") if p.strip()]
        if platforms
        else None
    )

    search_params = SearchParams(
        job_title=q,
        location=location,
        remote=remote,
        days_back=days_back,
        include_nigerian_sites=include_nigerian,
    )

    async def event_generator():
        try:
            async for event_name, event_data in orchestrator.run(
                search_params, target_platforms
            ):
                payload = event_data.model_dump_json()
                yield f"event: {event_name}\ndata: {payload}\n\n"
        except Exception as exc:
            err = ErrorEvent(message=f"Search provider error: {exc}", code="PROVIDER_ERROR")
            yield f"event: error\ndata: {err.model_dump_json()}\n\n"

    headers = {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",  # prevents Nginx from buffering SSE
        "Connection": "keep-alive",
    }

    return StreamingResponse(event_generator(), headers=headers)


@app.post("/subscribe", status_code=201)
async def subscribe(body: SubscribeRequest):
    """
    Appends email and optional search query to subscriptions.csv.
    Creates the file if it does not exist.
    """
    file_exists = os.path.isfile(settings.subscriptions_file)
    with open(settings.subscriptions_file, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["email", "search_query", "subscribed_at"])
        writer.writerow([
            body.email,
            body.search_query or "",
            datetime.now(timezone.utc).isoformat(),
        ])
    return {"subscribed": True}

"""AlleycaTV Server — FastAPI entry point.

Serves:
  /api/*      — playlist, zone, and content management REST endpoints
  /media/*    — static media files (nginx handles this in production;
                FastAPI serves it in dev via StaticFiles)
  /health     — liveness probe
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import MEDIA_BASE, MEDIA_SUBDIRS, API_HOST, API_PORT
from app.routers import content, playlists, zones

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
_LOGGER = logging.getLogger(__name__)

app = FastAPI(
    title="AlleycaTV Server",
    version="1.0.0",
    description="Video distribution system for Alleycat venues",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log API/manage requests and prevent stale cached API responses in the browser."""
    start = time.perf_counter()
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    if path.startswith("/api/") or path == "/manage":
        ms = (time.perf_counter() - start) * 1000
        _LOGGER.info(
            "%s %s -> %s (%.0fms)",
            request.method,
            path,
            response.status_code,
            ms,
        )
    return response

# ── Routers ────────────────────────────────────────────────────────────────────
app.include_router(content.router,   prefix="/api")
app.include_router(playlists.router, prefix="/api")
app.include_router(zones.router,     prefix="/api")


@app.on_event("startup")
async def startup() -> None:
    # Ensure media directories exist
    for sub in MEDIA_SUBDIRS:
        Path(MEDIA_BASE, sub).mkdir(parents=True, exist_ok=True)
    _LOGGER.info("AlleycaTV server started. Media root: %s", MEDIA_BASE)

    # Attempt MQTT connection (non-fatal if broker not available yet)
    try:
        from app.mqtt_client import get_mqtt
        get_mqtt()
    except Exception as exc:
        _LOGGER.warning("MQTT not available at startup (will retry on first use): %s", exc)


# ── Static media serving (dev mode; nginx takes over in production) ────────────
_media_path = Path(MEDIA_BASE)
_media_path.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(_media_path)), name="media")


@app.get("/manage", include_in_schema=False)
async def manage_ui():
    """Serve the drag-and-drop content management UI."""
    return FileResponse(
        Path(__file__).parent / "static" / "manage.html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/health")
async def health():
    return {"status": "ok", "media_base": MEDIA_BASE}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=API_HOST, port=API_PORT, reload=False)

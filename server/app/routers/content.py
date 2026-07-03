"""Content management router — upload, list, and delete media files."""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Form, HTTPException, UploadFile, File
from pydantic import BaseModel, Field

from app.config import (
    MEDIA_BASE,
    ANNOUNCEMENTS_URLS_FILE,
    ALLOWED_VIDEO_EXT,
    ALLOWED_PHOTO_EXT,
    MAX_UPLOAD_MB,
)
from app.models import AnnouncementUrlEntry, ContentFile, MediaType
from app.playlist_store import find_zones_with_file, load_playlists, remove_file_from_all_playlists, save_playlists


def _notify_zones_reload(zone_ids: List[str]) -> None:
    """Tell Pis in affected zones to reload their playlists after a library delete."""
    if not zone_ids:
        return
    try:
        from app.mqtt_client import get_mqtt
        mqtt = get_mqtt()
        for zone_id in zone_ids:
            mqtt.reload_zone(zone_id)
            _LOGGER.info("Sent playlist reload to zone %s", zone_id)
    except Exception as exc:
        _LOGGER.warning("Could not notify zones to reload playlist: %s", exc)

router = APIRouter(prefix="/content", tags=["content"])
_LOGGER = logging.getLogger(__name__)

_MAX_BYTES = MAX_UPLOAD_MB * 1024 * 1024


def _classify(filename: str) -> MediaType:
    ext = Path(filename).suffix.lower()
    if ext in ALLOWED_VIDEO_EXT:
        return MediaType.video
    if ext in ALLOWED_PHOTO_EXT:
        return MediaType.photo
    raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")


def _load_url_announcements() -> List[AnnouncementUrlEntry]:
    p = Path(ANNOUNCEMENTS_URLS_FILE)
    if not p.exists():
        return []
    try:
        raw = json.loads(p.read_text())
    except json.JSONDecodeError:
        return []
    return [AnnouncementUrlEntry(**item) for item in raw]


def _save_url_announcements(entries: List[AnnouncementUrlEntry]) -> None:
    p = Path(ANNOUNCEMENTS_URLS_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps([e.model_dump() for e in entries], indent=2))


class AnnouncementUrlCreate(BaseModel):
    label: str = Field(min_length=1)
    url: str = Field(min_length=1)
    duration: int = Field(default=30, ge=1, le=600)


class FileRef(BaseModel):
    """Reference to a file in videos/ or photos/."""
    subdir: str
    filename: str


class AnnouncementFileRef(BaseModel):
    filename: str


@router.get("/", response_model=List[ContentFile])
async def list_content(base_url: str = "http://localhost:8000"):
    """Return all media files across videos, photos, announcements, and URL entries."""
    files: List[ContentFile] = []
    for subdir in ("videos", "photos", "announcements"):
        folder = Path(MEDIA_BASE) / subdir
        folder.mkdir(parents=True, exist_ok=True)
        for f in sorted(folder.iterdir()):
            if not f.is_file():
                continue
            if f.name.startswith("_") and f.suffix == ".json":
                continue
            ext = f.suffix.lower()
            if ext in ALLOWED_VIDEO_EXT:
                mt = MediaType.announcement if subdir == "announcements" else MediaType.video
            elif ext in ALLOWED_PHOTO_EXT:
                mt = (
                    MediaType.announcement
                    if subdir == "announcements"
                    else MediaType.photo
                )
            else:
                continue
            duration = 30 if mt == MediaType.announcement and ext in ALLOWED_PHOTO_EXT else None
            if mt == MediaType.announcement and ext in ALLOWED_VIDEO_EXT:
                duration = None  # play full video
            files.append(ContentFile(
                filename=f.name,
                media_type=mt,
                size_bytes=f.stat().st_size,
                url=f"{base_url}/media/{subdir}/{quote(f.name)}",
                subdir=subdir,
                duration=duration,
            ))

    for entry in _load_url_announcements():
        files.append(ContentFile(
            filename=entry.label,
            media_type=MediaType.webpage,
            size_bytes=0,
            url=entry.url,
            subdir="announcements",
            duration=entry.duration,
            entry_id=entry.entry_id,
        ))
    return files


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    subdir: str = Form(default="videos"),
    zone_id: Optional[str] = Form(default=None),
):
    """Upload a media file. If zone_id is provided, auto-adds it to that zone's playlist."""
    if subdir not in ("videos", "photos", "announcements"):
        raise HTTPException(status_code=400, detail="subdir must be videos, photos, or announcements")

    media_type = _classify(file.filename)
    if subdir == "announcements":
        media_type = MediaType.announcement

    dest = Path(MEDIA_BASE) / subdir / file.filename
    dest.parent.mkdir(parents=True, exist_ok=True)

    total = 0
    with open(dest, "wb") as out:
        while chunk := await file.read(1024 * 1024):
            total += len(chunk)
            if total > _MAX_BYTES:
                dest.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail=f"File exceeds {MAX_UPLOAD_MB} MB limit")
            out.write(chunk)

    if zone_id:
        _add_to_playlist(zone_id, file.filename, media_type.value)

    return {
        "filename": file.filename,
        "media_type": media_type,
        "size_bytes": total,
        "subdir": subdir,
        "added_to_zone": zone_id,
    }


@router.post("/announcements/url", response_model=AnnouncementUrlEntry)
async def add_announcement_url(body: AnnouncementUrlCreate):
    """Add a scoreboard / webpage URL to the interrupt announcements library."""
    entries = _load_url_announcements()
    entry = AnnouncementUrlEntry(
        entry_id=str(uuid.uuid4()),
        label=body.label.strip(),
        url=body.url.strip(),
        duration=body.duration,
    )
    entries.append(entry)
    _save_url_announcements(entries)
    return entry


@router.delete("/announcements/url/{entry_id}")
async def delete_announcement_url(entry_id: str):
    """Remove a URL-based announcement."""
    entries = _load_url_announcements()
    kept = [e for e in entries if e.entry_id != entry_id]
    if len(kept) == len(entries):
        raise HTTPException(status_code=404, detail="Announcement URL not found")
    _save_url_announcements(kept)
    return {"deleted": entry_id}


def _safe_media_path(subdir: str, filename: str) -> Path:
    """Resolve a media file path and reject directory traversal."""
    base = (Path(MEDIA_BASE) / subdir).resolve()
    target = (Path(MEDIA_BASE) / subdir / filename).resolve()
    if base not in target.parents and target != base:
        raise HTTPException(status_code=400, detail="Invalid filename")
    return target


@router.post("/usage-check")
async def content_usage_post(body: FileRef):
    """Return zone playlists that reference a library file (JSON body — avoids long URL issues)."""
    if body.subdir not in ("videos", "photos"):
        raise HTTPException(status_code=400, detail="Usage lookup only applies to videos and photos")
    zones = find_zones_with_file(body.filename, body.subdir)
    return {"filename": body.filename, "subdir": body.subdir, "zones": zones}


@router.post("/delete-file")
async def delete_file_post(body: FileRef):
    """Delete a videos/photos library file (JSON body — reliable for long filenames)."""
    return await _delete_library_file(body.subdir, body.filename)


@router.post("/announcements/delete-file")
async def delete_announcement_file_post(body: AnnouncementFileRef):
    """Delete an announcement file (JSON body)."""
    return await _delete_announcement_file(body.filename)


async def _delete_announcement_file(filename: str):
    _LOGGER.info("Delete announcement file requested: %r", filename)
    target = _safe_media_path("announcements", filename)
    if not target.is_file():
        _LOGGER.warning("Announcement delete failed — not found: %s", target)
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")
    target.unlink()
    _LOGGER.info("Deleted announcement file: %s", target)
    return {"deleted": filename}


@router.delete("/announcements/file/{filename:path}")
async def delete_announcement_file(filename: str):
    """Delete a file from the announcements library (explicit route for /manage UI)."""
    return await _delete_announcement_file(filename)


def _add_to_playlist(zone_id: str, filename: str, media_type: str) -> None:
    """Append a file to a zone's playlist, creating the playlist if needed."""
    data = load_playlists()
    playlist = data.get(zone_id, {"zone_id": zone_id, "items": [], "photo_interval": 5})
    items = playlist.get("items", [])
    if not any(i.get("filename") == filename for i in items):
        items.append({"filename": filename, "media_type": media_type})
    playlist["items"] = items
    data[zone_id] = playlist
    save_playlists(data)


@router.get("/usage/{subdir}/{filename:path}")
async def content_usage(subdir: str, filename: str):
    """Return zone playlists that reference a library file (for delete confirmation)."""
    if subdir not in ("videos", "photos"):
        raise HTTPException(status_code=400, detail="Usage lookup only applies to videos and photos")
    zones = find_zones_with_file(filename, subdir)
    return {"filename": filename, "subdir": subdir, "zones": zones}


@router.delete("/{subdir}/{filename:path}")
async def delete_file(subdir: str, filename: str):
    """Delete a videos/photos library file and remove it from any zone playlists."""
    return await _delete_library_file(subdir, filename)


async def _delete_library_file(subdir: str, filename: str):
    _LOGGER.info("Delete file requested: subdir=%s filename=%r", subdir, filename)
    if subdir not in ("videos", "photos"):
        raise HTTPException(
            status_code=400,
            detail="Use POST /api/content/announcements/delete-file for announcements",
        )
    target = _safe_media_path(subdir, filename)
    if not target.is_file():
        _LOGGER.warning("Delete failed — not found: %s", target)
        raise HTTPException(status_code=404, detail=f"File not found: {filename}")
    removed_from = remove_file_from_all_playlists(filename, subdir)
    target.unlink()
    _notify_zones_reload(removed_from)
    _LOGGER.info("Deleted file: %s (removed from zones: %s)", target, removed_from)
    return {"deleted": filename, "subdir": subdir, "removed_from_zones": removed_from}

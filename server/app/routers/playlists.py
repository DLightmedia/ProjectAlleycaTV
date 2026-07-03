"""Playlist management router — per-zone playlist CRUD."""
from __future__ import annotations

from typing import Dict

from fastapi import APIRouter, HTTPException

from app.models import Playlist
from app.playlist_store import load_playlists, save_playlists

router = APIRouter(prefix="/playlists", tags=["playlists"])


def _load() -> Dict[str, dict]:
    return load_playlists()


def _save(data: Dict[str, dict]) -> None:
    save_playlists(data)


@router.get("/")
async def list_playlists():
    """Return all zone playlists."""
    return _load()


@router.get("/{zone_id}", response_model=Playlist)
async def get_playlist(zone_id: str):
    """Get the playlist for a specific zone."""
    data = _load()
    if zone_id not in data:
        return Playlist(zone_id=zone_id)
    return Playlist(**data[zone_id])


@router.put("/{zone_id}", response_model=Playlist)
async def upsert_playlist(zone_id: str, playlist: Playlist):
    """Create or replace the playlist for a zone."""
    if playlist.zone_id != zone_id:
        playlist = playlist.model_copy(update={"zone_id": zone_id})
    data = _load()
    data[zone_id] = playlist.model_dump()
    _save(data)
    return playlist


@router.delete("/{zone_id}")
async def delete_playlist(zone_id: str):
    """Remove a zone's playlist."""
    data = _load()
    if zone_id not in data:
        raise HTTPException(status_code=404, detail="Playlist not found")
    del data[zone_id]
    _save(data)
    return {"deleted": zone_id}

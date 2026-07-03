"""Pydantic models for the AlleycaTV API."""
from __future__ import annotations

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class MediaType(str, Enum):
    video = "video"
    photo = "photo"
    announcement = "announcement"
    webpage = "webpage"


class PlaylistMode(str, Enum):
    manual = "manual"
    auto = "auto"


class MediaItem(BaseModel):
    filename: str = ""
    media_type: MediaType
    photo_duration: int = Field(default=10, description="Seconds to display if media_type=photo")
    url: Optional[str] = Field(default=None, description="Required for media_type=webpage")
    duration: int = Field(default=30, description="Seconds to display if media_type=webpage")


class Playlist(BaseModel):
    zone_id: str
    items: List[MediaItem] = []
    photo_interval: int = Field(
        default=5,
        description="Insert one random photo every N videos (0 = no photos)"
    )
    mode: PlaylistMode = Field(
        default=PlaylistMode.manual,
        description="manual = saved order; auto = shuffle loop items each cycle"
    )


class Zone(BaseModel):
    zone_id: str
    name: str
    pi_ids: List[str] = []


class ZoneCommandAction(str, Enum):
    play     = "play"
    stop     = "stop"
    interrupt = "interrupt"
    reload   = "reload"
    volume   = "volume"


class ZoneCommand(BaseModel):
    action: ZoneCommandAction
    file_url: Optional[str] = None   # required for action=interrupt
    volume: Optional[int] = None     # required for action=volume (0-100)
    pi_id: Optional[str] = None      # if set, target single Pi instead of whole zone


class AnnouncementUrlEntry(BaseModel):
    """Scoreboard / webpage stored for interrupt-only playback (not a media file)."""
    entry_id: str
    label: str
    url: str
    duration: int = 30


class ContentFile(BaseModel):
    filename: str
    media_type: MediaType
    size_bytes: int
    url: str
    subdir: Optional[str] = Field(default=None, description="Media folder: videos, photos, or announcements")
    duration: Optional[int] = None
    entry_id: Optional[str] = None

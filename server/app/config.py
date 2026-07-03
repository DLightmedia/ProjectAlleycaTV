"""AlleycaTV server configuration.

Edit MQTT_BROKER and SERVER_IP to match your network before deploying.
All other values can stay as defaults for a standard install.
"""
import os

MEDIA_BASE       = os.getenv("ALLEYCATV_MEDIA",    "/opt/alleycatv/media")
PLAYLISTS_FILE        = os.getenv("ALLEYCATV_PLAYLISTS",      "/opt/alleycatv/playlists.json")
ZONES_FILE            = os.getenv("ALLEYCATV_ZONES",          "/opt/alleycatv/zones.json")
ANNOUNCEMENTS_URLS_FILE = os.getenv(
    "ALLEYCATV_ANNOUNCEMENTS",
    os.path.join(MEDIA_BASE, "announcements", "_urls.json"),
)

MQTT_BROKER      = os.getenv("ALLEYCATV_MQTT_HOST", "192.168.1.50")   # Mission Control broker
MQTT_PORT        = int(os.getenv("ALLEYCATV_MQTT_PORT", "1883"))
MQTT_USER        = os.getenv("ALLEYCATV_MQTT_USER", "mqtt_esp32")   # Leave blank if broker has no auth
MQTT_PASS        = os.getenv("ALLEYCATV_MQTT_PASS", "IOTadmin")
MQTT_TOPIC_PREFIX = "alleycatv"

API_HOST         = os.getenv("ALLEYCATV_HOST", "0.0.0.0")
API_PORT         = int(os.getenv("ALLEYCATV_PORT", "8000"))

MEDIA_SUBDIRS    = ("videos", "photos", "announcements")
ALLOWED_VIDEO_EXT = {".mp4", ".mkv", ".avi", ".mov"}
ALLOWED_PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp"}
MAX_UPLOAD_MB    = int(os.getenv("ALLEYCATV_MAX_UPLOAD_MB", "500"))

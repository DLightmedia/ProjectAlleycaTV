"""AlleycaTV Pi player configuration.

Edit PI_ID, ZONE_ID, SERVER_URL, and MQTT_BROKER for each device.
Everything else can stay at its default.

The install.sh script will prompt for these values and write them here.
"""
import os

# ── Per-device identity ────────────────────────────────────────────────────────
PI_ID    = os.getenv("ALLEYCATV_PI_ID",   "pi-01")   # Unique per device, e.g. "pi-lobby-1"
ZONE_ID  = os.getenv("ALLEYCATV_ZONE_ID", "zone-a")  # Zone this Pi belongs to

# ── Network ───────────────────────────────────────────────────────────────────
SERVER_URL   = os.getenv("ALLEYCATV_SERVER", "http://192.168.1.100")  # AlleycaTV LXC server
MQTT_BROKER  = os.getenv("ALLEYCATV_MQTT",      "192.168.1.50")   # Mission Control broker
MQTT_PORT    = int(os.getenv("ALLEYCATV_MQTT_PORT", "1883"))
MQTT_USER    = os.getenv("ALLEYCATV_MQTT_USER", "mqtt_esp32")   # Leave blank if broker has no auth
MQTT_PASS    = os.getenv("ALLEYCATV_MQTT_PASS", "IOTadmin")

# ── Playlist behaviour ────────────────────────────────────────────────────────
# Insert one random photo every N videos.  Set to 0 to disable photo injection.
PHOTO_INTERVAL = int(os.getenv("ALLEYCATV_PHOTO_INTERVAL", "5"))
# How long (seconds) to display each photo slide
PHOTO_DURATION = int(os.getenv("ALLEYCATV_PHOTO_DURATION", "10"))
# How often the Pi re-fetches its playlist from the server (seconds)
PLAYLIST_REFRESH_INTERVAL = int(os.getenv("ALLEYCATV_PLAYLIST_REFRESH", "300"))

# ── Player ─────────────────────────────────────────────────────────────────────
MPV_SOCKET_PATH   = os.getenv("ALLEYCATV_MPV_SOCKET", "/tmp/alleycatv-mpv.sock")
STATUS_INTERVAL   = int(os.getenv("ALLEYCATV_STATUS_INTERVAL", "30"))  # seconds

# ── MQTT topics ───────────────────────────────────────────────────────────────
TOPIC_PREFIX       = "alleycatv"
TOPIC_STATUS       = f"{TOPIC_PREFIX}/pi/{PI_ID}/status"
TOPIC_ZONE_CMD     = f"{TOPIC_PREFIX}/zone/{ZONE_ID}/cmd/#"
TOPIC_PI_CMD       = f"{TOPIC_PREFIX}/pi/{PI_ID}/cmd/#"
MEDIA_BASE_URL     = f"{SERVER_URL}/media"

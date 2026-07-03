# AlleycaTV Setup Guide

End-to-end deployment walkthrough: Proxmox server → Raspberry Pi clients → Home Assistant integration.

---

## Prerequisites

- Proxmox host with a free container ID and enough storage
- Existing Mission Control / Home Assistant instance with Mosquitto MQTT broker running
- Raspberry Pi 4 devices (one per display) on the same LAN
- All devices on 5GHz WiFi or wired ethernet

---

## 1. Proxmox LXC Server

### 1a. Create and provision the container

On your **Proxmox host**, run:

```bash
cd server/setup
chmod +x provision-lxc.sh
# Edit the variables at the top of provision-lxc.sh first:
#   CTID, IP, GW, STORAGE, BRIDGE
./provision-lxc.sh
```

This creates an Ubuntu 22.04 LXC container, installs nginx + Python + FastAPI, and starts the server.

### 1b. Configure MQTT broker IP

Inside the container, edit the server config:

```bash
pct exec <CTID> -- nano /opt/alleycatv/server/app/config.py
# Set MQTT_BROKER to your Mission Control IP
systemctl restart alleycatv-server
```

### 1c. Verify the server

```bash
curl http://<SERVER_IP>/health
# → {"status": "ok", "media_base": "/opt/alleycatv/media"}

curl http://<SERVER_IP>/api/content/
# → [] (empty until you upload files)
```

### 1d. Upload your first content

Via curl:

```bash
# Upload a video
curl -F "file=@promo.mp4" -F "subdir=videos" http://<SERVER_IP>/api/content/upload

# Upload an announcement
curl -F "file=@last-call.mp4" -F "subdir=announcements" http://<SERVER_IP>/api/content/upload

# Upload a photo slide
curl -F "file=@logo.jpg" -F "subdir=photos" http://<SERVER_IP>/api/content/upload
```

**Video encoding spec** (encode before uploading):
```bash
ffmpeg -i input.mov -c:v libx264 -profile:v high -level 4.1 -b:v 5M -c:a aac -b:a 128k output.mp4
```

### 1e. Create a zone and playlist

```bash
# Create a zone
curl -X POST http://<SERVER_IP>/api/zones/ \
  -H "Content-Type: application/json" \
  -d '{"zone_id": "zone-lobby", "name": "Lobby", "pi_ids": ["pi-lobby-1", "pi-lobby-2"]}'

# Set the zone playlist (photo every 5 videos)
curl -X PUT http://<SERVER_IP>/api/playlists/zone-lobby \
  -H "Content-Type: application/json" \
  -d '{
    "zone_id": "zone-lobby",
    "photo_interval": 5,
    "items": [
      {"filename": "promo.mp4",   "media_type": "video"},
      {"filename": "logo.jpg",    "media_type": "photo", "photo_duration": 12}
    ]
  }'
```

---

## 2. Raspberry Pi Client Setup

### 2a. Flash the Pi

1. Flash **Raspberry Pi OS Lite (64-bit)** to SD card using Raspberry Pi Imager
2. Enable SSH and set hostname/wifi in the imager advanced options
3. Boot the Pi and SSH in

### 2b. Run the install script

Copy the `client/` folder to the Pi (or clone the repo), then:

```bash
cd client
chmod +x install.sh
sudo ./install.sh
```

You will be prompted for:
- `PI_ID` — unique device name, e.g. `pi-lobby-1`
- `ZONE_ID` — zone this Pi belongs to, e.g. `zone-lobby`
- `SERVER_IP` — AlleycaTV LXC IP, e.g. `192.168.1.100`
- `MQTT_IP` — Mission Control MQTT broker IP, e.g. `192.168.1.50`
- `PHOTO_INTERVAL` — videos between photo slides (default 5)

The script installs `mpv`, Python deps, writes `config.py`, and enables the `alleycatv-player.service`.

### 2c. Verify playback

```bash
# Check service status
sudo systemctl status alleycatv-player

# Watch live logs
journalctl -u alleycatv-player -f

# Check MQTT status messages (run on any machine with mosquitto-clients)
mosquitto_sub -h <MQTT_IP> -t "alleycatv/pi/+/status" -v
```

### 2d. Repeat for each Pi

Each Pi only needs a different `PI_ID` in its `config.py`. All other settings can be identical for Pis in the same zone.

### 2e. Imaging additional Pis

Once a Pi is working, create a golden image with [rpi-clone](https://github.com/billw2/rpi-clone) or Pi Imager's "clone" feature. Flash to new Pis, then only change `PI_ID` in `/opt/alleycatv/alleycatv_player/config.py` and restart the service.

---

## 3. Home Assistant Integration

### 3a. Copy files to HA config

Copy these into your live HA configuration directory:

```
ha_integration/custom_components/alleycatv/  →  <HA_config>/custom_components/alleycatv/
ha_integration/www/alleycatv/                →  <HA_config>/www/alleycatv/
```

### 3b. Update configuration.yaml

The `ProjectMissionControl/HomeAssistConfig/Config/configuration.yaml` has already been updated with the AlleycaTV entries. Copy it to your live HA config directory, or manually add these lines:

```yaml
frontend:
  extra_module_url:
    - /local/alleycatv/alleycatv-panel.js   # add this line

panel_custom:
  - name: alleycatv-panel
    sidebar_title: AlleycaTV
    sidebar_icon: mdi:television-play
    url_path: alleycatv
    module_url: /local/alleycatv/alleycatv-panel.js

alleycatv:   # add this line
```

### 3c. Add the integration via HA UI

1. Go to **Settings → Integrations → Add Integration**
2. Search for **AlleycaTV**
3. Enter the AlleycaTV server URL (e.g. `http://192.168.1.100`)
4. Click Submit → Restart HA

### 3d. Verify the panel

Open the HA sidebar — you should see **AlleycaTV** with a TV icon. Zones appear as Pi devices come online.

---

## 4. Triggering Announcements from HA Automations

### YAML automation example

```yaml
automation:
  - alias: "Last Call Announcement"
    trigger:
      - platform: time
        at: "01:45:00"
    action:
      - service: alleycatv.interrupt_zone
        data:
          zone_id: "zone-lobby"
          file_url: "http://192.168.1.100/media/announcements/last-call.mp4"
```

### Available services

| Service | Parameters | Effect |
|---------|-----------|--------|
| `alleycatv.play_zone` | `zone_id` | Resume playlist |
| `alleycatv.stop_zone` | `zone_id` | Stop playback |
| `alleycatv.interrupt_zone` | `zone_id`, `file_url` | Play announcement then resume |
| `alleycatv.interrupt_pi` | `pi_id`, `file_url` | Interrupt single Pi |
| `alleycatv.reload_playlist` | `zone_id` | Re-fetch playlist from server |
| `alleycatv.set_volume_zone` | `zone_id`, `volume` (0-100) | Set volume |

---

## 5. Adding a New Zone or Pi

### New zone
```bash
curl -X POST http://<SERVER_IP>/api/zones/ \
  -H "Content-Type: application/json" \
  -d '{"zone_id": "zone-bar", "name": "Bar"}'
```
Then set its playlist via `PUT /api/playlists/zone-bar`.

### New Pi
1. Flash a Pi SD card from your golden image
2. Change `PI_ID` in `/opt/alleycatv/alleycatv_player/config.py`
3. Change `ZONE_ID` if needed
4. `sudo systemctl restart alleycatv-player`
5. The Pi appears in the AlleycaTV panel within 30 seconds

---

## 6. Regenerating Protobuf Bindings

If you modify `proto/alleycatv.proto`, regenerate the bindings:

```bash
cd proto
chmod +x generate_proto.sh
./generate_proto.sh
```

This regenerates `alleycatv_pb2.py` and copies it to both the HA integration and the Pi client.

---

## 7. Troubleshooting

| Symptom | Check |
|---------|-------|
| Pi screen stays black | `journalctl -u alleycatv-player -f` — look for playlist errors or mpv failures |
| Pi not visible in HA panel | `mosquitto_sub -t "alleycatv/pi/+/status"` — confirm Pi is publishing |
| Interrupt doesn't resume | Check logs for `INTERRUPT` and `resume` lines; ensure announcement URL is reachable |
| Photos not showing | Verify `photo_interval > 0` in zone playlist and photos are uploaded to `photos/` |
| High CPU on Pi | Ensure H.264 (not H.265) video — Pi 4 hardware-decodes H.264 natively |

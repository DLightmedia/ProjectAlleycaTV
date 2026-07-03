"""AlleycaTV — Home Assistant Custom Integration.

Bridges Home Assistant to Raspberry Pi video players via MQTT.
Payloads are Protocol Buffers (protobuf) binary — NOT JSON.
Schema: proto/alleycatv.proto → alleycatv_pb2.py (generated, do not edit).

Mirrors the esp32_commander integration architecture exactly.
"""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.components import mqtt, websocket_api

from .alleycatv_pb2 import (
    PiStatusMsg, PlayCmd, StopCmd, InterruptCmd, ReloadPlaylistCmd, SetVolumeCmd
)

_LOGGER = logging.getLogger(__name__)

DOMAIN = "alleycatv"
PLATFORMS: list[Platform] = []

CONFIG_SCHEMA = vol.Schema(
    {vol.Optional(DOMAIN): vol.Schema({}, extra=vol.ALLOW_EXTRA)},
    extra=vol.ALLOW_EXTRA,
)

# MQTT topic structure:
#   Commands TO zone:  alleycatv/zone/{zone_id}/cmd/{action}
#   Commands TO pi:    alleycatv/pi/{pi_id}/cmd/{action}
#   Status FROM pi:    alleycatv/pi/{pi_id}/status  (retained)
TOPIC_PREFIX       = "alleycatv"
TOPIC_STATUS_ALL   = f"{TOPIC_PREFIX}/pi/+/status"
TOPIC_ZONE_CMD     = f"{TOPIC_PREFIX}/zone/{{zone_id}}/cmd/{{action}}"
TOPIC_PI_CMD       = f"{TOPIC_PREFIX}/pi/{{pi_id}}/cmd/{{action}}"

# Service names
SERVICE_PLAY_ZONE        = "play_zone"
SERVICE_STOP_ZONE        = "stop_zone"
SERVICE_INTERRUPT_ZONE   = "interrupt_zone"
SERVICE_INTERRUPT_PI     = "interrupt_pi"
SERVICE_RELOAD_PLAYLIST  = "reload_playlist"
SERVICE_SET_VOLUME_ZONE  = "set_volume_zone"

# Service schemas
SERVICE_ZONE_SCHEMA = vol.Schema({
    vol.Required("zone_id"): cv.string,
})

SERVICE_INTERRUPT_ZONE_SCHEMA = vol.Schema({
    vol.Required("zone_id"): cv.string,
    vol.Required("file_url"): cv.string,
})

SERVICE_INTERRUPT_PI_SCHEMA = vol.Schema({
    vol.Required("pi_id"): cv.string,
    vol.Required("file_url"): cv.string,
})

SERVICE_VOLUME_SCHEMA = vol.Schema({
    vol.Required("zone_id"): cv.string,
    vol.Required("volume"): vol.All(int, vol.Range(min=0, max=100)),
})


def _to_bytes(payload: Any) -> bytes:
    """Normalise an MQTT payload to bytes regardless of how HA delivers it."""
    if isinstance(payload, (bytes, bytearray)):
        return bytes(payload)
    if isinstance(payload, str):
        return payload.encode("latin-1")
    return bytes(payload)


@websocket_api.websocket_command({
    vol.Required("type"): f"{DOMAIN}/list_devices",
})
@websocket_api.async_response
async def websocket_list_devices(hass: HomeAssistant, connection, msg) -> None:
    """Return all known AlleycaTV Pi devices from hass.data."""
    devices = hass.data.get(DOMAIN, {}).get("devices", {})
    connection.send_result(msg["id"], {"devices": list(devices.values())})


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up AlleycaTV from configuration.yaml."""
    _LOGGER.info("AlleycaTV: async_setup START")
    hass.data.setdefault(DOMAIN, {"devices": {}, "subscriptions": []})
    await _setup_integration(hass)
    _LOGGER.info("AlleycaTV: async_setup COMPLETE")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up AlleycaTV from a config entry (UI flow)."""
    _LOGGER.info("AlleycaTV: async_setup_entry START")
    hass.data.setdefault(DOMAIN, {"devices": {}, "subscriptions": []})
    await _setup_integration(hass)
    _LOGGER.info("AlleycaTV: async_setup_entry COMPLETE")
    return True


async def _setup_integration(hass: HomeAssistant) -> None:
    """Register services, websocket command, and MQTT subscription.

    Idempotent — skips re-registration if already done.
    Called from both async_setup (YAML) and async_setup_entry (UI config flow).
    """
    # ── 1. Register services ───────────────────────────────────────────────────
    if not hass.services.has_service(DOMAIN, SERVICE_PLAY_ZONE):
        await _register_services(hass)
        _LOGGER.info("AlleycaTV: services registered")
    else:
        _LOGGER.debug("AlleycaTV: services already registered, skipping")

    # ── 2. Register websocket command ──────────────────────────────────────────
    try:
        websocket_api.async_register_command(hass, websocket_list_devices)
        _LOGGER.info("AlleycaTV: websocket command registered")
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("AlleycaTV: websocket already registered or failed: %s", err)

    # ── 3. MQTT subscription (skip if already subscribed) ─────────────────────
    if hass.data[DOMAIN].get("subscriptions"):
        _LOGGER.debug("AlleycaTV: MQTT already subscribed, skipping")
        return

    async def handle_status_message(msg) -> None:
        """Decode an incoming protobuf PiStatusMsg from a Raspberry Pi."""
        try:
            topic_parts = msg.topic.split("/")
            if len(topic_parts) < 3:
                _LOGGER.warning("AlleycaTV: unexpected topic format: %s", msg.topic)
                return

            pi_id = topic_parts[2]  # alleycatv/pi/{pi_id}/status
            raw = _to_bytes(msg.payload)

            # Empty payload = LWT — Pi went offline
            if len(raw) == 0:
                if pi_id in hass.data[DOMAIN]["devices"]:
                    hass.data[DOMAIN]["devices"][pi_id]["online"] = False
                    hass.bus.async_fire(f"{DOMAIN}_device_update", {
                        "pi_id": pi_id, "online": False
                    })
                _LOGGER.info("AlleycaTV Pi [%s] went offline (LWT)", pi_id)
                return

            status = PiStatusMsg.FromString(raw)

            # Also handle online=False with empty pi_id as LWT
            if not status.online and not status.pi_id:
                if pi_id in hass.data[DOMAIN]["devices"]:
                    hass.data[DOMAIN]["devices"][pi_id]["online"] = False
                    hass.bus.async_fire(f"{DOMAIN}_device_update", {
                        "pi_id": pi_id, "online": False
                    })
                return

            hass.data[DOMAIN]["devices"][pi_id] = {
                "pi_id":          pi_id,
                "zone":           status.zone,
                "state":          status.state,
                "current_file":   status.current_file,
                "next_file":      status.next_file,
                "playlist_index": status.playlist_index,
                "ip":             status.ip,
                "uptime":         status.uptime,
                "online":         True,
            }
            hass.bus.async_fire(f"{DOMAIN}_device_update", {
                "pi_id": pi_id,
                **hass.data[DOMAIN]["devices"][pi_id],
            })
            _LOGGER.debug("AlleycaTV Pi [%s] updated — zone=%s state=%s",
                          pi_id, status.zone, status.state)

        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("AlleycaTV: failed to parse status from [%s]: %s", msg.topic, err)

    try:
        unsub = await mqtt.async_subscribe(
            hass, TOPIC_STATUS_ALL, handle_status_message, encoding=None
        )
        hass.data[DOMAIN]["subscriptions"].append(unsub)
        _LOGGER.info("AlleycaTV: MQTT subscription active on %s", TOPIC_STATUS_ALL)
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("AlleycaTV: MQTT subscription failed: %s", err)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload AlleycaTV config entry."""
    for unsub in hass.data[DOMAIN].get("subscriptions", []):
        unsub()
    hass.data[DOMAIN]["subscriptions"].clear()
    return True


async def _register_services(hass: HomeAssistant) -> None:
    """Register all AlleycaTV HA services."""

    async def handle_play_zone(call: ServiceCall) -> None:
        zone_id = call.data["zone_id"]
        topic = TOPIC_ZONE_CMD.format(zone_id=zone_id, action="play")
        await mqtt.async_publish(hass, topic, PlayCmd().SerializeToString(), qos=1)
        _LOGGER.info("AlleycaTV: play zone=%s", zone_id)

    async def handle_stop_zone(call: ServiceCall) -> None:
        zone_id = call.data["zone_id"]
        topic = TOPIC_ZONE_CMD.format(zone_id=zone_id, action="stop")
        await mqtt.async_publish(hass, topic, StopCmd().SerializeToString(), qos=1)
        _LOGGER.info("AlleycaTV: stop zone=%s", zone_id)

    async def handle_interrupt_zone(call: ServiceCall) -> None:
        zone_id  = call.data["zone_id"]
        file_url = call.data["file_url"]
        cmd = InterruptCmd()
        cmd.file_url = file_url
        topic = TOPIC_ZONE_CMD.format(zone_id=zone_id, action="interrupt")
        await mqtt.async_publish(hass, topic, cmd.SerializeToString(), qos=1)
        _LOGGER.info("AlleycaTV: interrupt zone=%s file=%s", zone_id, file_url)

    async def handle_interrupt_pi(call: ServiceCall) -> None:
        pi_id    = call.data["pi_id"]
        file_url = call.data["file_url"]
        cmd = InterruptCmd()
        cmd.file_url = file_url
        topic = TOPIC_PI_CMD.format(pi_id=pi_id, action="interrupt")
        await mqtt.async_publish(hass, topic, cmd.SerializeToString(), qos=1)
        _LOGGER.info("AlleycaTV: interrupt pi=%s file=%s", pi_id, file_url)

    async def handle_reload_playlist(call: ServiceCall) -> None:
        zone_id = call.data["zone_id"]
        topic = TOPIC_ZONE_CMD.format(zone_id=zone_id, action="reload")
        await mqtt.async_publish(hass, topic, ReloadPlaylistCmd().SerializeToString(), qos=1)
        _LOGGER.info("AlleycaTV: reload playlist zone=%s", zone_id)

    async def handle_set_volume_zone(call: ServiceCall) -> None:
        zone_id = call.data["zone_id"]
        cmd = SetVolumeCmd()
        cmd.volume = call.data["volume"]
        topic = TOPIC_ZONE_CMD.format(zone_id=zone_id, action="volume")
        await mqtt.async_publish(hass, topic, cmd.SerializeToString(), qos=1)
        _LOGGER.info("AlleycaTV: set volume=%d zone=%s", cmd.volume, zone_id)

    hass.services.async_register(DOMAIN, SERVICE_PLAY_ZONE,       handle_play_zone,       schema=SERVICE_ZONE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_STOP_ZONE,       handle_stop_zone,       schema=SERVICE_ZONE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_INTERRUPT_ZONE,  handle_interrupt_zone,  schema=SERVICE_INTERRUPT_ZONE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_INTERRUPT_PI,    handle_interrupt_pi,    schema=SERVICE_INTERRUPT_PI_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_RELOAD_PLAYLIST, handle_reload_playlist, schema=SERVICE_ZONE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_SET_VOLUME_ZONE, handle_set_volume_zone, schema=SERVICE_VOLUME_SCHEMA)

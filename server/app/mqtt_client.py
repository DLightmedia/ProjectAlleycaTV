"""MQTT publisher for the AlleycaTV server.

The server uses this to dispatch zone/pi commands when the REST API is called
directly (e.g. from a script or the web UI).  The HA integration also publishes
commands via its own MQTT connection — both use the same topic convention.
"""
from __future__ import annotations

import logging
import sys
import os

import paho.mqtt.client as mqtt

# Allow running from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from app.config import MQTT_BROKER, MQTT_PORT, MQTT_USER, MQTT_PASS, MQTT_TOPIC_PREFIX

# Import protobuf message types
_pb2_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '..', 'proto')
sys.path.insert(0, os.path.abspath(_pb2_path))
from alleycatv_pb2 import PlayCmd, StopCmd, InterruptCmd, ReloadPlaylistCmd, SetVolumeCmd

_LOGGER = logging.getLogger(__name__)


class AlleycaTVMQTT:
    """Thin paho-mqtt wrapper for publishing AlleycaTV commands."""

    def __init__(self) -> None:
        self._client = mqtt.Client(client_id="alleycatv-server")
        self._connected = False

    def connect(self) -> bool:
        try:
            self._client.on_connect = self._on_connect
            self._client.on_disconnect = self._on_disconnect
            if MQTT_USER:
                self._client.username_pw_set(MQTT_USER, MQTT_PASS or None)
            self._client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
            self._client.loop_start()
            return True
        except Exception as exc:
            _LOGGER.error("MQTT connect failed: %s", exc)
            return False

    def disconnect(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()

    # ── Internal callbacks ─────────────────────────────────────────────────────

    def _on_connect(self, client, userdata, flags, rc) -> None:
        self._connected = rc == 0
        if rc == 0:
            _LOGGER.info("AlleycaTV server connected to MQTT broker")
        else:
            _LOGGER.warning("MQTT connect failed rc=%d", rc)

    def _on_disconnect(self, client, userdata, rc) -> None:
        self._connected = False

    # ── Command publishers ─────────────────────────────────────────────────────

    def _publish(self, topic: str, payload: bytes) -> None:
        result = self._client.publish(topic, payload, qos=1)
        _LOGGER.debug("Published to %s (mid=%s)", topic, result.mid)

    def _zone_topic(self, zone_id: str, action: str) -> str:
        return f"{MQTT_TOPIC_PREFIX}/zone/{zone_id}/cmd/{action}"

    def _pi_topic(self, pi_id: str, action: str) -> str:
        return f"{MQTT_TOPIC_PREFIX}/pi/{pi_id}/cmd/{action}"

    def play_zone(self, zone_id: str) -> None:
        self._publish(self._zone_topic(zone_id, "play"), PlayCmd().SerializeToString())

    def stop_zone(self, zone_id: str) -> None:
        self._publish(self._zone_topic(zone_id, "stop"), StopCmd().SerializeToString())

    def interrupt_zone(self, zone_id: str, file_url: str) -> None:
        cmd = InterruptCmd()
        cmd.file_url = file_url
        self._publish(self._zone_topic(zone_id, "interrupt"), cmd.SerializeToString())

    def reload_zone(self, zone_id: str) -> None:
        self._publish(self._zone_topic(zone_id, "reload"), ReloadPlaylistCmd().SerializeToString())

    def set_volume_zone(self, zone_id: str, volume: int) -> None:
        cmd = SetVolumeCmd()
        cmd.volume = max(0, min(100, volume))
        self._publish(self._zone_topic(zone_id, "volume"), cmd.SerializeToString())

    def interrupt_pi(self, pi_id: str, file_url: str) -> None:
        cmd = InterruptCmd()
        cmd.file_url = file_url
        self._publish(self._pi_topic(pi_id, "interrupt"), cmd.SerializeToString())


# Module-level singleton — initialised lazily by main.py on startup
_mqtt: AlleycaTVMQTT | None = None


def get_mqtt() -> AlleycaTVMQTT:
    global _mqtt
    if _mqtt is None:
        _mqtt = AlleycaTVMQTT()
        _mqtt.connect()
    return _mqtt

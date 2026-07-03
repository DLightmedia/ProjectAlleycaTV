"""MQTT subscriber — decodes protobuf commands and queues them for the player."""
from __future__ import annotations

import logging
import queue
import threading
from typing import Any

import paho.mqtt.client as mqtt

from config import (
    PI_ID, ZONE_ID, MQTT_BROKER, MQTT_PORT, MQTT_USER, MQTT_PASS,
    TOPIC_STATUS, TOPIC_ZONE_CMD, TOPIC_PI_CMD, TOPIC_PREFIX
)
from alleycatv_pb2 import (
    PiStatusMsg, PlayCmd, StopCmd, InterruptCmd, ReloadPlaylistCmd, SetVolumeCmd
)

_LOGGER = logging.getLogger(__name__)

# Action names match the MQTT topic suffix (alleycatv/.../cmd/{action})
_CMD_DECODERS = {
    "play":      PlayCmd,
    "stop":      StopCmd,
    "interrupt": InterruptCmd,
    "reload":    ReloadPlaylistCmd,
    "volume":    SetVolumeCmd,
}


class MQTTHandler:
    """Subscribes to zone and pi MQTT topics, decodes protobuf commands,
    and delivers them to a thread-safe queue for the player main loop."""

    def __init__(self) -> None:
        self.cmd_queue: queue.Queue[Any] = queue.Queue()
        self._client = mqtt.Client(client_id=f"alleycatv-pi-{PI_ID}")
        self._client.on_connect    = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message    = self._on_message
        self._connected = threading.Event()

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Connect to the broker and start the background network loop."""
        if MQTT_USER:
            self._client.username_pw_set(MQTT_USER, MQTT_PASS or None)
        # Last-will: empty payload on our status topic = offline
        self._client.will_set(TOPIC_STATUS, payload=b"", qos=1, retain=True)
        self._client.connect_async(MQTT_BROKER, MQTT_PORT, keepalive=60)
        self._client.loop_start()
        _LOGGER.info("MQTT handler started — connecting to %s:%d", MQTT_BROKER, MQTT_PORT)

    def stop(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()

    def publish_status(self, status: PiStatusMsg) -> None:
        """Publish a retained PiStatusMsg to our status topic."""
        payload = status.SerializeToString()
        self._client.publish(TOPIC_STATUS, payload, qos=1, retain=True)

    def publish_offline(self) -> None:
        """Publish an empty payload (LWT equivalent) to mark this Pi offline."""
        self._client.publish(TOPIC_STATUS, b"", qos=1, retain=True)

    # ── MQTT callbacks ─────────────────────────────────────────────────────────

    def _on_connect(self, client, userdata, flags, rc) -> None:
        if rc != 0:
            _LOGGER.error("MQTT connect failed rc=%d", rc)
            return
        _LOGGER.info("Connected to MQTT broker")
        # Subscribe to zone wildcard and Pi-specific wildcard
        client.subscribe(TOPIC_ZONE_CMD, qos=1)
        client.subscribe(TOPIC_PI_CMD,  qos=1)
        _LOGGER.info("Subscribed to %s and %s", TOPIC_ZONE_CMD, TOPIC_PI_CMD)
        self._connected.set()

    def _on_disconnect(self, client, userdata, rc) -> None:
        self._connected.clear()
        if rc != 0:
            _LOGGER.warning("Unexpected MQTT disconnect rc=%d — will auto-reconnect", rc)

    def _on_message(self, client, userdata, msg) -> None:
        """Decode incoming protobuf command and enqueue it."""
        # Extract action from topic suffix: .../cmd/{action}
        parts = msg.topic.split("/")
        if len(parts) < 1:
            return
        action = parts[-1]

        decoder = _CMD_DECODERS.get(action)
        if decoder is None:
            _LOGGER.debug("Unknown action '%s' on topic %s", action, msg.topic)
            return

        raw = bytes(msg.payload) if not isinstance(msg.payload, bytes) else msg.payload

        # Note: do NOT skip empty payloads here — StopCmd, PlayCmd, and
        # ReloadPlaylistCmd are empty protobuf messages that serialize to b"".
        # Empty payload on the STATUS topic means LWT (handled separately).

        try:
            cmd = decoder.FromString(raw)
            _LOGGER.info("Received %s command via %s", action, msg.topic)
            self.cmd_queue.put_nowait(cmd)
        except Exception as exc:
            _LOGGER.warning("Failed to decode %s from %s: %s", action, msg.topic, exc)

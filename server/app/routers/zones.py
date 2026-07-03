"""Zone management router — CRUD and command dispatch."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from fastapi import APIRouter, HTTPException

from app.config import ZONES_FILE
from app.models import Zone, ZoneCommand, ZoneCommandAction
from app.mqtt_client import get_mqtt

router = APIRouter(prefix="/zones", tags=["zones"])


def _load() -> Dict[str, dict]:
    p = Path(ZONES_FILE)
    if p.exists():
        return json.loads(p.read_text())
    return {}


def _save(data: Dict[str, dict]) -> None:
    Path(ZONES_FILE).parent.mkdir(parents=True, exist_ok=True)
    Path(ZONES_FILE).write_text(json.dumps(data, indent=2))


@router.get("/", response_model=List[Zone])
async def list_zones():
    return [Zone(**v) for v in _load().values()]


@router.post("/", response_model=Zone)
async def create_zone(zone: Zone):
    data = _load()
    if zone.zone_id in data:
        raise HTTPException(status_code=409, detail="Zone already exists")
    data[zone.zone_id] = zone.model_dump()
    _save(data)
    return zone


@router.get("/{zone_id}", response_model=Zone)
async def get_zone(zone_id: str):
    data = _load()
    if zone_id not in data:
        raise HTTPException(status_code=404, detail="Zone not found")
    return Zone(**data[zone_id])


@router.put("/{zone_id}", response_model=Zone)
async def update_zone(zone_id: str, zone: Zone):
    data = _load()
    zone = zone.model_copy(update={"zone_id": zone_id})
    data[zone_id] = zone.model_dump()
    _save(data)
    return zone


@router.delete("/{zone_id}")
async def delete_zone(zone_id: str):
    data = _load()
    if zone_id not in data:
        raise HTTPException(status_code=404, detail="Zone not found")
    del data[zone_id]
    _save(data)
    return {"deleted": zone_id}


@router.post("/{zone_id}/command")
async def send_zone_command(zone_id: str, cmd: ZoneCommand):
    """Send an MQTT command to a zone (or single Pi if pi_id is set)."""
    mqtt = get_mqtt()
    target = cmd.pi_id  # None means whole zone

    if cmd.action == ZoneCommandAction.play:
        if target:
            mqtt._publish(mqtt._pi_topic(target, "play"), __import__("alleycatv_pb2", fromlist=["PlayCmd"]).PlayCmd().SerializeToString())
        else:
            mqtt.play_zone(zone_id)

    elif cmd.action == ZoneCommandAction.stop:
        if target:
            mqtt._publish(mqtt._pi_topic(target, "stop"), __import__("alleycatv_pb2", fromlist=["StopCmd"]).StopCmd().SerializeToString())
        else:
            mqtt.stop_zone(zone_id)

    elif cmd.action == ZoneCommandAction.interrupt:
        if not cmd.file_url:
            raise HTTPException(status_code=422, detail="file_url is required for interrupt")
        if target:
            mqtt.interrupt_pi(target, cmd.file_url)
        else:
            mqtt.interrupt_zone(zone_id, cmd.file_url)

    elif cmd.action == ZoneCommandAction.reload:
        mqtt.reload_zone(zone_id)

    elif cmd.action == ZoneCommandAction.volume:
        if cmd.volume is None:
            raise HTTPException(status_code=422, detail="volume is required")
        mqtt.set_volume_zone(zone_id, cmd.volume)

    return {"status": "sent", "zone_id": zone_id, "action": cmd.action}

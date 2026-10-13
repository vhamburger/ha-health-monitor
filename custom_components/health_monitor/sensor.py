"""Sensor platform for the Health Monitor integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import (
    AddEntitiesCallback,
    async_add_entities,
)

from .const import DOMAIN
from .watchdog import HealthMonitorStatusSensor


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the watchdog sensor."""
    sensor = HealthMonitorStatusSensor(entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = sensor
    async_add_entities([sensor])
    return True

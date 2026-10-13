"""Watchdog entity for the Health Monitor integration.

Reports whether the target template helper still matches the body the
integration would generate from its configured rows:

* ``ok``      – helper matches the generated body
* ``drifted`` – helper was changed by hand (or never generated)
* ``missing`` – the target helper entry cannot be found
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity

from . import apply as apply_mod
from . import generator
from .const import CONF_ROWS, CONF_TARGET, GEN_MARKER

_LOGGER = logging.getLogger(__name__)

STATE_OK = "ok"
STATE_DRIFTED = "drifted"
STATE_MISSING = "missing"

_ICONS = {
    STATE_OK: "mdi:heart-multiple",
    STATE_DRIFTED: "mdi:heart-broken",
    STATE_MISSING: "mdi:heart-off-outline",
}


def compute_status(hass: HomeAssistant, entry: ConfigEntry) -> tuple[str, dict]:
    """Compute the watchdog state and its attributes."""
    rows = entry.options.get(CONF_ROWS, [])
    target = entry.data.get(CONF_TARGET, "")
    attrs: dict = {
        "rows": len(rows),
        "row_names": [r.get("name", "") for r in rows],
        "target": target,
    }

    helper = apply_mod.find_helper_entry(hass, target)
    if helper is None:
        return STATE_MISSING, attrs

    body = (helper.options or {}).get("state", "")
    if GEN_MARKER not in body:
        attrs["detail"] = "helper contains no generated template"
        return STATE_DRIFTED, attrs

    expected = generator.generate_body(rows)
    if expected == body:
        return STATE_OK, attrs

    attrs["detail"] = "helper differs from generated body"
    attrs["expected_chars"] = len(expected)
    attrs["actual_chars"] = len(body)
    return STATE_DRIFTED, attrs


class HealthMonitorStatusSensor(Entity):
    """Sync-status watchdog for the generated template."""

    _attr_name = "Health Monitor Status"

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._state = STATE_MISSING
        self._attrs: dict = {}

    @property
    def unique_id(self) -> str:
        return f"health-monitor-status-{self._entry.entry_id}"

    @property
    def state(self) -> str:
        return self._state

    @property
    def state_attributes(self) -> dict:
        return dict(self._attrs)

    @property
    def icon(self) -> str:
        return _ICONS.get(self._state, "mdi:heart-pulse")

    @property
    def available(self) -> bool:
        return True

    async def async_recompute(self) -> None:
        """Recompute the watchdog state and push it to the state machine."""
        self._state, self._attrs = compute_status(self.hass, self._entry)
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        await self.async_recompute()

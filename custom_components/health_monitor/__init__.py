"""The Health Monitor integration.

Keeps a template sensor (the health dashboard's source of truth) in sync
with a structured monitor table:

* The monitor table lives in this integration's config entry (HA storage,
  editable in the UI as a data table with quick-add).
* On setup / options save / resync the template body is regenerated and
  written to the target template helper (other option keys preserved).
* A watchdog sensor reports drift between table and helper.
* On first setup, an existing hand-written template body is imported
  into the table automatically.
"""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import (
    CONFIG_ENTRY_UPDATED,
    ConfigEntry,
)
from homeassistant.core import Event, HomeAssistant, ServiceCall, callback
from homeassistant.helpers.typing import ConfigType

from . import apply as apply_mod
from .const import CONF_ROWS, CONF_TARGET, DOMAIN
from . import import_body
from .watchdog import HealthMonitorStatusSensor

_LOGGER = logging.getLogger(__name__)

SERVICE_REFRESH = "refresh"
SERVICE_RESYNC = "resync"

SERVICE_SCHEMA = vol.Schema({})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})

    # One-time import: if no rows yet, parse the existing template body.
    if not entry.options.get(CONF_ROWS):
        target = entry.data.get(CONF_TARGET, "")
        helper = apply_mod.find_helper_entry(hass, target)
        if helper is not None:
            body = (helper.options or {}).get("state", "")
            rows = import_body.parse_body(body) if body else []
            if rows:
                await hass.config_entries.async_update_entry(
                    entry, options={CONF_ROWS: rows}
                )
                _LOGGER.info(
                    "Health Monitor: imported %d monitors from existing template",
                    len(rows),
                )

    ok = await apply_mod.apply_config(hass, entry)
    if not ok:
        _LOGGER.warning(
            "Health Monitor: initial apply failed – the status sensor will show it"
        )

    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])
    await _register_services(hass)

    # Recompute the watchdog when the helper (or our own entry) changes.
    @callback
    def _on_entry_updated(event: Event) -> None:
        if event.data.get("action") != "updated":
            return
        ids = set(event.data.get("entry_ids", []))
        own = {entry.entry_id}
        helper = apply_mod.find_helper_entry(hass, entry.data.get(CONF_TARGET, ""))
        if helper is not None:
            own.add(helper.entry_id)
        if not ids & own:
            return
        sensor: HealthMonitorStatusSensor | None = hass.data.get(DOMAIN, {}).get(
            entry.entry_id
        )
        if sensor is not None:
            hass.async_run_job(sensor.async_recompute)

    unsub = hass.bus.async_listen(CONFIG_ENTRY_UPDATED, _on_entry_updated)
    hass.data[DOMAIN][entry.entry_id + "_unsub"] = unsub

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, ["sensor"])
    if unloaded:
        data = hass.data.get(DOMAIN, {})
        data.pop(entry.entry_id, None)
        unsub = data.pop(entry.entry_id + "_unsub", None)
        if unsub is not None:
            unsub()
        if not data:
            hass.data.pop(DOMAIN, None)
    return unloaded


async def _register_services(hass: HomeAssistant) -> None:
    if not hass.services.has_service(DOMAIN, SERVICE_REFRESH):
        hass.services.async_register(
            DOMAIN, SERVICE_REFRESH, _handle_refresh, schema=SERVICE_SCHEMA
        )
    if not hass.services.has_service(DOMAIN, SERVICE_RESYNC):
        hass.services.async_register(
            DOMAIN, SERVICE_RESYNC, _handle_resync, schema=SERVICE_SCHEMA
        )


async def _handle_refresh(call: ServiceCall) -> None:
    for entry in call.hass.config_entries.async_entries(DOMAIN):
        sensor: HealthMonitorStatusSensor | None = call.hass.data.get(DOMAIN, {}).get(
            entry.entry_id
        )
        if sensor is not None:
            await sensor.async_recompute()


async def _handle_resync(call: ServiceCall) -> None:
    for entry in call.hass.config_entries.async_entries(DOMAIN):
        await apply_mod.apply_config(call.hass, entry)
        sensor: HealthMonitorStatusSensor | None = call.hass.data.get(DOMAIN, {}).get(
            entry.entry_id
        )
        if sensor is not None:
            await sensor.async_recompute()

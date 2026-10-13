"""Apply the generated template body to the target helper."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import CONF_ROWS, CONF_TARGET
from . import generator

_LOGGER = logging.getLogger(__name__)


def find_helper_entry(hass: HomeAssistant, entity_id: str) -> ConfigEntry | None:
    """Find the config entry behind a registered entity (if any)."""
    if not entity_id:
        return None
    registry = er.async_get(hass)
    registered = registry.async_get(entity_id)
    if registered is None or registered.config_entry_id is None:
        return None
    return hass.config_entries.async_get_entry(registered.config_entry_id)


async def apply_config(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Regenerate the body from the entry's rows and write it to the target helper.

    Direct options update + reload is used (deterministic, no options-flow
    round-trip): the generated body is trusted, other option keys of the
    template entry are preserved.
    """
    rows = entry.options.get(CONF_ROWS, [])
    target = entry.data.get(CONF_TARGET, "")
    helper = find_helper_entry(hass, target)
    if helper is None or helper.domain != "template":
        _LOGGER.error(
            "Health Monitor: target helper '%s' not found (or not a template entry)",
            target,
        )
        return False

    body = generator.generate_body(rows)
    merged = dict(helper.options or {})
    merged["state"] = body
    try:
        hass.config_entries.async_update_entry(helper, options=merged)
        await hass.config_entries.async_reload(helper.entry_id)
    except Exception:  # noqa: BLE001
        _LOGGER.exception(
            "Health Monitor: writing generated template to %s failed", target
        )
        return False

    _LOGGER.info(
        "Health Monitor: generated template applied to %s (%d rows, %d chars)",
        target,
        len(rows),
        len(body),
    )
    return True

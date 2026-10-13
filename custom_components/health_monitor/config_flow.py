"""Config and options flow for the Health Monitor integration."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import HomeAssistant
from homeassistant.data_selector import (
    BooleanSelector,
    BooleanSelectorConfig,
    DataTableRow,
    DataTableSelector,
    DataTableSelectorConfig,
    MultiSelectSelector,
    MultiSelectSelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
)
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.typing import ConfigType

from . import apply as apply_mod
from .const import CONF_ROWS, CONF_TARGET, DOMAIN, QUICK_ADD_EXCLUDE
from .util import normalize_rows

_LOGGER = logging.getLogger(__name__)


def _friendly_name(hass: HomeAssistant, entity_id: str) -> str:
    registry = er.async_get(hass)
    entry = registry.async_get(entity_id)
    if entry is not None:
        return entry.original_name or entry.name or entity_id
    return entity_id


class HealthMonitorConfigFlow(ConfigFlow, domain=DOMAIN):
    """User flow: pick the template sensor that should be generated."""

    VERSION = 1

    async def async_step_user(self, user_input: ConfigType | None = None) -> None:
        if user_input is not None:
            self.async_set_unique_id(user_input[CONF_TARGET])
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=user_input.get("title") or "Health Monitor",
                data={CONF_TARGET: user_input[CONF_TARGET]},
            )

        options = []
        registry = er.async_get(self.hass)
        for ent in registry.entities.values():
            if ent.platform == "template" and ent.entity_id.startswith("sensor."):
                label = ent.original_name or ent.name or ent.entity_id
                options.append(
                    {"value": ent.entity_id, "label": f"{ent.entity_id} ({label})"}
                )
        options.sort(key=lambda o: o["label"])

        schema = vol.Schema(
            {
                vol.Required("title", default="Health Monitor"): str,
                vol.Required(CONF_TARGET): SelectSelector(
                    SelectSelectorConfig(options=options, mode="dropdown", custom_value=True)
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> "HealthMonitorOptionsFlow":
        return HealthMonitorOptionsFlow(config_entry)


class HealthMonitorOptionsFlow(OptionsFlow):
    """Edit the monitor table; on save the template is regenerated + applied."""

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._rows = normalize_rows(entry.options.get(CONF_ROWS))
        self._quick_domain = ""

    def _domain_options(self) -> list[dict]:
        opts = []
        seen = set()
        for e in self.hass.config_entries.async_entries():
            if e.domain in seen or e.domain in QUICK_ADD_EXCLUDE:
                continue
            seen.add(e.domain)
            opts.append(
                {"value": e.domain, "label": f"{e.title or e.domain} ({e.domain})"}
            )
        opts.sort(key=lambda o: o["label"])
        return opts

    def _entity_options(self, domain: str) -> list[dict]:
        registry = er.async_get(self.hass)
        entry_ids = {
            e.entry_id for e in self.hass.config_entries.async_entries(domain)
        }
        opts = []
        for ent in registry.entities.values():
            if ent.config_entry_id in entry_ids:
                label = ent.original_name or ent.name or ent.entity_id
                opts.append(
                    {"value": ent.entity_id, "label": f"{label} ({ent.entity_id})"}
                )
        opts.sort(key=lambda o: o["label"])
        return opts

    @staticmethod
    def _row_schema() -> DataTableRow:
        return DataTableRow(
            {
                "name": TextSelector(TextSelectorConfig(label="Name")),
                "entry": TextSelector(TextSelectorConfig(label="Config-Entries (UUIDs, kommagetrennt)")),
                "rep": TextSelector(TextSelectorConfig(label="Rep-Entity")),
                "plug": TextSelector(TextSelectorConfig(label="Stecker (Switch)")),
                "quiet": BooleanSelector(BooleanSelectorConfig(label="Quiet")),
                "frame": BooleanSelector(BooleanSelectorConfig(label="Frame")),
                "mass": TextSelector(TextSelectorConfig(label="Mass-Domain")),
                "mass_ext": TextSelector(TextSelectorConfig(label="Mass-Options (thr=3, match=x)")),
                "check": TextSelector(TextSelectorConfig(label="Check (entity|bad|text)")),
                "fresh": TextSelector(TextSelectorConfig(label="Fresh (entity|stunden)")),
            }
        )

    async def async_step_init(self, user_input: ConfigType | None = None) -> None:
        return await self.async_step_options()

    async def async_step_options(self, user_input: ConfigType | None = None) -> None:
        if user_input is not None:
            self._rows = normalize_rows(user_input.get("rows"))
            domain = (user_input.get("quick_add_domain") or "").strip()
            if domain:
                self._quick_domain = domain
                return await self.async_step_quick_add()
            return await self._finish()

        schema = vol.Schema(
            {
                vol.Optional("rows", default=list(self._rows)): DataTableSelector(
                    DataTableSelectorConfig(row=self._row_schema())
                ),
                vol.Optional("quick_add_domain"): SelectSelector(
                    SelectSelectorConfig(options=self._domain_options(), mode="dropdown")
                ),
            }
        )
        return self.async_show_form(
            step_id="options",
            data_schema=schema,
            description_placeholders={"rows": len(self._rows)},
        )

    async def async_step_quick_add(self, user_input: ConfigType | None = None) -> None:
        if user_input is not None:
            for entity_id in user_input.get("entities", []):
                if any(r["rep"] == entity_id for r in self._rows):
                    continue
                row = {
                    "name": _friendly_name(self.hass, entity_id),
                    "entry": "",
                    "rep": entity_id,
                    "plug": "",
                    "quiet": False,
                    "frame": False,
                    "mass": "",
                    "mass_ext": "",
                    "check": "",
                    "fresh": "",
                }
                self._rows.append(row)
            return await self.async_step_options()

        schema = vol.Schema(
            {
                vol.Optional("entities", default=[]): MultiSelectSelector(
                    MultiSelectSelectorConfig(options=self._entity_options(self._quick_domain))
                ),
            }
        )
        return self.async_show_form(
            step_id="quick_add",
            data_schema=schema,
            description_placeholders={"domain": self._quick_domain},
        )

    async def _finish(self) -> None:
        """Persist rows, apply the generated template, then finish the flow."""
        rows = self._rows
        await self.hass.config_entries.async_update_entry(
            self._entry, options={CONF_ROWS: rows}
        )
        ok = await apply_mod.apply_config(self.hass, self._entry)
        if not ok:
            _LOGGER.warning(
                "Health Monitor: applying generated template failed – "
                "the status sensor will show 'missing'/'drifted'"
            )
        return self.async_create_entry(data={CONF_ROWS: rows})

"""Config and options flow for the Health Monitor integration."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
)
from homeassistant.helpers.typing import ConfigType

from . import apply as apply_mod
from .const import CONF_ROWS, CONF_TARGET, DOMAIN, QUICK_ADD_EXCLUDE
from .util import normalize_rows

_LOGGER = logging.getLogger(__name__)


def _friendly_name(hass: HomeAssistant, entity_id: str) -> str:
    """Best display name for an entity (registry first, then entity_id)."""
    entry = er.async_get(hass).async_get(entity_id)
    if entry is not None:
        return entry.original_name or entry.name or entity_id
    return entity_id


class HealthMonitorConfigFlow(ConfigFlow, domain=DOMAIN):
    """User flow: pick the template sensor that should be generated and kept in sync."""

    VERSION = 1

    async def async_step_user(self, user_input: ConfigType | None = None) -> None:
        """Select the target template sensor."""
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
                    SelectSelectorConfig(
                        options=options, mode="dropdown", custom_value=True
                    )
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    @staticmethod
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> HealthMonitorOptionsFlow:
        return HealthMonitorOptionsFlow(config_entry)


class HealthMonitorOptionsFlow(OptionsFlow):
    """Edit the monitor table row by row; on save the template is regenerated.

    HA 2026.10 removed the data-table selector, so the options flow offers an
    action select (generate & apply, add, edit, delete) plus quick-add from an
    integration; each row is edited in a ten-field form.
    """

    ACTION_APPLY = "__apply__"
    ACTION_NEW = "__new__"
    ACTION_DELETE = "__delete__"
    ROW_PREFIX = "row:"

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._rows = normalize_rows(entry.options.get(CONF_ROWS))
        self._quick_domain = ""
        self._row_idx: int | None = None

    async def async_step_init(self, user_input: ConfigType | None = None) -> None:
        return await self.async_step_options()

    # -- helpers ----------------------------------------------------------

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

    def _row_label(self, row: dict) -> str:
        name = row.get("name") or "(unnamed)"
        rep = row.get("rep") or ""
        return f"{name} — {rep}" if rep else name

    def _action_options(self) -> list[dict]:
        opts = [
            {"value": self.ACTION_APPLY, "label": "Generate template & apply"},
            {"value": self.ACTION_NEW, "label": "+ Add new monitor"},
            {"value": self.ACTION_DELETE, "label": "Delete monitors…"},
        ]
        for i, row in enumerate(self._rows):
            opts.append(
                {
                    "value": f"{self.ROW_PREFIX}{i}",
                    "label": f"{i + 1}. {self._row_label(row)}",
                }
            )
        return opts

    # -- steps ------------------------------------------------------------

    async def async_step_options(self, user_input: ConfigType | None = None) -> None:
        """Overview: choose an action or quick-add from an integration."""
        if user_input is not None:
            domain = (user_input.get("quick_add_domain") or "").strip()
            if domain:
                self._quick_domain = domain
                return await self.async_step_quick_add()
            action = user_input.get("action") or self.ACTION_APPLY
            if action == self.ACTION_NEW:
                self._row_idx = None
                return await self.async_step_row()
            if action == self.ACTION_DELETE:
                return await self.async_step_delete()
            if action.startswith(self.ROW_PREFIX):
                self._row_idx = int(action[len(self.ROW_PREFIX) :])
                return await self.async_step_row()
            return await self._finish()

        schema = vol.Schema(
            {
                vol.Required("action"): SelectSelector(
                    SelectSelectorConfig(
                        options=self._action_options(), mode="dropdown"
                    )
                ),
                vol.Optional("quick_add_domain"): SelectSelector(
                    SelectSelectorConfig(
                        options=self._domain_options(), mode="dropdown"
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="options",
            data_schema=schema,
            description_placeholders={"rows": len(self._rows)},
        )

    async def async_step_row(self, user_input: ConfigType | None = None) -> None:
        """Edit (or create) a single monitor row."""
        row = dict(self._rows[self._row_idx]) if self._row_idx is not None else {}
        if user_input is not None:
            row = {
                "name": (user_input.get("name") or "").strip(),
                "entry": (user_input.get("entry") or "").strip(),
                "rep": user_input.get("rep") or "",
                "plug": user_input.get("plug") or "",
                "quiet": bool(user_input.get("quiet")),
                "frame": bool(user_input.get("frame")),
                "mass": (user_input.get("mass") or "").strip(),
                "mass_ext": (user_input.get("mass_ext") or "").strip(),
                "check": (user_input.get("check") or "").strip(),
                "fresh": (user_input.get("fresh") or "").strip(),
            }
            if self._row_idx is not None:
                self._rows[self._row_idx] = row
            else:
                self._rows.append(row)
            self._row_idx = None
            return await self.async_step_options()

        schema = vol.Schema(
            {
                vol.Required("name", default=row.get("name", "")): TextSelector({}),
                vol.Optional("entry", default=row.get("entry", "")): TextSelector({}),
                vol.Optional("rep", default=row.get("rep", "")): EntitySelector({}),
                vol.Optional("plug", default=row.get("plug", "")): EntitySelector({}),
                vol.Optional("quiet", default=row.get("quiet", False)): BooleanSelector(
                    {}
                ),
                vol.Optional("frame", default=row.get("frame", False)): BooleanSelector(
                    {}
                ),
                vol.Optional("mass", default=row.get("mass", "")): TextSelector({}),
                vol.Optional(
                    "mass_ext", default=row.get("mass_ext", "")
                ): TextSelector({}),
                vol.Optional("check", default=row.get("check", "")): TextSelector({}),
                vol.Optional("fresh", default=row.get("fresh", "")): TextSelector({}),
            }
        )
        return self.async_show_form(
            step_id="row",
            data_schema=schema,
            description_placeholders={"name": row.get("name") or "new"},
        )

    async def async_step_delete(self, user_input: ConfigType | None = None) -> None:
        """Remove selected rows from the table."""
        if user_input is not None:
            selected = {str(i) for i in (user_input.get("rows") or [])}
            self._rows = [
                row for i, row in enumerate(self._rows) if str(i) not in selected
            ]
            return await self.async_step_options()

        schema = vol.Schema(
            {
                vol.Required("rows"): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            {
                                "value": str(i),
                                "label": f"{i + 1}. {self._row_label(r)}",
                            }
                            for i, r in enumerate(self._rows)
                        ],
                        multiple=True,
                        mode="dropdown",
                    )
                ),
            }
        )
        return self.async_show_form(step_id="delete", data_schema=schema)

    async def async_step_quick_add(
        self, user_input: ConfigType | None = None
    ) -> None:
        """Add monitors from the entities of one integration (one row each)."""
        if user_input is not None:
            for entity_id in user_input.get("entities") or []:
                if any(r["rep"] == entity_id for r in self._rows):
                    continue
                self._rows.append(
                    {
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
                )
            return await self.async_step_options()

        schema = vol.Schema(
            {
                vol.Optional("entities", default=[]): SelectSelector(
                    SelectSelectorConfig(
                        options=self._entity_options(self._quick_domain),
                        multiple=True,
                        mode="dropdown",
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="quick_add",
            data_schema=schema,
            description_placeholders={"domain": self._quick_domain},
        )

    async def _finish(self) -> None:
        """Persist the table, apply the generated template, then finish."""
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

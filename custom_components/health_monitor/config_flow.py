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
from .const import CONF_ROWS, CONF_TARGET, DOMAIN, QUICK_ADD_EXCLUDE, ROW_FIELDS
from .util import normalize_rows

_LOGGER = logging.getLogger(__name__)


def _friendly_name(hass: HomeAssistant, entity_id: str) -> str:
    """Best display name for an entity (registry first, then entity_id)."""
    entry = er.async_get(hass).async_get(entity_id)
    if entry is not None:
        return entry.original_name or entry.name or entity_id
    return entity_id


def _resolve_row_from_entity(hass: HomeAssistant, entity_id: str) -> dict:
    """Build a complete row dict from a single entity_id, auto-filling all fields."""
    registry = er.async_get(hass)
    ent = registry.async_get(entity_id)

    device_name = ""
    config_entry_id = ""

    if ent is not None:
        device_name = ent.original_name or ent.name or entity_id
        if ent.device_id:
            device = registry.async_get(ent.device_id)
            if device is not None:
                device_name = (
                    device.name_by_user or device.name or device_name
                )
                config_entries = (
                    getattr(device, "config_entries", None)
                    or getattr(device, "config_entries_data", [])
                )
                config_entry_id = config_entries[0] if config_entries else ""
    else:
        device_name = entity_id

    row: dict = {field: "" for field in ROW_FIELDS}
    row["name"] = device_name
    row["entry"] = config_entry_id
    row["rep"] = entity_id
    row["quiet"] = False
    row["frame"] = False
    return row


class HealthMonitorConfigFlow(ConfigFlow, domain=DOMAIN):
    """User flow: pick the template sensor that should be generated and kept in sync."""

    VERSION = 1

    async def async_step_user(self, user_input: ConfigType | None = None) -> None:
        """Select the target template sensor."""
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_TARGET])
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
    """Edit the monitor table; on save the template is regenerated.

    Actions:
    - Generate template & apply
    - Add by entity (searchable entity picker, 1 field)
    - Add by integration (pick domain → all entities pre-selected)
    - Delete monitors (multi-select)
    - Edit individual rows (name, quiet, frame)
    """

    ACTION_APPLY = "__apply__"
    ACTION_ADD_ENTITY = "__add_entity__"
    ACTION_ADD_INTEGRATION = "__add_integration__"
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
            {"value": self.ACTION_APPLY, "label": "✓ Generate template & apply"},
            {"value": self.ACTION_ADD_ENTITY, "label": "+ Add by entity"},
            {
                "value": self.ACTION_ADD_INTEGRATION,
                "label": "+ Add by integration",
            },
            {"value": self.ACTION_DELETE, "label": "− Delete monitors…"},
        ]
        for i, row in enumerate(self._rows):
            opts.append(
                {
                    "value": f"{self.ROW_PREFIX}{i}",
                    "label": f"  {i + 1}. {self._row_label(row)}",
                }
            )
        return opts

    # -- steps ------------------------------------------------------------

    async def async_step_options(self, user_input: ConfigType | None = None) -> None:
        """Main menu: choose an action."""
        if user_input is not None:
            action = user_input.get("action") or self.ACTION_APPLY
            if action == self.ACTION_ADD_ENTITY:
                return await self.async_step_add_entity()
            if action == self.ACTION_ADD_INTEGRATION:
                return await self.async_step_pick_domain()
            if action == self.ACTION_DELETE:
                return await self.async_step_delete()
            if action.startswith(self.ROW_PREFIX):
                self._row_idx = int(action[len(self.ROW_PREFIX) :])
                return await self.async_step_edit_row()
            return await self._finish()

        schema = vol.Schema(
            {
                vol.Required("action"): SelectSelector(
                    SelectSelectorConfig(
                        options=self._action_options(), mode="dropdown"
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="options",
            data_schema=schema,
            description_placeholders={"rows": len(self._rows)},
        )

    async def async_step_add_entity(
        self, user_input: ConfigType | None = None
    ) -> None:
        """Add a single monitor from an entity (searchable dropdown, 1 field)."""
        if user_input is not None:
            entity_id = user_input.get("entity") or ""
            # EntitySelector may return a string or a dict depending on HA version
            if isinstance(entity_id, dict):
                entity_id = entity_id.get("entity_id", "")
            if entity_id:
                if not any(r.get("rep") == entity_id for r in self._rows):
                    self._rows.append(_resolve_row_from_entity(self.hass, entity_id))
            return await self.async_step_options()

        schema = vol.Schema(
            {
                vol.Required("entity"): EntitySelector({}),
            }
        )
        return self.async_show_form(
            step_id="add_entity",
            data_schema=schema,
        )

    async def async_step_pick_domain(
        self, user_input: ConfigType | None = None
    ) -> None:
        """Pick an integration domain for bulk-add."""
        if user_input is not None:
            self._quick_domain = (user_input.get("domain") or "").strip()
            if self._quick_domain:
                return await self.async_step_quick_add()
            return await self.async_step_options()

        schema = vol.Schema(
            {
                vol.Required("domain"): SelectSelector(
                    SelectSelectorConfig(
                        options=self._domain_options(), mode="dropdown"
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="pick_domain",
            data_schema=schema,
        )

    async def async_step_quick_add(
        self, user_input: ConfigType | None = None
    ) -> None:
        """Select entities from the picked domain (all new ones pre-selected)."""
        all_entities = self._entity_options(self._quick_domain)
        already_monitored = {r.get("rep") for r in self._rows}
        default_selection = [
            opt["value"] for opt in all_entities if opt["value"] not in already_monitored
        ]

        if user_input is not None:
            for entity_id in user_input.get("entities") or []:
                if any(r.get("rep") == entity_id for r in self._rows):
                    continue
                self._rows.append(_resolve_row_from_entity(self.hass, entity_id))
            return await self.async_step_options()

        schema = vol.Schema(
            {
                vol.Required("entities", default=default_selection): SelectSelector(
                    SelectSelectorConfig(
                        options=all_entities, multiple=True, mode="dropdown"
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="quick_add",
            data_schema=schema,
            description_placeholders={"domain": self._quick_domain},
        )

    async def async_step_edit_row(self, user_input: ConfigType | None = None) -> None:
        """Edit an existing row (simplified: name, quiet, frame)."""
        row = dict(self._rows[self._row_idx]) if self._row_idx is not None else {}

        if user_input is not None:
            row["name"] = (user_input.get("name") or row.get("name") or "").strip()
            row["quiet"] = bool(user_input.get("quiet", row.get("quiet", False)))
            row["frame"] = bool(user_input.get("frame", row.get("frame", False)))
            if self._row_idx is not None:
                self._rows[self._row_idx] = row
            self._row_idx = None
            return await self.async_step_options()

        schema = vol.Schema(
            {
                vol.Required("name", default=row.get("name", "")): TextSelector({}),
                vol.Optional(
                    "quiet", default=row.get("quiet", False)
                ): BooleanSelector({}),
                vol.Optional(
                    "frame", default=row.get("frame", False)
                ): BooleanSelector({}),
            }
        )
        return self.async_show_form(
            step_id="edit_row",
            data_schema=schema,
            description_placeholders={"name": row.get("name") or "?"},
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

    async def _finish(self) -> None:
        """Persist the table, apply the generated template, then finish."""
        rows = self._rows
        self.hass.config_entries.async_update_entry(
            self._entry, options={CONF_ROWS: rows}
        )
        ok = await apply_mod.apply_config(self.hass, self._entry)
        if not ok:
            _LOGGER.warning(
                "Health Monitor: applying generated template failed – "
                "the status sensor will show 'missing'/'drifted'"
            )
        return self.async_create_entry(data={CONF_ROWS: rows})

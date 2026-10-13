"""Small shared helpers for the Health Monitor integration."""

from __future__ import annotations

from .const import ROW_FIELDS


def normalize_rows(raw: object) -> list[dict]:
    """Coerce user-supplied rows (from the options flow) to the row model."""
    rows: list[dict] = []
    if not isinstance(raw, (list, tuple)):
        return rows
    for r in raw:
        if not isinstance(r, dict):
            continue
        name = str(r.get("name") or "").strip()
        if not name:
            continue
        row: dict = {"name": name}
        for field in ROW_FIELDS:
            if field == "name":
                continue
            if field in ("quiet", "frame"):
                row[field] = bool(r.get(field))
            else:
                row[field] = str(r.get(field) or "")
        rows.append(row)
    return rows

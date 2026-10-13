"""Parse a health-monitor template body into structured rows.

Works on both the hand-written v3.3 template and generated bodies –
the cfg rows use the same dict-literal syntax in both.

Each cfg row with N checks expands into N rows (same shared fields,
one check each); the generator merges same-named rows again.
"""

from __future__ import annotations

import re

from .const import ROW_FIELDS


def _first(pattern: str, s: str) -> str:
    m = re.search(pattern, s)
    return m.group(1) if m else ""


def parse_body(body: str) -> list[dict]:
    """Extract the monitor rows from a template body."""
    rows: list[dict] = []
    for line in body.splitlines():
        s = line.strip()
        if not s.startswith("{'name'"):
            continue
        name = _first(r"\{'name':\s*'([^']*)'", s)
        if not name:
            continue

        entry_groups = re.findall(r"'entries':\s*\[([^\]]*)\]", s)
        entries = re.findall(r"'([^']*)'", entry_groups[0]) if entry_groups else []
        rep = _first(r"'rep':\s*\{'e':\s*'([^']*)'", s)
        plug = _first(r"'plug':\s*'([^']*)'", s)
        quiet = "'quiet': true" in s
        frame = "'frame': true" in s

        mass = ""
        mass_ext = ""
        mass_m = re.search(r"'mass':\s*\{([^}]*)\}", s)
        if mass_m:
            inner = mass_m.group(1)
            mass = _first(r"'d':\s*'([^']*)'", inner)
            ext = []
            thr = re.search(r"'thr':\s*(\d+)", inner)
            if thr:
                ext.append("thr=" + thr.group(1))
            match = re.search(r"'match':\s*'([^']*)'", inner)
            if match:
                ext.append("match=" + match.group(1))
            mass_ext = " ".join(ext)

        fresh = ""
        fresh_m = re.search(r"'fresh':\s*\{([^}]*)\}", s)
        if fresh_m:
            inner = fresh_m.group(1)
            f_e = _first(r"'e':\s*'([^']*)'", inner)
            f_h = re.search(r"'h':\s*(\d+)", inner)
            fresh = f_e + ("|" + f_h.group(1) if f_h else "")

        check_strs: list[str] = []
        checks_m = re.search(r"'checks':\s*\[(.*)\].*$", s)
        if checks_m:
            for item in re.findall(r"\{[^{}]*\}", checks_m.group(1)):
                c_e = _first(r"'e':\s*'([^']*)'", item)
                bad_groups = re.findall(r"'bad':\s*\[([^\]]*)\]", item)
                bad_list = (
                    re.findall(r"'([^']*)'", bad_groups[0]) if bad_groups else []
                )
                text_m = re.search(r"'text':\s*'([^']*)'", item)
                text = text_m.group(1) if text_m else ""
                parts = [c_e]
                if bad_list:
                    parts.append(",".join(bad_list))
                parts.append(text)
                check_strs.append("|".join(parts))

        base = {
            "name": name,
            "entry": ",".join(entries),
            "rep": rep,
            "plug": plug,
            "quiet": quiet,
            "frame": frame,
            "mass": mass,
            "mass_ext": mass_ext,
            "check": "",
            "fresh": fresh,
        }
        if check_strs:
            for c in check_strs:
                r = dict(base)
                r["check"] = c
                rows.append(r)
        else:
            rows.append(dict(base))
    return rows


def complete_row(row: dict) -> dict:
    """Ensure every known field is present on a row."""
    out = {}
    for field in ROW_FIELDS:
        value = row.get(field, False if field in ("quiet", "frame") else "")
        if field in ("quiet", "frame"):
            out[field] = bool(value)
        else:
            out[field] = str(value)
    return out

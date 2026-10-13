"""Generate the health-monitor template body from structured rows.

The template skeleton (everything except the row list) is copied verbatim
from the hand-written v3.3 template. The only generated part is the
``{% set cfg = [...] %}`` block, which is rebuilt from the structured
rows stored in the config entry.

Row fields (see ``const.ROW_FIELDS``):

* ``name``      – display name, used in todo lines
* ``entry``     – comma separated config entry UUIDs (setup-state check)
* ``rep``       – representative entity (availability check)
* ``plug``      – power switch entity (gate: off = never flagged)
* ``quiet``     – quiet-hours fallback gate (22-08)
* ``frame``     – part of TheFrame aggregation group
* ``mass``      – mass domain (e.g. ``zha``)
* ``mass_ext``  – ``thr=<n>`` / ``match=<substr>`` (space separated)
* ``check``     – ``entity`` | ``entity|bad1,bad2`` | ``entity|bad|text``
* ``fresh``     – ``entity`` | ``entity|<hours>``

Rows with the same ``name`` are merged into a single cfg row
(checks accumulate, other fields deduplicated / last-wins).
"""

from __future__ import annotations

import re

from .const import VERSION

# Verbatim copy of the v3.3 template, everything before the cfg block.
# (The final "" entry keeps the blank line that precedes the cfg block.)
SKELETON_PRE = "\n".join(
    (
        "{#",
        "  Health-Monitor v3.3 – Integration-Health (Shadow-Phase)",
        "  State-basiert; counter.health_tick (Heartbeat, 5 Min) erzwingt Re-Render.",
        "  Frame-Gating v3.3: TheFrame = EIN TV, drei Ansichten (Samsung/SmartThings/Music Assistant) am TV-Stecker switch.tasmota2 (aus=gewollt; Stecker weg=Quiet-Hours 22-08).",
        '  Ausgabe: JSON {"p": Probleme, "m": Mass-Alerts [domain, aktuell, baseline]}',
        "  Achtung: State max. 255 Zeichen – 'm' enthält nur aktive Alerts.",
        "#}",
        "{% set now = now() %}",
        "{% set quiet = now.hour >= 22 or now.hour < 8 %}",
        "{% set DEB = 300 %}",
        "{% set bl_raw = states['input_text.health_mass_baseline'].state %}",
        "{% set ok_bl = bl_raw is defined and bl_raw is string and bl_raw != '' %}",
        "{% set _hb = states['counter.health_tick'].state %}",
        "{% set nsp = namespace(pm = []) %}",
        "{% if ok_bl %}",
        "  {% for chunk in bl_raw.split(';') %}",
        "    {% set f = chunk.split(':') %}",
        "    {% if f | length == 3 %}",
        "      {% set nsp.pm = nsp.pm + [f[0] | trim, f[1] | trim | int, f[2] | trim | int] %}",
        "    {% endif %}",
        "  {% endfor %}",
        "{% endif %}",
        "{% set prev_mass = nsp.pm %}",
        "",
    )
)

# Verbatim copy of the v3.3 template, everything after the cfg block.
# (The leading "" entry keeps the blank line after the cfg block.)
SKELETON_POST = "\n".join(
    (
        "",
        "{% set ns = namespace(problems = [], m = []) %}",
        "{% set nfr = namespace(frame = []) %}",
        "{% for row in cfg %}",
        "  {% if row.plug is not defined and row.quiet is defined and row.quiet and quiet %}",
        "  {% else %}",
        "    {% for eid in row.entries | default([]) %}",
        "      {% set st = config_entry_attr(eid, 'state') %}",
        "      {% if row.entries | length > 1 %}",
        "        {% set nm = row.name ~ ' ' ~ config_entry_attr(eid, 'title') %}",
        "      {% else %}",
        "        {% set nm = row.name %}",
        "      {% endif %}",
        "      {% if st == 'setup_error' %}",
        "        {% set ns.problems = ns.problems + [nm ~ ': Setup-Fehler'] %}",
        "      {% elif st == 'setup_retry' %}",
        "        {% set ns.problems = ns.problems + [nm ~ ': Setup-Fehler (im Retry)'] %}",
        "      {% elif st == 'failed' %}",
        "        {% set ns.problems = ns.problems + [nm ~ ': Setup fehlgeschlagen'] %}",
        "      {% endif %}",
        "    {% endfor %}",
        "    {% if row.rep is defined %}",
        "      {% set s = states[row.rep.e] %}",
        "      {% set ps = states[row.plug] if row.plug is defined else none %}",
        "      {% if s.state in ['unavailable', 'unknown'] and (now - s.last_changed).total_seconds() > DEB %}",
        "        {% set gate = (ps is not none and ps.state == 'off') or (ps is not none and ps.state in ['unavailable', 'unknown'] and quiet) or (ps is none and row.quiet is defined and row.quiet and quiet) %}",
        "        {% if not gate %}",
        "        {% if row.frame is defined and row.frame %}",
        "          {% set nfr.frame = nfr.frame + [row.name ~ ': offline'] %}",
        "          {% else %}",
        "          {% set ns.problems = ns.problems + [row.name ~ ': offline'] %}",
        "          {% endif %}",
        "        {% endif %}",
        "      {% endif %}",
        "    {% endif %}",
        "    {% for chk in row.checks | default([]) %}",
        "      {% set s = states[chk.e] %}",
        "      {% if s.state in chk.bad and (now - s.last_changed).total_seconds() > DEB %}",
        "        {% set ns.problems = ns.problems + [row.name ~ ': ' ~ chk.text] %}",
        "      {% endif %}",
        "    {% endfor %}",
        "    {% if row.fresh is defined %}",
        "      {% set s = states[row.fresh.e] %}",
        "      {% if s.last_updated is not none and (now - s.last_updated).total_seconds() > row.fresh.h * 3600 %}",
        "        {% set ns.problems = ns.problems + [row.name ~ ': keine Daten seit ' ~ (((now - s.last_updated).total_seconds() / 3600) | round(1)) ~ 'h'] %}",
        "      {% endif %}",
        "    {% endif %}",
        "    {% if row.mass is defined %}",
        "      {% set d = row.mass.d %}",
        "      {% set all_ents = integration_entities(d) %}",
        "      {% if row.mass.match is defined %}",
        "        {% set ns.ents = [] %}",
        "        {% for x in all_ents %}{% if row.mass.match in x %}{% set ns.ents = ns.ents + [x] %}{% endif %}{% endfor %}",
        "      {% else %}",
        "        {% set ns.ents = all_ents %}",
        "      {% endif %}",
        "      {% set total = ns.ents | length %}",
        "      {% set ns.cur = 0 %}",
        "      {% for x in ns.ents %}{% if states[x].state in ['unavailable', 'unknown'] %}{% set ns.cur = ns.cur + 1 %}{% endif %}{% endfor %}",
        "      {% set cur = ns.cur %}",
        "      {% set ns.pv = none %}",
        "      {% for p in prev_mass %}{% if p[0] == d %}{% set ns.pv = p %}{% endif %}{% endfor %}",
        "      {% set prev_base = ns.pv[1] if ns.pv is not none else cur %}",
        "      {% set prev_alert = ns.pv is not none %}",
        "      {% set thr = row.mass.thr if row.mass.thr is defined else [8, (total * 0.10) | int] | max %}",
        "      {% if prev_alert %}",
        "        {% set alert = cur > prev_base + 2 %}",
        "      {% else %}",
        "        {% set alert = (cur - prev_base) >= thr %}",
        "      {% endif %}",
        "      {% if alert %}",
        "        {% set ns.problems = ns.problems + [row.name ~ ': Massenausfall – ' ~ cur ~ ' von ' ~ total ~ ' Entitäten offline'] %}",
        "        {% set ns.m = ns.m + [d, cur, prev_base] %}",
        "      {% endif %}",
        "    {% endif %}",
        "  {% endif %}",
        "{% endfor %}",
        "{# TheFrame: ein physischer TV, drei Ansichten -> 2+ gleichzeitig offline = eine Zeile #}",
        "{% if nfr.frame | length == 1 %}",
        "  {% set ns.problems = ns.problems + nfr.frame %}",
        "{% elif nfr.frame | length > 1 %}",
        "  {% set ns.problems = ns.problems + ['TheFrame: offline (mehrere Ansichten)'] %}",
        "{% endif %}",
        "",
        "{% set nso = namespace(pf = ns.problems, b = []) %}",
        "{% for r in ns.m %}",
        "  {% set nso.b = nso.b + [r[0] ~ ':' ~ r[1] ~ ':' ~ r[2]] %}",
        "{% endfor %}",
        "{% set b_str = nso.b | join(';') %}",
        "{% for _i in range(0, 30) %}",
        "  {%- set marker = (['+' ~ (ns.problems | length - nso.pf | length) ~ ' weitere'] if nso.pf | length < ns.problems | length else []) -%}",
        "  {%- set cand = {'p': nso.pf + marker, 'b': b_str, 'hb': _hb} | to_json -%}",
        "  {% if cand | length <= 240 or nso.pf | length == 0 %}{% break %}{% endif %}",
        "  {% set nso.pf = nso.pf[: (nso.pf | length - 1)] %}",
        "{% endfor %}",
        "{% set marker = (['+' ~ (ns.problems | length - nso.pf | length) ~ ' weitere'] if nso.pf | length < ns.problems | length else []) %}",
        "{{ {'p': nso.pf + marker, 'b': b_str, 'hb': _hb} | to_json }}",
    )
)

_DEFAULT_TITLE = "Health-Monitor v3.3"


def _q(value: object) -> str:
    """Render a value as a Jinja single-quoted string literal.

    Jinja strings have no escape mechanism, so quotes are stripped
    (and whitespace collapsed) instead.
    """
    v = str(value).replace("'", "").replace("\n", " ").strip()
    return "'" + v + "'"


def _mass_extras(mass_ext: str) -> list[str]:
    """Split ``thr=3 match=status`` into Jinja dict fragments."""
    extras: list[str] = []
    thr = re.search(r"thr=(\d+)", mass_ext or "")
    if thr:
        extras.append("'thr': " + thr.group(1))
    match = re.search(r"match=(\S+)", mass_ext or "")
    if match:
        extras.append("'match': " + _q(match.group(1)))
    return extras


def render_cfg(rows: list[dict]) -> str:
    """Render the ``{% set cfg = [...] %}`` block from rows."""
    groups: dict[str, dict] = {}
    order: list[str] = []

    for row in rows:
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        if name not in groups:
            groups[name] = {
                "name": name,
                "entries": [],
                "rep": "",
                "plug": "",
                "quiet": False,
                "frame": False,
                "mass": "",
                "mass_ext": "",
                "checks": [],
                "fresh": "",
            }
            order.append(name)
        g = groups[name]
        for e in (row.get("entry") or "").split(","):
            e = e.strip()
            if e and e not in g["entries"]:
                g["entries"].append(e)
        if (row.get("rep") or "").strip():
            g["rep"] = row["rep"].strip()
        if (row.get("plug") or "").strip():
            g["plug"] = row["plug"].strip()
        g["quiet"] = g["quiet"] or bool(row.get("quiet"))
        g["frame"] = g["frame"] or bool(row.get("frame"))
        if (row.get("mass") or "").strip():
            g["mass"] = row["mass"].strip().lower()
        if (row.get("mass_ext") or "").strip():
            g["mass_ext"] = row["mass_ext"].strip()
        if (row.get("check") or "").strip():
            g["checks"].append(row["check"].strip())
        if (row.get("fresh") or "").strip():
            g["fresh"] = row["fresh"].strip()

    lines = ["{% set cfg = ["]
    for name in order:
        g = groups[name]
        parts = ["  {'name': " + _q(g["name"])]
        if g["frame"]:
            parts.append(", 'frame': true")
        if g["quiet"]:
            parts.append(", 'quiet': true")
        if g["entries"]:
            parts.append(
                ", 'entries': [" + ", ".join(_q(e) for e in g["entries"]) + "]"
            )
        if g["rep"]:
            parts.append(", 'rep': {'e': " + _q(g["rep"]) + "}")
        if g["plug"]:
            parts.append(", 'plug': " + _q(g["plug"]))
        if g["mass"]:
            mass = "{'d': " + _q(g["mass"])
            for extra in _mass_extras(g["mass_ext"]):
                mass += ", " + extra
            parts.append(", 'mass': " + mass + "}")
        if g["checks"]:
            rendered = []
            for c in g["checks"]:
                f = [x.strip() for x in c.split("|")]
                e = f[0]
                bad = [b.strip() for b in f[1].split(",") if b.strip()] if len(f) > 1 else []
                if not bad:
                    bad = ["unavailable", "unknown"]
                text = f[2] if len(f) > 2 and f[2] else "offline"
                rendered.append(
                    "{'e': "
                    + _q(e)
                    + ", 'bad': ["
                    + ", ".join(_q(b) for b in bad)
                    + "], 'text': "
                    + _q(text)
                    + "}"
                )
            parts.append(", 'checks': [" + ", ".join(rendered) + "]")
        if g["fresh"]:
            f = [x.strip() for x in g["fresh"].split("|")]
            h = f[1] if len(f) > 1 and f[1] else ""
            if not h.isdigit():
                h = "24"
            parts.append(", 'fresh': {'e': " + _q(f[0]) + ", 'h': " + h + "}")
        parts.append("},")
        lines.append("".join(parts))
    lines.append("] %}")
    return "\n".join(lines)


def generate_body(rows: list[dict], header: str | None = None) -> str:
    """Build the complete template body.

    ``header`` replaces the "Health-Monitor v3.3" title fragment in the
    comment block; by default it is set to the generation marker.
    """
    if header is None:
        header = "Health-Monitor (generated by health-monitor v" + VERSION + ")"
    pre = SKELETON_PRE.replace(_DEFAULT_TITLE, header, 1)
    return pre + "\n" + render_cfg(rows) + "\n" + SKELETON_POST

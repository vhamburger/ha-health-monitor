# Health Monitor

Eine kleine Custom-Integration für Home Assistant, die die Pflege eines
Template-basierten **Integration-Health-Monitors** übernimmt.

## Was macht sie?

* Der komplette Monitor-Katalog (41+ Zeilen: Name, Config-Entries,
  Rep-Entity, Power-Stecker, Quiet-/Frame-Flags, Mass-Domain,
  Zustands-Checks, Fresh-Checks) lebt **strukturiert im Config-Entry** der
  Integration – bearbeitbar über eine Data-Table im HA-UI (mit Quick-Add
  pro Integration), nicht mehr als 41-zeiliger Hand-Codetext in einem
  Template.
* Bei jedem Speichern wird das Ziel-Template **neu generiert und in den
  Template-Helper geschrieben** (sonstige Options des Helpers bleiben
  erhalten).
* Ein **Watchdog-Sensor** (`sensor.health_monitor_status`) meldet `ok` /
  `drifted` / `missing`, falls der Helper von Hand verändert wurde oder
  fehlt.
* Bei der **ersten Einrichtung** wird ein bestehendes, handgeschriebenes
  Template automatisch importiert (41-zeilige `cfg` → strukturierte Zeilen).

## Companion-Setup (einmalig, nicht von dieser Integration erzeugt)

Das Template setzt diese Helfer voraus (bleiben bei jedem Redesign unverändert):

* `counter.health_tick` – Heartbeat-Counter (5-Min-Takt erzwingt Re-Render)
* `input_text.health_mass_baseline` – Mass-Baseline (Format `domain:aktuell:baseline;…`)
* 2 Automationen (Diff-Alarm auf Helper-Änderung + Heartbeat-Inkrement)
* das Ziel-Template als **Template-Sensor** (z. B. `sensor.health_integration_problems`)

## Installation

```
HACS → Custom repositories → + → https://github.com/<dein-user>/ha-health-monitor
```
danach HA neu starten und unter *Einstellungen → Geräte & Dienste → Health Monitor*
einrichten (Ziel-Template-Sensor wählen).

## Services

| Service | Wirkung |
|---|---|
| `health_monitor.refresh` | Watchdog-Status neu berechnen |
| `health_monitor.resync` | Template aus der Tabelle neu generieren + in den Helper schreiben |

## Zeilen-Modell

| Feld | Bedeutung |
|---|---|
| `name` | Anzeigename (gleicher Name = Zeilen werden zusammengeführt) |
| `entry` | Config-Entry-UUIDs, kommagetrennt (Setup-State-Check) |
| `rep` | Repräsentative Entity (Availability-Check, 5-Min-Debounce) |
| `plug` | Power-Switch (aus = nie flaggen; weg = Quiet-Hours-Fallback) |
| `quiet` | Quiet-Hours-Gate (22–08) ohne Stecker |
| `frame` | Teil der TheFrame-Aggregation (2+ offline = 1 Zeile) |
| `mass` | Mass-Domain (z. B. `zha`), Threshold = max(8, 10 %) |
| `mass_ext` | `thr=<n>` und/oder `match=<substr>` |
| `check` | `entity\|bad1,bad2\|text` (mehrere → mehrere Zeilen, gleicher Name) |
| `fresh` | `entity\|stunden` (Staleness-Check) |

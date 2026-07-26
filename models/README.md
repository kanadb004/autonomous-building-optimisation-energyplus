# models/building.idf

Source: `5ZoneAirCooled.idf` from the EnergyPlus 26.1.0 `ExampleFiles/`
install, chosen per PROJECT_PLAN.md §1.1 (first-choice candidate; no
fallback needed — this file did not fight).

## Why this file

- Real HVAC with electricity consumption: VAV air system with hot-water
  reheat coils, central chilled-water cooling coil, electric chiller with
  air-cooled condenser, hot-water boiler. `Electricity:HVAC` meter is
  present and non-trivial (chiller + fans + pumps).
- Thermostats driven by named setpoint schedules: all 5 conditioned zones
  use `ThermostatSetpoint:DualSetpoint` referencing two shared schedules,
  `Htg-SetP-Sch` and `Clg-SetP-Sch` — these are the actuation targets for
  Phase 2.
- No `HVACTemplate:*` objects, so no `ExpandObjects` pre-processing step
  is needed — the API can run it as-is.
- Chicago TMY3 weather (bundled, copied into `models/weather/`) gives
  strong heating and cooling seasons.

## Zones

Single-story, 5000 ft² floor plate, 1 interior + 4 exterior conditioned
zones plus an unconditioned return plenum (not thermostat-controlled, not
polled by the telemetry logger):

- `SPACE1-1` (south/front, largest exterior zone)
- `SPACE2-1` (east/right)
- `SPACE3-1` (north/back)
- `SPACE4-1` (west/left)
- `SPACE5-1` (interior/core)
- `PLENUM-1` (return air plenum, unconditioned)

## HVAC

VAV (variable air volume) system with terminal reheat, one AHU serving all
5 zones, central chilled-water coil (electric chiller, air-cooled
condenser) and hot-water preheat/reheat (natural-gas boiler). Electricity
end uses on the `Electricity:HVAC` meter: chiller, supply/return fans,
pumps.

## Changes made from the stock example file

1. **RunPeriod trimmed** to a 1-week dev window: 1/14–1/20 (was 1/1–12/31).
   Per §1.1, demo period (1 month or two contrasting months) will be a
   separate config value applied later, not baked into this committed IDF.
2. **Added `Output:Variable,*,Zone People Occupant Count,hourly;`** — not
   present in the stock file, needed for the occupancy telemetry field.
3. **Added `Output:Meter,Electricity:HVAC,hourly;`** (stock file only had
   `Output:Meter:MeterFileOnly` at monthly/runperiod frequency) — makes the
   per-timestep HVAC electricity readable via a plain CLI run for
   cross-checking, alongside the API path.

All other Output:Variable/Output:Meter/Output:Table:SummaryReports
directives are unchanged from the stock file and already sufficient for
Phase 1 (zone temp, outdoor temp, HVAC electricity) and the `eplustbl.htm`
End Uses cross-check table (`AllSummaryAndSizingPeriod`).

## Setpoint schedules (context for Phase 2)

`Htg-SetP-Sch` / `Clg-SetP-Sch` already encode an occupied/unoccupied
setback (22.2/23.9 °C occupied weekdays 6:00–20:00, 16.7/29.4 °C
otherwise) — flagged here because PROJECT_PLAN.md §2 validation warns that
an already-set-back baseline can make the rule-based controller look like
it saves ~0%; the prescribed fix if that happens is documented there, not
here.

See `docs/discovered_names.md` for the exact variable/meter names and the
Phase 1 cross-check value, and `building_baseline_notes.md` for a shorter
changelog-style summary.

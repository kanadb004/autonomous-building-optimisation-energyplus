# Building Models (.idf)

Autonomous Building Management System — EnergyPlus building models.
Baseline model plus every variant generated at runtime during evaluation.

## Contents

```
baseline/
  building.idf                              base model, committed at models/building.idf

runtime_generated/
  january_week__building.idf                 heating-season evaluation week
  july_week__building.idf                    cooling-season evaluation week
  extended_january__building.idf             extended-horizon reliability run
  native_showcase__building.idf              native MCP tool-calling demo run
  phase2_sanity_check__building_one_day.idf  single-day actuation sanity check
```

## Baseline model

Derived from the EnergyPlus example file `5ZoneAirCooled.idf` — a single-story
building with four exterior conditioned zones, one interior conditioned zone,
and a return plenum. Electric chiller with air-cooled condenser; autosized
preheating and precooling water coils in the outside-air stream.

- IDF version: 26.1
- Location: Chicago, IL (weather: `USA_IL_Chicago-OHare.Intl.AP.725300_TMY3.epw`)
- Conditioned zones: SPACE1-1 … SPACE5-1
- Committed RunPeriod: 1/14 – 1/20 (the development window)

## How the runtime variants are generated

Each evaluation run copies the baseline and patches exactly one object — the
`RunPeriod` begin/end month and day — via `src/abms/idf_utils.py`, invoked from
`src/abms/orchestrator.py`. The patched copy is written into that run's output
directory alongside a `manifest.json` recording the source path and its SHA-256,
so every result traces back to a specific baseline revision.

**Nothing else in the model is modified.** In particular, the HVAC setpoints
that the agent controls are *not* written into the IDF. They are applied during
simulation through the EnergyPlus Python plugin/API actuator interface, so the
model geometry, construction, systems, schedules, and loads are byte-identical
across every run. This keeps the baseline, rule-based, and AI arms of each
comparison running on the same physical building.

| File | RunPeriod | Purpose |
|---|---|---|
| `baseline/building.idf` | 1/14 – 1/20 | Committed source model |
| `january_week__building.idf` | 1/14 – 1/20 | Heating-season comparison (baseline / rule-based / AI) |
| `july_week__building.idf` | 7/14 – 7/20 | Cooling-season comparison |
| `extended_january__building.idf` | 1/1 – 1/31 | Extended-horizon reliability run |
| `native_showcase__building.idf` | 1/14 – 1/14 | Native MCP tool-calling demonstration |
| `phase2_sanity_check__building_one_day.idf` | 1/14 – 1/14 | Actuation sanity check |

The last two are byte-identical to each other — both are the same single-day
window patched from the same baseline.

## Verification

Diffing any runtime variant against the baseline shows only the four RunPeriod
date fields:

```
diff baseline/building.idf runtime_generated/july_week__building.idf
```

SHA-256 checksums for all files are in `SHA256SUMS.txt`.

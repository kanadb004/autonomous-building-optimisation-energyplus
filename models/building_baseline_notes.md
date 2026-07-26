# Building model notes

Chosen: `5ZoneAirCooled.idf` (EnergyPlus 26.1.0 `ExampleFiles/`), first
candidate tried; no need to fall back to `RefBldgSmallOfficeNew2004_Chicago.idf`.

Changes from stock, in order applied:
1. RunPeriod trimmed to 1/14-1/20 (1-week dev window).
2. Added `Output:Variable,*,Zone People Occupant Count,hourly;`.
3. Added `Output:Meter,Electricity:HVAC,hourly;`.
4. **(Phase 2)** Added `Output:EnergyManagementSystem,Verbose,Verbose,Verbose;`
   to expose the `.edd` actuator listing.
5. **(Phase 2)** `Htg-SetP-Sch`/`Clg-SetP-Sch` simplified from the stock
   file's deep, oddly-timed setback to a conventional constant
   occupied-hours setpoint with a *modest* night setback: 21.0/24.0  C
   6:00-20:00 weekdays, 18.0/27.0  C otherwise. Two reasons, both documented
   in detail in `docs/decisions.md`: (a) the stock schedule already baked in
   a deep setback of its own, which made rule-based-vs-baseline savings
   ~0%, the exact failure mode to watch for; (b) a fully
   flat, zero-setback baseline (tried first) overshot to an implausible
   ~65% savings figure, so "modest setback" (per the baseline
   definition) was the right target, not "no setback at all."

Full rationale and zone/HVAC description: see `README.md` in this directory.

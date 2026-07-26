# Building model notes

Chosen: `5ZoneAirCooled.idf` (EnergyPlus 26.1.0 `ExampleFiles/`), first
candidate per §1.1 — no need to fall back to `RefBldgSmallOfficeNew2004_Chicago.idf`.

Changes from stock, in order applied:
1. RunPeriod trimmed to 1/14-1/20 (1-week dev window).
2. Added `Output:Variable,*,Zone People Occupant Count,hourly;`.
3. Added `Output:Meter,Electricity:HVAC,hourly;`.

Full rationale and zone/HVAC description: see `README.md` in this directory.

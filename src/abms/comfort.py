"""Fanger PMV thermal comfort index (GC-3, docs/GAP_CLOSURE_PLAN.md §2 Phase
GC-3).

Self-contained implementation of the Fanger Predicted Mean Vote per ISO 7730
/ ASHRAE 55 (the standard iterative clothing-surface-temperature solution).
No pip dependency -- the equation set is ~40 lines and the network in this
environment is unreliable, so `pythermalcomfort` was deliberately not added
(docs/GAP_CLOSURE_PLAN.md §4).

**Design decision (made -- not revisited here):** PMV is computed post-hoc
in Python from already-recorded telemetry, not via EnergyPlus's native
Fanger reporting. No resimulation happens in this phase.

**Fixed assumptions** (telemetry does not carry these inputs, so they are
held constant; also stated in docs/architecture.md per GC-3.1):
- mean radiant temperature = air temperature (no surface-temp data logged)
- relative humidity = 50% (humidity not tracked in telemetry)
- air velocity = 0.1 m/s (typical still indoor air)
- metabolic rate = 1.1 met (light office work)
- clothing insulation = 1.0 clo October-April (heating months), 0.5 clo
  May-September (cooling months), selected by the timestamp's month
"""

import math

RH_ASSUMED_PCT = 50.0
AIR_VELOCITY_ASSUMED_MPS = 0.1
METABOLIC_RATE_ASSUMED_MET = 1.1
CLO_HEATING_MONTHS = 1.0
CLO_COOLING_MONTHS = 0.5
HEATING_MONTHS = {10, 11, 12, 1, 2, 3, 4}


def clo_for_month(month: int) -> float:
    """1.0 clo Oct-Apr, 0.5 clo May-Sep (GC-3.1's fixed clothing schedule)."""
    return CLO_HEATING_MONTHS if month in HEATING_MONTHS else CLO_COOLING_MONTHS


def pmv(ta: float, tr: float, rh: float, vel: float, met: float, clo: float) -> float:
    """Fanger PMV via the standard iterative clothing-surface-temperature
    solution (ISO 7730 / ASHRAE 55). ta/tr in degC, rh in %, vel in m/s, met
    in met, clo in clo. External work (wme) is assumed zero."""
    pa = rh * 10.0 * math.exp(16.6536 - 4030.183 / (ta + 235.0))
    icl = 0.155 * clo
    m = met * 58.15
    mw = m  # external work (wme) assumed zero

    fcl = 1.0 + 1.29 * icl if icl <= 0.078 else 1.05 + 0.645 * icl

    hcf = 12.1 * math.sqrt(vel)
    taa = ta + 273.0
    tra = tr + 273.0
    tcla = taa + (35.5 - ta) / (3.5 * icl + 0.1)

    p1 = icl * fcl
    p2 = p1 * 3.96
    p3 = p1 * 100.0
    p4 = p1 * taa
    p5 = 308.7 - 0.028 * mw + p2 * (tra / 100.0) ** 4
    xn = tcla / 100.0
    xf = tcla / 100.0
    hc = hcf
    n = 0
    eps = 0.00015
    while n == 0 or abs(xn - xf) > eps:
        xf = (xf + xn) / 2.0
        hcn = 2.38 * abs(100.0 * xf - taa) ** 0.25
        hc = hcf if hcf > hcn else hcn
        xn = (p5 + p4 * hc - p2 * xf**4) / (100.0 + p3 * hc)
        n += 1
        if n > 150:
            break

    tcl = 100.0 * xn - 273.0

    hl1 = 3.05 * 0.001 * (5733.0 - 6.99 * mw - pa)
    hl2 = 0.42 * (mw - 58.15) if mw > 58.15 else 0.0
    hl3 = 1.7 * 0.00001 * m * (5867.0 - pa)
    hl4 = 0.0014 * m * (34.0 - ta)
    hl5 = 3.96 * fcl * (xn**4 - (tra / 100.0) ** 4)
    hl6 = fcl * hc * (tcl - ta)

    ts = 0.303 * math.exp(-0.036 * m) + 0.028
    return ts * (mw - hl1 - hl2 - hl3 - hl4 - hl5 - hl6)


def pmv_for_zone(air_temp_c: float, month: int) -> float:
    """High-level entry point: PMV from air temperature and month alone,
    applying GC-3.1's fixed assumptions (MRT = air temp, RH 50%, air
    velocity 0.1 m/s, 1.1 met, clo by month)."""
    return pmv(
        ta=air_temp_c,
        tr=air_temp_c,
        rh=RH_ASSUMED_PCT,
        vel=AIR_VELOCITY_ASSUMED_MPS,
        met=METABOLIC_RATE_ASSUMED_MET,
        clo=clo_for_month(month),
    )

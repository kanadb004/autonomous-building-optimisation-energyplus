"""Fanger PMV comfort index, per ISO 7730 / ASHRAE 55.

Computed after the fact from recorded telemetry rather than by EnergyPlus.
Telemetry doesn't carry the other PMV inputs, so they are held fixed:
mean radiant temp = air temp, RH 50%, air velocity 0.1 m/s, 1.1 met, and
clothing by month.
"""

import math

RH_ASSUMED_PCT = 50.0
AIR_VELOCITY_ASSUMED_MPS = 0.1
METABOLIC_RATE_ASSUMED_MET = 1.1
CLO_HEATING_MONTHS = 1.0
CLO_COOLING_MONTHS = 0.5
HEATING_MONTHS = {10, 11, 12, 1, 2, 3, 4}


def clo_for_month(month: int) -> float:
    """1.0 clo Oct-Apr, 0.5 clo May-Sep."""
    return CLO_HEATING_MONTHS if month in HEATING_MONTHS else CLO_COOLING_MONTHS


def pmv(ta: float, tr: float, rh: float, vel: float, met: float, clo: float) -> float:
    """PMV by the usual iterative solution for clothing surface temperature.

    ta/tr in degC, rh in %, vel in m/s. External work is assumed zero.
    """
    pa = rh * 10.0 * math.exp(16.6536 - 4030.183 / (ta + 235.0))
    icl = 0.155 * clo
    m = met * 58.15
    mw = m  # external work assumed zero

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
    """PMV from air temperature and month, using the fixed assumptions."""
    return pmv(
        ta=air_temp_c,
        tr=air_temp_c,
        rh=RH_ASSUMED_PCT,
        vel=AIR_VELOCITY_ASSUMED_MPS,
        met=METABOLIC_RATE_ASSUMED_MET,
        clo=clo_for_month(month),
    )

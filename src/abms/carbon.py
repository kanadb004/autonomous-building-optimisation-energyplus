"""Grid carbon intensity and carbon accounting.

A synthetic diurnal profile shaped like Illinois: low midday when solar is
up, peaking in the evening. Deliberately not a live feed, since simulation
time isn't wall time. It gives the controller a real trade-off to reason
about, such as pre-cooling during clean hours.
"""

# kg CO2 per kWh, by hour of day.
HOURLY_INTENSITY_KG_PER_KWH = [
    0.50, 0.50, 0.49, 0.48, 0.47, 0.46,  # overnight
    0.45, 0.42, 0.38, 0.33, 0.29, 0.26,  # morning, solar rising
    0.25, 0.25, 0.26, 0.28, 0.31, 0.36,  # midday trough
    0.45, 0.55, 0.55, 0.53, 0.52, 0.51,  # evening peak
]


def intensity_for_hour(hour: int) -> float:
    return HOURLY_INTENSITY_KG_PER_KWH[hour % 24]


def kwh_to_kg_co2(interval_kwh: float, hour: int) -> float:
    return interval_kwh * intensity_for_hour(hour)


# Standard EPA/EIA factor for pipeline natural gas. Doesn't vary by hour.
GAS_EMISSION_FACTOR_KG_PER_KWH = 0.181


def gas_kwh_to_kg_co2(interval_kwh: float) -> float:
    return interval_kwh * GAS_EMISSION_FACTOR_KG_PER_KWH

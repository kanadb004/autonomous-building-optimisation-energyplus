"""Synthetic time-varying grid-carbon-intensity profile + accounting (§5).
No live grid API by design -- simulation-time isn't wall-time, so a live feed
would be meaningless anyway. This is a representative MISO/Illinois-shaped
diurnal profile (low midday, solar-heavy; evening peak), documented here as
the source of truth rather than fetched. It gives later-phase controllers a
real trade-off to reason about (pre-cool during clean/cheap hours).
"""

# kg CO2 per kWh, indexed by hour-of-day (0-23).
HOURLY_INTENSITY_KG_PER_KWH = [
    0.50, 0.50, 0.49, 0.48, 0.47, 0.46,  # 00-05: overnight, baseload-heavy
    0.45, 0.42, 0.38, 0.33, 0.29, 0.26,  # 06-11: morning ramp-down as solar rises
    0.25, 0.25, 0.26, 0.28, 0.31, 0.36,  # 12-17: midday solar trough, afternoon climb
    0.45, 0.55, 0.55, 0.53, 0.52, 0.51,  # 18-23: evening peak, gradual decline
]


def intensity_for_hour(hour: int) -> float:
    return HOURLY_INTENSITY_KG_PER_KWH[hour % 24]


def kwh_to_kg_co2(interval_kwh: float, hour: int) -> float:
    return interval_kwh * intensity_for_hour(hour)


# Natural gas combustion emission factor (kg CO2 / kWh), not time-varying
# (unlike the grid, gas combustion intensity doesn't depend on time of day).
# ~0.181 kg CO2/kWh is the standard EPA/EIA pipeline natural-gas factor.
GAS_EMISSION_FACTOR_KG_PER_KWH = 0.181


def gas_kwh_to_kg_co2(interval_kwh: float) -> float:
    return interval_kwh * GAS_EMISSION_FACTOR_KG_PER_KWH

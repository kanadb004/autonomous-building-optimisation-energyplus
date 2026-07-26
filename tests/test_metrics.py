"""Unit tests for the peak-demand kW math (GC-2, docs/GAP_CLOSURE_PLAN.md
§2 Phase GC-2). Synthetic two-row fixtures only -- no EnergyPlus, per §6."""

from abms import metrics


def _row(timestamp: str, kwh: float) -> dict:
    return {"timestamp": timestamp, "hvac_electricity_interval_kwh": kwh}


def test_interval_minutes_derives_from_two_rows():
    rows = [_row("1986-01-14T00:15:00", 0.1), _row("1986-01-14T00:30:00", 0.1)]
    assert metrics.interval_minutes(rows) == 15.0


def test_interval_minutes_defaults_on_zero_or_one_row():
    assert metrics.interval_minutes([]) == metrics.DEFAULT_INTERVAL_MINUTES
    assert metrics.interval_minutes([_row("1986-01-14T00:15:00", 0.1)]) == metrics.DEFAULT_INTERVAL_MINUTES


def test_interval_kwh_to_kw():
    # 0.25 kWh over a 15-minute interval is an average 1 kW.
    assert metrics.interval_kwh_to_kw(0.25, 15.0) == 1.0


def test_peak_demand_kw_picks_max_interval_and_its_timestamp():
    rows = [
        _row("1986-01-14T00:15:00", 0.10),  # 0.4 kW
        _row("1986-01-14T00:30:00", 0.25),  # 1.0 kW <- peak
        _row("1986-01-14T00:45:00", 0.05),  # 0.2 kW
    ]
    peak_kw, peak_at = metrics.peak_demand_kw(rows)
    assert peak_kw == 1.0
    assert peak_at == "1986-01-14T00:30:00"


def test_peak_demand_kw_empty_rows():
    assert metrics.peak_demand_kw([]) == (0.0, None)


def test_pct_intervals_above_threshold():
    rows = [
        _row("1986-01-14T00:15:00", 0.10),  # 0.4 kW
        _row("1986-01-14T00:30:00", 0.25),  # 1.0 kW -- above
        _row("1986-01-14T00:45:00", 0.30),  # 1.2 kW -- above
        _row("1986-01-14T01:00:00", 0.05),  # 0.2 kW
    ]
    assert metrics.pct_intervals_above_threshold(rows, 0.5) == 50.0


def test_summarize_run_peak_demand_fields(tmp_path):
    zone_cols = ",".join(f"zone_temp_c_{z},zone_occupant_count_{z}" for z in metrics.ZONE_NAMES)
    zone_vals = ",".join("20.0,0" for _ in metrics.ZONE_NAMES)
    csv_text = (
        f"timestamp,run_id,mode,{zone_cols},"
        "hvac_electricity_interval_kwh,hvac_gas_interval_kwh,"
        "hvac_electricity_cumulative_kwh,hvac_gas_cumulative_kwh\n"
        f"1986-01-14T00:15:00,t,baseline,{zone_vals},0.10,0,0.10,0\n"
        f"1986-01-14T00:30:00,t,baseline,{zone_vals},0.25,0,0.35,0\n"
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "telemetry.csv").write_text(csv_text)

    summary = metrics.summarize_run(run_dir, peak_demand_kw_threshold=0.5)
    assert summary["peak_demand_kw"] == 1.0
    assert summary["peak_demand_at"] == "1986-01-14T00:30:00"
    assert summary["pct_intervals_above_threshold"] == 50.0

"""Quantitative savings dashboard (GC-6, docs/GAP_CLOSURE_PLAN.md §2 Phase
GC-6). A pure reader of `runs/demo_final/` -- never imports `abms.simulation`,
`abms.mcp_server`, or anything that touches EnergyPlus, so a dashboard crash
can never affect a simulation run in progress. `abms.metrics` / `abms.carbon`
/ `abms.comfort` are fine to import: pure math, computed once when the
committed runs were regenerated (`scripts/regenerate_summaries.py`), never
recomputed here -- every stat tile reads its value verbatim from the
committed `summary.json`.
"""

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from abms.carbon import HOURLY_INTENSITY_KG_PER_KWH
from abms.guardrails import OCCUPIED_COOL_CEILING_C, OCCUPIED_HEAT_FLOOR_C

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = REPO_ROOT / "runs" / "demo_final"

# Fixed categorical order (dataviz skill: assign hues in fixed order, never
# cycled) -- one identity per mode, reused across every chart in this app.
MODE_COLORS = {
    "ai": "#2a78d6",         # slot 1 blue -- the system under evaluation
    "baseline": "#eb6834",   # slot 2 orange -- the reference to beat
    "rulebased": "#1baf7a",  # slot 3 aqua -- the non-LLM comparison point
}
MODE_LABELS = {"ai": "AI", "baseline": "Baseline", "rulebased": "Rule-based"}
BAND_FILL = "rgba(225,224,217,0.55)"  # neutral gridline gray, low-opacity band
GAP_FILL = "rgba(42,120,214,0.12)"    # AI series hue, low-opacity gap shade
MUTED_INK = "#898781"

st.set_page_config(page_title="Honeywell Campus Connect -- Savings Dashboard", layout="wide")


# ---------------------------------------------------------------------------
# Data layer (GC-6.1). Every loader tolerates a missing mode/file/field by
# returning None -- callers degrade the corresponding section instead of
# crashing, since summaries from different phases may have different field
# sets (extended_january has no rulebased dir; older summaries may predate
# a metric).
# ---------------------------------------------------------------------------


def discover_periods() -> list:
    if not RUNS_ROOT.is_dir():
        return []
    return sorted(p.name for p in RUNS_ROOT.iterdir() if (p / "summary.json").is_file())


@st.cache_data
def _load_json_cached(path_str: str, _mtime: float) -> dict:
    import json

    return json.loads(Path(path_str).read_text())


def load_summary(period: str) -> dict | None:
    path = RUNS_ROOT / period / "summary.json"
    if not path.is_file():
        return None
    return _load_json_cached(str(path), path.stat().st_mtime)


@st.cache_data
def _load_telemetry_cached(path_str: str, _mtime: float) -> pd.DataFrame:
    return pd.read_csv(path_str, parse_dates=["timestamp"])


def load_telemetry(period: str, mode: str) -> pd.DataFrame | None:
    path = RUNS_ROOT / period / mode / "telemetry.csv"
    if not path.is_file():
        return None
    return _load_telemetry_cached(str(path), path.stat().st_mtime)


@st.cache_data
def _load_decisions_cached(path_str: str, _mtime: float) -> pd.DataFrame:
    df = pd.read_json(path_str, lines=True)
    if df.empty:
        return df
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["source"] = df["reasoning"].apply(
        lambda r: "fallback" if isinstance(r, str) and r.startswith("[fallback") else "llm"
    )
    df["guardrail_clamped"] = df["guardrail_notes"].apply(lambda n: bool(n))
    return df


def load_decisions(period: str, mode: str = "ai") -> pd.DataFrame | None:
    path = RUNS_ROOT / period / mode / "decisions.jsonl"
    if not path.is_file():
        return None
    return _load_decisions_cached(str(path), path.stat().st_mtime)


def available_modes(period: str) -> list:
    return [m for m in ("baseline", "rulebased", "ai") if (RUNS_ROOT / period / m / "telemetry.csv").is_file()]


# ---------------------------------------------------------------------------
# Header + period selector (GC-6.2)
# ---------------------------------------------------------------------------

st.title("Honeywell Campus Connect -- Quantitative Savings Dashboard")
st.caption("Pure reader of `runs/demo_final/` -- every number below comes verbatim from a committed `summary.json`.")

periods = discover_periods()
if not periods:
    st.error("No period directories with a `summary.json` found under `runs/demo_final/`.")
    st.stop()

period = st.sidebar.selectbox(
    "Period", periods, index=periods.index("january_week") if "january_week" in periods else 0
)
st.sidebar.caption(f"Modes present: {', '.join(available_modes(period)) or 'none'}")

summary = load_summary(period)
if summary is None:
    st.error(f"`{period}/summary.json` could not be read.")
    st.stop()

ai = summary.get("ai") or {}
baseline = summary.get("baseline") or {}
comparison = ((summary.get("comparison") or {}).get("ai_vs_baseline")) or {}
decisions_df = load_decisions(period, "ai")


def fmt(value, digits=1, suffix="") -> str:
    if value is None:
        return "N/A"
    try:
        return f"{value:.{digits}f}{suffix}"
    except (TypeError, ValueError):
        return "N/A"


# ---------------------------------------------------------------------------
# Stat tiles (GC-6.2)
# ---------------------------------------------------------------------------

st.subheader(f"{period} -- headline results")
tiles = st.columns(6)

with tiles[0]:
    st.metric("Energy saved (AI vs baseline)", fmt(comparison.get("energy_saved_pct"), 1, "%"))

with tiles[1]:
    st.metric("Comfort compliance (AI)", fmt(ai.get("comfort_compliance_pct"), 1, "%"))
    st.caption(f"baseline: {fmt(baseline.get('comfort_compliance_pct'), 1, '%')}")

with tiles[2]:
    st.metric("PMV compliance |PMV|<=0.5 (AI)", fmt(ai.get("pmv_within_pct"), 1, "%"))
    st.caption(f"baseline: {fmt(baseline.get('pmv_within_pct'), 1, '%')}")

with tiles[3]:
    if comparison.get("carbon_avoided_kg") is not None:
        st.metric("CO2 avoided", fmt(comparison.get("carbon_avoided_kg"), 1, " kg"))
    else:
        st.metric("CO2 avoided", "N/A")
        st.caption("not present in this summary")

with tiles[4]:
    st.metric("Peak-demand reduction", fmt(comparison.get("peak_demand_reduction_kw"), 2, " kW"))
    st.caption(f"{fmt(comparison.get('peak_demand_reduction_pct'), 1, '%')} vs baseline peak")

with tiles[5]:
    if decisions_df is not None and not decisions_df.empty:
        n = len(decisions_df)
        n_llm = int((decisions_df["source"] == "llm").sum())
        n_fallback = n - n_llm
        st.metric("Decisions made", str(n))
        st.caption(f"{n_llm} llm / {n_fallback} fallback")
    else:
        st.metric("Decisions made", "N/A")
        st.caption("no decisions.jsonl for this period")

st.divider()

# ---------------------------------------------------------------------------
# Cumulative energy chart (GC-6.3)
# ---------------------------------------------------------------------------

st.subheader("Cumulative HVAC energy")

cum_frames = {}
for mode in ("baseline", "rulebased", "ai"):
    df = load_telemetry(period, mode)
    if df is None:
        continue
    df = df.copy()
    df["cumulative_hvac_kwh"] = df["hvac_electricity_cumulative_kwh"] + df["hvac_gas_cumulative_kwh"]
    cum_frames[mode] = df

if not cum_frames:
    st.info("No telemetry available for this period.")
else:
    fig = go.Figure()
    for mode in ("baseline", "rulebased", "ai"):
        df = cum_frames.get(mode)
        if df is None:
            continue
        fig.add_trace(
            go.Scatter(
                x=df["timestamp"],
                y=df["cumulative_hvac_kwh"],
                mode="lines",
                name=MODE_LABELS[mode],
                line=dict(color=MODE_COLORS[mode], width=2),
            )
        )
    if "baseline" in cum_frames and "ai" in cum_frames:
        b, a = cum_frames["baseline"], cum_frames["ai"]
        merged = pd.merge_asof(
            b[["timestamp", "cumulative_hvac_kwh"]].rename(columns={"cumulative_hvac_kwh": "baseline_kwh"}),
            a[["timestamp", "cumulative_hvac_kwh"]].rename(columns={"cumulative_hvac_kwh": "ai_kwh"}),
            on="timestamp",
        )
        fig.add_trace(
            go.Scatter(
                x=merged["timestamp"], y=merged["baseline_kwh"],
                mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=merged["timestamp"], y=merged["ai_kwh"],
                mode="lines", line=dict(width=0), fill="tonexty", fillcolor=GAP_FILL,
                name="baseline - AI gap", hoverinfo="skip",
            )
        )
    fig.update_layout(
        template="plotly_white",
        xaxis_title="",
        yaxis_title="Cumulative HVAC kWh (electricity + gas)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(l=10, r=10, t=10, b=10),
        height=380,
    )
    st.plotly_chart(fig, use_container_width=True)

st.divider()

# ---------------------------------------------------------------------------
# Comfort + setpoint chart (GC-6.4)
# ---------------------------------------------------------------------------

st.subheader("Comfort band vs setpoints -- representative day")

modes_with_telemetry = list(cum_frames.keys())
if not modes_with_telemetry:
    st.info("No telemetry available for this period.")
else:
    default_mode = "ai" if "ai" in modes_with_telemetry else modes_with_telemetry[0]
    day_mode = st.selectbox(
        "Mode", modes_with_telemetry, index=modes_with_telemetry.index(default_mode),
        format_func=lambda m: MODE_LABELS[m],
    )
    df = cum_frames[day_mode]
    available_days = sorted(df["timestamp"].dt.date.unique())
    day = st.selectbox("Day", available_days, index=len(available_days) // 2)
    day_df = df[df["timestamp"].dt.date == day]

    zone_temp_cols = [c for c in df.columns if c.startswith("zone_temp_c_")]
    if day_df.empty or not zone_temp_cols:
        st.info("No rows for the selected day.")
    else:
        mean_zone_temp = day_df[zone_temp_cols].mean(axis=1)
        fig2 = go.Figure()
        fig2.add_trace(
            go.Scatter(
                x=list(day_df["timestamp"]) + list(day_df["timestamp"][::-1]),
                y=[OCCUPIED_COOL_CEILING_C] * len(day_df) + [OCCUPIED_HEAT_FLOOR_C] * len(day_df),
                fill="toself", fillcolor=BAND_FILL, line=dict(width=0),
                name="occupied comfort band", hoverinfo="skip",
            )
        )
        fig2.add_trace(
            go.Scatter(
                x=day_df["timestamp"], y=mean_zone_temp, mode="lines",
                name="mean zone temp", line=dict(color=MODE_COLORS[day_mode], width=2),
            )
        )
        fig2.add_trace(
            go.Scatter(
                x=day_df["timestamp"], y=day_df["heating_setpoint_c"], mode="lines",
                name="heating setpoint", line=dict(color=MUTED_INK, width=1.5, shape="hv", dash="dot"),
            )
        )
        fig2.add_trace(
            go.Scatter(
                x=day_df["timestamp"], y=day_df["cooling_setpoint_c"], mode="lines",
                name="cooling setpoint", line=dict(color=MUTED_INK, width=1.5, shape="hv", dash="dash"),
            )
        )
        fig2.update_layout(
            template="plotly_white",
            yaxis_title="Degrees C",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
            margin=dict(l=10, r=10, t=10, b=10),
            height=380,
        )
        st.plotly_chart(fig2, use_container_width=True)

st.divider()

# ---------------------------------------------------------------------------
# Decision feed (GC-6.5)
# ---------------------------------------------------------------------------

st.subheader("Decision feed -- autonomy and self-correction evidence")

if decisions_df is None or decisions_df.empty:
    st.info("No `decisions.jsonl` for this period's AI run.")
else:
    feed = pd.DataFrame(
        {
            "timestamp": decisions_df["timestamp"],
            "source": decisions_df["source"],
            "reasoning": decisions_df["reasoning"],
            "requested": decisions_df["requested"].apply(
                lambda d: f"{d.get('heating_c')}/{d.get('cooling_c')}" if isinstance(d, dict) else "N/A"
            ),
            "applied": decisions_df["applied"].apply(
                lambda d: f"{d.get('heating_c')}/{d.get('cooling_c')}" if isinstance(d, dict) else "N/A"
            ),
            "guardrail_notes": decisions_df["guardrail_notes"].apply(
                lambda notes: "; ".join(notes) if notes else ""
            ),
        }
    )

    only_clamped = st.checkbox("Show only guardrail-clamped decisions", value=False)
    if only_clamped:
        feed = feed[feed["guardrail_notes"] != ""]

    st.dataframe(
        feed,
        use_container_width=True,
        height=420,
        column_config={
            "timestamp": st.column_config.DatetimeColumn("Time", format="YYYY-MM-DD HH:mm"),
            "source": st.column_config.TextColumn("Source"),
            "reasoning": st.column_config.TextColumn("Reasoning", width="large"),
            "requested": st.column_config.TextColumn("Requested (H/C)"),
            "applied": st.column_config.TextColumn("Applied (H/C)"),
            "guardrail_notes": st.column_config.TextColumn("Guardrail notes", width="medium"),
        },
        hide_index=True,
    )
    n_clamped = int((decisions_df["guardrail_clamped"]).sum())
    st.caption(f"{n_clamped} of {len(decisions_df)} decisions were adjusted by the guardrail layer.")

st.divider()

# ---------------------------------------------------------------------------
# Carbon shift chart (GC-6.6, only if time remains -- included here since
# it reuses abms.carbon's already-computed intensity profile with no new
# math in the dashboard)
# ---------------------------------------------------------------------------

st.subheader("Carbon-aware load shift")

if "ai" not in cum_frames and "baseline" not in cum_frames:
    st.info("No telemetry available for this period.")
else:
    intensity_df = pd.DataFrame(
        {"hour": list(range(24)), "intensity_kg_per_kwh": HOURLY_INTENSITY_KG_PER_KWH}
    )
    fig3 = go.Figure()
    fig3.add_trace(
        go.Bar(
            x=intensity_df["hour"], y=intensity_df["intensity_kg_per_kwh"],
            name="grid intensity (kg CO2/kWh)", marker_color=BAND_FILL,
            yaxis="y2",
        )
    )
    for mode in ("baseline", "ai"):
        df = cum_frames.get(mode)
        if df is None:
            continue
        hourly = df.groupby(df["timestamp"].dt.hour)["hvac_electricity_interval_kwh"].mean()
        fig3.add_trace(
            go.Scatter(
                x=hourly.index, y=hourly.values, mode="lines+markers",
                name=f"{MODE_LABELS[mode]} mean hourly electricity kWh",
                line=dict(color=MODE_COLORS[mode], width=2),
            )
        )
    fig3.update_layout(
        template="plotly_white",
        xaxis_title="Hour of day",
        yaxis_title="Mean interval electricity kWh",
        yaxis2=dict(title="Grid intensity (kg CO2/kWh)", overlaying="y", side="right", showgrid=False),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(l=10, r=10, t=10, b=10),
        height=380,
    )
    st.plotly_chart(fig3, use_container_width=True)

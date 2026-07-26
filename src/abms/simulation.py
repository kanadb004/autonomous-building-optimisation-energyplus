"""EnergyPlus wrapper: dedicated thread, callbacks, variable/meter handles,
actuators, warmup/sizing filtering (§2 Phases 1-2, §6 loop mechanics).

The E+ API call blocks until simulation end, so it runs on a dedicated
thread; callbacks registered with the runtime execute on that thread.
"""

import json
import threading
import traceback
from datetime import datetime, timedelta
from pathlib import Path

from abms import guardrails
from abms.controllers.baseline import BaselineController
from abms.telemetry import FIELDNAMES, ZONE_NAMES, TelemetryLogger  # noqa: F401 (FIELDNAMES re-exported for callers)

# KindOfSim value for an actual weather-file run period (as opposed to a
# sizing design day or HVAC-sizing pass). Confirmed against the installed
# EnergyPlus 26.1.0 pyenergyplus API by the bundled example plugin script
# ExampleFiles/PythonPlugin1ZoneUncontrolledTrackHistory.py, which uses the
# same check (`kind_of_sim(state) != 3` to skip non-run-period callbacks).
KIND_OF_SIM_RUN_PERIOD_WEATHER = 3

HEATING_SETPOINT_SCHEDULE = "Htg-SetP-Sch"
COOLING_SETPOINT_SCHEDULE = "Clg-SetP-Sch"
HVAC_ELECTRICITY_METER = "Electricity:HVAC"
# Boiler natural-gas meter (§ Phase 2 energy-metric broadening, docs/decisions.md):
# in a heating-dominated week, setback savings land on gas (reheat coil), not
# electricity -- Electricity:HVAC alone made setback look like ~0% savings.
HVAC_GAS_METER = "Heating:NaturalGas"


def normalize_timestamp(year: int, month: int, day: int, hour: int, minutes: int) -> datetime:
    """Normalize EnergyPlus's end-of-interval time fields into a real
    datetime. `hour` is 0-23 and `minutes` is 1-60 *minutes into that hour*
    (i.e. minutes=60 means the interval ended exactly on the next hour, not
    literally ":60"). Using timedelta addition -- instead of manual
    hour/day/month carry logic -- lets Python's calendar arithmetic handle
    every rollover (hour, day, month, year) in one place."""
    return datetime(year, month, day) + timedelta(hours=hour, minutes=minutes)


class SimulationRunner:
    """Runs one EnergyPlus simulation on a dedicated thread, logging
    per-zone-timestep telemetry (excluding warmup and sizing periods) to
    `<output_dir>/telemetry.csv`.

    `on_state`, if given, is called with each telemetry record dict from the
    simulation thread -- callers must not block or raise.

    `on_decision`, if given, is called with each decision-log entry dict
    (same shape as one `decisions.jsonl` line) right after it's applied to
    the actuators and written to disk -- callers must not block or raise.
    Used by the MCP server (§3) to deliver the guardrail-applied values back
    to whichever `set_zone_setpoints` call is waiting on them.

    `controller`, if given, is consulted every `decision_interval_minutes`
    of simulation time (§2.3); its decisions pass through `guardrails.validate`
    and are written to the heating/cooling setpoint-schedule actuators
    (§2.1). Defaults to `BaselineController` (no actuation at all -- schedules
    run exactly as authored). Every decision is appended to
    `<output_dir>/decisions.jsonl` (§2.6).
    """

    def __init__(
        self,
        idf_path,
        epw_path,
        output_dir,
        run_id,
        mode="baseline",
        on_state=None,
        on_decision=None,
        controller=None,
        decision_interval_minutes=15,
        mute_console=False,
    ):
        self.idf_path = Path(idf_path)
        self.epw_path = Path(epw_path)
        self.output_dir = Path(output_dir)
        self.run_id = run_id
        self.mode = mode
        self.on_state = on_state
        self.on_decision = on_decision
        self.controller = controller if controller is not None else BaselineController()
        self.decision_interval = timedelta(minutes=decision_interval_minutes)
        # MCP mode needs this: EnergyPlus prints progress lines straight to
        # stdout/stderr, which corrupts the stdio JSON-RPC channel the MCP
        # server shares that same stdout with (§3 architecture decision).
        self.mute_console = mute_console

        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._error_log_path = self.output_dir / "callback_errors.log"
        self.telemetry = TelemetryLogger(self.output_dir / "telemetry.csv")
        self._decision_log_file = open(self.output_dir / "decisions.jsonl", "w")

        self.api = None
        self.state = None
        self._thread = None
        self._handles = None
        self._cumulative_hvac_kwh = 0.0
        self._cumulative_hvac_gas_kwh = 0.0
        self._last_decision_time = None
        self._applied_heating_c = None
        self._applied_cooling_c = None
        self.fatal_error = None
        self.exit_code = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name=f"eplus-{self.run_id}", daemon=True)
        self._thread.start()

    def join(self, timeout=None) -> None:
        self._thread.join(timeout)

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self) -> None:
        from pyenergyplus.api import EnergyPlusAPI

        self.api = EnergyPlusAPI()
        self.state = self.api.state_manager.new_state()

        if self.mute_console:
            self.api.runtime.set_console_output_status(self.state, False)

        # requestVariable must be called before run_energyplus starts (prior
        # to input processing) -- calling it from callback_begin_new_environment
        # is too late, since that callback fires after GetInput.
        for variable_name, key in self._variables_to_request():
            self.api.exchange.request_variable(self.state, variable_name, key)

        self.api.runtime.callback_end_zone_timestep_after_zone_reporting(self.state, self._on_end_zone_timestep)

        self.exit_code = self.api.runtime.run_energyplus(
            self.state,
            ["-w", str(self.epw_path), "-d", str(self.output_dir), "-r", str(self.idf_path)],
        )
        self.api.state_manager.delete_state(self.state)
        self.telemetry.close()
        self._decision_log_file.close()

    # -- callbacks (run on the simulation thread; every body is wrapped) --

    def _on_end_zone_timestep(self, state) -> None:
        try:
            if not self.api.exchange.api_data_fully_ready(state):
                return
            if self._handles is None:
                self._acquire_handles(state)
            if self.api.exchange.warmup_flag(state):
                return
            if self.api.exchange.kind_of_sim(state) != KIND_OF_SIM_RUN_PERIOD_WEATHER:
                return
            self._record_state(state)
        except Exception:
            self._log_callback_exception("end_zone_timestep")
            self.fatal_error = traceback.format_exc()

    @staticmethod
    def _variables_to_request():
        reqs = [("Site Outdoor Air Drybulb Temperature", "Environment")]
        for zone in ZONE_NAMES:
            reqs.append(("Zone Air Temperature", zone))
            reqs.append(("Zone People Occupant Count", zone))
        reqs.append(("Schedule Value", HEATING_SETPOINT_SCHEDULE))
        reqs.append(("Schedule Value", COOLING_SETPOINT_SCHEDULE))
        return reqs

    def _acquire_handles(self, state) -> None:
        """Hard-fails with a clear message naming the requested variable if
        any handle comes back invalid (-1) -- an invalid handle otherwise
        silently reads as garbage (§6 trap #2)."""

        def get_var(name, key):
            handle = self.api.exchange.get_variable_handle(state, name, key)
            if handle == -1:
                raise RuntimeError(f"Invalid variable handle: name={name!r} key={key!r}")
            return handle

        handles = {
            "outdoor_temp": get_var("Site Outdoor Air Drybulb Temperature", "Environment"),
            "zone_temp": {z: get_var("Zone Air Temperature", z) for z in ZONE_NAMES},
            "zone_occupant_count": {z: get_var("Zone People Occupant Count", z) for z in ZONE_NAMES},
            "heating_setpoint": get_var("Schedule Value", HEATING_SETPOINT_SCHEDULE),
            "cooling_setpoint": get_var("Schedule Value", COOLING_SETPOINT_SCHEDULE),
        }

        meter_handle = self.api.exchange.get_meter_handle(state, HVAC_ELECTRICITY_METER)
        if meter_handle == -1:
            raise RuntimeError(f"Invalid meter handle: name={HVAC_ELECTRICITY_METER!r}")
        handles["hvac_meter"] = meter_handle

        gas_meter_handle = self.api.exchange.get_meter_handle(state, HVAC_GAS_METER)
        if gas_meter_handle == -1:
            raise RuntimeError(f"Invalid meter handle: name={HVAC_GAS_METER!r}")
        handles["hvac_gas_meter"] = gas_meter_handle

        if self.controller.actuates:

            def get_actuator(component_type, control_type, key):
                handle = self.api.exchange.get_actuator_handle(state, component_type, control_type, key)
                if handle == -1:
                    raise RuntimeError(
                        f"Invalid actuator handle: component_type={component_type!r} "
                        f"control_type={control_type!r} key={key!r}"
                    )
                return handle

            handles["heating_actuator"] = get_actuator("Schedule:Compact", "Schedule Value", HEATING_SETPOINT_SCHEDULE)
            handles["cooling_actuator"] = get_actuator("Schedule:Compact", "Schedule Value", COOLING_SETPOINT_SCHEDULE)

        self._handles = handles

    def _record_state(self, state) -> None:
        h = self._handles
        ex = self.api.exchange

        ts = normalize_timestamp(ex.year(state), ex.month(state), ex.day_of_month(state), ex.hour(state), ex.minutes(state))

        # get_meter_value on this API version returns the interval (not
        # lifetime-cumulative) value -- verified against the installed
        # pyenergyplus docstring, which overrides the plan's general "meters
        # are cumulative" assumption for this specific API version. J -> kWh
        # conversion happens in exactly this one place.
        interval_kwh = ex.get_meter_value(state, h["hvac_meter"]) / 3.6e6
        self._cumulative_hvac_kwh += interval_kwh

        interval_gas_kwh = ex.get_meter_value(state, h["hvac_gas_meter"]) / 3.6e6
        self._cumulative_hvac_gas_kwh += interval_gas_kwh

        record = {
            "timestamp": ts.isoformat(),
            "run_id": self.run_id,
            "mode": self.mode,
            "outdoor_temp_c": ex.get_variable_value(state, h["outdoor_temp"]),
            "heating_setpoint_c": ex.get_variable_value(state, h["heating_setpoint"]),
            "cooling_setpoint_c": ex.get_variable_value(state, h["cooling_setpoint"]),
            "hvac_electricity_interval_kwh": interval_kwh,
            "hvac_electricity_cumulative_kwh": self._cumulative_hvac_kwh,
            "hvac_gas_interval_kwh": interval_gas_kwh,
            "hvac_gas_cumulative_kwh": self._cumulative_hvac_gas_kwh,
        }
        for zone in ZONE_NAMES:
            record[f"zone_temp_c_{zone}"] = ex.get_variable_value(state, h["zone_temp"][zone])
            record[f"zone_occupant_count_{zone}"] = ex.get_variable_value(state, h["zone_occupant_count"][zone])

        self.telemetry.append(record)
        if self.on_state is not None:
            self.on_state(record)

        if self.controller.actuates:
            self._maybe_decide(state, ts, record)

    def _maybe_decide(self, state, ts: datetime, record: dict) -> None:
        """Decision-interval gating (§2.3): the controller is consulted only
        every `decision_interval` of simulation time, not every zone
        timestep -- cheap timesteps vastly outnumber decision timesteps."""
        if self._last_decision_time is not None and ts - self._last_decision_time < self.decision_interval:
            return
        self._last_decision_time = ts

        if self._applied_heating_c is None:
            # First decision point: initialize "previous applied" from the
            # schedule's own authored value so the max-step guardrail has a
            # sane baseline instead of comparing against nothing.
            self._applied_heating_c = record["heating_setpoint_c"]
            self._applied_cooling_c = record["cooling_setpoint_c"]

        total_occupants = sum(record[f"zone_occupant_count_{z}"] for z in ZONE_NAMES)
        occupied = total_occupants > 0
        snapshot = dict(record, occupied=occupied)

        decision = self.controller.decide(snapshot)
        if decision is None:
            # "No change": explicitly re-write the last applied value rather
            # than relying on the actuator to revert on its own -- it never
            # does (§6 trap #9).
            result = guardrails.GuardrailResult(
                heating_c=self._applied_heating_c, cooling_c=self._applied_cooling_c, notes=[]
            )
        elif getattr(self.controller, "bypass_guardrails", False):
            # Only for the §2.1 absurd-value actuation sanity check --
            # writes the controller's raw request straight to the actuator,
            # unclamped, to prove the actuator is wired to the schedule the
            # thermostat actually reads. Never used by real controllers.
            requested_heating_c, requested_cooling_c = decision
            result = guardrails.GuardrailResult(heating_c=requested_heating_c, cooling_c=requested_cooling_c, notes=[])
        else:
            requested_heating_c, requested_cooling_c = decision
            result = guardrails.validate(
                requested_heating_c,
                requested_cooling_c,
                prev_heating_c=self._applied_heating_c,
                prev_cooling_c=self._applied_cooling_c,
                occupied=occupied,
            )

        ex = self.api.exchange
        ex.set_actuator_value(state, self._handles["heating_actuator"], result.heating_c)
        ex.set_actuator_value(state, self._handles["cooling_actuator"], result.cooling_c)
        self._applied_heating_c = result.heating_c
        self._applied_cooling_c = result.cooling_c

        self._log_decision(ts, occupied, decision, result)

    def _log_decision(self, ts: datetime, occupied: bool, decision, result) -> None:
        entry = {
            "timestamp": ts.isoformat(),
            "run_id": self.run_id,
            "controller": self.controller.name,
            "occupied": occupied,
            "requested": None if decision is None else {"heating_c": decision[0], "cooling_c": decision[1]},
            "applied": {"heating_c": result.heating_c, "cooling_c": result.cooling_c},
            "guardrail_notes": result.notes,
        }
        self._decision_log_file.write(json.dumps(entry) + "\n")
        self._decision_log_file.flush()
        if self.on_decision is not None:
            self.on_decision(entry)

    def _log_callback_exception(self, where: str) -> None:
        with open(self._error_log_path, "a") as f:
            f.write(f"--- exception in {where} at {datetime.utcnow().isoformat()} ---\n")
            f.write(traceback.format_exc())
            f.write("\n")

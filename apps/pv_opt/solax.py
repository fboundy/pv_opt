import pandas as pd
import time

TIMEFORMAT = "%H:%M"
LIMITS = ["start", "end"]
DIRECTIONS = ["charge"]
WRITE_POLL_SLEEP_DURATION = 0.5

INVERTER_DEFS = {
    "SOLAX_X1": {
        "MODE_ITEMS": [
            "use_mode",
            "allow_grid_charge",
            "lock_state",
            "backup_grid_charge",
        ],
        "PERIODS": {"charge": 2, "discharge": 0},
        # Default Configuration: Exposed as inverter.config and provides defaults for this inverter for the
        # required config. These config items can be over-written by config specified in the config.yaml
        # file. They are required for the main PV_Opt module and if they cannot be found an ERROR will be
        # raised
        "online": "number.{device_name}_battery_minimum_capacity",
        "default_config": {
            "maximum_dod_percent": "number.{device_name}_battery_minimum_capacity",
            "id_battery_soc": " sensor.{device_name}_battery_capacity",
            "id_consumption": "sensor.{device_name}_house_load",
            "id_grid_import_today": "sensor.{device_name}_today_s_import_energy",
            "id_grid_export_today": "sensor.{device_name}_today_s_export_energy",
            "supports_hold_soc": False,
            "supports_forced_discharge": False,
            "update_cycle_seconds": 300,
        },
        # Brand Conguration: Exposed as inverter.brand_config and can be over-written using arguments
        # from the config.yaml file but not rquired outside of this module
        "brand_config": {
            "battery_voltage": 101.8,
            "id_allow_grid_charge": "select.{device_name}_allow_grid_charge",
            "id_battery_capacity": "sensor.{device_name}_battery_capacity",
            "id_battery_minimum_capacity": "number.{device_name}_battery_minimum_capacity",
            "id_battery_charge_max_current": "number.{device_name}_battery_charge_max_current",
            "id_battery_discharge_max_current": "number.{device_name}_battery_discharge_max_current",
            "id_charge_end_time_1": "select.{device_name}_charger_end_time_1",
            "id_charge_start_time_1": "select.{device_name}_charger_start_time_1",
            "id_charge_end_time_2": "select.{device_name}_charger_end_time_2",
            "id_charge_start_time_2": "select.{device_name}_charger_start_time_2",
            "id_max_charge_current": "number.{device_name}_battery_charge_max_current",
            "id_use_mode": "select.{device_name}_use_mode",
            "id_export_duration": "select.{device_name}_export_duration",
            "id_target_soc": "number.{device_name}_forcetime_period_1_max_capacity",
        },
    },
}


class InverterController:
    def __init__(self, inverter_type, host) -> None:
        self.host = host
        self.tz = self.host.tz
        if host is not None:
            self.log = host.log
        self.type = inverter_type
        self.config = {}
        self.brand_config = {}
        for defs, conf in zip(
            [INVERTER_DEFS[self.type][x] for x in ["default_config", "brand_config"]],
            [self.config, self.brand_config],
        ):
            for item in defs:
                if isinstance(defs[item], str):
                    conf[item] = defs[item].replace("{device_name}", self.host.device_name)
                    # conf[item] = defs[item].replace("{inverter_sn}", self.host.inverter_sn)
                elif isinstance(defs[item], list):
                    conf[item] = [z.replace("{device_name}", self.host.device_name) for z in defs[item]]
                    # conf[item] = [z.replace("{inverter_sn}", self.host.inverter_sn) for z in defs[item]]
                else:
                    conf[item] = defs[item]

    def is_online(self):
        entity_id = INVERTER_DEFS[self.type].get("online", (None, None))
        if entity_id is not None:
            entity_id = entity_id.replace("{device_name}", self.host.device_name)
            return self.host.get_state(entity_id) not in ["unknown", "unavailable"]
        else:
            return True

    def enable_timed_mode(self):
        if self.type == "SOLAX_X1":
            self._solax_set_select("lock_state", "Unlocked - Advanced")
            self._solax_set_select("allow_grid_charge", "Period 1 Allowed")
            self._solax_set_select("backup_grid_charge", "Disabled")

        else:
            self._unknown_inverter()

    def control_charge(self, enable, **kwargs):
        if self.type == "SOLAX_X1":
            if enable:
                self._solax_set_select("use_mode", "Force Time Use")
                time_now = pd.Timestamp(tz=self.tz)
                start = kwargs.get("start", time_now).floor("15min").strftime(TIMEFORMAT)
                end = kwargs.get("end", time_now).ceil("30min").strftime(TIMEFORMAT)
                self._solax_set_select("charge_start_time_1", start)
                self._solax_set_select("charge_end_time_1", end)

                power = self.kwargs.get("power")
                if power is not None:
                    entity_id = self.host.config[f"id_max_charge_current"]
                    current = abs(round(power / self.host.get_config("battery_voltage"), 1))

                    self.log(f"Power {power:0.0f} = {current:0.1f}A at {self.host.get_config('battery_voltage')}V")
                    changed, written = self._write_and_poll_value(
                        entity_id=entity_id, value=current, tolerance=1, verbose=True
                    )

                    if changed:
                        if written:
                            self.log(f"Current {current}A written to inverter")
                        else:
                            self.log(f"Failed to write current of {current}A to inverter")
                    else:
                        self.log("Inverter already at correct current")

                target_soc = kwargs.get("target_soc", None)
                if target_soc is not None:
                    entity_id = self.host.config[f"id_target_soc"]

                    changed, written = self._write_and_poll_value(
                        entity_id=entity_id, value=target_soc, tolerance=1, verbose=True
                    )

                    if changed:
                        if written:
                            self.log(f"Target SOC {target_soc}% written to inverter")
                        else:
                            self.log(f"Failed to write Target SOC of {target_soc}% to inverter")
                    else:
                        self.log("Inverter already at correct Target SOC")

        else:
            self._unknown_inverter()

    def control_discharge(self, enable, **kwargs):
        if self.type == "SOLAX_X1":
            pass
        else:
            self._unknown_inverter()

    def _unknown_inverter(self):
        e = f"Unknown inverter type {self.type}"
        self.log(e, level="ERROR")
        self.host.status(e)
        raise Exception(e)

    def hold_soc(self, enable, soc=None):
        if self.type == "SOLAX_X1":
            pass
        else:
            self._unknown_inverter()

    @property
    def status(self):
        status = None
        if self.type == "SOLAX_X1":
            time_now = pd.Timestamp.now(tz=self.tz)
            midnight = time_now.normalize()

            status = self._solax_mode()

            status["charge"] = self._solax_charge_periods()
            status["charge"]["active"] = (
                time_now >= status["charge"]["start"]
                and time_now < status["charge"]["end"]
                and status["charge"]["current"] > 0
                and status["use_mode"]["Timed"] == "Force Time Use"
            )

            status["discharge"] = {
                "start": midnight,
                "end": midnight,
                "current": 0.0,
                "active": False,
            }
            status["hold_soc"] = {
                "active": False,
                "soc": 0.0,
            }

        else:
            self._unknown_inverter()

        return status

    def _write_and_poll_value(self, entity_id, value, tolerance=0.0, verbose=False):
        changed = False
        written = False
        return (changed, written)

    def _monitor_target_soc(self, target_soc, mode="charge"):
        pass

    def _solax_mode(self, **kwargs):
        if self.type == "SOLAX_X1":
            return {
                x: self.host.get_state(entity_id=self.host.config[f"id_{x}"])
                for x in INVERTER_DEFS[self.type]["MODE_ITEMS"]
            }

        else:
            self._unknown_inverter()

    def _solax_charge_periods(self, **kwargs):
        if self.type == "SOLAX_X1":
            return {
                l: pd.Timestamp(self.host.get_state(entity_id=self.host.config(f"id_charge_{l}_time_1")), tz=self.tz)
                for l in LIMITS
            } | {"current": self.host.get_state(entity_id=self.host.config[f"id_battery_charge_max_current"])}

        else:
            self._unknown_inverter()

    def _solax_set_select(self, item, state):
        if state is not None:
            entity_id = self.host.config[f"id_{item}"]
            if self.host.get_state(entity_id=entity_id) != state:
                self.host.call_service("select/select_option", entity_id=entity_id, option=state)
                self.log(f"Setting {entity_id} to {state}")

    def _write_and_poll_value(self, entity_id, value, tolerance=0.0, verbose=False):
        changed = False
        written = False
        state = float(self.host.get_state(entity_id=entity_id))
        new_state = None
        diff = abs(state - value)
        if diff > tolerance:
            changed = True
            try:
                self.host.call_service("number/set_value", entity_id=entity_id, value=str(value))

                time.sleep(WRITE_POLL_SLEEP_DURATION)
                new_state = float(self.host.get_state(entity_id=entity_id))
                written = new_state == value

            except:
                written = False

            if verbose:
                str_log = f"Entity: {entity_id:30s} Value: {float(value):4.1f}  Old State: {float(state):4.1f} "
                str_log += f"New state: {float(new_state):4.1f} Diff: {diff:4.1f} Tol: {tolerance:4.1f}"
                self.log(str_log)

        return (changed, written)

import pandas as pd
import time

TIMEFORMAT = "%H:%M"
INVERTER_DEFS = {
    "SOLIS_SOLAX_MODBUS": {
        "modes": {
            1: "Selfuse - No Grid Charging",
            3: "Timed Charge/Discharge - No Grid Charging",
            17: "Backup/Reserve - No Grid Charging",
            33: "Selfuse",
            35: "Timed Charge/Discharge",
            37: "Off-Grid Mode",
            41: "Battery Awaken",
            43: "Battery Awaken + Timed Charge/Discharge",
            49: "Backup/Reserve - No Timed Charge/Discharge",
            51: "Backup/Reserve",
        },
        "bits": [
            "SelfUse",
            "Timed",
            "OffGrid",
            "BatteryWake",
            "Backup",
            "GridCharge",
            "FeedInPriority",
        ],
        # Default Configuration: Exposed as inverter.config and provides defaults for this inverter for the
        # required config. These config items can be over-written by config specified in the config.yaml
        # file. They are required for the main PV_Opt module and if they cannot be found an ERROR will be
        # raised
        "default_config": {
            "maximum_dod_percent": "number.solis_battery_minimum_soc",
            "id_battery_soc": "sensor.solis_battery_soc",
            "id_consumption": ["sensor.solis_house_load", "sensor.solis_bypass_load"],
            "id_grid_import_power": "sensor.solis_grid_import_power",
            "id_grid_export_power": "sensor.solis_grid_export_power",
            "id_battery_charge_power": "sensor.solis_battery_input_energy",
            "id_inverter_ac_power": "sensor.solis_active_power",
        },
        # Brand Conguration: Exposed as inverter.brand_config and can be over-written using arguments
        # from the config.yaml file but not rquired outside of this module
        "brand_config": {
            "battery_voltage": "sensor.solis_battery_voltage",
            "id_timed_charge_start_hours": "number.solis_timed_charge_start_hours",
            "id_timed_charge_start_minutes": "number.solis_timed_charge_start_minutes",
            "id_timed_charge_end_hours": "number.solis_timed_charge_end_hours",
            "id_timed_charge_end_minutes": "number.solis_timed_charge_end_minutes",
            "id_timed_charge_current": "number.solis_timed_charge_current",
            "id_timed_discharge_start_hours": "number.solis_timed_discharge_start_hours",
            "id_timed_discharge_start_minutes": "number.solis_timed_discharge_start_minutes",
            "id_timed_discharge_end_hours": "number.solis_timed_discharge_end_hours",
            "id_timed_discharge_end_minutes": "number.solis_timed_discharge_end_minutes",
            "id_timed_discharge_current": "number.solis_timed_discharge_current",
            "id_timed_charge_discharge_button": "button.solis_update_charge_discharge_times",
            "id_inverter_mode": "select.solis_energy_storage_control_switch",
        },
    },
    "SOLIS_CORE_MODBUS": {
        "bits": [
            "SelfUse",
            "Timed",
            "OffGrid",
            "BatteryWake",
            "Backup",
            "GridCharge",
            "FeedInPriority",
        ],
        "registers": {
            "timed_charge_current": 43141,
            "timed_charge_start_hours": 43143,
            "timed_charge_start_minutes": 43144,
            "timed_charge_end_hours": 43145,
            "timed_charge_end_minutes": 43146,
            "timed_discharge_current": 43142,
            "timed_discharge_start_hours": 43147,
            "timed_discharge_start_minutes": 43148,
            "timed_discharge_end_hours": 43149,
            "timed_discharge_end_minutes": 43150,
            "storage_control_switch": 43110,
        },
        "default_config": {
            "maximum_dod_percent": "sensor.solis_overdischarge_soc",
            "id_battery_soc": "sensor.solis_battery_soc",
            "id_consumption": [
                "sensor.solis_house_load_power",
                "sensor.solis_backup_load_power",
            ],
            "id_grid_power": "sensor.solis_grid_active_power",
            "id_inverter_ac_power": "sensor.solis_inverter_ac_power",
        },
        "brand_config": {
            "modbus_hub": "solis",
            "modbus_slave": 1,
            "battery_voltage": "sensor.solis_battery_voltage",
            "id_timed_charge_start_hours": "sensor.solis_timed_charge_start_hour",
            "id_timed_charge_start_minutes": "sensor.solis_timed_charge_start_minute",
            "id_timed_charge_end_hours": "sensor.solis_timed_charge_end_hour",
            "id_timed_charge_end_minutes": "sensor.solis_timed_charge_end_minute",
            "id_timed_charge_current": "sensor.solis_timed_charge_current_limit",
            "id_timed_discharge_start_hours": "sensor.solis_timed_discharge_start_hour",
            "id_timed_discharge_start_minutes": "sensor.solis_timed_discharge_start_minute",
            "id_timed_discharge_end_hours": "sensor.solis_timed_discharge_end_hour",
            "id_timed_discharge_end_minutes": "sensor.solis_timed_discharge_end_minute",
            "id_timed_discharge_current": "sensor.solis_timed_discharge_current_limit",
            "id_inverter_mode": "sensor.solis_energy_storage_control_switch",
        },
    },
}


class InverterController:
    def __init__(self, inverter_type, host) -> None:
        self.type = inverter_type
        self.config = INVERTER_DEFS[self.type]["default_config"]
        self.brand_config = INVERTER_DEFS[self.type]["brand_config"]
        self.host = host
        self.tz = self.host.tz
        if host is not None:
            self.log = host.log

    def enable_timed_mode(self):
        if self.type == "SOLIS_SOLAX_MODBUS" or self.type == "SOLIS_CORE_MODBUS":
            self._solis_set_mode_switch(SelfUse=True, Timed=True, GridCharge=True)

    def control_charge(self, enable, **kwargs):
        self.enable_timed_mode()
        self._control_charge_discharge("charge", enable, **kwargs)

    def control_discharge(self, enable, **kwargs):
        self.enable_timed_mode()
        self._control_charge_discharge("discharge", enable, **kwargs)

    def hold_soc(self, soc, end=None):
        pass

    @property
    def status(self):
        status = None
        if self.type == "SOLIS_SOLAX_MODBUS" or self.type == "SOLIS_CORE_MODBUS":
            status = self._solis_state()

        return status

    def _write_and_poll_value(self, entity_id, value, tolerance=0.0, verbose=False):
        changed = False
        written = False
        state = float(self.host.get_state(entity_id=entity_id))
        new_state = None
        diff = abs(state - value)
        if diff > tolerance:
            changed = True
            try:
                self.host.call_service(
                    "number/set_value", entity_id=entity_id, value=value
                )

                time.sleep(0.5)
                new_state = float(self.host.get_state(entity_id=entity_id))
                written = new_state == value

            except:
                written = False

            if verbose:
                str_log = f"Entity: {entity_id:30s} Value: {float(value):4.1f}  Old State: {float(state):4.1f} "
                str_log += f"New state: {float(new_state):4.1f} Diff: {diff:4.1f} Tol: {tolerance:4.1f}"
                self.log(str_log)

        return (changed, written)

    def _monitor_target_soc(self, target_soc, mode="charge"):
        pass

    def _control_charge_discharge(self, direction, enable, **kwargs):
        if self.type == "SOLIS_SOLAX_MODBUS" or self.type == "SOLIS_CORE_MODBUS":
            self._solis_control_charge_discharge(direction, enable, **kwargs)

    def _solis_control_charge_discharge(self, direction, enable, **kwargs):
        times = {
            "start": kwargs.get("start", None),
            "end": kwargs.get("end", None),
        }
        power = kwargs.get("power")

        if not enable:
            self.log(f"Disabling inverter timed {direction}")

        else:
            self.log(f"Updating inverter {direction} control:")
            for x in kwargs:
                self.log(f"  {x}: {kwargs[x]}")

        # Disable by setting the times the same
        if (enable is not None) and (not enable):
            times["start"] = pd.Timestamp.now()
            times["end"] = times["start"]

        # Don't span midnight
        if times["end"] is not None:
            if times["start"] is None:
                start_day = pd.Timestamp.now().day
            else:
                start_day = times["start"].day

            if start_day != times["end"].day:
                times["end"] = times["end"].normalize() - pd.Timedelta("1T")
                self.log(f"End time clipped to {times['end'].strftime(TIMEFORMAT)}")

        write_flag = True
        value_changed = False
        self.log(f"Times: {times}")
        for limit in times:
            if times[limit] is not None:
                for unit in ["hours", "minutes"]:
                    entity_id = self.host.config[f"id_timed_{direction}_{limit}_{unit}"]
                    if unit == "hours":
                        value = times[limit].hour
                    else:
                        value = times[limit].minute

                    if self.type == "SOLIS_SOLAX_MODBUS":
                        changed, written = self._write_and_poll_value(
                            entity_id=entity_id, value=value, verbose=True
                        )
                    else:
                        changed, written = self._solis_core_write_time(
                            direction, limit, unit, value
                        )

                    if changed:
                        if written:
                            self.log(
                                f"Wrote {direction} {limit} {unit} of {value} to inverter"
                            )
                            value_changed = True
                        else:
                            self.log(
                                f"Failed to write {direction} {limit} {unit} to inverter",
                                level="ERROR",
                            )
                            write_flag = False

        if value_changed:
            if self.type == "SOLIS_SOLAX_MODBUS" and write_flag:
                entity_id = self.host.config["id_timed_charge_discharge_button"]
                self.host.call_service("button/press", entity_id=entity_id)
                time.sleep(0.5)
                time_pressed = pd.Timestamp(self.host.get_state(entity_id))

                dt = (pd.Timestamp.now(self.host.tz) - time_pressed).total_seconds()
                if dt < 10:
                    self.log(f"Successfully pressed button {entity_id}")

                else:
                    self.log(
                        f"Failed to press button {entity_id}. Last pressed at {time_pressed.strftime(TIMEFORMAT)} ({dt:0.2f} seconds ago)"
                    )

        else:
            self.log("Inverter already at correct time settings")

        if power is not None:
            entity_id = self.host.config[f"id_timed_{direction}_current"]

            current = abs(round(power / self.host.get_config("battery_voltage"), 1))
            self.log(
                f"Power {power:0.0f} = {current:0.1f}A at {self.host.get_config('battery_voltage')}V"
            )
            if self.type == "SOLIS_SOLAX_MODBUS":
                changed, written = self._write_and_poll_value(
                    entity_id=entity_id, value=current, tolerance=1
                )
            else:
                changed, written = self._solis_core_write_current(
                    direction, current, tolerance=1
                )

            if changed:
                if written:
                    self.log(f"Current {current} written to inverter")
                else:
                    self.log(f"Failed to write {current} to inverter")
            else:
                self.log("Inverter already at correct current")

    def _solis_set_mode_switch(self, **kwargs):
        if self.type == "SOLIS_SOLAX_MODBUS":
            status = self._solis_solax_mode_switch()
        else:
            status = self._solis_core_mode_switch()

        switches = status["switches"]
        for switch in switches:
            if switch in kwargs:
                switches[switch] = kwargs[switch]

        bits = INVERTER_DEFS[self.type]["bits"]
        bin_list = [2**i * switches[bit] for i, bit in enumerate(bits)]
        code = sum(bin_list)
        entity_id = self.host.config["id_inverter_mode"]

        if self.type == "SOLIS_SOLAX_MODBUS":
            mode = INVERTER_DEFS[self.type]["modes"].get(code)
            if mode is not None:
                if self.host.get_state(entity_id=entity_id) != mode:
                    self.host.call_service(
                        "select/select_option", entity_id=entity_id, option=mode
                    )
                    self.log(f"Setting {entity_id} to {mode}")
        else:
            address = INVERTER_DEFS[self.type]["registers"]["storage_control_switch"]
            self._solis_core_write_holding_register(
                address=address, value=code, entity_id=entity_id
            )

    def _solis_solax_mode_switch(self):
        modes = INVERTER_DEFS["SOLIS_SOLAX_MODBUS"]["modes"]
        bits = INVERTER_DEFS["SOLIS_SOLAX_MODBUS"]["bits"]
        codes = {modes[m]: m for m in modes}
        inverter_mode = self.host.get_state(
            entity_id=self.host.config["id_inverter_mode"]
        )
        # self.log(f"codes: {codes} modes:{inverter_mode}")
        code = codes[inverter_mode]
        switches = {bit: (code & 2**i == 2**i) for i, bit in enumerate(bits)}
        return {"mode": inverter_mode, "code": code, "switches": switches}

    def _solis_core_mode_switch(self):
        bits = INVERTER_DEFS["SOLIS_CORE_MODBUS"]["bits"]
        code = int(self.host.get_state(entity_id=self.host.config["id_inverter_mode"]))
        switches = {bit: (code & 2**i == 2**i) for i, bit in enumerate(bits)}
        return {"code": code, "switches": switches}

    def _solis_state(self):
        limits = ["start", "end"]
        if self.type == "SOLIS_SOLAX_MODBUS":
            status = self._solis_solax_mode_switch()
        else:
            status = self._solis_core_mode_switch()

        for direction in ["charge", "discharge"]:
            status[direction] = {}
            for limit in limits:
                states = {}
                for unit in ["hours", "minutes"]:
                    entity_id = self.host.config[f"id_timed_{direction}_{limit}_{unit}"]
                    states[unit] = int(float(self.host.get_state(entity_id=entity_id)))
                status[direction][limit] = pd.Timestamp(
                    f"{states['hours']:02d}:{states['minutes']:02d}", tz=self.host.tz
                )
            time_now = pd.Timestamp.now(tz=self.tz)
            status[direction]["current"] = float(
                self.host.get_state(self.host.config[f"id_timed_{direction}_current"])
            )

            status[direction]["active"] = (
                time_now >= status[direction]["start"]
                and time_now < status[direction]["end"]
                and status[direction]["current"] > 0
                and status["switches"]["Timed"]
                and status["switches"]["GridCharge"]
            )
        return status

    def _solis_core_write_holding_register(
        self, address, value, entity_id=None, tolerance=0
    ):
        changed = True
        written = False
        hub = self.host.get_config("modbus_hub")
        slave = self.host.get_config("modbus_slave")
        # self.log(f">>> entity{entity_id}")
        if entity_id is not None:
            old_value = int(self.host.get_state(entity_id=entity_id))
            # self.log(f">>>Old value: {old_value} Value: {value}")
            if isinstance(old_value, int) and abs(old_value - value) <= tolerance:
                self.log(f"Inverter value already set to {value:d}.")
                changed = False

        if changed:
            data = {"address": address, "slave": slave, "value": value, "hub": hub}
            # self.log(f">>>Writing to Modbus with data: {data}")
            self.host.call_service("modbus/write_register", **data)
            written = True

        return changed, written

    def _solis_core_write_current(self, direction, current, tolerance):
        address = INVERTER_DEFS["SOLIS_CORE_MODBUS"]["registers"][
            f"timed_{direction}_current"
        ]
        entity_id = self.host.config[f"id_timed_{direction}_current"]
        return self._solis_core_write_holding_register(
            address=address,
            value=current * 10,
            entity_id=entity_id,
            tolerance=tolerance * 10,
        )

    def _solis_core_write_time(self, direction, limit, unit, value):
        address = INVERTER_DEFS["SOLIS_CORE_MODBUS"]["registers"][
            f"timed_{direction}_{limit}_{unit}"
        ]
        entity_id = self.host.config[f"id_timed_{direction}_{limit}_{unit}"]

        return self._solis_core_write_holding_register(
            address=address, value=value, entity_id=entity_id
        )

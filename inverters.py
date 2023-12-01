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
    }
}


class InverterController:
    def __init__(self, inverter_type, host) -> None:
        self.type = inverter_type
        self.host = host
        self.tz = self.host.tz
        if host is not None:
            self.log = host.log
        self.enable_timed_mode()

    def enable_timed_mode(self):
        if self.type == "SOLIS_SOLAX_MODBUS":
            self._solis_set_mode_switch(SelfUse=True, Timed=True, GridCharge=True)

    def _control_charge_discharge(self, direction, enable, **kwargs):
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

        if self.type == "SOLIS_SOLAX_MODBUS":
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
                        entity_id = self.host.config[
                            f"id_timed_{direction}_{limit}_{unit}"
                        ]
                        if unit == "hours":
                            value = times[limit].hour
                        else:
                            value = times[limit].minute

                        changed, written = self._write_and_poll_value(
                            entity_id=entity_id, value=value, verbose=True
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
                if write_flag:
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

                current = abs(round(power / self.host.config["battery_voltage"], 1))
                self.log(
                    f"Power {power:0.0f} = {current:0.1f}A at {self.host.config['battery_voltage']}V"
                )
                changed, written = self._write_and_poll_value(
                    entity_id=entity_id, value=current, tolerance=1
                )
                if changed:
                    if written:
                        self.log(f"Current {current} written to inverter")
                    else:
                        self.log(f"Failed to write {current} to inverter")
                else:
                    self.log("Inverter already at correct current")

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

    def control_charge(self, enable, **kwargs):
        self.enable_timed_mode()
        self._control_charge_discharge("charge", enable, **kwargs)

    def control_discharge(self, enable, **kwargs):
        self.enable_timed_mode()
        self._control_charge_discharge("discharge", enable, **kwargs)

    def hold_soc(self, soc, end=None):
        pass

    def _solis_set_mode_switch(self, **kwargs):
        status = self._solis_mode_switch()
        # self.log(">>>Inverter init")
        # self.log(status)
        switches = status["switches"]
        # self.log(f">>>kwargs: {kwargs}")
        for switch in switches:
            if switch in kwargs:
                switches[switch] = kwargs[switch]
                # self.log(f"  {switch}: {switches[switch]}")

        # self.log(f">>>Switches: {switches}")
        bits = INVERTER_DEFS["SOLIS_SOLAX_MODBUS"]["bits"]
        bin_list = [2**i * switches[bit] for i, bit in enumerate(bits)]
        # self.log(f">>>bin_list: {bin_list}")
        code = sum(bin_list)
        # self.log(f">>>Code: {code}")
        mode = INVERTER_DEFS["SOLIS_SOLAX_MODBUS"]["modes"].get(code)
        # self.log(f">>>Mode: {mode}")
        if mode is not None:
            entity_id = self.host.config["id_inverter_mode"]
            # self.log(f">>>Entity {entity_id}")
            if self.host.get_state(entity_id=entity_id) != mode:
                self.host.call_service(
                    "select/select_option", entity_id=entity_id, option=mode
                )
                self.log(f"Setting {entity_id} to {mode}")

        # code = sum(val*(2**idx) for idx, val in enumerate(binary))

    def _solis_mode_switch(self):
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

    def _solis_state(self):
        limits = ["start", "end"]

        status = self._solis_mode_switch()
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

    @property
    def status(self):
        if self.type == "SOLIS_SOLAX_MODBUS":
            status = self._solis_state()
            return status

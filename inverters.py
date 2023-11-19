import pandas as pd
import time

TIMEFORMAT = "%H:%M"


class InverterController:
    def __init__(self, inverter_type, host) -> None:
        self.type = inverter_type
        self.host = host
        if host is not None:
            self.log = host.log

    def _control_charge_discharge(self, direction, enable, **kwargs):
        times = {
            "start": kwargs.get("start", pd.Timestamp.now()),
            "end": kwargs.get("end", pd.Timestamp("23:59")),
        }
        power = kwargs.get("power", self.host.config["charger_power_watts"])

        self.log(
            f"Updating inverter {direction} times to {times['start'].strftime(TIMEFORMAT)}-{times['end'].strftime(TIMEFORMAT)} at {power:0.0f}W"
        )
        if self.type == "SOLIS_SOLAX_MODBUS":
            # Disable by steting the times the same
            if not enable:
                times["end"] = times["start"]

            # Don't span midnight
            elif times["end"].day != times["start".day]:
                times["end"] = times["end"].normalize() - pd.Timedelta("1T")
                self.log(f"End time clipped to {times['end'].strftime(TIMEFORMAT)}")

            write_flag = True
            value_changed = False
            for limit in times:
                for unit in ["hours", "minutes"]:
                    entity_id = self.host.config[
                        f"entity_id_timed_{direction}_{limit}_{unit}"
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
                    entity_id = self.host.config[
                        "entity_id_timed_charge_discharge_button"
                    ]
                    self.host.call_service("button/press", entity_id=entity_id)
                    time.sleep(0.1)
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

            entity_id = self.host.config[f"entity_id_timed_{direction}_current"]

            current = power / self.host.config["battery_voltage"]
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

                time.sleep(0.1)
                new_state = float(self.host.get_state(entity_id=entity_id))
                written = new_state == value

            except:
                written = False

        if verbose:
            self.log(
                f"Entity: {entity_id} Value: {value}  Old State: {state} New state: {new_state} Diff: {diff} Tol: {tolerance}"
            )

        return (changed, written)

    def _monitor_target_soc(self, target_soc, mode="charge"):
        pass

    def control_charge(self, enable, **kwargs):
        self._control_charge_discharge("charge", enable, **kwargs)

    def control_dicharge(self, enable, **kwargs):
        self._control_charge_discharge("discharge", enable, **kwargs)

    def hold_soc(self, soc, end=None):
        pass

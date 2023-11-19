import pandas as pd
import time


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

        if self.type == "SOLIS_SOLAX_MODBUS":
            write_flag = True
            for limit in times:
                for unit in ["hours", "minutes"]:
                    entity_id = self.host.config[
                        f"entity_id_timed_{direction}_{limit}_{unit}"
                    ]
                    if unit == "hours":
                        value = times[limit].hour
                    else:
                        value = times[limit].minute
                    try:
                        self.host.call_service(
                            "number/set_value", entity_id=entity_id, value=value
                        )

                        time.sleep(0.1)
                        if int(self.host.get_state(entity_id=entity_id)) == value:
                            self.log(
                                f"Wrote {direction} {limit} {unit} of {value} to inverter"
                            )
                        else:
                            raise ValueError

                    except:
                        self.log(
                            f"Failed to write {direction} {limit} {unit} to inverter",
                            level="ERROR",
                        )
                        write_flag = False
            if write_flag:
                entity_id = self.host.config["entity_id_timed_charge_discharge_button"]

                self.log(f">>> Pressed button {entity_id}")

                self.host.call_service("button/press", entity_id=entity_id)
                self.log(f"Pressed button {entity_id}")
                #     sleep(1)
                #     time_pressed = datetime.strptime(entity.get_state(), TIME_FORMAT_SECONDS)

                # if (pytz.timezone("UTC").localize(datetime.now()) - time_pressed).seconds < 10:
                # self.log(
                #     f"Successfully pressed button {entity_id} on Inverter {self.id}"
                # )

                # except:
                #     self.log(f"Failed to press button {entity_id}")

    def _monitor_target_soc(self, target_soc, mode="charge"):
        pass

    def control_charge(self, enable, **kwargs):
        self._control_charge_discharge("charge", enable, **kwargs)

    def control_dicharge(self, enable, **kwargs):
        self._control_charge_discharge("discharge", enable, **kwargs)

    def hold_soc(self, soc, end=None):
        pass

import pandas as pd

INVERTER_TYPES = {
    "SOLIS_SOLAX_MODBUS": {
        "timed": True,
        "current_power": "Current",
    }
}


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
            for limit in times:
                for unit in ["hours", "minutes"]:
                    entity_id = self.host.config[
                        f"enitity_id_timed_{direction}_{limit}_{unit}"
                    ]
                    if unit == "hours":
                        value = times[limit].hour
                    else:
                        value = times[limit].minute
                    try:
                        self.host.set_state(entity_id=entity_id, state=value)
                        self.log(f"Wrote {direction} {limit} {unit} to inverter")
                    except:
                        self.log(
                            f"Failed to write {direction} {limit} {unit} to inverter",
                            level="WARNING",
                        )

    def _monitor_target_soc(self, target_soc, mode="charge"):
        pass

    def control_charge(self, enable, **kwargs):
        self._control_charge_discharge("charge", enable, **kwargs)

    def control_dicharge(self, enable, **kwargs):
        self._control_charge_discharge("discharge", enable, **kwargs)

    def hold_soc(self, soc, end=None):
        pass

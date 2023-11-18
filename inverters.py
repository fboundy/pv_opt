INVERTER_TYPES = {
    "SOLIS_SOLAX_MODBUS": {
        "timed": True,
        "current_power": "Current",
    }
}


class InverterController:
    def __init__(self, inverter_type, host=None) -> None:
        if host is not None:
            self.log = host.log
        else:
            self.log = print
        pass

    def control_discharge(
        self, enable, start=None, end=None, target_soc=None, power=None
    ):
        pass

    def control_charge(self, enable, start=None, end=None, target_soc=None, power=None):
        pass

    def hold_soc(self, soc, end=None):
        pass

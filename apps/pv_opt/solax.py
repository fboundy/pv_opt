import pandas as pd
import time

TIMEFORMAT = "%H:%M"
INVERTER_DEFS = {
    "SOLAX_X1": {
        # "modes": {
        #     1: "Selfuse - No Grid Charging",
        #     3: "Timed Charge/Discharge - No Grid Charging",
        #     17: "Backup/Reserve - No Grid Charging",
        #     33: "Selfuse",
        #     35: "Timed Charge/Discharge",
        #     37: "Off-Grid Mode",
        #     41: "Battery Awaken",
        #     43: "Battery Awaken + Timed Charge/Discharge",
        #     49: "Backup/Reserve - No Timed Charge/Discharge",
        #     51: "Backup/Reserve",
        # },
        # "bits": [
        #     "SelfUse",
        #     "Timed",
        #     "OffGrid",
        #     "BatteryWake",
        #     "Backup",
        #     "GridCharge",
        #     "FeedInPriority",
        # ],
        # Default Configuration: Exposed as inverter.config and provides defaults for this inverter for the
        # required config. These config items can be over-written by config specified in the config.yaml
        # file. They are required for the main PV_Opt module and if they cannot be found an ERROR will be
        # raised
        "default_config": {
            "maximum_dod_percent": "number.{device_name}_battery_minimum_capacity",
            "id_battery_soc": " sensor.{device_name}_battery_capacity",
            "id_consumption": "sensor.{device_name}_house_load",
            "id_grid_import_today": "sensor.{device_name}_today_s_import_energy",
            "id_grid_export_today": "sensor.{device_name}_today_s_export_energy",
            "supports_hold_soc": False,
            "update_cycle_seconds": 300,
        },
        # Brand Conguration: Exposed as inverter.brand_config and can be over-written using arguments
        # from the config.yaml file but not rquired outside of this module
        "brand_config": {
            "battery_voltage": "sensor.{device_name}_battery_voltage_charge",
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

    def enable_timed_mode(self):
        if self.type == "SOLAX_X1":
            pass

    def control_charge(self, enable, **kwargs):
        if enable:
            self.enable_timed_mode()
        self._control_charge_discharge("charge", enable, **kwargs)

    def control_discharge(self, enable, **kwargs):
        if enable:
            self.enable_timed_mode()
        self._control_charge_discharge("discharge", enable, **kwargs)

    def hold_soc(self, enable, soc=None):
        if self.type == "SOLAX_X1":
            if enable:
                self._solis_set_mode_switch(SelfUse=True, Timed=False, GridCharge=True, Backup=True)
            else:
                self.enable_timed_mode()

            # Waiyt for a second to make sure the mode is correct
            time.sleep(1)

            if soc is None:
                soc = self.host.get_config("maximum_dod_percent")

            entity_id = self.host.config["id_backup_mode_soc"]

            self.log(f"Setting Backup SOC to {soc}%")
            if self.type == "SOLIS_SOLAX_MODBUS":
                changed, written = self._write_and_poll_value(entity_id=entity_id, value=soc)
            elif self.type == "SOLIS_CORE_MODBUS" or self.type == "SOLIS_SOLARMAN":
                changed, written = self.solis_write_holding_register(
                    address=INVERTER_DEFS(self.type)["registers"]["backup_mode_soc"],
                    value=soc,
                    entity_id=entity_id,
                )
            else:
                e = "Unknown inverter type"
                self.log(e, level="ERROR")
                raise Exception(e)

    @property
    def status(self):
        status = None
        if self.type == "SOLAX_X1":
            status = "Status"

        return status

    def _write_and_poll_value(self, entity_id, value, tolerance=0.0, verbose=False):
        changed = False
        written = False
        return (changed, written)

    def _monitor_target_soc(self, target_soc, mode="charge"):
        pass

    def _control_charge_discharge(self, direction, enable, **kwargs):
        if self.type == "SOLAX_X1":
            pass

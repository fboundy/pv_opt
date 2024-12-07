import pandas as pd
import time
import hashlib
import hmac
import base64
import json
import re
import requests
from http import HTTPStatus
from datetime import datetime, timezone
from abc import ABC, abstractmethod
from typing import final
from time import sleep

LIMITS = ["start", "end"]
DIRECTIONS = ["charge", "discharge"]
TIME_UNITS = ["hours", "minutes"]

URLS = {
    "root": "https://www.soliscloud.com:13333",
    "login": "/v2/api/login",
    "control": "/v2/api/control",
    "inverterList": "/v1/api/inverterList",
    "atRead": "/v2/api/atRead",
}

SOLIS_CODES = {
    True: {
        "Self-Use - No Grid Charging": 1,
        "Off-Grid Mode": 5,
        "Battery Awaken - No Grid Charging": 9,
        "Self-Use": 33,
        "Battery Awaken": 41,
        "Backup/Reserve": 49,
        "Feed-in priority": 64,
    },
    False: {
        "SelfUse - No Grid Charging": 1,
        "Self-Use - No Grid Charging": 1,
        "Timed Charge/Discharge - No Grid Charging": 3,
        "Backup/Reserve - No Grid Charging": 17,
        "SelfUse": 33,
        "Self-Use - No Timed Charge/Discharge": 33,
        "Self-Use": 35,
        "Timed Charge/Discharge": 35,
        "Off-Grid Mode": 37,
        "Battery Awaken": 41,
        "Battery Awaken + Timed Charge/Discharge": 43,
        "Backup/Reserve - No Timed Charge/Discharge": 49,
        "Backup/Reserve": 51,
        "Feed-in priority - No Grid Charging": 64,
        "Feed-in priority - No Timed Charge/Discharge": 96,
        "Feed-in priority": 98,
    },
}

REGISTERS = {
    True: {
        "timed_charge_soc": 43708,
        "timed_charge_current": 43709,
        "timed_charge_start_hours": 43711,
        "timed_charge_start_minutes": 43712,
        "timed_charge_end_hours": 43713,
        "timed_charge_end_minutes": 43714,
        "timed_discharge_soc": 43750,
        "timed_discharge_current": 43151,
        "timed_discharge_start_hours": 43153,
        "timed_discharge_start_minutes": 43154,
        "timed_discharge_end_hours": 43155,
        "timed_discharge_end_minutes": 43156,
        "storage_control_switch": 43110,
        "backup_mode_soc": 43024,
    },
    False: {
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
        "backup_mode_soc": 43024,
    },
}

SOLIS_BITS = [
    "SelfUse",
    "Timed",
    "OffGrid",
    "BatteryWake",
    "Backup",  # Used for Hold SOC
    "GridCharge",
    "FeedInPriority",
]


TIMEFORMAT = "%H:%M"
INVERTER_DEFS = {
    "SOLIS_SOLAX_MODBUS": {
        "online": "number.{device_name}_battery_minimum_soc",
        "codes": {
            "SelfUse - No Grid Charging": 1,
            "Self-Use - No Grid Charging": 1,
            "Timed Charge/Discharge - No Grid Charging": 3,
            "Backup/Reserve - No Grid Charging": 17,
            "SelfUse": 33,
            "Self-Use - No Timed Charge/Discharge": 33,
            "Self-Use": 35,
            "Timed Charge/Discharge": 35,
            "Off-Grid Mode": 37,
            "Battery Awaken": 41,
            "Battery Awaken + Timed Charge/Discharge": 43,
            "Backup/Reserve - No Timed Charge/Discharge": 49,
            "Backup/Reserve": 51,
            "Feed-in priority - No Grid Charging": 64,
            "Feed-in priority - No Timed Charge/Discharge": 96,
            "Feed-in priority": 98,
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
            "maximum_dod_percent": "number.{device_name}_battery_minimum_soc",
            "id_battery_soc": "sensor.{device_name}_battery_soc",
            "id_consumption_today": "sensor.{device_name}_house_load_today",
            "id_consumption": [
                "sensor.{device_name}_house_load_x",
                "sensor.{device_name}_bypass_load_x",
            ],
            "id_grid_import_today": "sensor.{device_name}_grid_import_today",
            "id_grid_export_today": "sensor.{device_name}_grid_export_today",
            "id_battery_charge_power": "sensor.{device_name}_battery_input_energy",
            "id_inverter_ac_power": "sensor.{device_name}_active_power",
            "supports_hold_soc": True,
            "supports_forced_discharge": True,
            "update_cycle_seconds": 15,
        },
        # Brand Conguration: Exposed as inverter.brand_config and can be over-written using arguments
        # from the config.yaml file but not rquired outside of this module
        "brand_config": {
            "battery_voltage": "sensor.{device_name}_battery_voltage",
            "id_timed_charge_start_hours": "number.{device_name}_timed_charge_start_hours",
            "id_timed_charge_start_minutes": "number.{device_name}_timed_charge_start_minutes",
            "id_timed_charge_end_hours": "number.{device_name}_timed_charge_end_hours",
            "id_timed_charge_end_minutes": "number.{device_name}_timed_charge_end_minutes",
            "id_timed_charge_current": "number.{device_name}_timed_charge_current",
            "id_timed_charge_soc": "number.{device_name}_timed_charge_soc",
            "id_timed_discharge_start_hours": "number.{device_name}_timed_discharge_start_hours",
            "id_timed_discharge_start_minutes": "number.{device_name}_timed_discharge_start_minutes",
            "id_timed_discharge_end_hours": "number.{device_name}_timed_discharge_end_hours",
            "id_timed_discharge_end_minutes": "number.{device_name}_timed_discharge_end_minutes",
            "id_timed_discharge_current": "number.{device_name}_timed_discharge_current",
            "id_timed_discharge_soc": "number.{device_name}_timed_discharge_soc",
            "id_timed_charge_button": "button.{device_name}_update_charge_times",
            "id_timed_discharge_button": "button.{device_name}_update_discharge_times",
            "id_timed_charge_discharge_button": "button.{device_name}_update_charge_discharge_times",
            "id_inverter_mode": "select.{device_name}_energy_storage_control_switch",
            "id_backup_mode_soc": "number.{device_name}_backup_mode_soc",
        },
    },
    "SOLIS_CORE_MODBUS": {
        "online": "sensor.{device_name}_overdischarge_soc",
        "default_config": {
            "maximum_dod_percent": "sensor.{device_name}_overdischarge_soc",
            "id_battery_soc": "sensor.{device_name}_battery_soc",
            "id_consumption_today": "sensor.{device_name}_daily_consumption",
            "id_grid_import_today": "sensor.{device_name}_daily_energy_imported",
            "id_grid_export_today": "sensor.{device_name}_daily_energy_exported",
            # "id_consumption": [
            #     "sensor.{device_name}_house_load_power",
            #     "sensor.{device_name}_backup_load_power",
            # ],
            "id_grid_power": "sensor.{device_name}_grid_active_power",
            "id_inverter_ac_power": "sensor.{device_name}_inverter_ac_power",
            "supports_hold_soc": True,
            "supports_forced_discharge": True,
            "update_cycle_seconds": 60,
        },
        "brand_config": {
            "modbus_hub": "solis",
            "modbus_slave": 1,
            "battery_voltage": "sensor.{device_name}_battery_voltage",
            "id_timed_charge_start_hours": "sensor.{device_name}_timed_charge_start_hour",
            "id_timed_charge_start_minutes": "sensor.{device_name}_timed_charge_start_minute",
            "id_timed_charge_end_hours": "sensor.{device_name}_timed_charge_end_hour",
            "id_timed_charge_end_minutes": "sensor.{device_name}_timed_charge_end_minute",
            "id_timed_charge_current": "sensor.{device_name}_timed_charge_current_limit",
            "id_timed_discharge_start_hours": "sensor.{device_name}_timed_discharge_start_hour",
            "id_timed_discharge_start_minutes": "sensor.{device_name}_timed_discharge_start_minute",
            "id_timed_discharge_end_hours": "sensor.{device_name}_timed_discharge_end_hour",
            "id_timed_discharge_end_minutes": "sensor.{device_name}_timed_discharge_end_minute",
            "id_timed_discharge_current": "sensor.{device_name}_timed_discharge_current_limit",
            "id_inverter_mode": "sensor.{device_name}_energy_storage_control_switch",
            "id_backup_mode_soc": "sensor.{device_name}_backup_mode_soc",
        },
    },
    "SOLIS_SOLARMAN": {
        "default_config": {
            "maximum_dod_percent": 15,
            "id_battery_soc": "sensor.{device_name}_battery_soc",
            "id_consumption_today": "sensor.{device_name}_daily_house_backup_consumption",
            "id_grid_power": "sensor.{device_name}_meter_active_power",
            "id_inverter_ac_power": "sensor.{device_name}_inverter_ac_power",
            "supports_hold_soc": True,
            "supports_forced_discharge": True,
            "update_cycle_seconds": 60,
        },
        "brand_config": {
            "battery_voltage": "sensor.{device_name}_battery_voltage",
            "id_timed_charge_start_hours": "sensor.{device_name}_timed_charge_start_hour",
            "id_timed_charge_start_minutes": "sensor.{device_name}_timed_charge_start_minute",
            "id_timed_charge_end_hours": "sensor.{device_name}_timed_charge_end_hour",
            "id_timed_charge_end_minutes": "sensor.{device_name}_timed_charge_end_minute",
            "id_timed_charge_current": "sensor.{device_name}_timed_charge_current_limit",
            "id_timed_discharge_start_hours": "sensor.{device_name}_timed_discharge_start_hour",
            "id_timed_discharge_start_minutes": "sensor.{device_name}_timed_discharge_start_minute",
            "id_timed_discharge_end_hours": "sensor.{device_name}_timed_discharge_end_hour",
            "id_timed_discharge_end_minutes": "sensor.{device_name}_timed_discharge_end_minute",
            "id_timed_discharge_current": "sensor.{device_name}_timed_discharge_current_limit",
            "id_inverter_mode": "sensor.{device_name}_storage_control_mode",
            "id_backup_mode_soc": "sensor.{device_name}_backup_mode_soc",
        },
    },
    "SOLIS_CLOUD": {
        "online": "sensor.{device_name}_state",
        "default_config": {
            "maximum_dod_percent": "sensor.{device_name}_force_discharge_soc",
            "id_consumption_today": "sensor.{device_name}_daily_grid_energy_used",
            "id_grid_import_today": "sensor.{device_name}_daily_grid_energy_purchased",
            "id_grid_export_today": "sensor.{device_name}_daily_on_grid_energy",
            "id_battery_soc": "sensor.{device_name}_remaining_battery_capacity",
            "supports_hold_soc": True,
            "supports_forced_discharge": True,
            "update_cycle_seconds": 0,
        },
        "brand_config": {
            "battery_voltage": "sensor.{device_name}_battery_voltage",
            "id_inverter_mode": "select.{device_name}_energy_storage_control_switch",
            "id_timed_charge_start": "time.{device_name}_timed_charge_start_1",
            "id_timed_charge_end": "time.{device_name}_timed_charge_end_1",
            "id_timed_charge_current": "number.{device_name}_timed_charge_current_1",
            "id_timed_charge_soc": "number.{device_name}_timed_charge_soc_1",
            "id_timed_discharge_start": "time.{device_name}_timed_discharge_start_1",
            "id_timed_discharge_end": "time.{device_name}_timed_discharge_end_1",
            "id_timed_discharge_current": "number.{device_name}_timed_discharge_current_1",
            "id_timed_discharge_soc": "number.{device_name}_timed_discharge_soc_1",
            "id_timed_charge_button": "button.{device_name}_update_timed_charge_1",
            "id_timed_discharge_button": "button.{device_name}_update_timed_discharge_1",
            "id_timed_charge_discharge_button": "button.{device_name}_update_timed_charge_discharge_1",
        },
    },
}


def create_inverter_controller(inverter_type: str, host):
    if inverter_type == "SOLIS_CORE_MODBUS":
        return SolisCoreModbusInverter(
            inverter_type=inverter_type,
            host=host,
        )

    elif inverter_type == "SOLIS_CLOUD":
        return SolisCloudInverter(
            inverter_type=inverter_type,
            host=host,
        )

    elif inverter_type == "SOLIS_SOLAX_MODBUS":
        return SolisSolaxModbusInverter(
            inverter_type=inverter_type,
            host=host,
        )

    elif inverter_type == "SOLIS_SOLARMAN_MODBUS":
        return SolisSolarmanModbusInverter(
            inverter_type=inverter_type,
            host=host,
        )

    else:
        host.log(f"Unknown inverter type {inverter_type}")
        return False


# This is the Base Class
class BaseInverterController(ABC):
    def __init__(self, inverter_type: str, host) -> None:
        self._host = host
        self._tz = self._host.tz
        if host is not None:
            self.log = host.log
        self._type = inverter_type
        self._device_name = self._host.device_name
        self._config = {}
        self._brand_config = {}
        self._online = INVERTER_DEFS[self._type]["online"].replace("{device_name}", self._device_name)
        for defs, conf in zip(
            [INVERTER_DEFS[self._type][x] for x in ["default_config", "brand_config"]],
            [self._config, self._brand_config],
        ):
            for item in defs:
                if isinstance(defs[item], str):
                    conf[item] = defs[item].replace("{device_name}", self._device_name)
                elif isinstance(defs[item], list):
                    conf[item] = [z.replace("{device_name}", self._device_name) for z in defs[item]]
                else:
                    conf[item] = defs[item]
        self.log(f"Loading controller for inverter type {self._type}")

    @property
    @abstractmethod
    def is_online(self):
        pass

    @property
    @abstractmethod
    def timed_mode(self):
        pass

    @abstractmethod
    def enable_timed_mode(self):
        pass

    @abstractmethod
    def control_charge(self, enable, **kwargs):
        pass

    @abstractmethod
    def control_discharge(self, enable, **kwargs):
        pass

    @abstractmethod
    def hold_soc(self, enable, soc=None, **kwargs):
        pass

    def get_config(self, config_variable, default=None):
        return self._host.get_config(config_variable, default)

    @property
    @abstractmethod
    def status(self):
        pass

    @property
    def config(self):
        return self._config

    @property
    def brand_config(self):
        return self._brand_config

    def write_to_hass(self, entity_id, value, **kwargs):
        self.log(f">>> {value}")
        try:
            value = float(value)
        except:
            pass

        if isinstance(value, int) or isinstance(value, float):
            return self._host.write_and_poll_value(entity_id=entity_id, value=value, **kwargs)
        else:
            try:
                return self._host.write_and_poll_time(entity_id=entity_id, time=value, **kwargs)
            except:
                self.log(f"Unable to write value {value} to entity {entity_id}", level="ERROR")
                return True, False

    def _press_button(self, entity_id):
        self._host.call_service("button/press", entity_id=entity_id)
        time.sleep(0.5)
        try:
            time_pressed = pd.Timestamp(self._host.get_state_retry(entity_id))
            dt = (pd.Timestamp.now(self._tz) - time_pressed).total_seconds()
            if dt < 10:
                self.log(f"Successfully pressed button {entity_id}")
            else:
                self.log(
                    f"Failed to press button {entity_id}. Last pressed at {time_pressed.strftime(TIMEFORMAT)} ({dt:0.2f} seconds ago)"
                )
        except:
            self.log(f"Failed to press button {entity_id}: it appears to never have been pressed.")


class SolisInverter(BaseInverterController):
    def __init__(self, inverter_type, host):
        super().__init__(inverter_type, host)
        self._hmi_fb00 = host.args.get("hmi_firmware_fb00_plus", False)
        self.log(f"HMI Firmware Flag set to {self._hmi_fb00}")
        self._codes = SOLIS_CODES[self._hmi_fb00]
        self._reverse_codes = {self._codes[code]: code for code in self._codes}
        self._bits = SOLIS_BITS

    @property
    def timed_mode(self):
        if self._hmi_fb00:
            code = 33
        else:
            code = 35
        return int(self._get_energy_control_code()) == code

    @final
    def enable_timed_mode(self):
        # set the energy control switch depending on HMI version
        if self._hmi_fb00:
            code = 33
        else:
            code = 35
        self.log(f">>> Setting energy control switch to {code} to enable timed mode")
        self._set_energy_control_switch(code)

    @abstractmethod
    def _set_energy_control_switch(self, code):
        pass

    @property
    @final
    def status(self):
        time_now = pd.Timestamp.now(tz=self._tz)
        code = self._get_energy_control_code()
        status = {"code": code}
        status = status | {"switches": self._switches(code)}
        status = status | {direction: self._get_times_current(direction=direction) for direction in DIRECTIONS}
        voltage = self.voltage
        for direction in DIRECTIONS:
            status[direction]["power"] = status[direction]["current"] * voltage
            status[direction]["active"] = (
                time_now >= status[direction]["start"]
                and time_now < status[direction]["end"]
                and status[direction].get("current", 0) > 0
                and (self._hmi_fb00 or status["switches"].get("Timed", False))
                and status["switches"].get("GridCharge", False)
            )
        # status["hold_soc"] = {
        #     "active": status["switches"].get("GridCharge", False) and status["switches"].get("Backup", False)
        # }
        return status

    def _switches(self, code):
        return {bit: (code & 2**i == 2**i) for i, bit in enumerate(self._bits)}

    @property
    def is_online(self):
        entity_id = self._online
        if entity_id is not None:
            return self._host.get_state_retry(entity_id) not in ["unknown", "unavailable"]
        else:
            return False

    @abstractmethod
    def _get_energy_control_code(self):
        pass

    def control_charge(self, enable, **kwargs):
        self._control_charge_discharge("charge", enable, **kwargs)

    def control_discharge(self, enable, **kwargs):
        self._control_charge_discharge("discharge", enable, **kwargs)

    def _control_charge_discharge(self, direction, enable, **kwargs):
        times = {}
        if enable:
            times["start"] = kwargs.get("start", None)
            times["end"] = kwargs.get("end", None)
            current = kwargs.get("current", round(kwargs.get("power", 0) / self.voltage, 1))
            soc = kwargs.get("target_soc", None)

        else:
            # Disable by setting end time = start time:
            times["start"] = self.status["charge"]["start"]
            times["end"] = times["start"]
            current = 0
            soc = None

        if soc is None and self._hmi_fb00:
            if direction == "charge":
                soc = 100
            else:
                soc = 15

        self.log(f">>> direction: {direction}")
        self.log(f">>> times: {times}")
        self.log(f">>> current: {current}")
        changed = self._set_times(direction, **times)
        self.log(f">>> changed: {changed}")
        changed = changed or self._set_current(direction, current)
        self.log(f">>> changed: {changed}")

        if changed and self._requires_button:
            self.log("Something changed - need to press the appropriate Button")
            if self._hmi_fb00:
                entity_id = self.brand_config.get(f"id_timed_{direction}_button", None)
            else:
                entity_id = self.brand_config.get(f"id_timed_charge_discharge_button", None)

            self.log(f">>> {entity_id}")
            if entity_id is not None:
                self._press_button(entity_id=entity_id)

        if changed and self._hmi_fb00:
            """
            There seems to be a bug where with the FB00+ firmware the changes aren't saved unless
            the target SOC is also set
            """
            self._set_target_soc(direction, soc, forced=True)

    def hold_soc(self, enable, soc=None, **kwargs):
        start = kwargs.get("start", pd.Timestamp.now(tz=self._tz).floor("1min"))
        end = kwargs.get("end", pd.Timestamp.now(tz=self._tz).ceil("30min"))
        if self._hmi_fb00:
            self._control_charge_discharge(
                "charge",
                enable=enable,
                start=start,
                end=end,
                power=3000,
                soc=soc,
            )
        else:
            self._control_charge_discharge(
                "charge",
                enable=enable,
                start=start,
                end=end,
                power=0,
            )

    @abstractmethod
    def _get_times_current(self, direction):
        pass

    @abstractmethod
    def _set_times(self, direction, **kwargs) -> bool:
        pass

    @abstractmethod
    def _set_current(self, direction, current) -> bool:
        pass

    @property
    def voltage(self):
        return self.get_config("battery_voltage", 50)


class SolisCloudInverter(SolisInverter):
    def __init__(self, inverter_type: str, host):
        super().__init__(inverter_type, host)
        self._requires_button = True
        self.log(self._config)
        self.log(self._brand_config)

    def _get_energy_control_code(self):
        mode = self.get_config("id_inverter_mode")
        code = self._codes[mode]
        return code

    def _set_energy_control_switch(self, code: int):
        self.log(f"Setting energy control switch to {code}")

    def hold_soc(self, enable, soc=None, **kwargs):
        self.log("Holding SOC")

    def set_reserve_soc(self, sotrc: int):
        pass

    def _get_times_current(self, direction):
        times = {
            limit: pd.Timestamp(self.get_config(f"id_timed_{direction}_{limit}", "0:00"), tz=self._tz)
            for limit in LIMITS
        }
        current = {"current": self.get_config(f"id_timed_{direction}_current", 0)}
        return times | current

    def _set_times(self, direction, **times) -> bool:
        value_changed = False
        for limit in LIMITS:
            time = times.get(limit, None)
            if time is not None:
                entity_id = self._host.config.get(f"id_timed_{direction}_{limit}", None)
                if entity_id is not None:
                    changed, written = self.write_to_hass(entity_id=entity_id, value=time, verbose=True)
                    value_changed = value_changed or written

        return value_changed

    def _set_current(self, direction, current: float = 0) -> bool:
        entity_id = self._host.config.get(f"id_timed_{direction}_current", None)
        if entity_id is not None:
            changed, written = self.write_to_hass(entity_id=entity_id, value=current, tolerance=0.1, verbose=True)

        if changed:
            if written:
                self.log(f"Current {current}A written to inverter")
            else:
                self.log(f"Failed to write {current} to inverter")
        else:
            self.log("Inverter already at correct current")

        return not (changed and not written)

    def _set_target_soc(self, direction, soc: int = 100, forced=True) -> bool:
        entity_id = self._host.config.get(f"id_timed_{direction}_soc", None)
        if forced:
            tolerance = -1
        else:
            tolerance = 0

        if entity_id is not None:
            changed, written = self.write_to_hass(entity_id=entity_id, value=soc, tolerance=tolerance, verbose=True)

        if changed:
            if written:
                self.log(f"Target SOC {soc}% written to inverter")
            else:
                self.log(f"Failed to write SOC {soc}% to inverter")
        else:
            self.log("Inverter already at correct target SOC")

        return not (changed and not written)


class SolisModbusInverter(SolisInverter):
    def __init__(self, inverter_type, host):
        super().__init__(inverter_type, host)

    @abstractmethod
    def write_time_register(self, direction, limit, unit, value):
        pass

    @abstractmethod
    def write_current_register(self, direction, current, tolerance):
        pass

    @abstractmethod
    def _get_energy_control_code(self):
        pass

    @abstractmethod
    def _set_energy_control_switch(self, code: int):
        pass

    def _get_times_current(self, direction):
        times = {}
        for limit in LIMITS:
            x = {unit: self.get_config(f"id_timed_{direction}_{limit}_{unit}", 0) for unit in TIME_UNITS}
            times[limit] = pd.Timestamp(pd.Timestamp.today().date(), tz=self._tz) + pd.Timedelta(**x)

        current = {"current": self.get_config(f"id_timed_{direction}_current", 0)}
        return times | current

    def _set_times(self, direction, **times) -> bool:
        value_changed = False
        for limit in LIMITS:
            time = times.get(limit, None)
            if time is not None:
                changed, written = self.write_time_register(direction, limit, "hours", time.hour)
                value_changed = value_changed or (changed and written)
                changed, written = self.write_time_register(direction, limit, "minutes", time.minute)
                value_changed = value_changed or (changed and written)
        return value_changed

    def _set_current(self, direction, current):
        changed, written = self.write_current_register(direction, current, tolerance=0.1)
        return changed and written


class SolisSolaxModbusInverter(SolisModbusInverter):
    def __init__(self, inverter_type: str, host):
        super().__init__(inverter_type, host)
        self._requires_button = True

    def _get_energy_control_code(self):
        mode = self.get_config("id_inverter_mode")
        code = self._codes[mode]
        return code

    def _set_energy_control_switch(self, code: int):
        self.log(f"Setting energy control switch to {code}")

    def write_time_register(self, direction, limit, unit, value):
        param = f"id_timed_{direction}_{limit}_{unit}"
        self.log(f">>> param: {param}")
        entity_id = self._host.config.get(param, None)
        self.log(f">>> entity_id: {entity_id}")
        self.log(f">>> value: {value}")
        if entity_id is not None:
            return self.write_to_hass(entity_id=entity_id, value=value, verbose=True)
        else:
            return False, False

    def write_current_register(self, direction, current, tolerance):
        entity_id = self._host.config.get(f"id_timed_{direction}_current", None)
        if entity_id is not None:
            return self.write_to_hass(entity_id=entity_id, value=current, tolerance=tolerance, verbose=True)
        else:
            return False, False

    def _set_target_soc(self, direction, soc: int = 100, forced=True) -> bool:
        entity_id = self._host.config.get(f"id_timed_{direction}_soc", None)
        if forced:
            tolerance = -1
        else:
            tolerance = 0

        if entity_id is not None:
            changed, written = self.write_to_hass(entity_id=entity_id, value=soc, tolerance=tolerance, verbose=True)

        if changed:
            if written:
                self.log(f"Target SOC {soc}% written to inverter")
            else:
                self.log(f"Failed to write SOC {soc}% to inverter")
        else:
            self.log("Inverter already at correct target SOC")

        return not (changed and not written)


class SolisCoreModbusInverter(SolisModbusInverter):
    def __init__(self, inverter_type, host):
        super().__init__(inverter_type, host)
        self._requires_button = False
        self._registers = REGISTERS[self._hmi_fb00]
        self._hub = self.get_config("modbus_hub")
        self._slave = self.get_config("modbus_slave")

    def _get_energy_control_code(self):
        code = int(self.get_config("id_inverter_mode"))
        return code

    def _set_energy_control_switch(self, code: int):
        cfg = "id_inverter_mode"
        return self._write_modbus_register(
            register=self._registers["storage_control_switch"],
            value=int(code),
            cfg=cfg,
        )

    def write_time_register(self, direction, limit, unit, value):
        cfg = f"id_timed_{direction}_{limit}_{unit}"
        register = self._registers[f"timed_{direction}_{limit}_{unit}"]
        return self._write_modbus_register(
            register=register,
            value=int(value),
            cfg=cfg,
        )

    def write_current_register(self, direction, current, tolerance):
        cfg = f"id_timed_{direction}_current"
        register = self._registers[f"timed_{direction}_current"]
        return self._write_modbus_register(
            register=register, value=round(current, 1), cfg=cfg, tolerance=tolerance, multiplier=10
        )

    def write_soc_register(self, direction, soc):
        cfg = "id_timed_{direction}_soc"
        register = self._registers[f"timed_{direction}_soc"]
        return self._write_modbus_register(register=register, value=int(soc), cfg=cfg)

    def _write_modbus_register(self, register, value, cfg=None, tolerance=0, multiplier=1):
        changed = True
        written = False
        self.log(f"Setting register {register} to {value} for entity {cfg}")
        if cfg is not None:
            current_value = int(float(self.get_config(cfg)))
            if isinstance(current_value, int) and abs(current_value / multiplier - value) <= tolerance:
                self.log(f"Inverter value already set to {value}.")
                changed = False

            if changed:
                data = {
                    "address": register,
                    "slave": self._slave,
                    "value": int(round(value * multiplier, 0)),
                    "hub": self._hub,
                }
                self._host.call_service("modbus/write_register", **data)
                sleep(0.1)
                new_value = int(float(self.get_config(cfg))) / multiplier
                self.log(f">>> current_value: {current_value/multiplier}")
                self.log(f">>> value: {value}")
                self.log(f">>> new_value: {new_value}")
                written = new_value == value
        return changed, written


class SolisSolarmanModbusInverter(SolisModbusInverter):
    def __init__(self, inverter_type, host):
        super().__init__(inverter_type, host)
        self._requires_button = False

    def _set_energy_control_switch(self, code: int):
        self.log(f"Setting energy control switch to {code}")

    def write_time_register(self, direction, limit, unit, value):
        pass

    def write_current_register(self, direction, current, tolerance):
        pass


class SolisCloud:
    URLS = {
        "root": "https://www.soliscloud.com:13333",
        "login": "/v2/api/login",
        "control": "/v2/api/control",
        "inverterList": "/v1/api/inverterList",
        "inverterDetail": "/v1/api/inverterDetail",
        "atRead": "/v2/api/atRead",
    }

    MAX_RETRIES = 5

    def __init__(self, username, password, key_id, key_secret, plant_id, **kwargs):
        self.username = username
        self.key_id = key_id
        self.key_secret = key_secret
        self.plant_id = plant_id
        self.md5password = hashlib.md5(password.encode("utf-8")).hexdigest()
        self.token = ""
        self.log = kwargs.get("log", print)

    def get_body(self, **params):
        body = "{"
        for key in params:
            body += f'"{key}":"{params[key]}",'
        body = body[:-1] + "}"
        return body

    def digest(self, body: str) -> str:
        return base64.b64encode(hashlib.md5(body.encode("utf-8")).digest()).decode("utf-8")

    def header(self, body: str, canonicalized_resource: str) -> dict[str, str]:
        content_md5 = self.digest(body)
        content_type = "application/json"

        now = datetime.now(timezone.utc)
        date = now.strftime("%a, %d %b %Y %H:%M:%S GMT")

        encrypt_str = "POST" + "\n" + content_md5 + "\n" + content_type + "\n" + date + "\n" + canonicalized_resource
        hmac_obj = hmac.new(self.key_secret.encode("utf-8"), msg=encrypt_str.encode("utf-8"), digestmod=hashlib.sha1)
        sign = base64.b64encode(hmac_obj.digest())
        authorization = "API " + str(self.key_id) + ":" + sign.decode("utf-8")

        header = {
            "Content-MD5": content_md5,
            "Content-Type": content_type,
            "Date": date,
            "Authorization": authorization,
        }
        return header

    @property
    def inverter_id(self):
        body = self.get_body(stationId=self.plant_id)
        header = self.header(body, self.URLS["inverterList"])
        response = requests.post(self.URLS["root"] + self.URLS["inverterList"], data=body, headers=header)
        if response.status_code == HTTPStatus.OK:
            return response.json()["data"]["page"]["records"][0].get("id", "")

    @property
    def inverter_sn(self):
        body = self.get_body(stationId=self.plant_id)
        header = self.header(body, self.URLS["inverterList"])
        response = requests.post(self.URLS["root"] + self.URLS["inverterList"], data=body, headers=header)
        if response.status_code == HTTPStatus.OK:
            return response.json()["data"]["page"]["records"][0].get("sn", "")

    @property
    def inverter_details(self):
        body = self.get_body(id=self.inverter_id, sn=self.inverter_sn)
        header = self.header(body, self.URLS["inverterDetail"])
        response = requests.post(self.URLS["root"] + self.URLS["inverterDetail"], data=body, headers=header)

        if response.status_code == HTTPStatus.OK:
            return response.json()["data"]
        else:
            return {"state": 0}

    @property
    def is_online(self):
        return self.inverter_details["state"] == 1

    @property
    def last_seen(self):
        return pd.to_datetime(int(self.inverter_details["dataTimestamp"]), unit="ms")

    def read_code(self, cid):
        retries = 0
        data = "ERROR"
        while (data == "ERROR") and (retries < self.MAX_RETRIES):
            if self.token == "":
                self.login()
            body = self.get_body(inverterSn=self.inverter_sn, cid=cid)
            headers = self.header(body, self.URLS["atRead"])
            headers["token"] = self.token
            response = requests.post(self.URLS["root"] + self.URLS["atRead"], data=body, headers=headers)
            if response.status_code == HTTPStatus.OK:
                data = response.json()["data"]["msg"]
            else:
                data = "ERROR"

            if data == "ERROR":
                self.token = ""
                retries += 1
            else:
                return data

    def set_code(self, cid, value):
        if self.token == "":
            self.login()

        if self.token != "":
            body = self.get_body(inverterSn=self.inverter_sn, cid=cid, value=value)
            headers = self.header(body, self.URLS["control"])
            headers["token"] = self.token
            response = requests.post(self.URLS["root"] + self.URLS["control"], data=body, headers=headers)
            if response.status_code == HTTPStatus.OK:
                return response.json()

    def login(self):
        body = self.get_body(username=self.username, password=self.md5password)
        header = self.header(body, self.URLS["login"])
        response = requests.post(self.URLS["root"] + self.URLS["login"], data=body, headers=header)
        status = response.status_code
        if status == HTTPStatus.OK:
            result = response.json()
            self.token = result["csrfToken"]
            print("Logged in to SolisCloud OK")

        else:
            print(status)

    def read_mode_switch(self):
        bits = INVERTER_DEFS["SOLIS_CLOUD"]["bits"]
        code = int(self.read_code("636"))
        switches = {bit: (code & 2**i == 2**i) for i, bit in enumerate(bits)}
        return {"code": code, "switches": switches}

    def timed_status(self, tz="GB"):
        data = self.read_code("103").split(",")
        return {
            "charge": {
                "current": float(data[0]),
                "start": pd.Timestamp(data[2].split("-")[0], tz=tz),
                "end": pd.Timestamp(data[2].split("-")[1], tz=tz),
            },
            "discharge": {
                "current": float(data[1]),
                "start": pd.Timestamp(data[3].split("-")[0], tz=tz),
                "end": pd.Timestamp(data[3].split("-")[1], tz=tz),
            },
        }

    def read_backup_mode_soc(self):
        return int(self.read_code("157"))

    def set_mode_switch(self, code):
        return self.set_code("636", code)

    def get_time_string(self, time_status):
        time_string = ",".join(
            [
                str(int(time_status["charge"]["current"])),
                str(int(time_status["discharge"]["current"])),
                f'{time_status["charge"]["start"].strftime("%H:%M")}-{time_status["charge"]["end"].strftime("%H:%M")}',
                f'{time_status["discharge"]["start"].strftime("%H:%M")}-{time_status["discharge"]["end"].strftime("%H:%M")}',
            ]
        )
        return f"{time_string},0,0,00:00-00:00,00:00-00:00,0,0,00:00-00:00,00:00-00:00"

    def set_timer(self, direction, start, end, current):
        current_times = self.timed_status()
        new_times = current_times.copy()
        if start is not None:
            new_times[direction]["start"] = start
        if end is not None:
            new_times[direction]["end"] = end
        new_times[direction]["current"] = current
        current_time_string = self.read_code(103)
        new_time_string = self.get_time_string(new_times)
        if new_time_string != current_time_string:
            return self.set_code("103", new_time_string)
        else:
            return {"code": -1}


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
                elif isinstance(defs[item], list):
                    conf[item] = [z.replace("{device_name}", self.host.device_name) for z in defs[item]]
                else:
                    conf[item] = defs[item]
        if self.type == "SOLIS_CLOUD":
            params = {
                item: host.args.get(f"soliscloud_{item}")
                for item in ["username", "password", "key_id", "key_secret", "plant_id"]
            }
            if all([x is not None for x in params.values()]):
                self.cloud = SolisCloud(**params, log=self.log)
            else:
                raise Exception("Unable to create Solis Cloud controller")

    def is_online(self):
        if self.type == "SOLIS_CLOUD":
            return self.cloud.is_online
        else:
            entity_id = INVERTER_DEFS[self.type].get("online", (None, None))
            if entity_id is not None:
                entity_id = entity_id.replace("{device_name}", self.host.device_name)
                return self.host.get_state_retry(entity_id) not in ["unknown", "unavailable"]
            else:
                return True

    def enable_timed_mode(self):
        if self.type in ["SOLIS_SOLAX_MODBUS", "SOLIS_CORE_MODBUS", "SOLIS_SOLARMAN", "SOLIS_CLOUD"]:
            self._solis_set_mode_switch(SelfUse=True, Timed=True, GridCharge=True, Backup=False)
        else:
            self._unknown_inverter()

    def control_charge(self, enable, **kwargs):
        if enable:
            self.enable_timed_mode()
        self._control_charge_discharge("charge", enable, **kwargs)

    def control_discharge(self, enable, **kwargs):
        if enable:
            self.enable_timed_mode()
        self._control_charge_discharge("discharge", enable, **kwargs)

    def hold_soc(self, enable, soc=None, **kwargs):
        if self.type in ["SOLIS_SOLAX_MODBUS", "SOLIS_CORE_MODBUS", "SOLIS_SOLARMAN", "SOLIS_CLOUD"]:
            start = kwargs.get("start", pd.Timestamp.now(tz=self.tz).floor("1min"))
            end = kwargs.get("end", pd.Timestamp.now(tz=self.tz).ceil("30min"))
            self._solis_control_charge_discharge(
                "charge",
                enable=enable,
                start=start,
                end=end,
                power=0,
            )
        else:
            self._unknown_inverter()

    def _unknown_inverter(self):
        e = f"Unknown inverter type {self.type}"
        self.log(e, level="ERROR")
        self.host.status(e)
        raise Exception(e)

    def hold_soc_old(self, enable, soc=None):
        if self.type == "SOLIS_SOLAX_MODBUS" or self.type == "SOLIS_CORE_MODBUS" or self.type == "SOLIS_SOLARMAN":

            if enable:
                self._solis_set_mode_switch(SelfUse=True, Timed=False, GridCharge=True, Backup=True)
            else:
                self.enable_timed_mode()

            # Wait for a second to make sure the mode is correct
            time.sleep(1)

            if soc is None:
                soc = self.host.get_config("maximum_dod_percent")

            entity_id = self.host.config["id_backup_mode_soc"]

            self.log(f"Setting Backup SOC to {soc}%")
            if self.type == "SOLIS_SOLAX_MODBUS":
                changed, written = self.host.write_and_poll_value(entity_id=entity_id, value=soc)
            elif self.type == "SOLIS_CORE_MODBUS" or self.type == "SOLIS_SOLARMAN":
                changed, written = self.solis_write_holding_register(
                    address=INVERTER_DEFS(self.type)["registers"]["backup_mode_soc"],
                    value=soc,
                    entity_id=entity_id,
                )
        elif self.type == "SOLIS_CLOUD":
            pass
        else:
            self._unknown_inverter()

    @property
    def status(self):
        status = None
        if self.type in ["SOLIS_SOLAX_MODBUS", "SOLIS_CORE_MODBUS", "SOLIS_SOLARMAN", "SOLIS_CLOUD"]:
            status = self._solis_state()
        return status

    def _monitor_target_soc(self, target_soc, mode="charge"):
        pass

    def _control_charge_discharge(self, direction, enable, **kwargs):
        if self.type in ["SOLIS_SOLAX_MODBUS", "SOLIS_CORE_MODBUS", "SOLIS_SOLARMAN", "SOLIS_CLOUD"]:
            self._solis_control_charge_discharge(direction, enable, **kwargs)

    def _solis_control_charge_discharge(self, direction, enable, **kwargs):
        status = self._solis_state()

        times = {
            "start": kwargs.get("start", None),
            "end": kwargs.get("end", None),
        }
        power = kwargs.get("power", 0)

        if times["start"] is not None:
            times["start"] = times["start"].floor("1min")

        if not enable:
            self.log(f"Disabling inverter timed {direction}")

        else:
            self.log(f"Updating inverter {direction} control:")
            for x in kwargs:
                self.log(f"  {x}: {kwargs[x]}")

        # Disable by setting the times the same
        if (enable is not None) and (not enable):
            times["start"] = status[direction]["start"]
            times["end"] = times["start"]

        # Don't span midnight
        if times["end"] is not None:
            if times["start"] is None:
                start_day = pd.Timestamp.now().day
            else:
                start_day = times["start"].day

            if start_day != times["end"].day:
                times["end"] = times["end"].normalize() - pd.Timedelta(1, "minutes")
                self.log(f"End time clipped to {times['end'].strftime(TIMEFORMAT)}")

        write_flag = True
        value_changed = False

        if self.type in ["SOLIS_SOLAX_MODBUS", "SOLIS_SOLARMAN", "SOLIS_CORE_MODBUS"]:
            for limit in times:
                if times[limit] is not None:
                    for unit in ["hours", "minutes"]:
                        entity_id = self.host.config[f"id_timed_{direction}_{limit}_{unit}"]
                        if unit == "hours":
                            value = times[limit].hour
                        else:
                            value = times[limit].minute

                        if self.type == "SOLIS_SOLAX_MODBUS":
                            changed, written = self.host.write_and_poll_value(
                                entity_id=entity_id, value=value, verbose=True
                            )
                        elif self.type == "SOLIS_CORE_MODBUS" or self.type == "SOLIS_SOLARMAN":
                            changed, written = self._solis_write_time_register(direction, limit, unit, value)

                        else:
                            e = "Unknown inverter type"
                            self.log(e, level="ERROR")
                            raise Exception(e)

                        if changed:
                            if written:
                                self.log(f"Wrote {direction} {limit} {unit} of {value} to inverter")
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
                    try:
                        time_pressed = pd.Timestamp(self.host.get_state_retry(entity_id))

                        dt = (pd.Timestamp.now(self.host.tz) - time_pressed).total_seconds()
                        if dt < 10:
                            self.log(f"Successfully pressed button {entity_id}")

                        else:
                            self.log(
                                f"Failed to press button {entity_id}. Last pressed at {time_pressed.strftime(TIMEFORMAT)} ({dt:0.2f} seconds ago)"
                            )
                    except:
                        self.log(f"Failed to press button {entity_id}: it appears to never have been pressed.")

            else:
                self.log("Inverter already at correct time settings")

            if power is not None:
                entity_id = self.host.config[f"id_timed_{direction}_current"]

                current = abs(round(power / self.host.get_config("battery_voltage"), 1))
                current = min(current, self.host.get_config("battery_current_limit_amps"))
                self.log(f"Power {power:0.0f} = {current:0.1f}A at {self.host.get_config('battery_voltage')}V")
                if self.type == "SOLIS_SOLAX_MODBUS":
                    changed, written = self.host.write_and_poll_value(entity_id=entity_id, value=current, tolerance=1)
                elif self.type == "SOLIS_CORE_MODBUS" or self.type == "SOLIS_SOLARMAN":
                    changed, written = self._solis_write_current_register(direction, current, tolerance=1)
                else:
                    e = "Unknown inverter type"
                    self.log(e, level="ERROR")
                    raise Exception(e)

                if changed:
                    if written:
                        self.log(f"Current {current}A written to inverter")
                    else:
                        self.log(f"Failed to write {current} to inverter")
                else:
                    self.log("Inverter already at correct current")

        elif self.type == "SOLIS_CLOUD":
            current = abs(round(power / self.host.get_config("battery_voltage"), 0))
            current = min(current, self.host.get_config("battery_current_limit_amps"))
            self.log(f"Power {power:0.0f} = {current:0.0f}A at {self.host.get_config('battery_voltage')}V")
            response = self.cloud.set_timer(direction, times["start"], times["end"], current)
            if response["code"] == -1:
                self.log("Inverter already at correct time and current settings")
            elif response["code"] == 0:
                self.log(
                    f"Wrote {direction} time of {times['start'].strftime('%H:%M')}-{times['end'].strftime('%H:%M')} to inverter"
                )
                self.log(f"Current {current}A written to inverter")

    def _solis_set_mode_switch(self, **kwargs):
        # Read the mode switch
        if self.type == "SOLIS_SOLAX_MODBUS" or self.type == "SOLIS_SOLARMAN":
            status = self._solis_solax_solarman_mode_switch()

        elif self.type == "SOLIS_CORE_MODBUS":
            status = self._solis_core_mode_switch()

        elif self.type == "SOLIS_CLOUD":
            status = self.cloud.read_mode_switch()

        switches = status["switches"]
        if self.host.debug:
            self.log(f">>> kwargs: {kwargs}")
            self.log(">>> Solis switch status:")

        for switch in switches:
            if switch in kwargs:
                if self.host.debug:
                    self.log(f">>> {switch}: {kwargs[switch]}")
                switches[switch] = kwargs[switch]

        # Set the mode switch
        bits = INVERTER_DEFS[self.type]["bits"]
        bin_list = [2**i * switches[bit] for i, bit in enumerate(bits)]
        code = sum(bin_list)

        if self.type != "SOLIS_CLOUD":
            entity_id = self.host.config["id_inverter_mode"]

        if self.type == "SOLIS_SOLAX_MODBUS":
            entity_modes = self.host.get_state_retry(entity_id, attribute="options")
            modes = {INVERTER_DEFS[self.type]["codes"].get(mode): mode for mode in entity_modes}
            # mode = INVERTER_DEFS[self.type]["modes"].get(code)
            mode = modes.get(code)
            if self.host.debug:
                self.log(f">>> Inverter Code: {code}")
                self.log(f">>> Entity modes: {entity_modes}")
                self.log(f">>> Modes: {modes}")
                self.log(f">>> Inverter Mode: {mode}")

            self.host.set_select("inverter_mode", mode)

        elif self.type == "SOLIS_CORE_MODBUS" or self.type == "SOLIS_SOLARMAN":
            address = INVERTER_DEFS[self.type]["registers"]["storage_control_switch"]
            self._solis_write_holding_register(address=address, value=code, entity_id=entity_id)

        elif self.type == "SOLIS_CLOUD":
            self.cloud.set_mode_switch(code)

    def _solis_solax_solarman_mode_switch(self):
        inverter_mode = self.host.get_state_retry(entity_id=self.host.config["id_inverter_mode"])
        if self.type == "SOLIS_SOLAX_MODBUS":
            code = INVERTER_DEFS[self.type]["codes"][inverter_mode]
        else:
            modes = INVERTER_DEFS[self.type]["modes"]
            code = {modes[m]: m for m in modes}[inverter_mode]
        if self.host.debug:
            self.log(f">>> Inverter Mode: {inverter_mode}")
            self.log(f">>> Inverter Code: {code}")

        bits = INVERTER_DEFS[self.type]["bits"]
        switches = {bit: (code & 2**i == 2**i) for i, bit in enumerate(bits)}
        return {"mode": inverter_mode, "code": code, "switches": switches}

    def _solis_core_mode_switch(self):
        bits = INVERTER_DEFS["SOLIS_CORE_MODBUS"]["bits"]
        code = int(self.host.get_state_retry(entity_id=self.host.config["id_inverter_mode"]))
        switches = {bit: (code & 2**i == 2**i) for i, bit in enumerate(bits)}
        return {"code": code, "switches": switches}

    def _solis_state(self):
        limits = ["start", "end"]

        if self.type == "SOLIS_SOLAX_MODBUS" or self.type == "SOLIS_SOLARMAN":
            status = self._solis_solax_solarman_mode_switch()
        elif self.type == "SOLIS_CORE_MODBUS":
            status = self._solis_core_mode_switch()
        elif self.type == "SOLIS_CLOUD":
            status = self.cloud.read_mode_switch()

        if self.type in ["SOLIS_SOLAX_MODBUS", "SOLIS_SOLARMAN", "SOLIS_CORE_MODBUS"]:
            for direction in ["charge", "discharge"]:
                status[direction] = {
                    "current": 0,
                    "start": pd.Timestamp("00:00", tz=self.tz),
                    "end": pd.Timestamp("00:00", tz=self.tz),
                }
                for limit in limits:
                    states = {}
                    for unit in ["hours", "minutes"]:
                        entity_id = self.host.config[f"id_timed_{direction}_{limit}_{unit}"]
                        states[unit] = int(float(self.host.get_state_retry(entity_id=entity_id)))
                    status[direction][limit] = pd.Timestamp(
                        f"{states['hours']:02d}:{states['minutes']:02d}", tz=self.host.tz
                    )

            status[direction]["current"] = float(
                self.host.get_state_retry(self.host.config[f"id_timed_{direction}_current"])
            )

        elif self.type == "SOLIS_CLOUD":
            status = status | self.cloud.timed_status(tz=self.host.tz)

        time_now = pd.Timestamp.now(tz=self.tz)
        for direction in ["charge", "discharge"]:
            status[direction]["active"] = (
                time_now >= status[direction]["start"]
                and time_now < status[direction]["end"]
                and status[direction].get("current", 0) > 0
                and status["switches"].get("Timed", False)
                and status["switches"].get("GridCharge", False)
            )

        status["hold_soc"] = {"active": status["switches"]["Backup"]}
        if self.type == "SOLIS_SOLAX_MODBUS" or self.type == "SOLIS_CORE_MODBUS":
            status["hold_soc"]["soc"] = self.host.get_config("id_backup_mode_soc")
        elif self.type == "SOLIS_CLOUD":
            status["hold_soc"]["soc"] = self.cloud.read_backup_mode_soc()
        else:
            status["hold_soc"]["soc"] = None

        return status

    def _solis_write_holding_register(
        self,
        address,
        value,
        entity_id=None,
        tolerance=0,
        multiplier=1,
    ):
        changed = True
        written = False
        if self.type == "SOLIS_CORE_MODBUS":
            hub = self.host.get_config("modbus_hub")
            slave = self.host.get_config("modbus_slave")

            if entity_id is not None:
                old_value = int(float(self.host.get_state_retry(entity_id=entity_id)))
                if isinstance(old_value, int) and abs(old_value - value) <= tolerance:
                    self.log(f"Inverter value already set to {value}.")
                    changed = False

            if changed:
                data = {
                    "address": address,
                    "slave": slave,
                    "value": int(round(value * multiplier, 0)),
                    "hub": hub,
                }
                self.host.call_service("modbus/write_register", **data)
                written = True

        elif self.type == "SOLIS_SOLARMAN":
            if entity_id is not None and self.host.entity_exists(entity_id):
                old_value = int(float(self.host.get_state_retry(entity_id=entity_id)))
                if isinstance(old_value, int) and abs(old_value - value) <= tolerance:
                    self.log(f"Inverter value already set to {value}.")
                    changed = False

            if changed:
                data = {"register": address, "value": value}
                # self.host.call_service("solarman/write_holding_register", **data)
                self.log(">>> Writing {value} to inverter register {address} using Solarman")
                written = True

        return changed, written

    def _solis_write_current_register(self, direction, current, tolerance):
        address = INVERTER_DEFS[self.type]["registers"][f"timed_{direction}_current"]
        entity_id = self.host.config[f"id_timed_{direction}_current"]
        return self._solis_write_holding_register(
            address=address,
            value=round(current, 1),
            entity_id=entity_id,
            tolerance=tolerance,
            multiplier=10,
        )

    def _solis_write_time_register(self, direction, limit, unit, value):
        address = INVERTER_DEFS[self.type]["registers"][f"timed_{direction}_{limit}_{unit}"]
        entity_id = self.host.config[f"id_timed_{direction}_{limit}_{unit}"]

        return self._solis_write_holding_register(address=address, value=value, entity_id=entity_id)

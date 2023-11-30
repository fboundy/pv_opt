# %%
import appdaemon.plugins.hass.hassapi as hass
import appdaemon.adbase as ad
import appdaemon.plugins.mqtt.mqttapi as mqtt
from json import dumps

# import mqttapi as mqtt
import pandas as pd
import time

# import requests
# import datetime
import pvpy as pv
import inverters as inv
import numpy as np
from numpy import nan


# import pvpy as pv
OCTOPUS_PRODUCT_URL = r"https://api.octopus.energy/v1/products/"

# %%
#
PV_MULT = 1.0
USE_TARIFF = True

VERSION = "3.0.1"

DATE_TIME_FORMAT_LONG = "%Y-%m-%d %H:%M:%S%z"
DATE_TIME_FORMAT_SHORT = "%d-%b %H:%M"
TIME_FORMAT = "%H:%M"


EVENT_TRIGGER = "PV_OPT"
DEBUG_TRIGGER = "PV_DEBUG"

OUTPUT_START_ENTITY = "sensor.solaropt_charge_start"
OUTPUT_END_ENTITY = "sensor.solaropt_charge_end"
OUTPUT_CURRENT_ENTITY = "sensor.solaropt_charge_current"

OUTPUT_COST_ENTITY = "sensor.pvopt_base_cost"
OUTPUT_BASE_COST_ENTITY = "sensor.solaropt_base_cost"
OUTPUT_OPT_COST_ENTITY = "sensor.solaropt_optimised_cost"
OUTPUT_ALT_OPT_ENTITY = "sensor.solaropt_alt"

BOTTLECAP_DAVE = {
    "domain": "event",
    "tariff_code": "tariff_code",
    "rates": "current_day_rates",
}

INVERTER_TYPES = ["SOLIS_SOLAX_MODBUS", "SOLIS_CORE_MODBUS"]

IMPEXP = ["import", "export"]

MQTT_CONFIGS = {
    "switch": {
        "payload_on": "ON",
        "payload_off": "OFF",
        "state_on": "ON",
        "state_off": "OFF",
    },
}

DEFAULT_CONFIG = {
    "forced_charge": {"default": True, "domain": "switch"},
    "forced_discharge": {"default": False, "domain": "switch"},
    "read_only": {"default": False, "domain": "switch"},
    "optimise_frequency_minutes": {
        "default": 10,
        "attributes": {
            "min": 5,
            "max": 60,
            "step": 5,
        },
        "domain": "number",
    },
    "manual_tariff": {"default": False, "domain": "switch"},
    "octopus_auto": {"default": True, "domain": "switch"},
    "solcast_integration": {"default": True, "domain": "switch"},
    "battery_capacity_Wh": {
        "default": 10000,
        "domain": "number",
        "attributes": {
            "min": 2000,
            "max": 20000,
            "step": 100,
            "unit_of_measurement": "Wh",
            "device_class": "energy",
        },
    },
    "inverter_efficiency_percent": {
        "default": 97,
        "domain": "number",
        "attributes": {"min": 90, "max": 100, "step": 1, "unit_of_measurement": "%"},
    },
    "charger_efficiency_percent": {
        "default": 91,
        "domain": "number",
        "attributes": {"min": 80, "max": 100, "step": 1, "unit_of_measurement": "%"},
    },
    "charger_power_watts": {
        "default": 3000,
        "domain": "number",
        "attributes": {
            "min": 1000,
            "max": 10000,
            "step": 100,
            "unit_of_measurement": "W",
            "device_class": "power",
        },
    },
    "inverter_power_watts": {
        "default": 3600,
        "domain": "number",
        "attributes": {
            "min": 1000,
            "max": 10000,
            "step": 100,
            "unit_of_measurement": "W",
            "device_class": "power",
        },
    },
    "inverter_loss_watts": {
        "default": 100,
        "domain": "number",
        "attributes": {
            "min": 0,
            "max": 300,
            "step": 10,
            "unit_of_measurement": "W",
            "device_class": "power",
        },
    },
    "battery_voltage": {
        "default": 52,
        "domain": "number",
        "attributes": {
            "min": 48,
            "max": 55,
            "step": 1,
            "unit_of_measurement": "V",
            "device_class": "voltage",
        },
    },
    "solar_forecast": {
        "default": "Solcast",
        "attributes": {"options": ["Solcast", "Solcast_p10", "Solcast_p90"]},
        "domain": "select",
    },
    "consumption_from_entity": {"default": True},
    "consumption_history_days": {
        "default": 7,
        "domain": "number",
        "attributes": {"min": 1, "max": 28, "step": 1},
    },
    "consumption_margin": {
        "default": 10,
        "domain": "number",
        "attributes": {"min": 0, "max": 100, "step": 5, "unit_of_measurement": "%"},
    },
    "consumption_grouping": {
        "default": "mean",
        "domain": "select",
        "attributes": {"options": ["mean", "median", "max"]},
    },
    "alt_tariffs": {"default": [], "domain": "input_select"},
    "id_solcast_today": {"default": "sensor.solcast_pv_forecast_forecast_today"},
    "id_solcast_tomorrow": {"default": "sensor.solcast_pv_forecast_forecast_tomorrow"},
}

DEFAULT_CONFIG_BY_BRAND = {
    "SOLIS_SOLAX_MODBUS": {
        "maximum_dod_percentage": {"default": "number.solis_battery_minimum_soc"},
        "id_battery_soc": {"default": "sensor.solis_battery_soc"},
        "id_consumption": {"default": "sensor.solis_house_load"},
        "id_timed_charge_start_hours": {
            "default": "numbers.solis_timed_charge_start_hours"
        },
        "id_timed_charge_start_minutes": {
            "default": "number.solis_timed_charge_start_minutes"
        },
        "id_timed_charge_end_hours": {
            "default": "number.solis_timed_charge_end_hours",
        },
        "id_timed_charge_end_minutes": {
            "default": "number.solis_timed_charge_end_minutes"
        },
        "id_timed_charge_current": {"default": "number.solis_timed_charge_current"},
        "id_timed_discharge_start_hours": {
            "default": "number.solis_timed_discharge_start_hours"
        },
        "id_timed_discharge_start_minutes": {
            "default": "number.solis_timed_discharge_start_minutes"
        },
        "id_timed_discharge_end_hours": {
            "default": "number.solis_timed_discharge_end_hours",
        },
        "id_timed_discharge_end_minutes": {
            "default": "number.solis_timed_discharge_end_minutes"
        },
        "id_timed_discharge_current": {
            "default": "number.solis_timed_discharge_current"
        },
        "id_timed_charge_discharge_button": {
            "default": "button.solis_update_charge_discharge_times"
        },
        "id_inverter_mode": {"default": "select.solis_energy_storage_control_switch"},
    }
}


class PVOpt(hass.Hass):
    def hass2df(self, entity_id, days=2, log=False):
        hist = self.get_history(entity_id=entity_id, days=days)
        if log:
            self.log(hist)
        df = pd.DataFrame(hist[0]).set_index("last_updated")["state"]
        df.index = pd.to_datetime(df.index, format="ISO8601")
        df = df.sort_index()
        df = df[df != "unavailable"]
        df = df[df != "unknown"]
        return df

    def initialize(self):
        self.debug = False
        self.config = {}
        self.log("")
        self.log(f"******************* PV Opt v{VERSION} *******************")
        self.log("")
        self.adapi = self.get_ad_api()
        self.log(f"Time Zone Offset: {self.get_tz_offset()} minutes")
        self.change_items = {}
        self.cum_delta = {}
        self.timer_handle = None
        self.inverter_type = "SOLIS_SOLAX_MODBUS"
        self.charging = False
        self.handles = {}
        self.mqtt = self.get_plugin_api("MQTT")
        self.saving_events = {}
        self.contract = None

        # payloa

        self._load_args()

        self._load_inverter()

        self._status("Initialising PV Model")
        self.inverter_model = pv.InverterModel(
            inverter_efficiency=self.config["inverter_efficiency_percent"] / 100,
            inverter_power=self.config["inverter_power_watts"],
            inverter_loss=self.config["inverter_loss_watts"],
            charger_efficiency=self.config["charger_efficiency_percent"] / 100,
            charger_power=self.config["charger_power_watts"],
        )
        self.battery_model = pv.BatteryModel(
            capacity=self.config["battery_capacity_Wh"],
            max_dod=self.config["maximum_dod_percent"] / 100,
        )
        self.pv_system = pv.PVsystemModel(
            "PV_Opt", self.inverter_model, self.battery_model, host=self
        )

        self._load_contract()

        if self.agile:
            self._setup_agile_schedule()

        # Optimise on an EVENT trigger:
        self.listen_event(
            self.optimise_event,
            EVENT_TRIGGER,
        )
        if self.config["forced_charge"]:
            self.log("")
            self.log("Running initial Optimisation:")
            self.optimise()
            self._setup_schedule()

        if self.debug:
            self.log(f"PV Opt Initialisation complete. Listen_state Handles:")
            for id in self.handles:
                self.log(
                    f"  {id} {self.handles[id]}  {self.info_listen_state(self.handles[id])}"
                )
        self._status("Idle")

    def _load_inverter(self):
        self.inverter = inv.InverterController(
            inverter_type=self.inverter_type, host=self
        )

    def _setup_agile_schedule(self):
        # start = (pd.Timestamp.now().round("1H") + pd.Timedelta("5T")).to_pydatetime()
        start = (pd.Timestamp.now() + pd.Timedelta("1T")).to_pydatetime()
        self.timer_handle = self.run_every(
            self._load_agile_cb,
            start=start,
            interval=3600,
        )

    @ad.app_lock
    def _load_agile_cb(self, cb_args):
        # reload if the time is after 16:00 and the last data we have is today

        if (
            self.contract.imp.end().day == pd.Timestamp.now().day
        ) and pd.Timestamp.now().hour > 16:
            self.log(
                f"Contract end day: {self.contract.imp.end().day} Today:{pd.Timestamp.now().day}"
            )
            self._load_contract()

    def _setup_schedule(self):
        if self.config["forced_charge"]:
            start_opt = (
                pd.Timestamp.now()
                .ceil(f"{self.config['optimise_frequency_minutes']}T")
                .to_pydatetime()
            )
            self.timer_handle = self.run_every(
                self.optimise_time,
                start=start_opt,
                interval=self.config["optimise_frequency_minutes"] * 60,
            )
            self.log(
                f"Optimiser will run every {self.config['optimise_frequency_minutes']} minutes from {start_opt.strftime('%H:%M')} or on {EVENT_TRIGGER} Event"
            )

        else:
            if self.timer_handle and self.timer_running(self.timer_handle):
                self.cancel_timer(self.timer_handle)
                self.log("Optimer Schedule Disabled")
                self._set_status("Disabled")

    def _load_contract(self):
        self.log("")
        self.log("Loading Contract:")
        self._status("Loading Contract")
        self.log("-----------------")
        self.tariff_codes = {}
        self.agile = False

        while self.contract is None:
            if self.config["octopus_auto"]:
                try:
                    self.log(f"Trying to auto detect Octopus tariffs:")

                    octopus_entities = [
                        name
                        for name in self.get_state(BOTTLECAP_DAVE["domain"]).keys()
                        if (
                            "octopus_energy_electricity" in name
                            and BOTTLECAP_DAVE["rates"] in name
                        )
                    ]

                    entities = {}
                    entities["import"] = [
                        x for x in octopus_entities if not "export" in x
                    ]
                    entities["export"] = [x for x in octopus_entities if "export" in x]

                    for imp_exp in IMPEXP:
                        for entity in entities[imp_exp]:
                            self.log(f"    Found {imp_exp} entity {entity}")

                    tariffs = {x: None for x in IMPEXP}
                    for imp_exp in IMPEXP:
                        if len(entities[imp_exp]) > 0:
                            tariff_code = self.get_state(
                                entities[imp_exp][0], attribute="all"
                            )["attributes"][BOTTLECAP_DAVE["tariff_code"]]

                            tariffs[imp_exp] = pv.Tariff(
                                tariff_code, export=(imp_exp == "export"), host=self
                            )
                            if "AGILE" in tariff_code:
                                self.agile = True

                    self.contract = pv.Contract(
                        "current",
                        imp=tariffs["import"],
                        exp=tariffs["export"],
                        host=self,
                    )
                    self.log("Contract tariffs loaded OK")

                except Exception as e:
                    self.log(f"{e.__traceback__.tb_lineno}: {e}", level="ERROR")
                    self.log(
                        "Failed to find tariff from Octopus Energy Integration",
                        level="WARNING",
                    )
                    self.contract = None

            if self.contract is None:
                if ("octopus_account" in self.config) and (
                    "octopus_api_key" in self.config
                ):
                    if (self.config["octopus_account"] is not None) and (
                        self.config["octopus_api_key"] is not None
                    ):
                        try:
                            self.log(
                                f"Trying to load tariffs using Account: {self.config['octopus_account']} API Key: {self.config['octopus_api_key']}"
                            )
                            self.octopus_account = pv.OctopusAccount(
                                self.config["octopus_account"],
                                self.config["octopus_api_key"],
                            )

                            self.contract = pv.Contract(
                                "current",
                                octopus_account=self.octopus_account,
                                host=self,
                            )

                            self.log(
                                "Tariffs loaded using Octopus Account details from API Key",
                                level="WARN",
                            )

                        except Exception as e:
                            self.log(e, level="ERROR")
                            self.log(
                                f"Unable to load Octopus Account details using API Key: {e} Trying other methods.",
                                level="WARNING",
                            )

            if self.contract is None or USE_TARIFF:
                if (
                    "octopus_import_tariff_code" in self.config
                    and self.config["octopus_import_tariff_code"] is not None
                ):
                    try:
                        str = f"INFO Trying to load tariff codes: Import: {self.config['octopus_import_tariff_code']}"

                        if "octopus_export_tariff_code" in self.config:
                            str += (
                                f" Export: {self.config['octopus_export_tariff_code']}"
                            )
                        self.log(str)

                        tariffs = {x: None for x in IMPEXP}
                        for imp_exp in IMPEXP:
                            if f"octopus_{imp_exp}_tariff_code" in self.config:
                                tariffs[imp_exp] = pv.Tariff(
                                    self.config[f"octopus_{imp_exp}_tariff_code"],
                                    export=(imp_exp == "export"),
                                    host=self,
                                )

                        self.contract = pv.Contract(
                            "current",
                            imp=tariffs["import"],
                            exp=tariffs["export"],
                            host=self,
                        )
                        self.log("Contract tariffs loaded OK from Tariff Codes")
                    except Exception as e:
                        self.log(f"Unable to load Tariff Codes {e}", level="ERROR")

            if self.contract is None:
                e = "Unable to load contract tariffs. Waiting 2 minutes to re-try"
                self.log(e, level="ERROR")
                self._status(e)
                time.sleep(120)

            else:
                for imp_exp, t in zip(IMPEXP, [self.contract.imp, self.contract.exp]):
                    self.log(f"  {imp_exp.title()}: {t.name}")
                    if "AGILE" in t.name:
                        self.agile = True

                if self.agile:
                    self.log("AGILE tariff detected. Rates will update at 16:00 daily")

                self.log("")

                self._load_saving_events()

    def _load_saving_events(self):
        if (
            len(
                [
                    name
                    for name in self.get_state("event").keys()
                    if ("octoplus_saving_session_events" in name)
                ]
            )
            > 0
        ):
            saving_events_entity = [
                name
                for name in self.get_state("event").keys()
                if ("octoplus_saving_session_events" in name)
            ][0]
            self.log("")
            self.log(f"Found Octopus Savings Events entity: {saving_events_entity}")

            available_events = self.get_state(saving_events_entity, attribute="all")[
                "attributes"
            ]["available_events"]

            if len(available_events) > 0:
                self.log("Joining the following new Octoplus Events:")
                for event in available_events:
                    if event["id"] not in self.saving_events:
                        self.saving_events[event["id"]] = event
                        self.log(
                            f"{event['id']:8d}: {pd.Timestamp(event['start']).strftime(DATE_TIME_FORMAT_SHORT)} - {pd.Timestamp(event['end']).strftime(DATE_TIME_FORMAT_SHORT)} at {int(event['octopoints_per_kwh'])/8:5.1f}p/kWh"
                        )
                        self.call_service(
                            "octopus_energy/join_octoplus_saving_session_event",
                            entity_id=saving_events_entity,
                            event_code=event["code"],
                        )

            joined_events = self.get_state(saving_events_entity, attribute="all")[
                "attributes"
            ]["joined_events"]

            for event in joined_events:
                if event["id"] not in self.saving_events:
                    self.saving_events[event["id"]] = event

        if len(self.saving_events) > 0:
            self.log("")
            self.log("The following Octopus Sevings Events have been Joined:")
            for id in self.saving_events:
                self.log(
                    f"{id:8d}: {pd.Timestamp(self.saving_events[id]['start']).strftime(DATE_TIME_FORMAT_SHORT)} - {pd.Timestamp(self.saving_events[id]['end']).strftime(DATE_TIME_FORMAT_SHORT)} at {int(self.saving_events[id]['octopoints_per_kwh'])/8:5.1f}p/kWh"
                )

    def get_ha_value(self, entity_id):
        value = None

        # if the entity doesn't exist return None
        if self.entity_exists(entity_id=entity_id):
            state = self.get_state(entity_id=entity_id)

            # if the state is None return None
            if state is not None:
                # if the state is 'on' or 'off' then it's a bool
                if state in ["on", "off"]:
                    value = state == "on"

                # see if we can coerce it into an int 1st and then a floar
                for t in [int, float]:
                    try:
                        value = t(state)
                    except:
                        pass

                # if none of the above return a string
                if value is None:
                    value = state

        return value

    def get_default_config(self, item):
        if item in DEFAULT_CONFIG:
            return DEFAULT_CONFIG[item]["default"]
        if item in DEFAULT_CONFIG_BY_BRAND[self.inverter_type]:
            return DEFAULT_CONFIG_BY_BRAND[self.inverter_type][item]["default"]
        else:
            return None

    def same_type(self, a, b):
        if type(a) != type(b):
            (isinstance(a, int) | isinstance(a, float)) & (
                isinstance(b, int) | isinstance(b, float)
            )
        else:
            return True

    def _load_args(self, items=None):
        if self.debug:
            self.log(self.args)

        self.prefix = self.args["prefix"]

        self._status("Loading Configuation")

        change_entities = []

        self.log("Reading arguments from YAML:")
        self.log("-----------------------------------")

        if items is None:
            items = [i for i in self.args if i not in ["module", "class", "prefix"]]

        for item in items:
            # Attempt to read entity states for all string paramters unless they start
            # with"entity_id":
            if not isinstance(self.args[item], list):
                self.args[item] = [self.args[item]]
            values = self.args[item]

            if values[0] is None:
                self.config[item] = self.get_default_config(item)
                self.log(
                    f"    {item:34s} = {str(self.config[item]):57s} Source: system default. Null entry found in YAML.",
                    level="WARNING",
                )
            # if the item starts with 'entitiy_id' then it must be an entity that exists:
            elif "id_" in item:
                if min([self.entity_exists(v) for v in values]):
                    if len(values) == 1:
                        self.config[item] = values[0]
                    else:
                        self.config[item] = values

                    # for v in values:
                    #     self.change_items[v] = item

                    self.log(
                        f"    {item:34s} = {str(self.config[item]):57s} Source: value(s) in YAML"
                    )

                elif self.entity_exists(self.get_default_config(item)):
                    self.config = self.get_default_config(item)
                    self.log(
                        f"    {item:34s} = {str(self.config[item]):57s} Source: system default. Entities listed in YAML {value} do not all exist in HA.",
                        level="ERROR",
                    )
                else:
                    e = f"    {item:34s} : Neither the entities listed in the YAML {values[0]} nor the system default of {self.get_default_config(item)} exist in HA."
                    self.log(e)
                    raise ValueError(e)

            else:
                if self.debug:
                    self.log(f"{item}:")
                    for value in self.args[item]:
                        self.log(f"\t{value}")

                arg_types = {
                    t: [isinstance(v, t) for v in values]
                    for t in [str, float, int, bool]
                }

                # check for validity. Valid formats are:
                #   - all strings: add the entitity values from HA (if the last string is
                #     not an entity then treat it as a default)
                #   - single number or single boolean: just use that
                #   - single number as last entry with any number of strings before that

                if (
                    len(values) == 1
                    and isinstance(values[0], str)
                    and (
                        pd.to_datetime(values[0], errors="ignore", format="%H:%M")
                        != values[0]
                    )
                ):
                    self.config[item] = values[0]
                    self.log(
                        f"    {item:34s} = {str(self.config[item]):57s} Source: value in YAML"
                    )

                elif min(arg_types[str]):
                    if self.debug:
                        self.log("\tFound a valid list of strings")

                    ha_values = [self.get_ha_value(entity_id=v) for v in values]
                    val_types = {
                        t: np.array([isinstance(v, t) for v in ha_values])
                        for t in [str, float, int, bool]
                    }
                    # if they are all float or int

                    valid_strings = [
                        j
                        for j in [h for h in zip(ha_values[:-1], values[:-1]) if h[0]]
                        if j[0] in DEFAULT_CONFIG[item]["options"]
                    ]

                    if np.min(val_types[int] | val_types[float]):
                        self.config[item] = sum(ha_values)
                        self.log(
                            f"    {item:34s} = {str(self.config[item]):57s} Source: HA entities listed in YAML"
                        )
                    # if any of list but the last one are strings and the default for the item is a string
                    # try getting values from all the entities
                    elif valid_strings:
                        self.config[item] = valid_strings[0][0]
                        if not "sensor" in valid_strings[0][1]:
                            self.change_items[valid_strings[0][1]] = item
                        self.log(
                            f"    {item:34s} = {str(self.config[item]):57s} Source: HA entities listed in YAML"
                        )

                    elif len(values) > 1:
                        if self.same_type(values[-1], self.get_default_config(item)):
                            self.config[item] = values[-1]
                            self.log(
                                f"    {item:34s} = {str(self.config[item]):57s} Source: YAML default. Unable to read from HA entities listed in YAML."
                            )

                        elif values[-1] in self.get_default_config(item):
                            self.log(values)
                            self.config[item] = values[-1]
                            self.log(
                                f"    {item:34s} = {str(self.config[item]):57s} Source: YAML default. Unable to read from HA entities listed in YAML."
                            )
                    else:
                        if item in DEFAULT_CONFIG:
                            self.config[item] = self.get_default_config(item)

                            self.log(
                                f"    {item:34s} = {str(self.config[item]):57s} Source: system default. Unable to read from HA entities listed in YAML. No default in YAML.",
                                level="WARNING",
                            )
                        elif item in DEFAULT_CONFIG_BY_BRAND[self.inverter_type]:
                            self.config[item] = self.get_default_config(item)

                            self.log(
                                f"    {item:34s} = {str(self.config[item]):57s} Source: inverter brand default. Unable to read from HA entities listed in YAML. No default in YAML.",
                                level="WARNING",
                            )
                        else:
                            self.config[item] = values[0]
                            self.log(
                                f"    {item:34s} = {str(self.config[item]):57s} Source: YAML default value. No default defined."
                            )

                elif len(values) == 1 and (
                    arg_types[bool][0] or arg_types[int][0] or arg_types[float][0]
                ):
                    if self.debug:
                        self.log("\tFound a single default value")

                    self.config[item] = values[0]
                    self.log(
                        f"    {item:34s} = {str(self.config[item]):57s} Source: value in YAML"
                    )

                elif (
                    len(values) > 1
                    and (min(arg_types[str][:-1]))
                    and (
                        arg_types[bool][-1]
                        or arg_types[int][-1]
                        or arg_types[float][-1]
                    )
                ):
                    if self.debug:
                        self.log(
                            "\tFound a valid list of strings followed by a single default value"
                        )
                    ha_values = [self.get_ha_value(entity_id=v) for v in values[:-1]]
                    val_types = {
                        t: np.array([isinstance(v, t) for v in ha_values])
                        for t in [str, float, int, bool]
                    }
                    # if they are all float or int
                    if np.min(val_types[int] | val_types[float]):
                        self.config[item] = sum(ha_values)
                        self.log(
                            f"    {item:34s} = {str(self.config[item]):57s} Source: HA entities listed in YAML"
                        )
                        # If these change then we need to trigger automatically
                        for v in values[:-1]:
                            if not "sensor" in v:
                                self.change_items[v] = item

                    else:
                        self.config[item] = values[-1]
                        self.log(
                            f"    {item:34s} = {str(self.config[item]):57s} Source: YAML default. Unable to read from HA entities listed in YAML."
                        )

                else:
                    self.config[item] = self.get_default_config(item)
                    self.log(
                        f"    {item:34s} = {str(self.config[item]):57s} Source: system default. Invalid arguments in YAML.",
                        level="ERROR",
                    )

        self.log("")
        self.log("Checking config:")
        self.log("-----------------------")
        items_not_defined = [i for i in DEFAULT_CONFIG if i not in self.config] + [
            i
            for i in DEFAULT_CONFIG_BY_BRAND[self.inverter_type]
            if i not in self.config
        ]
        if len(items_not_defined) > 0:
            for item in items_not_defined:
                self.config[item] = self.get_default_config(item)
                self.log(
                    f"    {item:34s} = {str(self.config[item]):57s} Source: system default. Not in YAML.",
                    level="WARNING",
                )
        else:
            self.log("All config items defined OK")

        self.log("")
        self.log("Exposing config to Home Assistant:")
        self.log("----------------------------------")
        self._expose_configs()

        if self.change_items:
            self.log("")
            self.log("State change entities:")
            self.log("----------------------")
            for entity_id in self.change_items:
                if not "sensor" in entity_id:
                    self.log(
                        f"           {entity_id:>50s} -> {self.change_items[entity_id]:40s}"
                    )
                    self.handles[entity_id] = self.listen_state(
                        callback=self.optimise_state_change, entity_id=entity_id
                    )
                    self.cum_delta[entity_id] = 0

        if "manual_tz" in self.config:
            self.tz = self.params["manual_tz"]
        else:
            self.tz = "GB"

        self.log(f"Local timezone set to {self.tz}")

    def _name_from_item(self, item):
        name = item.replace("_", " ")
        for word in name.split():
            name = name.replace(word, word.title())
        return f"{self.prefix} {name}"

    def _state_from_value(self, value):
        if isinstance(value, bool):
            state = f"{value*'on'}{(1-value)*'off'}"
        else:
            state = value
        return state

    def _expose_configs(self):
        for defaults in [DEFAULT_CONFIG, DEFAULT_CONFIG_BY_BRAND[self.inverter_type]]:
            untracked_items = [
                item
                for item in defaults
                if (
                    item
                    not in [self.change_items[entity] for entity in self.change_items]
                )
                and ("id_" not in item)
                and ("alt_" not in item)
                and "domain" in defaults[item]
            ]
            for item in untracked_items:
                domain = defaults[item]["domain"]
                id = f"{self.prefix.lower()}_{item}"
                entity_id = f"{domain}.{id}"

                if not self.entity_exists(entity_id=entity_id):
                    self.log(
                        f"Creating HA Entity {entity_id} for {item} using MQTT Discovery"
                    )
                    conf = {
                        "state_topic": f"homeassistant/{domain}/{id}/state",
                        "command_topic": f"homeassistant/{domain}/{id}/set",
                        "name": self._name_from_item(item),
                        "optimistic": True,
                    }

                    if "attributes" in defaults[item]:
                        conf = conf | defaults[item]["attributes"]

                    if domain in MQTT_CONFIGS:
                        conf = conf | MQTT_CONFIGS[domain]

                    conf_topic = f"homeassistant/{domain}/{id}/config"
                    self.mqtt.mqtt_publish(conf_topic, dumps(conf), retain=True)

                self.set_state(
                    state=self._state_from_value(self.config[item]),
                    entity_id=entity_id,
                )
                if domain != "sensor":
                    self.change_items[entity_id] = item

    def _status(self, status):
        entity_id = f"sensor.{self.prefix.lower()}_status"
        attributes = {
            "last_updated": pd.Timestamp.now().strftime(DATE_TIME_FORMAT_LONG)
        }
        self.set_state(state=status, entity_id=entity_id, attributes=attributes)

    @ad.app_lock
    def optimise_state_change(self, entity_id, attribute, old, new, kwargs):
        item = self.change_items[entity_id]
        self.log(
            f"State change detected for {entity_id} [config item: {item}] from {old} to {new}:"
        )
        delta = None
        value = None
        if (
            "attributes" in DEFAULT_CONFIG[item]
            and "step" in DEFAULT_CONFIG[item]["attributes"]
        ):
            delta = DEFAULT_CONFIG[item]["attributes"]["step"]
        try:
            self.cum_delta[entity_id] += float(new) - float(old)
            if self.cum_delta[entity_id] >= delta:
                self.log(
                    f"Entity {entity_id} changed from {old} to {new}. Cumulative{self.cum_delta[entity_id]} vs {delta}"
                )
                value = self._value_from_state(new)
                self.cum_delta[entity_id] = 0
        except:
            self.log(f"Entity {entity_id} changed from {old} to {new}. ")
            value = self._value_from_state(new)

        if value is not None:
            self.log(f"State resolved to {value} [with type{type(value)}")
            self.config[item] = value

        if "forced" in item:
            self._setup_schedule()
        else:
            self.optimise()

    def _value_from_state(self, state):
        value = None
        try:
            value = int(state)
        except:
            pass

        if value is None:
            try:
                value = float(state)
            except:
                pass

        if value is None:
            if state in ["on", "off"]:
                value = state == "on"

        if value is None:
            time_value = pd.to_datetime(state, errors="ignore", format="%H:%M")
            if time_value != state:
                value = state

        if value is None:
            value = state

        return value

    @ad.app_lock
    def optimise_event(self, event_name, data, kwargs):
        self.log(f"Optimiser triggered by {event_name}")
        self.optimise()

    @ad.app_lock
    def optimise_time(self, cb_args):
        self.log(f"Optimser triggered by Scheduler ")
        self.optimise()

    @ad.app_lock
    def optimise(self):
        # initialse a DataFrame to cover today and tomorrow at 30 minute frequency
        self.log("")

        if self.config["forced_discharge"]:
            discharge_enable = "enabled"
        else:
            discharge_enable = "disabled"
        self.log(f"Starting Opimisation with discharge {discharge_enable}")
        self.log(
            f"-------------------------------------------{len(discharge_enable)*'-'}"
        )
        self.t0 = pd.Timestamp.now()
        self.static = pd.DataFrame(
            index=pd.date_range(
                pd.Timestamp.utcnow().normalize(),
                pd.Timestamp.utcnow().normalize() + pd.Timedelta(days=2),
                freq="30T",
                inclusive="left",
            ),
        )

        # Load Solcast
        self.load_solcast()
        self.load_consumption()

        # try:
        #     if not self.load_consumption():
        #         raise Exception

        # except Exception as e:
        #     self.log(f"Unable to load estimated consumption: {e}", level="ERROR")
        #     self._status("Failed to load consumption")
        #     return False

        self.time_now = pd.Timestamp.utcnow()
        self.static = self.static[self.time_now.floor("30T") :].fillna(0)
        self.soc_now = float(self.get_state(self.config["id_battery_soc"]))

        # if self.config["alt_tariffs"] is None:
        #     self.tariffs = [None]
        # else:
        #     self.tariffs = self.config["alt_tariffs"] + [None]

        x = self.hass2df(
            self.config["id_battery_soc"],
            days=1,
        ).astype(float)
        x = x.loc[x.loc[: self.static.index[0]].index[-1] :]
        x = pd.concat(
            [
                x,
                pd.Series(
                    data=[self.soc_now, nan],
                    index=[self.time_now, self.static.index[0]],
                ),
            ]
        ).sort_index()
        self.initial_soc = x.interpolate().loc[self.static.index[0]]
        self.log(f"Initial SOC: {self.initial_soc}")

        self.log("Calculating Base flows")
        self.base = self.pv_system.flows(
            self.initial_soc, self.static, solar=self.config["solar_forecast"]
        )
        self.log("Calculating Base cost")
        self.log(f">>>{self.contract.host}")

        self.base_cost = self.contract.net_cost(self.base)

        self.log(
            f'Optimising for {self.config["solar_forecast"]} forecast from {self.static.index[0].strftime(DATE_TIME_FORMAT_SHORT)} to {self.static.index[-1].strftime(DATE_TIME_FORMAT_SHORT)}'
        )

        self._status("Optimising charge plan")

        self.opt = self.pv_system.optimised_force(
            self.initial_soc,
            self.static,
            self.contract,
            solar=self.config["solar_forecast"],
            discharge=self.config["forced_discharge"],
        )
        self.opt_cost = self.contract.net_cost(self.opt)
        self.opt["period"] = (self.opt["forced"].diff() > 0).cumsum()

        self.log("")
        if (self.opt["forced"] != 0).sum() > 0:
            self.log("Optimal forced charge/discharge slots:")
            x = self.opt[self.opt["forced"] > 0].copy()
            x["start"] = x.index
            x["end"] = x.index + pd.Timedelta("30T")
            windows = pd.concat(
                [
                    x.groupby("period").first()[["start", "soc", "forced"]],
                    x.groupby("period").last()[["end", "soc_end"]],
                ],
                axis=1,
            )

            x = self.opt[self.opt["forced"] < 0].copy()
            x["start"] = x.index
            x["end"] = x.index + pd.Timedelta("30T")
            self.windows = pd.concat(
                [
                    x.groupby("period").first()[["start", "soc", "forced"]],
                    x.groupby("period").last()[["end", "soc_end"]],
                ],
                axis=1,
            )

            self.windows = pd.concat([windows, self.windows]).sort_values("start")

            for window in self.windows.iterrows():
                self.log(
                    f"  {window[1]['start'].strftime('%d-%b %H:%M'):>13s} - {window[1]['end'].strftime('%d-%b %H:%M'):<13s}  Power: {window[1]['forced']:5.0f}W  SOC: {window[1]['soc']:4.1f}% -> {window[1]['soc_end']:4.1f}%"
                )
            self.charge_power = self.windows["forced"].iloc[0]
            self.charge_current = self.charge_power / self.config["battery_voltage"]
            self.charge_start_datetime = self.windows["start"].iloc[0]
            self.charge_end_datetime = self.windows["end"].iloc[0]

        else:
            self.log(f"No charging slots")
            self.charge_current = 0
            self.charge_power = 0

            self.charge_start_datetime = self.static.index[0]
            self.charge_end_datetime = self.static.index[0]

        self.log("")
        self.log(
            f"Plan time: {self.static.index[0].strftime('%d-%b %H:%M')} - {self.static.index[-1].strftime('%d-%b %H:%M')} Initial SOC: {self.initial_soc} Base Cost: {self.base_cost.sum():5.2f} Opt Cost: {self.opt_cost.sum():5.2f}"
        )
        self.log("")
        self.log(
            f"Optimiser elapsed time {(pd.Timestamp.now()- self.t0).total_seconds():0.2f} seconds"
        )
        self.log("")
        self.log("")

        # Get the current status of the inverter
        self._status("Updating Inverter")
        status = self.inverter.status
        self._log_inverter_status(status)

        time_to_slot_start = (
            self.charge_start_datetime - pd.Timestamp.now(self.tz)
        ).total_seconds() / 60
        time_to_slot_end = (
            self.charge_end_datetime - pd.Timestamp.now(self.tz)
        ).total_seconds() / 60

        if (time_to_slot_start > 0) and (
            time_to_slot_start < self.config["optimise_frequency_minutes"]
        ):
            self.log(
                f"Next charge/discharge window starts in {time_to_slot_start:0.1f} minutes."
            )
            if self.charge_power > 0:
                self.inverter.control_charge(
                    enable=True,
                    start=self.charge_start_datetime,
                    end=self.charge_end_datetime,
                    power=self.charge_power,
                )
            elif self.charge_power < 0:
                self.inverter.control_discharge(
                    enable=True,
                    start=self.charge_start_datetime,
                    end=self.charge_end_datetime,
                    power=self.charge_power,
                )

        elif (time_to_slot_start <= 0) and (
            time_to_slot_start < self.config["optimise_frequency_minutes"]
        ):
            self.log(
                f"Current charge/discharge windows ends in {time_to_slot_end:0.1f} minutes."
            )
            if self.charge_power > 0:
                self.inverter.control_charge(
                    enable=True,
                    end=self.charge_end_datetime,
                    power=self.charge_power,
                )
            elif self.charge_power < 0:
                self.inverter.control_discharge(
                    enable=True,
                    end=self.charge_end_datetime,
                    power=self.charge_power,
                )

        else:
            str_log = f"Next charge/discharge window starts in {time_to_slot_start:0.1f} minutes."

            # If the next slot isn't soon then just check that current status matches what we see:
            if status["charge"]["active"]:
                str_log += " but inverter is charging. Disabling charge."
                self.log(str_log)
                self.inverter.control_charge(enable=False)

            elif status["discharge"]["active"]:
                str_log += " but inverter is discharging. Disabling discharge."
                self.log(str_log)
                self.inverter.control_discharge(enable=False)

            else:
                str_log += " Nothing to do."
                self.log(str_log)

        self._status("Writing to HA")
        self.write_output()
        self._status("Idle")

    def _log_inverter_status(self, status):
        self.log("")
        self.log(f"Current inverter status:")
        self.log("------------------------")
        for s in status:
            if not isinstance(status[s], dict):
                self.log(f"  {s:18s}: {status[s]}")
            else:
                self.log(f"  {s:18s}:")
                for x in status[s]:
                    if isinstance(status[s][x], pd.Timestamp):
                        self.log(
                            f"    {x:16s}: {status[s][x].strftime(DATE_TIME_FORMAT_SHORT)}"
                        )
                    else:
                        self.log(f"    {x:16s}: {status[s][x]}")
        self.log("")

    def write_to_hass(self, entity, state, attributes):
        try:
            self.my_entity = self.get_entity(entity)
            self.my_entity.set_state(state=state, attributes=attributes)
            if self.debug:
                self.log(f"Output written to {self.my_entity}")

        except Exception as e:
            self.log(f"Couldn't write to entity {entity}: {e}")

    def write_cost(self, name, entity, cost, df):
        df = df.fillna(0).round(2)
        df["period_start"] = (
            df.index.tz_convert(self.tz).strftime("%Y-%m-%dT%H:%M:%S%z").str[:-2]
            + ":00"
        )
        cols = ["soc", "forced", "import", "export", "grid", "consumption"]

        self.write_to_hass(
            entity=entity,
            state=round(cost, 2),
            attributes={
                "friendly_name": name,
                "unit_of_measurement": "GBP",
            }
            | {
                col: df[["period_start", col]].to_dict("records")
                for col in cols
                if col in df.columns
            },
        )

    def write_output(self):
        self.write_cost(
            "PV Opt Base Cost",
            entity=f"sensor.{self.prefix}_base_cost",
            cost=self.base_cost.sum(),
            df=self.base,
        )

        self.write_cost(
            "PV Opt Optimised Cost",
            entity=f"sensor.{self.prefix}_opt_cost",
            cost=self.opt_cost.sum(),
            df=self.opt,
        )

        self.write_to_hass(
            entity=f"sensor.{self.prefix}_charge_start",
            state=self.charge_start_datetime,
            attributes={
                "friendly_name": "PV Opt Next Charge Period Start",
                "windows": [
                    {
                        k: window[1][k]
                        for k in ["start", "end", "forced", "soc", "soc_end"]
                    }
                    for window in self.windows.iterrows()
                ],
            },
        )

        self.write_to_hass(
            entity=f"sensor.{self.prefix}_charge_end",
            state=self.charge_end_datetime,
            attributes={
                "friendly_name": "PV Opt Next Charge Period End",
            },
        )

        self.write_to_hass(
            entity=f"sensor.{self.prefix}_charge_current",
            state=round(self.charge_current, 2),
            attributes={
                "friendly_name": "PV Opt Charging Current",
                "unit_of_measurement": "A",
                "state_class": "measurement",
                "device_class": "current",
            },
        )

    def load_solcast(self):
        if self.debug:
            self.log("Getting Solcast data")
        try:
            solar = self.get_state(self.config["id_solcast_today"], attribute="all")[
                "attributes"
            ]["detailedForecast"]
            solar += self.get_state(
                self.config["id_solcast_tomorrow"], attribute="all"
            )["attributes"]["detailedForecast"]

        except Exception as e:
            self.log(f"Failed to get solcast attributes: {e}")
            return False

        try:
            # Convert to timestamps
            for s in solar:
                s["period_start"] = pd.Timestamp(s["period_start"])

            df = pd.DataFrame(solar)
            df = df.set_index("period_start")
            df.index = pd.to_datetime(df.index, utc=True)
            df = df.set_axis(["Solcast", "Solcast_p10", "Solcast_p90"], axis=1)

            # Convert from kWh/30min period to W
            df *= 1000
            df *= PV_MULT

            self.static = pd.concat([self.static, df.fillna(0)], axis=1)
            self.log("Solcast forecast loaded OK")
            return True

        except Exception as e:
            self.log(f"Error loading Solcast: {e}", level="ERROR")
            return False

    def load_consumption(self):
        self.log("Getting expected consumption data")

        if self.config["consumption_from_entity"]:
            consumption = pd.Series(index=self.static.index, data=0)
            for entity_id in self.config["id_consumption"]:
                try:
                    # load history fot the last N days from the specified sensors
                    # self.log(self.config["consumption_history_days"])
                    df = self.hass2df(
                        entity_id,
                        days=int(self.config["consumption_history_days"]),
                    )

                except Exception as e:
                    self.log(
                        f"Unable to get historical consumption from {entity_id}. {e}",
                        level="ERROR",
                    )
                    return False

                try:
                    df.index = pd.to_datetime(df.index)
                    df = (
                        pd.to_numeric(df, errors="coerce")
                        .dropna()
                        .resample("30T")
                        .mean()
                        .fillna(0)
                    )
                    df = df * (1 + self.config["consumption_margin"] / 100)

                    # Group by time and take the mean
                    df = df.groupby(df.index.time).aggregate(
                        self.config["consumption_grouping"]
                    )
                    df.name = "consumption"

                    temp = self.static.copy()
                    temp["time"] = temp.index.time
                    temp = temp.merge(df, "left", left_on="time", right_index=True)
                    # self.log(temp["consumption"].sum())
                    consumption += temp["consumption"]
                    self.log(f"  - Estimated consumption from {entity_id} loaded OK ")

                # self.log(temp)

                except Exception as e:
                    self.log(f"Error loading consumption data: {e}")
                    return False

            self.static["consumption"] = consumption
            return True

        else:
            try:
                df = pd.DataFrame(
                    index=["0:00", "4:00", "8:30", "14:30", "19:30", "22:00", "23:30"],
                    data=[200, 150, 500, 390, 800, 800, 320],
                )
                df.index = pd.to_datetime(df.index).tz_localize(self.tz)
                df2 = df.copy()
                df2.index += pd.Timedelta("1D")
                df = pd.concat([df, df2]).set_axis(["consumption"], axis=1)
                # if self.debug:
                #     self.log(df.index)
                self.static = pd.concat([self.static, df], axis=1).interpolate()
                self.static["consumption"] *= (
                    self.config["daily_consumption_Wh"] / 11000
                )
                return True

            except Exception as e:
                self.log(f"Error calculating modelled consumption data: {e}")
                return False


# %%

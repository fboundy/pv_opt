# %%
import appdaemon.plugins.hass.hassapi as hass
import appdaemon.adbase as ad
import appdaemon.plugins.mqtt.mqttapi as mqtt
from json import dumps

import pandas as pd
import time

import pvpy as pv
import numpy as np
from numpy import nan


# import pvpy as pv
OCTOPUS_PRODUCT_URL = r"https://api.octopus.energy/v1/products/"

# %%
#
USE_TARIFF = True

VERSION = "3.4.3"

DATE_TIME_FORMAT_LONG = "%Y-%m-%d %H:%M:%S%z"
DATE_TIME_FORMAT_SHORT = "%d-%b %H:%M"
TIME_FORMAT = "%H:%M"


EVENT_TRIGGER = "PV_OPT"
DEBUG_TRIGGER = "PV_DEBUG"
HOLD_TOLERANCE = 3
MAX_ITERS = 10

BOTTLECAP_DAVE = {
    "domain": "event",
    "tariff_code": "tariff_code",
    "rates": "current_day_rates",
}

INVERTER_TYPES = ["SOLIS_SOLAX_MODBUS", "SOLIS_CORE_MODBUS", "SOLIS_SOLARMAN"]

IMPEXP = ["import", "export"]

MQTT_CONFIGS = {
    "switch": {
        "payload_on": "ON",
        "payload_off": "OFF",
        "state_on": "ON",
        "state_off": "OFF",
    },
    "number": {
        "mode": "slider",
    },
}

DEFAULT_CONFIG = {
    "forced_charge": {"default": True, "domain": "switch"},
    "forced_discharge": {"default": True, "domain": "switch"},
    "read_only": {"default": True, "domain": "switch"},
    "allow_cyclic": {"default": False, "domain": "switch"},
    "optimise_frequency_minutes": {
        "default": 10,
        "attributes": {
            "min": 5,
            "max": 30,
            "step": 5,
            "mode": "slider",
        },
        "domain": "number",
    },
    "slot_threshold_p": {
        "default": 1.0,
        "attributes": {
            "min": 0.0,
            "max": 3.0,
            "step": 0.1,
            "mode": "slider",
        },
        "domain": "number",
    },
    "day_of_week_weighting": {
        "default": 0.5,
        "attributes": {
            "min": 0.0,
            "max": 1.0,
            "step": 0.1,
            "mode": "slider",
        },
        "domain": "number",
    },
    "pass_threshold_p": {
        "default": 4.0,
        "attributes": {
            "min": 0.0,
            "max": 10.0,
            "step": 0.5,
            "mode": "slider",
        },
        "domain": "number",
    },
    "octopus_auto": {"default": True, "domain": "switch"},
    "battery_capacity_wh": {
        "default": 10000,
        "domain": "number",
        "attributes": {
            "min": 2000,
            "max": 20000,
            "step": 100,
            "unit_of_measurement": "Wh",
            "device_class": "energy",
            "mode": "slider",
        },
    },
    "inverter_efficiency_percent": {
        "default": 97,
        "domain": "number",
        "attributes": {
            "min": 90,
            "max": 100,
            "step": 1,
            "unit_of_measurement": "%",
            "mode": "slider",
        },
    },
    "charger_efficiency_percent": {
        "default": 91,
        "domain": "number",
        "attributes": {
            "min": 80,
            "max": 100,
            "step": 1,
            "unit_of_measurement": "%",
            "mode": "slider",
        },
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
            "mode": "slider",
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
            "mode": "slider",
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
            "mode": "slider",
        },
    },
    "solar_forecast": {
        "default": "Solcast",
        "attributes": {"options": ["Solcast", "Solcast_p10", "Solcast_p90"]},
        "domain": "select",
    },
    "id_solcast_today": {"default": "sensor.solcast_pv_forecast_forecast_today"},
    "id_solcast_tomorrow": {"default": "sensor.solcast_pv_forecast_forecast_tomorrow"},
    "consumption_history_days": {
        "default": 7,
        "domain": "number",
        "attributes": {
            "min": 1,
            "max": 28,
            "step": 1,
            "mode": "slider",
        },
    },
    "consumption_margin": {
        "default": 10,
        "domain": "number",
        "attributes": {
            "min": -50,
            "max": 100,
            "step": 5,
            "unit_of_measurement": "%",
            "mode": "slider",
        },
    },
    "consumption_grouping": {
        "default": "mean",
        "domain": "select",
        "attributes": {"options": ["mean", "median", "max"]},
    },
    "forced_power_group_tolerance": {
        "default": 100,
        "domain": "number",
        "attributes": {
            "min": 0,
            "max": 1000,
            "step": 100,
            "unit_of_measurement": "W",
            "device_class": "power",
            "mode": "slider",
        },
    },
    # "alt_tariffs": {"default": [], "domain": "input_select"},
}


def importName(modulename, name):
    """Import a named object from a module in the context of this function."""
    try:
        module = __import__(modulename, globals(), locals(), [name])
    except ImportError:
        return None
    return vars(module)[name]


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
        self.mqtt = self.get_plugin_api("MQTT")
        self._load_tz()
        self.log(f"Time Zone Offset: {self.get_tz_offset()} minutes")

        # self.log(self.args)
        self.inverter_type = self.args.pop("inverter_type", "SOLIS_SOLAX_MODBUS")
        self.device_name = self.args.pop("device_name", "solis")
        self._load_inverter()

        self.change_items = {}
        self.config_state = {}
        self.timer_handle = None
        self.handles = {}
        self.mqtt_handles = {}

        self.saving_events = {}
        self.contract = None

        # Load arguments from the YAML file
        # If there are none then use the defaults in DEFAULT_CONFIG and DEFAULT_CONFIG_BY_BRAND
        # if there are existing entities for the configs in HA then read those values
        # if not, set up entities using MQTT discovery and write the initial state to them
        self._load_args()

        self._estimate_capacity()
        self._load_pv_system_model()
        if self.get_config("alt_tariffs") is not None:
            self._compare_tariffs()

        self._load_contract()

        if self.agile:
            self._setup_agile_schedule()

        self._cost_today()

        # Optimise on an EVENT trigger:
        self.listen_event(
            self.optimise_event,
            EVENT_TRIGGER,
        )

        if not self.get_config("read_only"):
            self.inverter.enable_timed_mode()

        if self.get_config("forced_charge"):
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

    def _estimate_capacity(self):
        if "id_battery_charge_power" in self.config:
            df = pd.DataFrame(
                self.hass2df(
                    entity_id=self.config["id_battery_charge_power"], days=7
                ).astype(int, errors="ignore")
            ).set_axis(["Power"], axis=1)

            df["period"] = (df["Power"] > 200).diff().abs().cumsum()
            df["dt"] = -df.index.diff(-1).total_seconds() / 3600
            df["Energy"] = df["dt"] * df["Power"]
            x = df.groupby("period").sum()
            p = x[x["Energy"] == x["Energy"].max()].index[0]
            start = df[df["period"] == p].index[0]
            end = df[df["period"] == p].index[-1]
            soc = (
                self.hass2df(entity_id=self.config["id_battery_soc"], days=7)
                .astype(int, errors="ignore")
                .loc[start:end]
            )
            start = soc.index[0]
            end = soc.index[-1]
            energy = df.loc[start:end]["Energy"].sum()
            dsoc = soc.iloc[-1] - soc.iloc[0]

            return energy * 100 / dsoc
        else:
            return None

    def _load_tz(self):
        self.tz = self.args.pop("manual_tz", "GB")
        self.log(f"Local timezone set to {self.tz}")

    def _load_inverter(self):
        if self.inverter_type in INVERTER_TYPES:
            inverter_brand = self.inverter_type.split("_")[0].lower()
            InverterController = importName(f"{inverter_brand}", "InverterController")
            self.log(
                f"Inverter type: {self.inverter_type}: inverter module: {inverter_brand}.py"
            )
            self.inverter = InverterController(
                inverter_type=self.inverter_type, host=self
            )

        else:
            e = f"Inverter type {self.inverter_type} is not yet supported. Only read-only mode with explicit config from the YAML will work."
            self.log(e, level="ERROR")

    def _load_pv_system_model(self):
        self._status("Initialising PV Model")

        self.inverter_model = pv.InverterModel(
            inverter_efficiency=self.get_config("inverter_efficiency_percent") / 100,
            inverter_power=self.get_config("inverter_power_watts"),
            inverter_loss=self.get_config("inverter_loss_watts"),
            charger_efficiency=self.get_config("charger_efficiency_percent") / 100,
            charger_power=self.get_config("charger_power_watts"),
        )

        self.battery_model = pv.BatteryModel(
            capacity=self.get_config("battery_capacity_wh"),
            max_dod=self.get_config("maximum_dod_percent") / 100,
        )
        self.pv_system = pv.PVsystemModel(
            "PV_Opt", self.inverter_model, self.battery_model, host=self
        )

    def _setup_agile_schedule(self):
        # start = (pd.Timestamp.now().round("1H") + pd.Timedelta("5T")).to_pydatetime()
        start = (pd.Timestamp.now() + pd.Timedelta("1T")).to_pydatetime()
        self.timer_handle = self.run_every(
            self._load_agile_cb,
            start=start,
            interval=3600,
        )

    def _cost_today(self):
        index = pd.date_range(
            pd.Timestamp.now(tz="UTC").normalize(),
            pd.Timestamp.now(tz="UTC"),
            freq="30T",
        )
        if (
            "id_grid_import_today" in self.config
            and "id_grid_export_today" in self.config
        ):
            cols = ["grid_import", "grid_export"]
            grid = (
                pd.concat(
                    [
                        self.hass2df(self.config[f"id_{col}_today"], days=1)
                        .astype(float)
                        .resample("30T")
                        .ffill()
                        .reindex(index)
                        .ffill()
                        for col in cols
                    ],
                    axis=1,
                )
                .set_axis(cols, axis=1)
                .loc[pd.Timestamp.now(tz="UTC").normalize() :]
            )
            grid = (-grid.diff(-1).clip(upper=0) * 2000).round(0)[:-1].fillna(0)

        elif (
            "id_grid_import_power" in self.config
            and "id_grid_export_power" in self.config
        ):
            grid = (
                pd.concat(
                    [
                        self.hass2df(self.config["id_grid_import_power"], days=1)
                        .astype(float)
                        .resample("30T")
                        .mean()
                        .reindex(index)
                        .fillna(0)
                        .reindex(index),
                        self.hass2df(self.config["id_grid_export_power"], days=1)
                        .astype(float)
                        .resample("30T")
                        .mean()
                        .reindex(index)
                        .fillna(0),
                    ],
                    axis=1,
                )
                .set_axis(["grid_import", "grid_export"], axis=1)
                .loc[pd.Timestamp.now(tz="UTC").normalize() :]
            )

        elif "id_grid_power" in self.config:
            grid = (
                -(
                    self.hass2df(self.config["id_grid_power"], days=1)
                    .astype(float)
                    .resample("30T")
                    .mean()
                    .reindex(index)
                    .fillna(0)
                    .reindex(index)
                )
            ).loc[pd.Timestamp.now(tz="UTC").normalize() :]

        # self.log(grid)
        cost_today = self.contract.net_cost(grid_flow=grid)
        return cost_today

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

    def get_config(self, item):
        if item in self.config_state:
            return self._value_from_state(self.config_state[item])

        if item in self.config:
            if isinstance(self.config[item], str) and self.entity_exists(
                self.config[item]
            ):
                x = self.get_ha_value(self.config[item])
                return x
            elif isinstance(self.config[item], list):
                if min([isinstance(x, str)] for x in self.config[item])[0]:
                    if min([self.entity_exists(e) for e in self.config[item]]):
                        l = [self.get_ha_value(e) for e in self.config[item]]
                        try:
                            return sum(l)
                        except:
                            return l
                else:
                    return self.config[item]
            else:
                return self.config[item]

    def _setup_schedule(self):
        if self.get_config("forced_charge"):
            start_opt = (
                pd.Timestamp.now()
                .ceil(f"{self.get_config('optimise_frequency_minutes')}T")
                .to_pydatetime()
            )
            self.timer_handle = self.run_every(
                self.optimise_time,
                start=start_opt,
                interval=self.get_config("optimise_frequency_minutes") * 60,
            )
            self.log(
                f"Optimiser will run every {self.get_config('optimise_frequency_minutes')} minutes from {start_opt.strftime('%H:%M')} or on {EVENT_TRIGGER} Event"
            )

        else:
            if self.timer_handle and self.timer_running(self.timer_handle):
                self.cancel_timer(self.timer_handle)
                self.log("Optimer Schedule Disabled")
                self._status("Disabled")

    def _load_contract(self):
        self.log("")
        self.log("Loading Contract:")
        self._status("Loading Tariffs")
        self.log("-----------------")
        self.tariff_codes = {}
        self.agile = False

        i = 0
        n = 5
        while self.contract is None and i < n:
            if self.get_config("octopus_auto"):
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
                        str = f"Trying to load tariff codes: Import: {self.config['octopus_import_tariff_code']}"

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
                i += 1
                self.log(
                    f"Failed to load contact - Attempt {i} of {n}. Waiting 2 minutes to re-try"
                )
                time.sleep(12)

        if self.contract is None:
            e = f"Failed to load contract in {n} attempts. FATAL ERROR"
            self.log(e)
            raise ValueError(e)

        else:
            for imp_exp, t in zip(IMPEXP, [self.contract.imp, self.contract.exp]):
                self.log(f"  {imp_exp.title()}: {t.name}")
                if "AGILE" in t.name:
                    self.agile = True

            if self.agile:
                self.log("AGILE tariff detected. Rates will update at 16:00 daily")

            self.log("")
            self._load_saving_events()
        self.log("Finished loading contract")

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
                if event["id"] not in self.saving_events and pd.Timestamp(
                    event["end"], tz="UTC"
                ) > pd.Timestamp.now(tz="UTC"):
                    self.saving_events[event["id"]] = event

        self.log("")
        if len(self.saving_events) > 0:
            self.log("The following Octopus Saving Events have been joined:")
            for id in self.saving_events:
                self.log(
                    f"{id:8d}: {pd.Timestamp(self.saving_events[id]['start']).strftime(DATE_TIME_FORMAT_SHORT)} - {pd.Timestamp(self.saving_events[id]['end']).strftime(DATE_TIME_FORMAT_SHORT)} at {int(self.saving_events[id]['octopoints_per_kwh'])/8:5.1f}p/kWh"
                )
        else:
            self.log("No upcoming Octopus Saving Events detected or joined:")

    def get_ha_value(self, entity_id):
        value = None

        # if the entity doesn't exist return None
        if self.entity_exists(entity_id=entity_id):
            state = self.get_state(entity_id=entity_id)

            # if the state is None return None
            if state is not None:
                # if the state is 'on' or 'off' then it's a bool
                if state.lower() in ["on", "off", "true", "false"]:
                    value = state.lower() in ["on", "true"]

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
        if item in self.inverter.config:
            return self.inverter.config[item]
        if item in self.inverter.brand_config:
            return self.inverter.brand_config[item]
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
            items = [
                i
                for i in self.args
                if i not in ["module", "class", "prefix", "log", "dependencies"]
            ]

        for item in items:
            # Attempt to read entity states for all string paramters unless they start
            # with"id_":
            if not isinstance(self.args[item], list):
                self.args[item] = [self.args[item]]

            values = [
                v.replace("{device_name}", self.device_name)
                if isinstance(v, str)
                else v
                for v in self.args[item]
            ]

            if values[0] is None:
                self.config[item] = self.get_default_config(item)
                self.log(
                    f"    {item:34s} = {str(self.config[item]):57s} {str(self.get_config(item)):>6s}: system default. Null entry found in YAML.",
                    level="WARNING",
                )

            # if the item starts with 'id_' then it must be an entity that exists:
            elif item == "alt_tariffs":
                self.config[item] = values
                self.log(
                    f"    {item:34s} = {str(self.config[item]):57s} {str(self.get_config(item)):>6s}: value(s) in YAML"
                )

            elif "id_" in item:
                if min([self.entity_exists(v) for v in values]):
                    if len(values) == 1:
                        self.config[item] = values[0]
                    else:
                        self.config[item] = values

                    self.log(
                        f"    {item:34s} = {str(self.config[item]):57s} {str(self.get_config(item)):>6s}: value(s) in YAML"
                    )

                elif self.entity_exists(self.get_default_config(item)):
                    self.config[item] = self.get_default_config(item)
                    self.log(
                        f"    {item:34s} = {str(self.config[item]):57s} {str(self.get_config(item)):>6s}: system default. Entities listed in YAML {values} do not all exist in HA.",
                        level="WARNING",
                    )
                else:
                    e = f"    {item:34s} : Neither the entities listed in the YAML {values[0]} nor the system default of {self.get_default_config(item)} exist in HA."
                    self.log(e, level="ERROR")
                    raise ValueError(e)

            else:
                # The value should be read explicitly
                if self.debug:
                    self.log(f"{item}:")
                    for value in self.args[item]:
                        self.log(f"\t{value}")

                arg_types = {
                    t: [isinstance(v, t) for v in values]
                    for t in [str, float, int, bool]
                }

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
                        f"    {item:34s} = {str(self.config[item]):57s} {str(self.get_config(item)):>6s}: value in YAML"
                    )

                elif min(arg_types[str]):
                    if self.debug:
                        self.log("\tFound a valid list of strings")

                    if (
                        isinstance(self.get_default_config(item), str)
                        and len(values) == 1
                    ):
                        self.config[item] = values[0]
                        self.log(
                            f"    {item:34s} = {str(self.config[item]):57s} {str(self.get_config(item)):>6s}: value in YAML"
                        )

                    else:
                        ha_values = [self.get_ha_value(entity_id=v) for v in values]
                        val_types = {
                            t: np.array([isinstance(v, t) for v in ha_values])
                            for t in [str, float, int, bool]
                        }
                        # if they are all float or int

                        valid_strings = [
                            j
                            for j in [
                                h for h in zip(ha_values[:-1], values[:-1]) if h[0]
                            ]
                            if j[0] in DEFAULT_CONFIG[item]["options"]
                        ]

                        if self.debug:
                            self.log(f">>> {DEFAULT_CONFIG[item]['options']}")

                        if np.min(val_types[int] | val_types[float]):
                            self.config[item] = values
                            self.log(
                                f"    {item:34s} = {str(sum(ha_values)):57s} {str(self.get_config(item)):>6s}: HA entities listed in YAML"
                            )
                        # if any of list but the last one are strings and the default for the item is a string
                        # try getting values from all the entities
                        elif valid_strings:
                            self.config[item] = valid_strings[0][0]
                            if not "sensor" in valid_strings[0][1]:
                                self.change_items[valid_strings[0][1]] = item
                            self.log(
                                f"    {item:34s} = {str(self.config[item]):57s} {str(self.get_config(item)):>6s}: HA entities listed in YAML"
                            )

                        elif len(values) > 1:
                            if self.same_type(
                                values[-1], self.get_default_config(item)
                            ):
                                self.config[item] = values[-1]
                                self.log(
                                    f"    {item:34s} = {str(self.config[item]):57s} {str(self.get_config(item)):>6s}: YAML default. Unable to read from HA entities listed in YAML."
                                )

                            elif values[-1] in self.get_default_config(item):
                                self.log(values)
                                self.config[item] = values[-1]
                                self.log(
                                    f"    {item:34s} = {str(self.config[item]):57s} {str(self.get_config(item)):>6s}: YAML default. Unable to read from HA entities listed in YAML."
                                )
                        else:
                            if item in DEFAULT_CONFIG:
                                self.config[item] = self.get_default_config(item)

                                self.log(
                                    f"    {item:34s} = {str(self.config[item]):57s} {str(self.get_config(item)):>6s}: system default. Unable to read from HA entities listed in YAML. No default in YAML.",
                                    level="WARNING",
                                )
                            elif (
                                item in self.inverter.config
                                or item in self.inverter.brand_config
                            ):
                                self.config[item] = self.get_default_config(item)

                                self.log(
                                    f"    {item:34s} = {str(self.config[item]):57s} {str(self.get_config(item)):>6s}: inverter brand default. Unable to read from HA entities listed in YAML. No default in YAML.",
                                    level="WARNING",
                                )
                            else:
                                self.config[item] = values[0]
                                self.log(
                                    f"    {item:34s} = {str(self.config[item]):57s} {str(self.get_config(item)):>6s}: YAML default value. No default defined."
                                )

                elif len(values) == 1 and (
                    arg_types[bool][0] or arg_types[int][0] or arg_types[float][0]
                ):
                    if self.debug:
                        self.log("\tFound a single default value")

                    self.config[item] = values[0]
                    self.log(
                        f"    {item:34s} = {str(self.config[item]):57s} {str(self.get_config(item)):>6s}: value in YAML"
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
                            f"    {item:34s} = {str(self.config[item]):57s} {str(self.get_config(item)):>6s}: HA entities listed in YAML"
                        )
                        # If these change then we need to trigger automatically
                        for v in values[:-1]:
                            if not "sensor" in v:
                                self.change_items[v] = item

                    else:
                        self.config[item] = values[-1]
                        self.log(
                            f"    {item:34s} = {str(self.config[item]):57s} {str(self.get_config(item)):>6s}: YAML default. Unable to read from HA entities listed in YAML."
                        )

                else:
                    self.config[item] = self.get_default_config(item)
                    self.log(
                        f"    {item:34s} = {str(self.config[item]):57s} {str(self.get_config(item)):>6s}: system default. Invalid arguments in YAML.",
                        level="ERROR",
                    )

        self.log("")
        self.log("Checking config:")
        self.log("-----------------------")
        items_not_defined = (
            [i for i in DEFAULT_CONFIG if i not in self.config]
            + [i for i in self.inverter.config if i not in self.config]
            + [i for i in self.inverter.brand_config if i not in self.config]
        )

        if len(items_not_defined) > 0:
            for item in items_not_defined:
                self.config[item] = self.get_default_config(item)
                self.log(
                    f"    {item:34s} = {str(self.config[item]):57s} {str(self.get_config(item)):>6s}: system default. Not in YAML.",
                    level="WARNING",
                )
        else:
            self.log("All config items defined OK")

        self.log("")

        self.log("Exposing config to Home Assistant:")
        self.log("----------------------------------")
        self._expose_configs()

    def _name_from_item(self, item):
        name = item.replace("_", " ")
        for word in name.split():
            name = name.replace(word, word.title())
        return f"{self.prefix.title()} {name}"

    def _state_from_value(self, value):
        if isinstance(value, bool):
            if value:
                state = "on"
            else:
                state = "off"
        elif isinstance(value, list):
            state = value[0]
        else:
            state = value
        return state

    def _expose_configs(self):
        mqtt_items = [
            item
            for item in DEFAULT_CONFIG
            if (item not in [self.change_items[entity] for entity in self.change_items])
            and ("id_" not in item)
            and ("alt_" not in item)
            and ("auto" not in item)
            and "domain" in DEFAULT_CONFIG[item]
        ]

        for item in mqtt_items:
            state = None
            domain = DEFAULT_CONFIG[item]["domain"]
            id = f"{self.prefix.lower()}_{item}"
            entity_id = f"{domain}.{id}"
            attributes = DEFAULT_CONFIG[item].get("attributes", {})

            command_topic = f"homeassistant/{domain}/{id}/set"
            state_topic = f"homeassistant/{domain}/{id}/state"

            if not self.entity_exists(entity_id=entity_id):
                self.log(
                    f"  - Creating HA Entity {entity_id} for {item} using MQTT Discovery"
                )
                conf = (
                    {
                        "state_topic": state_topic,
                        "command_topic": command_topic,
                        "name": self._name_from_item(item),
                        "optimistic": True,
                        "object_id": id,
                        "unique_id": id,
                    }
                    | attributes
                    | MQTT_CONFIGS.get(domain, {})
                )

                conf_topic = f"homeassistant/{domain}/{id}/config"
                self.mqtt.mqtt_publish(conf_topic, dumps(conf), retain=True)
                state = self._state_from_value(self.config[item])
                if domain == "switch":
                    self.mqtt.mqtt_publish(command_topic, state.upper(), retain=True)
                    self.mqtt.mqtt_publish(state_topic, state.upper(), retain=True)
                else:
                    self.mqtt.mqtt_publish(state_topic, state, retain=True)
                    self.mqtt.mqtt_publish(command_topic, state, retain=True)

                self.mqtt.mqtt_subscribe(state_topic)

            elif isinstance(self.get_ha_value(entity_id), str) and self.get_ha_value(
                entity_id
            ) not in attributes.get("options", {}):
                state = self._state_from_value(self.get_default_config(item))

                self.log(
                    f"  - Found unexpected str for {entity_id} reverting to default of {state}"
                )

                self.set_state(state=state, entity_id=entity_id)

            #     if item == "battery_capacity_wh":
            #         capacity = round(self._estimate_capacity() / 100, 0) * 100
            #         if capacity is not None:
            #             self.config[item] = capacity
            #             self.log(f"Battery capacity estimated to be {capacity} Wh")

            #     # Only set the state for entities that don't currently exists
            #     state = self._state_from_value(self.config[item])

            # self.log(f">>>*>> {state}")
            # # Or entities where the sensor value is no use
            # if isinstance(self.get_ha_value(entity_id), str) and self.get_ha_value(
            #     entity_id
            # ) not in attributes.get("options", {}):
            #     self.log(f">>Found unexpected str for {entity_id}")
            #     if item == "battery_capacity_wh":
            #         capacity = round(self._estimate_capacity() / 100, 0) * 100
            #         if capacity is not None:
            #             state = capacity
            #             self.log(f"Battery capacity estimated to be {capacity} Wh")
            #         else:
            #             state = self._state_from_value(self.config[item])
            #     else:
            #         state = self._state_from_value(self.config[item])
            #         self.log(
            #             f"Can't resolve HA entity {entity_id} to correct type. Using YAML default value of {state}"
            #         )
            # elif state is None:
            #     state = self.get_ha_value(entity_id)

            # self.set_state(
            #     state=self._state_from_value(state),
            #     entity_id=entity_id,
            #     attributes=attributes
            #     | {"friendly_name": self._name_from_item(item)},
            # )

            # Now that we have published it, write the entity back to the config so we check the entity in future
            else:
                state = self.get_state(entity_id)

            self.config[item] = entity_id
            self.change_items[entity_id] = item
            self.config_state[item] = state

        if self.change_items:
            self.log("")
            self.log(f"  {'Config Item':40s}  {'HA Entity':42s}  Current State")
            self.log(f"  {'-----------':40s}  {'---------':42s}  -------------")

            for entity_id in self.change_items:
                if not "sensor" in entity_id:
                    self.log(
                        f"  {self.change_items[entity_id]:40s}  {entity_id:42s}  {self.config_state[self.change_items[entity_id]]}"
                    )
                    self.handles[entity_id] = self.listen_state(
                        callback=self.optimise_state_change, entity_id=entity_id
                    )

        self.mqtt.listen_state(
            callback=self.optimise_state_change,
        )

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

        self.config_state[item] = new

        if "forced" in item:
            self._setup_schedule()

        if item in [
            "inverter_efficiency_percent",
            "inverter_power_watts",
            "inverter_loss_watts",
            "charger_efficiency_percent",
            "battery_capacity_wh",
            "maximum_dod_percent",
        ]:
            self._load_pv_system_model()

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
        self.log(f"Optimiser triggered by Scheduler ")
        self.optimise()

    @ad.app_lock
    def optimise(self):
        # initialse a DataFrame to cover today and tomorrow at 30 minute frequency
        self.log("")
        self._load_saving_events()

        if self.get_config("forced_discharge"):
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
        solcast = self.load_solcast()
        consumption = self.load_consumption(
            pd.Timestamp.utcnow().normalize(),
            pd.Timestamp.utcnow().normalize() + pd.Timedelta(days=2),
        )

        self.static = pd.concat([solcast, consumption], axis=1)
        self.time_now = pd.Timestamp.utcnow()

        self.static = self.static[self.time_now.floor("30T") :].fillna(0)
        # self.load_consumption()
        self.soc_now = self.get_config("id_battery_soc")

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
            self.initial_soc, self.static, solar=self.get_config("solar_forecast")
        )
        self.log("Calculating Base cost")

        self.base_cost = self.contract.net_cost(self.base)

        self.log(
            f'Optimising for {self.get_config("solar_forecast")} forecast from {self.static.index[0].strftime(DATE_TIME_FORMAT_SHORT)} to {self.static.index[-1].strftime(DATE_TIME_FORMAT_SHORT)}'
        )

        self._status("Optimising charge plan")

        self.opt = self.pv_system.optimised_force(
            self.initial_soc,
            self.static,
            self.contract,
            solar=self.get_config("solar_forecast"),
            discharge=self.get_config("forced_discharge"),
            max_iters=MAX_ITERS,
        )
        self.opt_cost = self.contract.net_cost(self.opt)

        self.log("")

        self._create_windows()

        self.log("")
        self.log(
            f"Plan time: {self.static.index[0].strftime('%d-%b %H:%M')} - {self.static.index[-1].strftime('%d-%b %H:%M')} Initial SOC: {self.initial_soc} Base Cost: {self.base_cost.sum():5.2f} Opt Cost: {self.opt_cost.sum():5.2f}"
        )
        self.log("")
        optimiser_elapsed = round((pd.Timestamp.now() - self.t0).total_seconds(), 1)
        self.log(f"Optimiser elapsed time {optimiser_elapsed:0.1f} seconds")
        self.log("")
        self.log("")
        self.write_to_hass(
            entity=f"sensor.{self.prefix}_optimiser_elapsed",
            state=optimiser_elapsed,
            attributes={"state_class": "measurement"},
        )

        self._status("Writing to HA")
        self._write_output()

        if self.get_config("read_only"):
            self.log("Read only mode enabled. Not querying inverter.")
            self._status("Idle (Read Only)")

        else:
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

            did_something = True

            if (time_to_slot_start > 0) and (
                time_to_slot_start < self.get_config("optimise_frequency_minutes")
            ):
                # Next slot starts before the next optimiser run. This implies we are not currently in
                # a charge or discharge slot

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
                    self.inverter.control_discharge(enable=False)

                elif self.charge_power < 0:
                    self.inverter.control_discharge(
                        enable=True,
                        start=self.charge_start_datetime,
                        end=self.charge_end_datetime,
                        power=self.charge_power,
                    )
                    self.inverter.control_charge(enable=False)

            elif (time_to_slot_start <= 0) and (
                time_to_slot_start < self.get_config("optimise_frequency_minutes")
            ):
                # We are currently in a charge/discharge slot

                # If the current slot is a Hold SOC slot and we aren't holding then we need to
                # enable Hold SOC
                if self.hold[0]["active"]:
                    if (
                        not status["hold_soc"]["active"]
                        or status["hold_soc"]["soc"] != self.hold[0]["soc"]
                    ):
                        self.log(
                            f"  Enabling SOC hold at SOC of {self.hold[0]['soc']:0.0f}%"
                        )
                        self.inverter.hold_soc(enabled=True, soc=self.hold[0]["soc"])
                    else:
                        self.log(
                            f"  Inverter already holding SOC of {self.hold[0]['soc']:0.0f}%"
                        )

                else:
                    self.log(
                        f"Current charge/discharge windows ends in {time_to_slot_end:0.1f} minutes."
                    )

                    if self.charge_power > 0:
                        if not status["charge"]["active"]:
                            start = pd.Timestamp.now()
                        else:
                            start = None

                        self.inverter.control_charge(
                            enable=True,
                            start=start,
                            end=self.charge_end_datetime,
                            power=self.charge_power,
                        )

                    elif self.charge_power < 0:
                        if not status["discharge"]["active"]:
                            start = pd.Timestamp.now()
                        else:
                            start = None

                        self.inverter.control_discharge(
                            enable=True,
                            start=start,
                            end=self.charge_end_datetime,
                            power=self.charge_power,
                        )

            else:
                if self.charge_power > 0:
                    direction = "charge"
                elif self.charge_power < 0:
                    direction = "discharge"

                # We aren't in a charge/discharge slot and the next one doesn't start before the
                # optimiser runs again

                str_log = f"Next {direction} window starts in {time_to_slot_start:0.1f} minutes."

                # If the next slot isn't soon then just check that current status matches what we see:
                if status["charge"]["active"]:
                    str_log += " but inverter is charging. Disabling charge."
                    self.log(str_log)
                    self.inverter.control_charge(enable=False)

                elif status["discharge"]["active"]:
                    str_log += " but inverter is discharging. Disabling discharge."
                    self.log(str_log)
                    self.inverter.control_discharge(enable=False)

                elif (
                    direction == "charge"
                    and self.charge_start_datetime > status["discharge"]["start"]
                    and status["discharge"]["start"] != status["discharge"]["end"]
                ):
                    str_log += " but inverter is has a discharge slot before then. Disabling discharge."
                    self.log(str_log)
                    self.inverter.control_discharge(enable=False)

                elif (
                    direction == "discharge"
                    and self.charge_start_datetime > status["charge"]["start"]
                    and status["charge"]["start"] != status["charge"]["end"]
                ):
                    str_log += " but inverter is has a charge slot before then. Disabling charge."
                    self.log(str_log)
                    self.inverter.control_charge(enable=False)

                elif status["hold_soc"]["active"]:
                    self.inverter.hold_soc(enabled=False)
                    str_log += " but inverter is holding SOC. Disabling."
                    self.log(str_log)

                else:
                    str_log += " Nothing to do."
                    self.log(str_log)
                    did_something = False

            if did_something:
                if self.get_config("update_cycle_seconds") is not None:
                    i = int(self.get_config("update_cycle_seconds"))
                    self.log(f"Wating for Modbus Read cycle: {i} seconds")
                    while i > 0:
                        self._status(f"Waiting for Modbus Read cycle: {i}")
                        time.sleep(1)
                        i -= 1

                    status = self.inverter.status
                    self._log_inverter_status(status)

            if status["hold_soc"]["active"]:
                self._status(f"Holding SOC at {status['hold_soc']['soc']:0.0f}%")
            elif status["charge"]["active"]:
                self._status("Charging")
            elif status["discharge"]["active"]:
                self._status("Discharging")
            else:
                self._status("Idle")

    def _create_windows(self):
        self.opt["period"] = (self.opt["forced"].diff() > 0).cumsum()
        if (self.opt["forced"] != 0).sum() > 0:
            self.log("Optimal forced charge/discharge slots:")
            x = self.opt[self.opt["forced"] > 0].copy()
            x["start"] = x.index
            x["end"] = x.index + pd.Timedelta("30T")
            x["soc"] = x["soc"].round(0).astype(int)
            x["soc_end"] = x["soc_end"].round(0).astype(int)
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
            tolerance = self.get_config("forced_power_group_tolerance")
            self.windows["forced"] = (
                (self.windows["forced"] / tolerance).round(0) * tolerance
            ).astype(int)

            self.windows["soc"] = self.windows["soc"].round(0).astype(int)
            self.windows["soc_end"] = self.windows["soc_end"].round(0).astype(int)

            self.windows["hold_soc"] = ""
            if self.config["supports_hold_soc"]:
                self.log("Checking for Hold SOC slots")
                self.windows["hold_soc"].loc[
                    (self.windows["soc_end"] - self.windows["soc"]).abs()
                    < HOLD_TOLERANCE
                ] = "<="

            for window in self.windows.iterrows():
                self.log(
                    f"  {window[1]['start'].strftime('%d-%b %H:%M'):>13s} - {window[1]['end'].strftime('%d-%b %H:%M'):<13s}  Power: {window[1]['forced']:5.0f}W  SOC: {window[1]['soc']:4d}% -> {window[1]['soc_end']:4d}%  {window[1]['hold_soc']}"
                )

            self.charge_power = self.windows["forced"].iloc[0]
            self.charge_current = self.charge_power / self.get_config("battery_voltage")
            self.charge_start_datetime = self.windows["start"].iloc[0]
            self.charge_end_datetime = self.windows["end"].iloc[0]
            self.hold = [
                {
                    "active": self.windows["hold_soc"].iloc[i] == "<=",
                    "soc": self.windows["soc_end"].iloc[i],
                }
                for i in range(0, min(len(self.windows), 1))
            ]

        else:
            self.log(f"No charging slots")
            self.charge_current = 0
            self.charge_power = 0
            self.charge_start_datetime = self.static.index[0]
            self.charge_end_datetime = self.static.index[0]
            self.hold = []

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

    def write_to_hass(self, entity, state, attributes={}):
        try:
            self.set_state(state=state, entity_id=entity, attributes=attributes)
            self.log(f"Output written to {entity}")

        except Exception as e:
            self.log(f"Couldn't write to entity {entity}: {e}")

    def write_cost(self, name, entity, cost, df):
        cost_today = self._cost_today()
        midnight = pd.Timestamp.now(tz="UTC").normalize() + pd.Timedelta("24H")
        df = df.fillna(0).round(2)
        df["period_start"] = (
            df.index.tz_convert(self.tz).strftime("%Y-%m-%dT%H:%M:%S%z").str[:-2]
            + ":00"
        )
        cols = ["soc", "forced", "import", "export", "grid", "consumption"]

        cost = pd.DataFrame(pd.concat([cost_today, cost])).set_axis(["cost"], axis=1)
        cost["cumulative_cost"] = cost["cost"].cumsum()

        for d in [df, cost]:
            d["period_start"] = (
                d.index.tz_convert(self.tz).strftime("%Y-%m-%dT%H:%M:%S%z").str[:-2]
                + ":00"
            )

        state = round((cost["cost"].sum()) / 100, 2)

        attributes = (
            {
                "friendly_name": name,
                "unit_of_measurement": "GBP",
                "cost_today": round(
                    (cost["cost"].loc[: midnight - pd.Timedelta("30T")].sum()) / 100,
                    2,
                ),
                "cost_tomorrow": round((cost["cost"].loc[midnight:].sum()) / 100, 2),
            }
            | {
                col: df[["period_start", col]].to_dict("records")
                for col in cols
                if col in df.columns
            }
            | {"cost": cost[["period_start", "cumulative_cost"]].to_dict("records")}
        )

        self.write_to_hass(
            entity=entity,
            state=state,
            attributes=attributes,
        )

    def _write_output(self):
        self.write_cost(
            "PV Opt Base Cost",
            entity=f"sensor.{self.prefix}_base_cost",
            cost=self.base_cost,
            df=self.base,
        )

        self.write_cost(
            "PV Opt Optimised Cost",
            entity=f"sensor.{self.prefix}_opt_cost",
            cost=self.opt_cost,
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
                        for k in [
                            "start",
                            "end",
                            "forced",
                            "soc",
                            "soc_end",
                            "hold_soc",
                        ]
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

        for offset in [1, 4, 8, 12]:
            loc = pd.Timestamp.now(tz="UTC") + pd.Timedelta(f"{offset}H")
            locs = [loc.floor("30T"), loc.ceil("30T")]
            socs = [self.opt.loc[l]["soc"] for l in locs]
            soc = (loc - locs[0]) / (locs[1] - locs[0]) * (socs[1] - socs[0]) + socs[0]
            entity_id = f"sensor.{self.prefix}_soc_h{offset}"
            attributes = {
                "friendly_name": f"PV Opt Predicted SOC ({offset} hour delay)",
                "unit_of_measurement": "%",
                "state_class": "measurement",
                "device_class": "battery",
            }
            self.write_to_hass(entity=entity_id, state=soc, attributes=attributes)

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
            return

        try:
            # Convert to timestamps
            for s in solar:
                s["period_start"] = pd.Timestamp(s["period_start"])

            df = pd.DataFrame(solar)
            df = df.set_index("period_start")
            df.index = pd.to_datetime(df.index, utc=True)
            df = df.set_axis(["Solcast", "Solcast_p10", "Solcast_p90"], axis=1)

            df *= 1000
            df = df.fillna(0)
            # self.static = pd.concat([self.static, df], axis=1)
            self.log("Solcast forecast loaded OK")
            return df

        except Exception as e:
            self.log(f"Error loading Solcast: {e}", level="ERROR")
            return

    def load_consumption(self, start, end):
        self.log("Getting expected consumption data")
        index = pd.date_range(
            start,
            end,
            freq="30T",
            inclusive="left",
        )
        consumption = pd.DataFrame(index=index, data={"consumption": 0})
        for entity_id in self.config["id_consumption"]:
            try:
                df = self.hass2df(
                    entity_id,
                    days=int(self.get_config("consumption_history_days")),
                )

            except Exception as e:
                self.log(
                    f"Unable to get historical consumption from {entity_id}. {e}",
                    level="ERROR",
                )
                return

            df.index = pd.to_datetime(df.index)
            df = (
                pd.to_numeric(df, errors="coerce")
                .dropna()
                .resample("30T")
                .mean()
                .fillna(0)
            )

            df = df * (1 + self.get_config("consumption_margin") / 100)
            dfx = pd.Series(index=df.index, data=df.to_list())
            # Group by time and take the mean
            df = df.groupby(df.index.time).aggregate(
                self.get_config("consumption_grouping")
            )
            df.name = "consumption"

            temp = pd.DataFrame(index=index)
            temp["time"] = temp.index.time
            temp = temp.merge(df, "left", left_on="time", right_index=True)[
                "consumption"
            ] * (1 - self.get_config("day_of_week_weighting"))

            y = self.get_config("day_of_week_weighting") * dfx.iloc[: len(temp)]
            x = temp.to_numpy() + y.to_numpy()
            consumption["consumption"] += pd.Series(x, index=temp.index)
            self.log(f"  - Estimated consumption from {entity_id} loaded OK ")

        return consumption

    def _compare_tariffs(self):
        self.log("")
        self.log("Comparing yesterday's tariffs")
        solar = self._get_solar_yesterday()

    def _get_solar_yesterday(self):
        self.log("  - Getting yesterday's solar generation")
        entity_id = self.config["id_daily_solar"]
        if entity_id is None or not self.entity_exists(entity_id):
            return

        dt = pd.date_range(
            pd.Timestamp.now(tz="UTC").normalize() - pd.Timedelta("24H"),
            periods=49,
            freq="30T",
        )

        df = self.hass2df(entity_id, days=2).astype(float).resample("30T").ffill()
        df.index = pd.to_datetime(df.index)
        df = -df.loc[dt[0] : dt[-1]].diff(-1).clip(upper=0).iloc[:-1] * 2000
        return df

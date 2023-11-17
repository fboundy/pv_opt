# %%
import appdaemon.plugins.hass.hassapi as hass
import appdaemon.adbase as ad

# import mqttapi as mqtt
import pandas as pd

# import requests
# import datetime
import pvpy as pv
import numpy as np
from numpy import nan

# import pvpy as pv
OCTOPUS_PRODUCT_URL = r"https://api.octopus.energy/v1/products/"

# %%
#

VERSION = "2.1.0"

TIME_FORMAT = "%Y-%m-%d %H:%M:%S%z"

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
    "domain": "sensor",
    "tariff_code": "tariff",
    "rates": "current_rate",
}

IMPEXP = ["import", "export"]

DEFAULT_CONFIG = {
    "force_charge": {"default": True, "domain": "switch"},
    "force_discharge": {"default": True, "domain": "switch"},
    "manual_tariff": {"default": False, "domain": "switch"},
    "octopus_auto": {"default": True, "domain": "switch"},
    "solcast_integration": {"default": True, "domain": "switch"},
    "battery_capacity_Wh": {
        "default": 10000,
        "domain": "input_number",
        "attributes": {"min": 2000, "max": 20000, "step": 100},
    },
    "inverter_efficiency_percent": {
        "default": 97,
        "domain": "input_number",
        "attributes": {"min": 90, "max": 100, "step": 1},
    },
    "charger_efficiency_percent": {
        "default": 91,
        "domain": "input_number",
        "attributes": {"min": 80, "max": 100, "step": 1},
    },
    "maximum_dod_percent": {
        "default": 15,
        "domain": "input_number",
        "attributes": {"min": 0, "max": 50, "step": 1},
    },
    "charger_power_watts": {
        "default": 3000,
        "domain": "input_number",
        "attributes": {"min": 1000, "max": 10000, "step": 100},
    },
    "inverter_power_watts": {
        "default": 3600,
        "domain": "input_number",
        "attributes": {"min": 1000, "max": 10000, "step": 100},
    },
    "inverter_loss_watts": {
        "default": 100,
        "domain": "input_number",
        "attributes": {"min": 0, "max": 300, "step": 10},
    },
    "battery_voltage": {
        "default": 52,
        "domain": "input_number",
        "attributes": {"min": 48, "max": 55, "step": 1},
    },
    "solar_forecast": {
        "default": "Solcast",
        "options": ["Solcast p10", "Solcast p90"],
        "domain": "select",
    },
    "consumption_from_entity": {"default": True, "domain": "switch"},
    "consumption_history_days": {
        "default": 7,
        "domain": "input_number",
        "attributes": {"min": 1, "max": 28, "step": 1},
    },
    "consumption_margin": {
        "default": 0.1,
        "domain": "input_number",
        "attributes": {"min": 0, "max": 1, "step": 0.05},
    },
    "consumption_grouping": {
        "default": "mean",
        "domain": "select",
        "attributes": {"options": ["mean", "median", "max"]},
    },
    "alt_tariffs": {"default": [], "domain": "input_select"},
    "entity_id_consumption": {"default": "sensor.solis_house_load"},
    "entity_id_battery_soc": {"default": "sensor.solis_battery_soc"},
    "entity_id_solcast_today": {"default": "sensor.solcast_pv_forecast_forecast_today"},
    "entity_id_solcast_tomorrow": {
        "default": "sensor.solcast_pv_forecast_forecast_tomorrow"
    },
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
        self.log(f"INFO:  Time Zone Offset: {self.get_tz_offset()} minutes")
        self.change_items = {}
        self.cum_delta = {}

        self._load_args()

        self._status("Initialising PV Model")
        self.inverter = pv.HybridInverter(
            inverter_efficiency=self.config["inverter_efficiency_percent"] / 100,
            inverter_power=self.config["inverter_power_watts"],
            inverter_loss=self.config["inverter_loss_watts"],
            charger_efficiency=self.config["charger_efficiency_percent"] / 100,
            charger_power=self.config["charger_power_watts"],
        )
        self.battery = pv.Battery(
            capacity=self.config["battery_capacity_Wh"],
            max_dod=self.config["maximum_dod_percent"] / 100,
        )
        self.pv_system = pv.PVsystem(
            "PV_Opt", self.inverter, self.battery, log=self.log
        )
        self.load_contract()
        self._status("Idle")
        # # Optimise on an EVENT trigger:
        # self.listen_event(
        #     self.optimise_event,
        #     EVENT_TRIGGER,
        # )
        # self.listen_event(self.optimise_debug_event, DEBUG_TRIGGER)
        # # Optimise when the Solcast forecast changes:
        # self.log(self.config["entity_id_solcast_today"])
        # self.listen_state(
        #     self.optimise_state_change, self.config["entity_id_solcast_today"]
        # )

        # self.log(f"************** PV Opt Initialised ************")
        # self.log(f"******** Waiting for {EVENT_TRIGGER} Event *********")

    def load_contract(self):
        self.contract = None
        self.log("")
        self.log("INFO:  Loading Contract:")
        self.log("------------------------")
        try:
            if self.config["octopus_auto"]:
                self.log(f"INFO:  Trying to auto detect Octopus tariffs")

                octopus_entities = [
                    name
                    for name in self.get_state(BOTTLECAP_DAVE["domain"]).keys()
                    if (
                        "octopus_energy_electricity" in name
                        and BOTTLECAP_DAVE["rates"] in name
                    )
                ]

                entities = {}
                entities["import"] = [x for x in octopus_entities if not "export" in x]
                entities["export"] = [x for x in octopus_entities if "export" in x]

                for imp_exp in IMPEXP:
                    for entity in octopus_entities:
                        self.log(f"INFO:  Found {imp_exp} entity {entity}")

                tariffs = {x: None for x in IMPEXP}
                for imp_exp in IMPEXP:
                    if len(entities[imp_exp]) > 0:
                        tariff_code = self.get_state(
                            entities[imp_exp][0], attribute="all"
                        )["attributes"][BOTTLECAP_DAVE["tariff_code"]]
                        tariffs[imp_exp] = pv.Tariff(
                            tariff_code, export=(imp_exp == "export")
                        )

                self.contract = pv.Contract(
                    "current", imp=tariffs["import"], exp=tariffs["export"], base=self
                )
                self.log("INFO:  Contract tariffs loaded OK")
        except:
            self.log("WARN:  Failed to find tariff from Octopus Energy Integration")

        if self.contract is None:
            if ("octopus_account" in self.config) and (
                "octopus_api_key" in self.config
            ):
                if (self.config["octopus_account"] is not None) and (
                    self.config["octopus_api_key"] is not None
                ):
                    try:
                        self.log(
                            f"INFO:  Trying to load tariffs using Account: {self.config['octopus_account']} API Key: {self.config['octopus_api_key']}"
                        )
                        self.octopus_account = pv.OctopusAccount(
                            self.config["octopus_account"],
                            self.config["octopus_api_key"],
                        )

                        self.contract = pv.Contract(
                            "current", octopus_account=self.octopus_account, base=self
                        )
                        self.log("INFO:  Contract tariffs loaded OK")

                    except:
                        self.log(
                            "WARN:  Unable to load Octopus Account details using API Key"
                        )

        if self.contract is None:
            if (
                "octopus_import_tariff_code" in self.config
                and self.config["octopus_import_tariff_code"] is not None
            ):
                try:
                    str = f"INFO Trying to load tariff codes: Import: {self.config['octopus_import_tariff_code']}"

                    if "octopus_export_tariff_code" in self.config:
                        str += f" Export: {self.config['octopus_export_tariff_code']}"
                    self.log(str)

                    tariffs = {x: None for x in IMPEXP}
                    for imp_exp in IMPEXP:
                        if f"octopus_{imp_exp}_tariff_code" in self.config:
                            tariffs[imp_exp] = pv.Tariff(
                                self.config[f"octopus_{imp_exp}_tariff_code"],
                                export=(imp_exp == "export"),
                            )

                    self.contract = pv.Contract(
                        "current",
                        imp=tariffs["import"],
                        exp=tariffs["export"],
                        base=self,
                    )
                    self.log("INFO:  Contract tariffs loaded OK from Tariff Codes")
                except:
                    self.log("WARN: Unable to load Tariff Codes")

        if self.contract is None:
            e = "ERROR: Unable to load contract tariffs"
            self.log(e)
            self._status(e)
            raise ValueError(e)

        # else:
        #     self.log(self.contract.__str__())

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

        self.log("INFO:  Reading arguments from YAML:")
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
                    f"WARN:      {item:30s} = {str(self.config[item]):57s} Source: system default. Null entry found in YAML."
                )
            # if the item starts with 'entitiy_id' then it must be an entity that exists:
            elif "entity_id" in item:
                if min([self.entity_exists(v) for v in values]):
                    if len(values) == 1:
                        self.config[item] = values[0]
                    else:
                        self.config[item] = values

                    # for v in values:
                    #     self.change_items[v] = item

                    self.log(
                        f"INFO:      {item:30s} = {str(self.config[item]):57s} Source: value(s) in YAML"
                    )

                elif self.entity_exists(self.get_default_config(item)):
                    self.config = self.get_default_config(item)
                    self.log(
                        f"INFO:      {item:30s} = {str(self.config[item]):57s} Source: system default. Entities listed in YAML {value} do not all exist in HA."
                    )
                else:
                    e = f"ERROR:     {item:30s} : Neither the entities listed in the YAML {value} nor the system default of {self.get_default_config(item)} exist in HA."
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
                        f"INFO:      {item:30s} = {str(self.config[item]):57s} Source: value in YAML"
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
                            f"INFO:      {item:30s} = {str(self.config[item]):57s} Source: HA entities listed in YAML"
                        )
                    # if any of list but the last one are strings and the default for the item is a string
                    # try getting values from all the entities
                    elif valid_strings:
                        self.config[item] = valid_strings[0][0]
                        self.change_items[valid_strings[0][1]] = item
                        self.log(
                            f"INFO:      {item:30s} = {str(self.config[item]):57s} Source: HA entities listed in YAML"
                        )

                    elif len(values) > 1:
                        if self.same_type(values[-1], self.get_default_config(item)):
                            self.config[item] = values[-1]
                            self.log(
                                f"INFO:      {item:30s} = {str(self.config[item]):57s} Source: YAML default. Unable to read from HA entities listed in YAML."
                            )

                        elif values[-1] in self.get_default_config(item):
                            self.log(values)
                            self.config[item] = values[-1]
                            self.log(
                                f"INFO:      {item:30s} = {str(self.config[item]):57s} Source: YAML default. Unable to read from HA entities listed in YAML."
                            )
                    else:
                        if item in DEFAULT_CONFIG:
                            self.config[item] = self.get_default_config(item)

                            self.log(
                                f"ERROR:     {item:30s} = {str(self.config[item]):57s} Source: system default. Unable to read from HA entities listed in YAML. No default in YAML."
                            )
                        else:
                            self.config[item] = values[0]
                            self.log(
                                f"INFO:      {item:30s} = {str(self.config[item]):57s} Source: YAML default value. No default defined."
                            )

                elif len(values) == 1 and (
                    arg_types[bool][0] or arg_types[int][0] or arg_types[float][0]
                ):
                    if self.debug:
                        self.log("\tFound a single default value")

                    self.config[item] = values[0]
                    self.log(
                        f"INFO:      {item:30s} = {str(self.config[item]):57s} Source: value in YAML"
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
                            f"INFO:      {item:30s} = {str(self.config[item]):57s} Source: HA entities listed in YAML"
                        )
                        # If these change then we need to trigger automatically
                        for v in values[:-1]:
                            self.change_items[v] = item

                    else:
                        self.config[item] = values[-1]
                        self.log(
                            f"INFO:      {item:30s} = {str(self.config[item]):57s} Source: YAML default. Unable to read from HA entities listed in YAML."
                        )

                else:
                    self.config[item] = self.get_default_config(item)
                    self.log(
                        f"ERROR:     {item:30s} = {str(self.config[item]):57s} Source: system default. Invalid arguments in YAML."
                    )

        self.log("")
        self.log("INFO:  Checking config:")
        self.log("-----------------------")
        items_not_defined = [i for i in DEFAULT_CONFIG if i not in self.config]
        if len(items_not_defined) > 0:
            for item in DEFAULT_CONFIG:
                if item not in self.config:
                    self.config[item] = self.get_default_config(item)
                    self.log(
                        f"WARN:      {item:30s} = {str(self.config[item]):57s} Source: system default. Not in YAML."
                    )
        else:
            self.log("INFO:  All config items defined OK")

        self.log("")
        self.log("INFO:  Exposing config to Home Assistant:")
        self.log("-----------------------")
        self._expose_configs()

        if self.change_items:
            self.log("")
            self.log("INFO:  State change entities:")
            self.log("-----------------------------")
            for entity_id in self.change_items:
                self.log(
                    f"           {entity_id:>50s} -> {self.change_items[entity_id]:40s}"
                )
                self.listen_state(self.optimise_state_change, entity_id)
                self.cum_delta[entity_id] = 0

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
        untracked_items = [
            item
            for item in DEFAULT_CONFIG
            if (item not in [self.change_items[entity] for entity in self.change_items])
            and ("entity_id" not in item)
            and ("alt_" not in item)
        ]
        for item in untracked_items:
            entity_id = f"{DEFAULT_CONFIG[item]['domain']}.{self.prefix.lower()}_{item}"

            attributes = {"friendly_name": self._name_from_item(item)}
            if "attributes" in DEFAULT_CONFIG[item]:
                attributes = attributes | DEFAULT_CONFIG[item]["attributes"]

            if not self.entity_exists(entity_id=entity_id):
                self.log(f"INFO:  Creating HA Entity {entity_id} for {item}")
                self.set_state(
                    state=self._state_from_value(self.config[item]),
                    entity_id=entity_id,
                    attributes=attributes,
                )
                self.listen_state(self.optimise_state_change, entity_id)
            self.change_items[entity_id] = item

    def _status(self, status):
        entity_id = f"sensor.{self.prefix.lower()}_status"
        attributes = {"last_updated": pd.Timestamp.now().strftime(TIME_FORMAT)}
        self.set_state(state=status, entity_id=entity_id, attributes=attributes)

    @ad.app_lock
    def optimise_state_change(self, entity_id, attribute, old, new, kwargs):
        item = self.change_items[entity_id]
        delta = None
        value = None
        if "step" in DEFAULT_CONFIG[item]["attributes"]:
            delta = DEFAULT_CONFIG[item]["attributes"]["step"]
        try:
            self.cum_delta[entity_id] += float(new) - float(old)
            if self.cum_delta[entity_id] >= delta:
                self.log(
                    f"INFO:  Entity {entity_id} changed from {old} to {new}. Cumulative{self.cum_delta[entity_id]} vs {delta}"
                )
                value = self._value_from_state(new)
        except:
            self.log(f"INFO:  Entity {entity_id} changed from {old} to {new}. ")
            value = self._value_from_state(new)

        if value is not None:
            self.log(f"INFO:  State resolved to {value} [with type{type(value)}")
            # self.optimise()

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

        value = state

        return value

    def optimise_event(self, event_name, data, kwargs):
        self.log(f"********* {event_name} Event triggered **********")
        self.log(kwargs)
        self.optimise()

    def optimise_debug_event(self, event_name, data, kwargs):
        self.log(f"********* {event_name} Event triggered **********")
        debug_old = self.debug
        self.debug = True
        self.optimise()
        self.debug = debug_old

    def optimise(self):
        # initialse a DataFrame to cover today and tomorrow at 30 minute frequency
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
        try:
            if not self.load_solcast():
                raise Exception

        except Exception as e:
            self.log(f"Unable to load solar forecast: {e}")
            return False

        # Load the expected consumption
        try:
            if not self.load_consumption():
                raise Exception

        except Exception as e:
            self.log(f"Unable to load estimated consumption: {e}")
            return False

        self.time_now = pd.Timestamp.utcnow()
        self.static = self.static[self.time_now.floor("30T") :].fillna(0)
        self.soc_now = float(self.get_state(self.config["entity_id_battery_soc"]))

        # if self.config["alt_tariffs"] is None:
        #     self.tariffs = [None]
        # else:
        #     self.tariffs = self.config["alt_tariffs"] + [None]

        x = self.hass2df(
            self.config["entity_id_battery_soc"],
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

        self.base = self.pv_system.flows(
            self.initial_soc, self.static, solar=self.config["solar_forecast"]
        )
        self.base_cost = self.contract.net_cost(self.base)

        if self.debug:
            self.log(f'Optimising for {self.config["solar_forecast"]} forecast')

        self.opt = self.pv_system.optimised_force(
            self.initial_soc,
            self.static,
            self.contract,
            solar=self.config["solar_forecast"],
            discharge=True,
        )
        self.opt_cost = self.contract.net_cost(self.opt)

        if (self.opt["forced"] > 0).sum() > 0:
            charge_power = self.opt[self.opt["forced"] > 0].iloc[0]["forced"]
            self.charge_current = charge_power / self.config["battery_voltage"]
            self.log(f"First slot power:{charge_power}")
            charge_window = self.opt[self.opt["forced"] == charge_power]
            self.charge_start_datetime = charge_window.index[0]
            self.charge_end_datetime = charge_window.index[0] + pd.Timedelta("30T")

        else:
            self.log(f"No charging slots")
            self.charge_current = 0
            self.charge_start_datetime = self.static.index[0]
            self.charge_end_datetime = self.static.index[0]

        self.log(f"Elapsed time {pd.Timestamp.now()- self.t0}")

        if self.debug:
            self.log(f"Start time: {self.static.index[0]}")
            self.log(f"End time: {self.static.index[-1]}")
            self.log("Optimising for default prices")
            self.log(self.static.columns)
            self.log(f"Initial SOC: {self.initial_soc}")
            self.log(f"Base Cost: {self.base_cost.sum()}")
            self.log(f"Opt Cost: {self.opt_cost.sum()}")
            self.log(self.base.columns)
            self.log(self.opt.columns)
            self.log(self.base.iloc[-1])

        self.write_output()

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
            "Base",
            entity=OUTPUT_BASE_COST_ENTITY,
            cost=self.base_cost.sum(),
            df=self.base,
        )
        self.write_cost(
            "Opt", entity=OUTPUT_OPT_COST_ENTITY, cost=self.opt_cost.sum(), df=self.opt
        )

        self.write_to_hass(
            entity=OUTPUT_START_ENTITY,
            state=self.charge_start_datetime,
            attributes={
                "friendly_name": "PV_Opt Next Charge Period End",
            },
        )

        self.write_to_hass(
            entity=OUTPUT_END_ENTITY,
            state=self.charge_end_datetime,
            attributes={
                "friendly_name": "PV_Opt Next Charge Period End",
            },
        )

        self.write_to_hass(
            entity=OUTPUT_CURRENT_ENTITY,
            state=round(self.charge_current, 2),
            attributes={
                "unique_id": OUTPUT_CURRENT_ENTITY,
                "friendly_name": "PV_Opt Charging Current",
                "unit_of_measurement": "A",
                "state_class": "measurement",
                "device_class": "current",
            },
        )

    def load_solcast(self):
        if self.debug:
            self.log("Getting Solcast data")
        try:
            solar = self.get_state(
                self.config["entity_id_solcast_today"], attribute="all"
            )["attributes"]["detailedForecast"]
            solar += self.get_state(
                self.config["entity_id_solcast_tomorrow"], attribute="all"
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

            self.static = pd.concat([self.static, df.fillna(0)], axis=1)
            if self.debug:
                self.log("** Solcast forecast loaded OK **")
            return True

        except Exception as e:
            self.log(f"Error loading Solcast: {e}")
            return False

    def load_consumption(self):
        self.log("INFO:  Getting expected consumption data")

        if self.config["consumption_from_entity"]:
            try:
                # load history fot the last N days from the specified sensor
                # self.log(self.config["consumption_history_days"])
                df = self.hass2df(
                    self.config["entity_id_consumption"],
                    days=int(self.config["consumption_history_days"]),
                )

            except Exception as e:
                self.log(
                    f"Unable to get historical consumption from {self.config['entity_id_consumption']}"
                )
                self.log(f"Error: {e}")
                return False

            try:
                # df = pd.DataFrame(hist[0]).set_index("last_updated")["state"]
                df.index = pd.to_datetime(df.index)
                df = (
                    pd.to_numeric(df, errors="coerce")
                    .dropna()
                    .resample("30T")
                    .mean()
                    .fillna(0)
                )
                df *= 1 + self.config["consumption_margin"] / 100

                # Group by time and take the mean
                df = df.groupby(df.index.time).aggregate(
                    self.config["consumption_grouping"]
                )
                df.name = "consumption"

                self.static["time"] = self.static.index.time
                self.static = self.static.merge(
                    df, "left", left_on="time", right_index=True
                )

                if self.debug:
                    self.log("** Estimated consumption loaded OK **")
                return True

            except Exception as e:
                self.log(f"Error loading consumption data: {e}")
                return False

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
                    self.config["daily_consumption_Wh"] / -11000
                )
                return True

            except Exception as e:
                self.log(f"Error calculating modelled consumption data: {e}")
                return False


# %%

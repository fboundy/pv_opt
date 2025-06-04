# %%
from copy import copy
from datetime import datetime

import numpy as np
import pandas as pd
import requests
from numpy import isnan

OCTOPUS_PRODUCT_URL = r"https://api.octopus.energy/v1/products/"
AGILE_PREDICT_URL = r"https://agilepredict.com/api/"

TIME_FORMAT = "%d/%m %H:%M %Z"
MAX_ITERS = 3

AGILE_FACTORS = {
    "import": {
        "A": (0.21, 0, 13),
        "B": (0.20, 0, 14),
        "C": (0.20, 0, 12),
        "D": (0.22, 0, 13),
        "E": (0.21, 0, 12),
        "F": (0.21, 0, 12),
        "G": (0.21, 0, 12),
        "H": (0.21, 0, 12),
        "J": (0.22, 0, 12),
        "K": (0.22, 0, 12),
        "L": (0.23, 0, 11),
        "M": (0.20, 0, 13),
        "N": (0.21, 0, 13),
        "P": (0.24, 0, 12),
    },
    "export": {
        "A": (0.095, 1.09, 7.04),
        "B": (0.094, 0.78, 6.27),
        "C": (0.095, 1.30, 5.93),
        "D": (0.097, 1.26, 5.97),
        "E": (0.094, 0.77, 6.50),
        "F": (0.095, 0.87, 4.88),
        "G": (0.096, 1.10, 5.89),
        "H": (0.094, 0.93, 7.05),
        "J": (0.094, 1.09, 7.41),
        "K": (0.094, 0.97, 5.46),
        "L": (0.093, 0.83, 7.14),
        "M": (0.096, 0.72, 5.78),
        "N": (0.097, 0.90, 3.85),
        "P": (0.096, 1.36, 2.68),
    },
}

BOTTLECAP_DAVE = {
    "domain": "event",
    "tariff_code": "tariff_code",
    "rates": "current_day_rates",
}


# Tariff Class
# Calls "get octopus" to load the pricing information
# outputs self.unit.


def get_dt_hours(df: pd.DataFrame | pd.Series) -> pd.Series:
    df = pd.DataFrame(df)
    df["dt_hours"] = -df.index.diff(-1) / pd.Timedelta("60min")
    return df["dt_hours"].ffill()


class Tariff:
    def __init__(
        self,
        name,
        export=False,
        fixed=0,
        unit=0,
        valid_from=pd.Timestamp.now(tz="UTC").normalize() - pd.Timedelta(hours=24),
        day=None,
        night=None,
        eco7=False,
        octopus=True,
        eco7_start="01:00",
        host=None,
        manual=False,
        **kwargs,
    ) -> None:
        self.name = name
        self.host = host

        if host is None:
            self.log = print
            self.rlog = print
            self.tz = "GB"
        else:
            self.log = host.log
            self.rlog = host.rlog
            self.tz = host.tz

        # SVB logging
        # self.log("")
        # self.log("Entered pv.Tariff")
        # self.log("name = ")
        # self.log(name)

        self.export = export
        self.eco7 = eco7
        self.area = kwargs.get("area", None)
        self.day_ahead = None
        self.agile_predict = None
        self.eco7_start = pd.Timestamp(eco7_start, tz="UTC")
        self.manual = manual

        self.host.io_prices = {}

        if octopus:
            self.get_octopus_from_website(**kwargs)
            # self.log("")
            # self.log("Returned from get_octopus_from_website")
        else:

            if self.manual:
                self.unit = unit
                self.fixed = fixed
            else:
                self.fixed = [{"value_inc_vat": fixed, "valid_from": valid_from}]
                self.unit = [{"value_inc_vat": unit, "valid_from": valid_from}]
                if eco7:
                    self.day = [{"value_inc_vat": day, "valid_from": valid_from}]
                    self.night = [{"value_inc_vat": night, "valid_from": valid_from}]

        if "INTELLI" in name and not self.export:
            if self.host.get_config("octopus_auto"):
                try:
                    self.log(f"    Trying to find Octopus Intelligent Entities from Octopus Energy Integration:")
                    self.host.octopus_import_entity = [
                        name
                        for name in self.host.get_state_retry(BOTTLECAP_DAVE["domain"]).keys()
                        if (
                            "octopus_energy_electricity" in name
                            and BOTTLECAP_DAVE["rates"] in name
                            and not "export" in name
                        )
                    ]
                    self.rlog(f"      Octopus Intelligent Import Entity found: {self.host.octopus_import_entity}")

                    self.host.io_prices = self.host.get_io_tariffs(self.host.octopus_import_entity[0])
                    # self.host.io_prices = self.host.get_io_tariffs(self.host.octopus_import_entity)        # Error forcing: failure to load prices

                except Exception as e:
                    self.log(f"{e.__traceback__.tb_lineno}: {e}", level="ERROR")
                    self.log(
                        "Failed to find Octopus Intellgient tariffs from Octopus Energy Integration, extra IO slots will not be loaded",
                        level="WARNING",
                    )

    def _oct_time(self, d):
        # print(d)
        return datetime(
            year=pd.Timestamp(d).year,
            month=pd.Timestamp(d).month,
            day=pd.Timestamp(d).day,
        )

    def get_octopus_from_website(self, **kwargs):
        code = self.name
        product = code[5:-2]
        self.eco7 = code[:4] == "E-2R"
        self.area = code[-1]

        params = {
            "page_size": 500,
            "order_by": "period",
        } | {
            k: self._oct_time(kwargs.get(k, None))
            for k in ["period_from", "period_to"]
            if kwargs.get(k, None) is not None
        }

        if not self.export:
            url = f"{OCTOPUS_PRODUCT_URL}{product}/electricity-tariffs/{code}/standing-charges/"
            self.fixed = [
                x
                for x in requests.get(url, params=params).json()["results"]
                if x["payment_method"] != "NON_DIRECT_DEBIT"
            ]

        if self.eco7:
            url = f"{OCTOPUS_PRODUCT_URL}{product}/electricity-tariffs/{code}/day-unit-rates/"

            self.day = [
                x for x in requests.get(url, params=params).json()["results"] if x["payment_method"] == "DIRECT_DEBIT"
            ]
            url = f"{OCTOPUS_PRODUCT_URL}{product}/electricity-tariffs/{code}/night-unit-rates/"
            self.night = [
                x for x in requests.get(url, params=params).json()["results"] if x["payment_method"] == "DIRECT_DEBIT"
            ]
            self.unit = self.day

        else:
            url = f"{OCTOPUS_PRODUCT_URL}{product}/electricity-tariffs/{code}/standard-unit-rates/"
            self.unit = requests.get(url, params=params).json()["results"]
            # SVB logging
            # self.log("")
            # self.log("Printing self.unit")
            # self.log(self.unit)
            # self.log("")

    def __str__(self):
        if self.export:
            str = f"Export Tariff: {self.name}"
        else:
            str = f"Import Tariff: {self.name}"

        if self.eco7:
            str += " [Economy 7]"

        return str

    def start(self):
        if self.manual:
            return pd.Timestamp("2020-01-01", tz=self.tz)
        else:
            return min([pd.Timestamp(x["valid_from"]) for x in self.unit])

    def end(self):
        if self.manual:
            return pd.Timestamp.now(tz=self.tz)
        else:
            return max([pd.Timestamp(x["valid_to"]) for x in self.unit])

    def to_df(self, start=None, end=None, **kwargs):

        if self.host.debug and "V" in self.host.debug_cat:
            self.log(f">>> {self.name}")
            self.log(f">>> Start: {start.strftime(TIME_FORMAT)} End: {end.strftime(TIME_FORMAT)}")

        time_now = pd.Timestamp.now(tz="UTC")

        if start is None:
            if self.eco7:
                start = min([pd.Timestamp(x["valid_from"]) for x in self.day])

            elif self.manual:
                start = pd.Timestamp.now(tz=self.tz).floor("1D")

            else:
                start = min([pd.Timestamp(x["valid_from"]) for x in self.unit])

        if end is None:
            end = pd.Timestamp.now(tz=start.tzinfo).ceil("30min")

        use_day_ahead = kwargs.get("day_ahead", ((start > time_now) or (end > time_now)))

        if self.eco7:
            df = pd.concat(
                [pd.DataFrame(x).set_index("valid_from")["value_inc_vat"] for x in [self.day, self.night]],
                axis=1,
            ).set_axis(["unit", "Night"], axis=1)
            df.index = pd.to_datetime(df.index)
            df = df.sort_index()
            df = df.reindex(
                index=pd.date_range(
                    min([pd.Timestamp(x["valid_from"]) for x in self.day]),
                    end,
                    freq="30min",
                )
            ).ffill()
            mask = (df.index.time >= self.eco7_start.time()) & (
                df.index.time < (self.eco7_start + pd.Timedelta(7, "hours")).time()
            )
            df.loc[mask, "unit"] = df.loc[mask, "Night"]
            df = df["unit"].loc[start:end]

        elif self.manual:
            df = (
                pd.concat(
                    [
                        pd.DataFrame(
                            index=[midnight + pd.Timedelta(f"{x['period_start']}:00") for x in self.unit],
                            data=[{"unit": x["price"]} for x in self.unit],
                        ).sort_index()
                        for midnight in pd.date_range(
                            start.floor("1D") - pd.Timedelta("1D"),
                            end.ceil("1D"),
                            freq="1D",
                        )
                    ]
                )
                .resample("30min")
                .ffill()
                .loc[start:end]
            )

        else:
            df = pd.DataFrame(self.unit).set_index("valid_from")["value_inc_vat"]
            df.index = pd.to_datetime(df.index)
            df = df.sort_index()
            if "AGILE" in self.name and use_day_ahead:
                if self.agile_predict is None:
                    self.agile_predict = self._get_agile_predict()

                if self.agile_predict is not None:
                    df = pd.concat(
                        [
                            df,
                            self.agile_predict.loc[df.index[-1] + pd.Timedelta("30min") : end],
                        ]
                    )

            # If the index frequency >30 minutes so we need to just extend it:
            if (len(df) > 1 and ((df.index[-1] - df.index[-2]).total_seconds() / 60) > 30) or len(df) == 1:
                newindex = pd.date_range(df.index[0], end, freq="30min")
                df = df.reindex(index=newindex).ffill().loc[start:]
            else:
                i = 0
                while df.index[-1] < end and i < 7:
                    i += 1
                    extended_index = pd.date_range(
                        df.index[-1] + pd.Timedelta(30, "minutes"),
                        df.index[-1] + pd.Timedelta(24, "hours"),
                        freq="30min",
                    )
                    dfx = pd.concat([df, pd.DataFrame(index=extended_index)]).shift(48).loc[extended_index[0] :]
                    df = pd.concat([df, dfx])
                    df = df[df.columns[0]]
                df = df.loc[start:end]
            df.name = "unit"

            # SVB logging
            # self.log("")
            # self.log("Printin df just before concat.....")
            # self.log(df.to_string())

            # SVB #
            # It is at this point that df now looks like the Dataframe that compare_tariffs loads. This is the point
            # to overwrite the Df with IOG data from the BottlecapDave integration, loaded in pv_opt.py and passed in here via self.host.io_prices.
            # (SVB Note: io_prices should be passed in via Class, but I cannot figure out the structure of Tariff and Contract Classes to do this)

            if len(self.host.io_prices) > 0 and "INTELLI" in self.name:
                # Add IO slot prices as a column to dataframe.
                df = pd.concat([df, self.host.io_prices], axis=1).set_axis(["unit", "io_unit"], axis=1)

                df = df.dropna(subset=["unit"])  # Drop Nans
                mask = df["io_unit"] < df["unit"]  # Mask is true if an IOslot
                df.loc[mask, "unit"] = df[
                    "io_unit"
                ]  # Overwrite unit (prices from website) with io_unit (prices from OE integration) if in an IOslot.
                df = df.drop(["io_unit"], axis=1)  # remove IO prices column

                # SVB logging
                # self.log("To_df, Printing result")
                # self.log(df.to_string())

        # Add a column "fixed" for the standing charge.
        if not self.export:
            if not self.manual:
                x = pd.DataFrame(self.fixed).set_index("valid_from")["value_inc_vat"].sort_index()
                x.index = pd.to_datetime(x.index)
                newindex = pd.date_range(x.index[0], df.index[-1], freq="30min")
                x = x.reindex(newindex).sort_index()
                x = x.ffill().loc[df.index[0] :]
            else:
                x = pd.DataFrame(index=df.index, data={"fixed": self.fixed})

            df = pd.concat([df, x], axis=1).set_axis(["unit", "fixed"], axis=1)
            mask = df.index.time != pd.Timestamp("00:00", tz="UTC").time()
            df.loc[mask, "fixed"] = 0

        df = pd.DataFrame(df)
        # SVB logging
        # self.log("")
        # self.log("Printing final result of to_df.....")
        # self.log(df.to_string())

        # Update for Octopus Savings Events if they exists
        if (self.host is not None) and ("unit" in df.columns):
            events = self.host.saving_events
            for id in events:
                event_start = pd.Timestamp(events[id]["start"], tz="UTC").floor("30min")
                event_end = pd.Timestamp(events[id]["end"], tz="UTC").ceil("30min")
                event_value = int(events[id]["octopoints_per_kwh"]) / 8

                self.log("Savings Events debugging")
                self.log("")
                self.log(f"start = {start}")
                self.log(f"end = {end}")
                self.log(f"event_start = {event_start}")
                self.log(f"event_end = {event_end}")

                if event_start <= end or event_end > start and event_value > 0:
                    event_start = max(event_start, start)
                    event_end = min(event_end - pd.Timedelta(30, "minutes"), end)

                    self.log("Recalculating event_start and event_end")
                    self.log("")
                    self.log(f"event_start = {event_start}")
                    self.log(f"event_end = {event_end}")
                    self.log(f"event_value = {event_value}")

                    df.loc[event_start:event_end, "unit"] += event_value

        return df

    def _get_agile_predict(self):
        url = f"{AGILE_PREDICT_URL}{self.area}?days=2&high_low=false"
        try:
            r = requests.get(url)
            r.raise_for_status()  # Raise an exception for unsuccessful HTTP status codes

        except requests.exceptions.RequestException as e:
            return

        df = pd.DataFrame(r.json()[0]["prices"]).set_index("date_time")
        df.index = pd.to_datetime(df.index, utc=True)
        return df["agile_pred"]

    def get_day_ahead(self, start):
        url = "https://www.nordpoolgroup.com/api/marketdata/page/325?currency=GBP"

        try:
            r = requests.get(url)
            r.raise_for_status()  # Raise an exception for unsuccessful HTTP status codes

        except requests.exceptions.RequestException as e:
            return

        index = []
        data = []
        for row in r.json()["data"]["Rows"]:
            str = ""
            # pprint.pprint(row)

            for column in row:
                if isinstance(row[column], list):
                    for i in row[column]:
                        if i["CombinedName"] == "CET/CEST time":
                            if len(i["Value"]) > 10:
                                time = f"T{i['Value'][:2]}:00"
                                # print(time)
                        else:
                            if len(i["Name"]) > 8:
                                try:
                                    # self.log(time, i["Name"], i["Value"])
                                    data.append(float(i["Value"].replace(",", ".")))
                                    index.append(
                                        pd.Timestamp(
                                            i["Name"].split("-")[2]
                                            + "-"
                                            + i["Name"].split("-")[1]
                                            + "-"
                                            + i["Name"].split("-")[0]
                                            + " "
                                            + time
                                        )
                                    )
                                except:
                                    pass

        price = pd.Series(index=index, data=data).sort_index()
        price.index = price.index.tz_localize("CET")
        price.index = price.index.tz_convert("UTC")
        price = price[~price.index.duplicated()]
        return price.resample("30min").ffill().loc[start:]


class InverterModel:
    """Describes the inverter

    Attributes:
        inverter_efficiency: A float describing the DC-AC efficiency of the inverter.
        charger_efficiency: A float describing the AC-DC efficiency of the inverter.
        inverter_loss: An int describing the internal power consumption of the inverter at zero load.
        inverter_power: An int describing the DC-AC power of the inverter.
        charger_power: An int describing the AC-CC power of the inverter.
    """

    def __init__(
        self,
        inverter_efficiency: float = 0.97,
        charger_efficiency: float = 0.91,
        inverter_loss: int = 100,
        inverter_power: int = 3000,
        charger_power: int = 3500,
    ) -> None:
        self.inverter_efficiency = inverter_efficiency
        self.charger_efficiency = charger_efficiency
        self.inverter_power = inverter_power
        self.charger_power = charger_power
        self.inverter_loss = inverter_loss

    def __str__(self):
        pass

    # def calibrate(self, data, **kwargs):
    #     cols = {k: kwargs.get(k, k) for k in ["solar", "consumption", "grid", "battery", "soc"]}

    #     # Cealculate inverter efficiency when no grid flow
    #     mask = (data[cols["grid"]] <= 0) & (data[cols["battery"]] >= 0)
    #     x = (data[cols["battery"]] + data[cols["solar"]])[mask]
    #     y = (data[cols["consumption"]] - data[cols["grid"]])[mask]
    #     print(sum(mask))
    #     plt.scatter(x, y)

    #     slope, intercept, r_value, p_value, std_err = linregress(x, y)

    #     self.inverter_efficiency = slope
    #     self.inverter_loss = -intercept

    #     return mask


class BatteryModel:
    """Describes the battery system attached to the inverter

    Attributes:
        capacity: An integer describing the Wh capacity of the battery.
        max_dod: A float describing the maximum depth of discharge of the battery.
        current_limit_amps: An int describing the maximum amps at which the battery can charge/discharge.
        voltage: An int describing the voltage of the battery system.
    """

    def __init__(
        self,
        capacity: int,
        max_dod: float = 0.15,
        current_limit_amps: int = 100,
        voltage: int = 50,
    ) -> None:
        self.capacity = capacity
        self.max_dod = max_dod
        self.current_limit_amps = current_limit_amps
        self.voltage = voltage

    def __str__(self):
        pass

    @property
    def max_charge_power(self) -> int:
        """returns the maximum watts at which the battery can charge."""
        try:
            max_charge_power = self.current_limit_amps * self.voltage
        except:
            self.log(
                f"Unable to calculate max_charge_power from current limit {self.current_limit_amps} x voltage {self.voltage}",
                level="WARINING",
            )
            max_charge_power = 100000
        return max_charge_power

    @property
    def max_discharge_power(self) -> int:
        """returns the maximum watts at which the battery can discharge."""
        return self.max_charge_power


class OctopusAccount:
    def __init__(self, account_number, api_key) -> None:
        self.account_number = account_number
        self.api_key = api_key

    def __str__(self):
        str = f"Account Number: {self.account_number}\n"
        str += f"API Key: {self.api_key}"


# Contract Class.
# Has the tariff code passed in, or gets it from your Octopus Account using your Octopus Account details
# Also contains the function net_cost, which calculates cost based on predicted power flows.
# No other functions.
class Contract:
    def __init__(
        self,
        name: str,
        imp: Tariff = None,
        exp: Tariff = None,
        octopus_account: OctopusAccount = None,
        host=None,
    ) -> None:

        self.name = name
        self.host = host
        if self.host:
            self.log = host.log
            self.rlog = host.rlog
            self.tz = host.tz
        else:
            self.log = print
            self.rlog = print
            self.tz = "GB"

        if imp is None and octopus_account is None:
            raise ValueError("Either a named import tariff or Octopus Account details much be provided")

        self.tariffs = {}

        if octopus_account is None:
            self.tariffs["import"] = imp
            self.tariffs["export"] = exp

        else:
            url = f"https://api.octopus.energy/v1/accounts/{octopus_account.account_number}/"
            self.rlog(f"Connecting to {url}")
            try:
                r = requests.get(url, auth=(octopus_account.api_key, ""))
                r.raise_for_status()  # Raise an exception for unsuccessful HTTP status codes

            except requests.exceptions.RequestException as e:
                self.rlog(f"HTTP error occurred: {e}")
                self.tariffs["import"] = None
                return

            self.host.mpans = r.json()["properties"][0]["electricity_meter_points"]
            for mpan in self.mpans:
                self.redact_patterns.append(mpan["mpan"])

            for mpan in self.host.mpans:
                self.rlog(f"Getting details for MPAN {mpan['mpan']}")
                df = pd.DataFrame(mpan["agreements"])
                df = df.set_index("valid_from")
                df.index = pd.to_datetime(df.index)
                df = df.sort_index()
                tariff_code = df["tariff_code"].iloc[-1]

                self.rlog(f"Retrieved most recent tariff code {tariff_code}")
                if mpan["is_export"]:
                    self.tariffs["export"] = Tariff(tariff_code, export=True, host=self.host)
                else:
                    self.tariffs["import"] = Tariff(tariff_code, host=self.host)

            if self.tariffs["import"] is None:
                e = "Either a named import tariff or valid Octopus Account details much be provided"
                self.rlog(e, level="ERROR")
                raise ValueError(e)

    def __str__(self):
        str = f"Contract: {self.name}\n"
        str += f'{"-"*(11 + len(self.name))}\n\n'
        for tariff in self.tariffs:
            str += f"{tariff.__str__()}\n"
        return str

    def net_cost(self, grid_flow, sum=True, decimals=1, **kwargs):
        if len(grid_flow) == 0:
            return pd.Series()

        grid_import = kwargs.pop("grid_import", "grid_import")
        grid_export = kwargs.pop("grid_export", "grid_export")
        grid_col = kwargs.pop("grid_col", "grid")
        start = grid_flow.index[0]
        end = grid_flow.index[-1]

        # SVB debugging
        # self.log(f"Start = {start}, End = {end}")
        

        if (
            isinstance(grid_flow, pd.DataFrame)
            and (grid_export in grid_flow.columns)
            and (grid_import in grid_flow.columns)
        ):
            grid_imp = grid_flow[grid_import]
            grid_exp = grid_flow[grid_export]
        else:
            if isinstance(grid_flow, pd.DataFrame):
                grid_flow = grid_flow[grid_col]

            grid_imp = grid_flow.clip(0)
            grid_exp = grid_flow.clip(upper=0)

        dt = get_dt_hours(grid_flow)
         

        # imp_df = self.tariffs["import"].to_df(start, end, **kwargs)
        imp_df = self.tariffs["import"].to_df(start=start.floor("30min"), end=end, **kwargs)
        imp_df.index = [start] + list(imp_df.index[1:])


        # SVB logging
        #self.log("dt = ")
        # self.log(f"\n{dt.to_string()}")
        # self.log("imp_df = ")
        # self.log(f"\n{imp_df.to_string()}")
        # self.log("grid_imp = ")
        # self.log(f"\n{grid_imp.to_string()}")
        # self.log("grid_exp = ")
        # self.log(f"\n{grid_exp.to_string()}")

        nc = imp_df["fixed"]
        nc += imp_df["unit"] * grid_imp / 1000 * dt

        if self.tariffs["export"] is not None:
            exp_df = self.tariffs["export"].to_df(start=start.floor("30min"), end=end, **kwargs)
            exp_df.index = [start] + list(exp_df.index[1:])
            nc += exp_df["unit"] * grid_exp / 1000 * dt


        if kwargs.get("log") and (self.host.debug and "F" in self.host.debug_cat):
            self.rlog(f">>> Import{self.tariffs['import'].to_df(start,end).to_string()}")
            self.rlog(f">>> Export{self.tariffs['export'].to_df(start,end).to_string()}")

        if self.host.debug and "F" in self.host.debug_cat:
            self.log("")
            self.log(">>> Return from net_cost routine")
            self.log(f">>> net_cost returned is {nc}")


        # SVB logging
        # self.log("nc.sum = ")
        # self.log(nc.sum().round(decimals))
        # self.log("nc = ")
        # self.log(f"\n{nc.to_string()}")

        if sum:
            return nc.sum().round(decimals)
        else:
            return nc

    def prices(self, start=None, end=None):
        prices = pd.concat(
            [
                self.tariffs[direction].to_df(start=start.floor("30min"), end=end)["unit"]
                for direction in self.tariffs
                if self.tariffs[direction] is not None
            ],
            axis=1,
        )

        prices.index = [start] + list(prices.index[1:])

        return prices


class PVsystemModel:
    def __init__(self, name: str, inverter: InverterModel, battery: BatteryModel, host=None) -> None:
        self.name = name
        self.inverter = inverter
        self.battery = battery
        self.host = host
        if host:
            self.log = host.log
            self.tz = host.tz
        else:
            self.log = print
            self.tz = "GB"
        self.prices = None
        self.static_flows = None
        self.solar_id = "solar"
        self.consumption_id = "consumption"
        self.flows = None
        self.contract = None

    def __str__(self):
        pass

    def calculate_flows(self, slots=[], solar_id="solar", consumption_id="consumption", **kwargs):
        # solar = self.static_flows[solar_id]
        # consumption = self.static_flows[consumption_id]

        self.flows = self.static_flows.copy()[[solar_id, consumption_id]].set_axis(["solar", "consumption"], axis=1)
        self.flows["dt_hours"] = get_dt_hours(self.flows)
        self.flows["battery_grid_requirement"] = self.flows["consumption"] - self.flows["solar"]
        self.flows["forced"] = 0
        self.flows["battery_temp"] = self.flows["consumption"] - self.flows["solar"]
        # forced_charge = pd.Series(index=self.flows.index, data=0)

        if len(slots) > 0:
            timed_slot_flows = pd.Series(index=self.flows.index, data=0)

            for t, c in slots:
                if not isnan(c):
                    timed_slot_flows.loc[t] += int(c)

            chg_mask = timed_slot_flows != 0
            # self.flows["battery_temp"][chg_mask] = -timed_slot_flows[chg_mask]
            # self.flows["forced"][chg_mask] = timed_slot_flows[chg_mask]

            self.flows.loc[chg_mask, "battery_temp"] = -timed_slot_flows[chg_mask]
            self.flows.loc[chg_mask, "forced"] = timed_slot_flows[chg_mask]

        chg = [self.initial_soc / 100 * self.battery.capacity]

        for idx in self.flows.index:
            flow = self.flows["battery_temp"].loc[idx]
            dt_hours = self.flows["dt_hours"].loc[idx]

            if flow > 0:
                flow = flow / self.inverter.inverter_efficiency
            else:
                flow = flow * self.inverter.charger_efficiency

            chg.append(
                round(
                    max(
                        [
                            min(
                                [
                                    chg[-1] - flow * dt_hours,
                                    self.battery.capacity,
                                ]
                            ),
                            self.battery.max_dod * self.battery.capacity,
                        ]
                    ),
                    1,
                )
            )

        self.flows["chg"] = chg[:-1]
        self.flows["chg"] = self.flows["chg"].ffill()
        self.flows["chg_end"] = chg[1:]
        self.flows["chg_end"] = self.flows["chg_end"].bfill()
        self.flows["battery"] = pd.Series(chg).diff(-1)[:-1].to_list()
        self.flows["battery"] /= self.flows["dt_hours"]
        self.flows.loc[self.flows["battery"] > 0, "battery"] = (
            self.flows["battery"] * self.inverter.inverter_efficiency
        )
        self.flows.loc[self.flows["battery"] < 0, "battery"] = self.flows["battery"] / self.inverter.charger_efficiency
        self.flows["grid"] = (self.flows["battery_grid_requirement"] - self.flows["battery"]).round(0)
        self.flows["soc"] = (self.flows["chg"] / self.battery.capacity) * 100
        self.flows["soc_end"] = (self.flows["chg_end"] / self.battery.capacity) * 100

        if self.prices is not None:
            self.flows = pd.concat(
                [self.flows, self.prices],
                axis=1,
            )

    @property
    def net_cost(self):
        if self.flows is not None:
            return self.contract.net_cost(self.flows)

    def optimised_force(
        self,
        log=True,
        discharge=False,
        use_export=True,
        max_iters=MAX_ITERS,
    ):

        if log and (self.host.debug and "B" in self.host.debug_cat):
            self.log("Called optimised_force")

        start = self.static_flows.index[0]
        end = self.static_flows.index[-1]

        self.prices = self.contract.prices(start=start, end=end)
        self.prices = self.prices.set_axis(
            [t for t in self.contract.tariffs.keys() if self.contract.tariffs[t] is not None],
            axis=1,
        )

        if not use_export:
            if log:
                self.log(f"Ignoring export pricing because Use Export is turned off")
            discharge = False
            self.prices["export"] = 0

        if log and (self.host.debug and "B" in self.host.debug_cat):
            self.log("")
            self.log("Prices is")
            self.log(f"\n{self.prices.to_string()}")
            self.log("")

        if log:
            self.log(
                f"Optimiser prices loaded for period {self.prices.index[0].strftime(TIME_FORMAT)} - {self.prices.index[-1].strftime(TIME_FORMAT)}"
            )

        self.calculate_flows()
        self.base_cost = self.net_cost
        self.best_cost = self.base_cost
        self.net_costs = [self.base_cost]

        if log:
            self.log(f"Base cost:  {self.base_cost}")

        self._high_cost_swaps(log=log)

        # Only do the rest if there is an export tariff:
        # self.log(f"Sum of Export Prices = {prices['export'].sum()}")
        if self.prices["export"].sum() > 0:
            j = 0
        else:
            j = max_iters

        self.slots_added = 999

        while (self.slots_added > 0) and (j < max_iters):
            j += 1
            # No need to iterate if this is charge only
            if not discharge:
                j += max_iters

            self._low_cost_charging(log=log)

            if log:
                self.log(f"Iteration {j:2d}: Slots added: {self.slots_added:3d}")

            if discharge:
                self._discharging(log=log)

        self.calculate_flows(slots=self.slots)

        # df.index = pd.to_datetime(df.index)

        if (not self.host.get_config("allow_cyclic")) and (len(self.slots) > 0) and discharge:
            if log:
                self.log("")
                self.log("Removing cyclic charge/discharge")
            a = self.flows["forced"][self.flows["forced"] != 0].to_dict()
            new_slots = [(k, a[k]) for k in a]

            revised_slots = []
            skip_flag = False
            for i, x in enumerate(zip(new_slots[:-1], new_slots[1:])):

                if (
                    (int(x[0][1]) == self.inverter.charger_power)
                    & (int(-x[1][1]) == self.inverter.charger_power)
                    & (x[1][0] - x[0][0] == pd.Timedelta("30min"))
                ):
                    skip_flag = True
                    if log:
                        self.log(
                            f"  Skipping slots at {x[0][0].strftime(TIME_FORMAT)} ({x[0][1]}W) and {x[1][0].strftime(TIME_FORMAT)} ({x[1][1]}W)"
                        )
                elif skip_flag:
                    skip_flag = False
                else:
                    revised_slots.append(x[0])
                    if i == len(new_slots) - 2:
                        revised_slots.append(x[1])

            self.calculate_flows(slots=revised_slots)

            best_cost_new = self.net_cost
            if log:
                self.log(f"  Net cost revised from {self.best_cost:0.1f}p to {best_cost_new:0.1f}p")
            slots = revised_slots
            # self.flows.index = pd.to_datetime(df.index)
        return self.flows

    def _search_window(self, df: pd.DataFrame, available: pd.Series, max_slot):
        # Need to check why this .iloc[:-1] is here....
        x = df.loc[: max_slot - pd.Timedelta("30min")].copy()
        if len(x) > 0:
            x = x[available.loc[: max_slot - pd.Timedelta("30min")]]
            x["countback"] = (x["soc_end"] >= 97).sum() - (x["soc_end"] >= 97).cumsum()
            x = x[x["countback"] == 0]
            x = x[x["forced"] < (self.inverter.charger_power)]
            x = x[x["soc_end"] <= 97]
        return x

    def _high_cost_swaps(self, log=True):
        # --------------------------------------------------------------------------------------------
        #  Charging 1st Pass
        # --------------------------------------------------------------------------------------------
        if log:
            self.log("")
            self.log("High Cost Usage Swaps")
            self.log("---------------------")
            self.log("")

            if log and (self.host.debug and "C" in self.host.debug_cat):
                self.log(
                    "SPR = Slot Power Required, SCPA = Slot Charger Power Available, SAC = Slot Available Capacity, RSC = Remaining Slot Capacity"
                )
                self.log("")

        done = False
        i = 0
        slots = []
        available = pd.Series(index=self.flows.index, data=(self.flows["forced"] == 0))
        tested = pd.Series(index=self.flows.index, data=False)
        slot_count = [0]
        best_cost = self.base_cost

        while not done:
            i += 1

            if (i > 96) or (available.sum() == 0):
                done = True

            import_cost = ((self.flows["import"] * self.flows["grid"]).clip(0) * self.flows["dt_hours"] / 1000)[
                ~tested
            ]

            if len(import_cost[self.flows["forced"] == 0]) > 0:
                max_import_cost = import_cost[self.flows["forced"] == 0].max()
                if len(import_cost[import_cost == max_import_cost]) > 0:
                    max_slot = import_cost[import_cost == max_import_cost].index[0]
                    max_slot_energy = round(
                        self.flows["grid"].loc[max_slot] / 1000 * self.flows["dt_hours"].loc[max_slot], 2
                    )  # kWh
                    str_log = f"{i:3d} {available.sum():3d} {max_slot.tz_convert(self.tz).strftime(TIME_FORMAT)}:"

                    if max_slot_energy > 0:
                        round_trip_energy_required = (
                            max_slot_energy / self.inverter.charger_efficiency / self.inverter.inverter_efficiency
                        )

                        search_window = self._search_window(self.flows, available, max_slot)
                        str_log += f" {round_trip_energy_required:5.2f} kWh at {max_import_cost:6.2f}p. "

                        if len(search_window) > 0:
                            min_price = search_window["import"].min()

                            window = search_window[search_window["import"] == min_price].index
                            start_window = window[0]
                            end_window = window[-1]

                            cost_at_min_price = round_trip_energy_required * min_price

                            str_log += f"<==> {start_window.tz_convert(self.tz).strftime(TIME_FORMAT)}: {min_price:5.2f}p/kWh {cost_at_min_price:5.2f}p "
                            str_log += f" SOC: {search_window.loc[window[0]]['soc']:5.1f}%->{search_window.loc[window[-1]]['soc_end']:5.1f}% "

                            slot_power_required = (
                                round_trip_energy_required * 1000 / search_window["dt_hours"].loc[window].sum()
                            )

                            if round(cost_at_min_price, 1) < round(max_import_cost, 1):
                                slots_added = 0
                                j = 1
                                for slot in window:
                                    slot_charger_power_available = max(
                                        self.inverter.charger_power
                                        - search_window["forced"].loc[slot]
                                        - search_window["solar"].loc[slot],
                                        0,
                                    )
                                    slot_available_capacity = max(
                                        ((100 - search_window["soc_end"].loc[slot]) / 100 * self.battery.capacity)
                                        / search_window["dt_hours"].loc[slot],
                                        0,
                                    )
                                    min_power = min(
                                        slot_power_required,
                                        slot_charger_power_available,
                                        slot_available_capacity,
                                    )
                                    remaining_slot_capacity = slot_charger_power_available - min_power

                                    if remaining_slot_capacity < 10:
                                        available[slot] = False

                                    if log and self.host.debug:
                                        # if log:
                                        str_log_x = (
                                            # f">>> {i:3d} Slot: {slot.strftime(TIME_FORMAT)} Factor: {factor:0.3f} Forced: {search_window['forced'].loc[slot]:6.0f}W  "
                                            f">>> {i:3d} Slot: {slot.strftime(TIME_FORMAT)} Forced: {search_window['forced'].loc[slot]:6.0f}W  "
                                            + f"End SOC: {search_window['soc_end'].loc[slot]:4.1f}%  SPR: {slot_power_required:6.0f}W  "
                                            + f"SCPA: {slot_charger_power_available:6.0f}W  SAC: {slot_available_capacity:6.0f}W  Min Power: {min_power:6.0f}W "
                                            + f"RSC: {remaining_slot_capacity:6.0f}W"
                                        )
                                        if not available[slot]:
                                            str_log_x += " <== FULL"
                                        self.log(str_log_x)

                                    slots.append(
                                        (
                                            slot,
                                            round(min_power, 0),
                                        )
                                    )
                                    slots_added += 1

                                self.calculate_flows(slots=slots)
                                self.net_costs.append(self.net_cost)

                                slot_count.append(len(window))

                                str_log += f"New SOC: {self.flows.loc[start_window]['soc']:5.1f}%->{self.flows.loc[end_window]['soc_end']:5.1f}% "
                                best_cost = self.net_costs[-1]
                                str_log += f"Net: {best_cost:6.1f}"

                                if log:
                                    self.log(str_log)

                            else:
                                if log:
                                    self.log(str_log + "No cheaper slots")
                                tested.loc[max_slot] = True
                        else:
                            if log:
                                self.log(str_log + "No search window")
                            tested.loc[max_slot] = True
                else:
                    done = True
            else:
                self.log("No slots available")
                done = True

        self.calculate_flows(slots=slots)
        self.best_cost = self.net_cost

        if self.base_cost - best_cost <= self.host.get_config("pass_threshold_p"):
            if log:
                self.log(
                    f"Charge net cost delta:  {self.base_cost - best_cost:0.1f}p: < Pass Threshold ({self.host.get_config('pass_threshold_p'):0.1f}p) => Slots Excluded"
                )
            slots = []
            self.best_cost = self.base_cost
            self.calculate_flows()

        self.slots = slots

    def _low_cost_charging(self, log=True):
        slots = [slot for slot in self.slots]
        best_cost = self.best_cost
        slots_added = 0

        # Check how many slots which aren't full are at an import price less than any export price:
        max_export_price = self.flows[self.flows["forced"] <= 0]["export"].max()
        if log:
            self.log("")
            self.log("Low Cost Charging")
            self.log("------------------")
            self.log("")

        # net_cost_previous = best_cost

        if log:
            self.log(f"Max export price when there is no forced charge: {max_export_price:0.2f}p/kWh.")

        i = 0
        available = (
            (self.flows["import"] < max_export_price)
            & (self.flows["forced"] < self.inverter.charger_power)
            & (self.flows["forced"] >= 0)
        )

        a0 = available.sum()
        if log:
            self.log(f"{available.sum()} slots have an import price less than the max export price")
        done = available.sum() == 0

        if self.host.debug and "C" in self.host.debug_cat:
            self.log("Self.flows is")
            self.log(f"\n{self.flows.to_string()}")
            self.log("")
            self.log(f"best_cost = {best_cost}")
            self.log("")

        while not done:
            x = (
                self.flows.loc[available]
                .loc[self.flows["import"] < max_export_price]
                .loc[self.flows["forced"] < self.inverter.charger_power]
                .loc[self.flows["forced"] >= 0]
                .copy()
            )
            i += 1
            done = i > a0

            min_price = x["import"].min()

            # Add rounding to ensure matching (may not be needed)
            x["import"] = x["import"].round(2)
            min_price = min_price.round(2)

            if len(x[x["import"] == min_price]) > 0:
                start_window = x[x["import"] == min_price].index[0]
                available.loc[start_window] = False
                str_log = ""
                str_log = f"{available.sum():>2d} Min import price {min_price:5.2f}p/kWh at {start_window.strftime(TIME_FORMAT)} {x.loc[start_window]['forced']:4.0f}W "

                str_log += "  "

                str_log += f"SOC: {x.loc[start_window]['soc']:5.1f}%->{x.loc[start_window]['soc_end']:5.1f}% "

                if self.host.debug and "C" in self.host.debug_cat:
                    self.log(
                        f"SOC (before modelling Forced Charge): {x.loc[start_window]['soc']:5.1f}%->{x.loc[start_window]['soc_end']:5.1f}% "
                    )

                forced_charge = min(
                    min(self.battery.max_charge_power, self.inverter.charger_power)- x["forced"].loc[start_window] - x["solar"].loc[start_window],
                    ((100 - x["soc_end"].loc[start_window]) / 100 * self.battery.capacity) / x["dt_hours"].loc[start_window],
                )

                if self.host.debug and "C" in self.host.debug_cat:
                    value1 = min(self.battery.max_charge_power, self.inverter.charger_power)- x["forced"].loc[start_window] - x["solar"].loc[start_window]
                    value2 = ((100 - x["soc_end"].loc[start_window]) / 100 * self.battery.capacity) 
                    value3 = x["dt_hours"].loc[start_window]
                    value4 = ((100 - x["soc_end"].loc[start_window]) / 100 * self.battery.capacity) / x["dt_hours"].loc[start_window]
                    self.log(f"Start window = {start_window}")
                    self.log(f"Value 1 = {value1:6.1f}, Value2 = {value2:6.1f}, Value3 = {value3:6.1f}, Value4 = {value4:6.1f}")
                    self.log(f"Forced Charge = {forced_charge}")
                slot = (
                    start_window,
                    forced_charge,
                )

                slots.append(slot)

                self.calculate_flows(slots=slots)
            

                if self.host.debug and "F" in self.host.debug_cat:
                    self.log("self.flows after flows called = ")
                    self.log(f"\n{self.flows.to_string()}")

                net_cost = self.net_cost

                if self.host.debug and "C" in self.host.debug_cat:
                    self.log(f"Cost = {net_cost:5.1f}")
                    if net_cost < best_cost:
                        self.log("Cost reduction found - printing flows")
                        self.log(f"\n{self.flows.to_string()}")


                str_log += f"Net: {net_cost:5.1f} "
                if net_cost < best_cost - self.host.get_config("slot_threshold_p"):
                    str_log += f"New SOC: {self.flows.loc[start_window]['soc']:5.1f}%->{self.flows.loc[start_window]['soc_end']:5.1f}% "
                    str_log += f"Max export: {-self.flows['grid'].min():0.0f}W "
                    best_cost = net_cost
                    slots_added += 1
                    if log:
                        self.log(str_log)
                else:
                    # done = True
                    slots = slots[:-1]
                    self.calculate_flows(slots=slots)

                done = available.sum() == 0
            else:
                done = True

        cost_delta = best_cost - self.best_cost
        str_log = f"Charge net cost delta:{(-cost_delta):5.1f}p"
        if cost_delta > -self.host.get_config("pass_threshold_p"):
            self.slots_added = 0
            str_log += f": < Pass Threshold {self.host.get_config('pass_threshold_p'):0.1f}p => Slots Excluded"
            self.calculate_flows(slots=self.slots)
        else:
            str_log += f": > Pass Threshold {self.host.get_config('pass_threshold_p'):0.1f}p => Slots Included"
            self.slots = slots
            self.slots_added = slots_added
            self.best_cost = best_cost

        if log:
            self.log("")
            self.log(str_log)

    def _discharging(self, log=True):
        # -----------
        # Discharging
        # -----------
        slots = [slot for slot in self.slots]
        best_cost = self.best_cost
        slots_added = self.slots_added

        # Check how many slots which aren't full are at an export price less than any import price:
        min_import_price = self.flows["import"].min()
        if log:
            self.log("")
            self.log("Forced Discharging")
            self.log("------------------")
            self.log("")

        i = 0
        available = (self.flows["export"] > min_import_price) & (self.flows["forced"] == 0)
        a0 = available.sum()
        if log:
            self.log(f"{available.sum()} slots have an export price greater than the min import price")
        done = available.sum() == 0

        while not done:
            x = self.flows[available].copy()
            i += 1
            done = i > a0
            max_price = x["export"].max()

            if len(x[x["export"] == max_price]) > 0:
                # self.log("Entered routine successfully")
                start_window = x[x["export"] == max_price].index[0]
                available.loc[start_window] = False
                str_log = f"{available.sum():>2d} Max export price {max_price:5.2f}p/kWh at {start_window.strftime(TIME_FORMAT)} "
                str_log += "  "

                str_log += f"SOC: {x.loc[start_window]['soc']:5.1f}%->{x.loc[start_window]['soc_end']:5.1f}% "

                slot = (
                    start_window,
                    -min(
                        min(
                            self.battery.max_discharge_power,
                            self.inverter.charger_power,
                        )
                        - x["solar"].loc[start_window],
                        ((x["soc_end"].loc[start_window] - self.battery.max_dod) / 100 * self.battery.capacity)
                        / x["dt_hours"].loc[start_window],
                    ),
                )

                slots.append(slot)

                self.calculate_flows(slots=slots)

                if self.host.debug and "F" in self.host.debug_cat:
                    self.log("self.flows after flows called = ")
                    self.log(f"\n{self.flows.to_string()}")

                net_cost = self.net_cost

                str_log += f"Net: {net_cost:5.1f} "
                if net_cost < best_cost - self.host.get_config("slot_threshold_p"):
                    str_log += f"New SOC: {self.flows.loc[start_window]['soc']:5.1f}%->{self.flows.loc[start_window]['soc_end']:5.1f}% "
                    str_log += f"Max export: {-self.flows['grid'].min():0.0f}W "
                    best_cost = net_cost
                    slots_added += 1
                    if log:
                        self.log(str_log)
                else:
                    # done = True
                    slots = slots[:-1]
                    self.calculate_flows(slots=slots)
            else:
                done = True

        cost_delta = best_cost - self.best_cost
        str_log = f"Discharge net cost delta:{(-cost_delta):5.1f}p"
        if cost_delta > -self.host.get_config("discharge_threshold_p"):
            str_log += (
                f": < Discharge threshold ({self.host.get_config('discharge_threshold_p'):0.1f}p) => Slots excluded"
            )
        else:
            str_log += (
                f": > Discharge Threshold ({self.host.get_config('discharge_threshold_p'):0.1f}p) => Slots included"
            )
            self.slots = slots
            self.slots_added = slots_added
            self.best_cost = best_cost

        if log:
            self.log("")
            self.log(str_log)


# %%

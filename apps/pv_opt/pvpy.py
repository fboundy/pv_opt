# %%
import pandas as pd
import requests
from copy import copy

# from scipy.stats import linregress
from datetime import datetime

OCTOPUS_PRODUCT_URL = r"https://api.octopus.energy/v1/products/"
TIME_FORMAT = "%d/%m %H:%M"
COST_DELTA_THRESHOLD = -4.0
COST_DELTA_THRESHOLD_SLOT = -1.0


class Tariff:
    def __init__(
        self,
        name,
        export=False,
        fixed=None,
        unit=None,
        day=None,
        night=None,
        eco7=False,
        octopus=True,
        eco7_start="01:00",
        host=None,
        **kwargs,
    ) -> None:
        self.name = name
        self.host = host
        if host is None:
            self.log = print
        else:
            self.log = host.log

        self.export = export
        self.eco7 = eco7
        self.area = kwargs.get("area", None)
        self.day_ahead = None
        self.eco7_start = pd.Timestamp(eco7_start, tz="UTC")

        if octopus:
            self.get_octopus(**kwargs)

        else:
            self.fixed = fixed
            self.unit = unit
            self.day = day
            self.night = night

    def _oct_time(self, d):
        # print(d)
        return datetime(
            year=pd.Timestamp(d).year,
            month=pd.Timestamp(d).month,
            day=pd.Timestamp(d).day,
        )

    def get_octopus(self, **kwargs):
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
                x
                for x in requests.get(url, params=params).json()["results"]
                if x["payment_method"] == "DIRECT_DEBIT"
            ]
            url = f"{OCTOPUS_PRODUCT_URL}{product}/electricity-tariffs/{code}/night-unit-rates/"
            self.night = [
                x
                for x in requests.get(url, params=params).json()["results"]
                if x["payment_method"] == "DIRECT_DEBIT"
            ]
            self.unit = self.day

        else:
            url = f"{OCTOPUS_PRODUCT_URL}{product}/electricity-tariffs/{code}/standard-unit-rates/"
            self.unit = requests.get(url, params=params).json()["results"]

        if self.host.debug and "AGILE" not in code:
            self.log(f">>> {code}: Unit Cost")
            for x in self.unit:
                self.log(f">>> {x}")

    def __str__(self):
        if self.export:
            str = f"Export Tariff: {self.name}"
        else:
            str = f"Import Tariff: {self.name}"

        if self.eco7:
            str += " [Economy 7]"

        return str

    def start(self):
        return min([pd.Timestamp(x["valid_from"]) for x in self.unit])

    def end(self):
        return max([pd.Timestamp(x["valid_to"]) for x in self.unit])

    def to_df(self, start=None, end=None, **kwargs):
        if self.host.debug:
            self.log(f">>> {self.name}")
            self.log(
                f">>> Start: {start.strftime(TIME_FORMAT)} End: {end.strftime(TIME_FORMAT)}"
            )

        use_day_ahead = kwargs.get("day_ahead", True)
        if start is None:
            if self.eco7:
                start = min([pd.Timestamp(x["valid_from"]) for x in self.day])

            else:
                start = min([pd.Timestamp(x["valid_from"]) for x in self.unit])

        if end is None:
            end = pd.Timestamp.now(tz=start.tzinfo).ceil("30T")

        # self.get_octopus(area=self.area, period_from=start, period_to=end)

        if self.eco7:
            df = pd.concat(
                [
                    pd.DataFrame(x).set_index("valid_from")["value_inc_vat"]
                    for x in [self.day, self.night]
                ],
                axis=1,
            ).set_axis(["unit", "Night"], axis=1)
            df.index = pd.to_datetime(df.index)
            df = df.sort_index()
            df = df.reindex(
                index=pd.date_range(
                    min([pd.Timestamp(x["valid_from"]) for x in self.day]),
                    end,
                    freq="30T",
                )
            ).ffill()
            mask = (df.index.time >= self.eco7_start.time()) & (
                df.index.time < (self.eco7_start + pd.Timedelta(7, "hours")).time()
            )
            df.loc[mask, "unit"] = df.loc[mask, "Night"]
            df = df["unit"].loc[start:end]

        else:
            df = pd.DataFrame(self.unit).set_index("valid_from")["value_inc_vat"]
            df.index = pd.to_datetime(df.index)
            df = df.sort_index()

            if "AGILE" in self.name and use_day_ahead:
                if self.day_ahead is not None and df.index[-1].day == end.day:
                    # reset the day ahead forecasts if we've got a forecast going into tomorrow
                    self.day_ahead = None
                    self.log("")
                    self.log(f"Cleared day ahead forecast for tariff {self.name}")

                if self.host.debug:
                    self.log(f">>> {df.index[-1].day}  {end.day}")

                if pd.Timestamp.now(tz="UTC").hour > 11 and df.index[-1].day != end.day:
                    # if it is after 11 but we don't have new Agile prices yet, check for a day-ahead forecast
                    if self.day_ahead is None:
                        self.day_ahead = self.get_day_ahead(df.index[0])
                        self.day_ahead = self.day_ahead.sort_index()
                        self.log("")
                        self.log(
                            f"Retrieved day ahead forecast for period {self.day_ahead.index[0].strftime(TIME_FORMAT)} - {self.day_ahead.index[-1].strftime(TIME_FORMAT)} for tariff {self.name}"
                        )

                    if self.day_ahead is not None:
                        mask = (self.day_ahead.index.hour >= 16) & (
                            self.day_ahead.index.hour < 19
                        )
                        agile = (
                            pd.concat(
                                [
                                    self.day_ahead[mask] * 0.186 + 16.5,
                                    self.day_ahead[~mask] * 0.229 - 0.6,
                                ]
                            )
                            .sort_index()
                            .loc[df.index[-1] :]
                            .iloc[1:]
                        )

                        df = pd.concat([df, agile])

            # If the index frequency >30 minutes so we need to just extend it:
            if (
                len(df) > 1
                and ((df.index[-1] - df.index[-2]).total_seconds() / 60) > 30
            ) or len(df) == 1:
                newindex = pd.date_range(df.index[0], end, freq="30T")
                df = df.reindex(index=newindex).ffill().loc[start:]
            else:
                if self.host.debug:
                    self.log(">>> Index <= 30")

                i = 0
                while df.index[-1] < end and i < 7:
                    i += 1
                    extended_index = pd.date_range(
                        df.index[-1] + pd.Timedelta(30, "minutes"),
                        df.index[-1] + pd.Timedelta(24, "hours"),
                        freq="30T",
                    )
                    dfx = (
                        pd.concat([df, pd.DataFrame(index=extended_index)])
                        .shift(48)
                        .loc[extended_index[0] :]
                    )
                    df = pd.concat([df, dfx])
                    df = df[df.columns[0]]
                df = df.loc[start:end]
            df.name = "unit"

        if not self.export:
            x = (
                pd.DataFrame(self.fixed)
                .set_index("valid_from")["value_inc_vat"]
                .sort_index()
            )
            x.index = pd.to_datetime(x.index)
            newindex = pd.date_range(x.index[0], df.index[-1], freq="30T")
            x = x.reindex(newindex).sort_index()
            x = x.ffill().loc[df.index[0] :]
            df = pd.concat([df, x], axis=1).set_axis(["unit", "fixed"], axis=1)

            mask = df.index.time != pd.Timestamp("00:00", tz="UTC").time()
            df.loc[mask, "fixed"] = 0

        df = pd.DataFrame(df)
        # Update for Octopus Savings Events if they exists
        if (self.host is not None) and ("unit" in df.columns):
            events = self.host.saving_events
            for id in events:
                event_start = pd.Timestamp(events[id]["start"])
                event_end = pd.Timestamp(events[id]["end"])
                event_value = int(events[id]["octopoints_per_kwh"]) / 8

                if event_start <= end or event_end > start:
                    event_start = max(event_start, start)
                    event_end = min(event_end - pd.Timedelta(30, "minutes"), end)
                    df["unit"].loc[event_start:event_end] += event_value

        return df

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
                                print(time)
                        else:
                            if len(i["Name"]) > 8:
                                print(i["Name"])
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

        price = pd.Series(index=index, data=data).sort_index()
        price.index = price.index.tz_localize("CET")
        price.index = price.index.tz_convert("UTC")
        price = price[~price.index.duplicated()]
        return price.resample("30T").ffill().loc[start:]


class InverterModel:
    def __init__(
        self,
        inverter_efficiency=0.97,
        charger_efficiency=0.91,
        inverter_loss=100,
        inverter_power=3000,
        charger_power=3500,
    ) -> None:
        self.inverter_efficiency = inverter_efficiency
        self.charger_efficiency = charger_efficiency
        self.inverter_power = inverter_power
        self.charger_power = charger_power
        self.inverter_loss = inverter_loss

    # def __str__(self):
    #     pass

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
    def __init__(self, capacity: int, max_dod: float = 0.15) -> None:
        self.capacity = capacity
        self.max_dod = max_dod

    def __str__(self):
        pass


class OctopusAccount:
    def __init__(self, account_number, api_key) -> None:
        self.account_number = account_number
        self.api_key = api_key

    def __str__(self):
        str = f"Account Number: {self.account_number}\n"
        str += f"API Key: {self.api_key}"


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
        else:
            self.log = print

        if imp is None and octopus_account is None:
            raise ValueError(
                "Either a named import tariff or Octopus Account details much be provided"
            )

        if octopus_account is None:
            self.imp = imp
            self.exp = exp

        else:
            url = f"https://api.octopus.energy/v1/accounts/{octopus_account.account_number}/"
            self.log(f"Connecting to {url}")
            try:
                r = requests.get(url, auth=(octopus_account.api_key, ""))
                r.raise_for_status()  # Raise an exception for unsuccessful HTTP status codes

            except requests.exceptions.RequestException as e:
                self.log(f"HTTP error occurred: {e}")
                self.imp = None
                return

            mpans = r.json()["properties"][0]["electricity_meter_points"]
            for mpan in mpans:
                self.log(f"Getting details for MPAN {mpan['mpan']}")
                df = pd.DataFrame(mpan["agreements"])
                df = df.set_index("valid_from")
                df.index = pd.to_datetime(df.index)
                df = df.sort_index()
                tariff_code = df["tariff_code"].iloc[-1]

                self.log(f"Retrieved most recent tariff code {tariff_code}")
                if mpan["is_export"]:
                    self.exp = Tariff(tariff_code, export=True, host=self.host)
                else:
                    self.imp = Tariff(tariff_code, host=self.host)

            if self.imp is None:
                e = "Either a named import tariff or valid Octopus Account details much be provided"
                self.log(e, level="ERROR")
                raise ValueError(e)

    def __str__(self):
        str = f"Contract: {self.name}\n"
        str += f'{"-"*(11 + len(self.name))}\n\n'
        for tariff in [self.imp, self.exp]:
            str += f"{tariff.__str__()}\n"
        return str

    def net_cost(self, grid_flow, **kwargs):
        if len(grid_flow) == 0:
            return pd.Series()

        grid_import = kwargs.pop("grid_import", "grid_import")
        grid_export = kwargs.pop("grid_export", "grid_export")
        grid_col = kwargs.pop("grid_col", "grid")
        start = grid_flow.index[0]
        end = grid_flow.index[-1]
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

        imp_df = self.imp.to_df(start, end, **kwargs)
        nc = imp_df["fixed"]
        if kwargs.get("log"):
            self.log(f">>> Import{self.imp.to_df(start,end).to_string()}")
        nc += imp_df["unit"] * grid_imp / 2000
        if kwargs.get("log"):
            self.log(f">>> Export{self.exp.to_df(start,end).to_string()}")
        nc += self.exp.to_df(start, end, **kwargs)["unit"] * grid_exp / 2000

        return nc


class PVsystemModel:
    def __init__(
        self, name: str, inverter: InverterModel, battery: BatteryModel, host=None
    ) -> None:
        self.name = name
        self.inverter = inverter
        self.battery = battery
        self.host = host
        if host:
            self.log = host.log
        else:
            self.log = print

    def __str__(self):
        pass

    def flows(self, initial_soc, static_flows, slots=[], soc_now=None, **kwargs):
        cols = {k: kwargs.get(k, k) for k in ["solar", "consumption"]}
        solar = static_flows[cols["solar"]]
        consumption = static_flows[cols["consumption"]]

        df = static_flows.copy()

        battery_flows = solar - consumption
        forced_charge = pd.Series(index=df.index, data=0)

        if len(slots) > 0:
            timed_slot_flows = pd.Series(index=df.index, data=0)

            for t, c in slots:
                timed_slot_flows.loc[t] += int(c)

            chg_mask = timed_slot_flows != 0
            battery_flows[chg_mask] = timed_slot_flows[chg_mask]
            forced_charge[chg_mask] = timed_slot_flows[chg_mask]

        if soc_now is None:
            chg = [initial_soc / 100 * self.battery.capacity]
            freq = pd.infer_freq(static_flows.index) / pd.Timedelta(60, "minutes")

        else:
            chg = [soc_now[1] / 100 * self.battery.capacity]
            freq = (soc_now[0] - df.index[0]) / pd.Timedelta(60, "minutes")

        for i, flow in enumerate(battery_flows):
            if flow < 0:
                flow = flow / self.inverter.inverter_efficiency
            else:
                flow = flow * self.inverter.charger_efficiency

            chg.append(
                round(
                    max(
                        [
                            min(
                                [
                                    chg[-1] + flow * freq,
                                    self.battery.capacity,
                                ]
                            ),
                            self.battery.max_dod * self.battery.capacity,
                        ]
                    ),
                    1,
                )
            )
            if (soc_now is not None) and (i == 0):
                freq = pd.infer_freq(static_flows.index) / pd.Timedelta(60, "minutes")

        if soc_now is not None:
            chg[0] = [initial_soc / 100 * self.battery.capacity]

        df["chg"] = chg[:-1]
        df["chg"] = df["chg"].ffill()
        df["chg_end"] = chg[1:]
        df["chg_end"] = df["chg_end"].bfill()
        df["battery"] = (pd.Series(chg).diff(-1) / freq)[:-1].to_list()
        df.loc[df["battery"] > 0, "battery"] = (
            df["battery"] * self.inverter.inverter_efficiency
        )
        df.loc[df["battery"] < 0, "battery"] = (
            df["battery"] / self.inverter.charger_efficiency
        )
        df["grid"] = -(solar - consumption + df["battery"]).round(0)
        df["forced"] = forced_charge
        df["soc"] = (df["chg"] / self.battery.capacity) * 100
        df["soc_end"] = (df["chg_end"] / self.battery.capacity) * 100

        return df

    def optimised_force(self, initial_soc, static_flows, contract: Contract, **kwargs):
        log = kwargs.pop("log", True)

        cols = {k: kwargs.get(k, k) for k in ["consumption"]}
        consumption = static_flows[cols["consumption"]]
        consumption.name = "consumption"

        discharge = kwargs.pop("discharge", False)
        max_iters = kwargs.pop("max_iters", 3)

        prices = pd.DataFrame()
        for tariff in [contract.imp, contract.exp]:
            prices = pd.concat(
                [
                    prices,
                    tariff.to_df(
                        start=static_flows.index[0], end=static_flows.index[-1]
                    )["unit"],
                ],
                axis=1,
            )

        if log:
            self.log(
                f"  Optimiser prices loaded for period {prices.index[0].strftime(TIME_FORMAT)} - {prices.index[-1].strftime(TIME_FORMAT)}"
            )

        prices = prices.set_axis(["import", "export"], axis=1)

        df = pd.concat(
            [prices, consumption, self.flows(initial_soc, static_flows, **kwargs)],
            axis=1,
        )
        base_cost = contract.net_cost(df).sum()
        net_cost = []
        net_cost_opt = base_cost

        slots = []

        # --------------------------------------------------------------------------------------------
        #  Charging 1st Pass
        # --------------------------------------------------------------------------------------------
        if log:
            self.log("")
            self.log("High Cost Usage Swaps")
            self.log("---------------------")
            self.log("")

        done = False
        i = 0
        df = pd.concat(
            [
                prices,
                consumption,
                self.flows(initial_soc, static_flows, slots=slots, **kwargs),
            ],
            axis=1,
        )
        available = pd.Series(index=df.index, data=(df["forced"] == 0))
        net_cost = [base_cost]
        slot_count = [0]
        while not done:
            i += 1
            if (i > 96) or (available.sum() == 0):
                done = True

            import_cost = ((df["import"] * df["grid"]).clip(0) / 2000)[available]
            if len(import_cost[df["forced"] == 0]) > 0:
                max_import_cost = import_cost[df["forced"] == 0].max()
                max_slot = import_cost[import_cost == max_import_cost].index[0]

                max_slot_energy = df["grid"].loc[max_slot] / 2000  # kWh

                if max_slot_energy > 0:
                    round_trip_energy_required = (
                        max_slot_energy
                        / self.inverter.charger_efficiency
                        / self.inverter.inverter_efficiency
                    )

                    # potential windows end at the max_slot
                    x = df.loc[:max_slot].copy()

                    # count back to find the slots where soc_end < 100
                    x["countback"] = (x["soc_end"] >= 97).sum() - (
                        x["soc_end"] >= 97
                    ).cumsum()

                    x = x[x["countback"] == 0]

                    # ignore slots which are already fully charging
                    x = x[x["forced"] < self.inverter.charger_power]

                    x = x[x["soc_end"] <= 97]

                    search_window = x.index
                    str_log = f"{max_slot.strftime(TIME_FORMAT)}: {round_trip_energy_required:5.2f} kWh at {max_import_cost:6.2f}p. "
                    if len(search_window) > 0:
                        # str_log += f"Window: [{search_window[0].strftime(TIME_FORMAT)}-{search_window[-1].strftime(TIME_FORMAT)}] "
                        pass
                    else:
                        # str_log = "No available window."
                        done = True
                    if len(x) > 0:
                        min_price = x["import"].min()
                        # self.log(
                        #     f">>> {min_price} {x.index[0].strftime(TIME_FORMAT)} - {x.index[-1].strftime(TIME_FORMAT)}"
                        # )
                        window = x[x["import"] == min_price].index
                        start_window = window[0]

                        cost_at_min_price = round_trip_energy_required * min_price
                        str_log += f"<==> {start_window.strftime(TIME_FORMAT)}: {min_price:5.2f}p/kWh {cost_at_min_price:5.2f}p "
                        str_log += f" SOC: {x.loc[window[0]]['soc']:5.1f}%->{x.loc[window[-1]]['soc_end']:5.1f}% "
                        factors = []
                        for slot in window:
                            if pd.Timestamp.now() > slot.tz_localize(None):
                                factors.append(
                                    (
                                        (
                                            slot.tz_localize(None)
                                            + pd.Timedelta(30, "minutes")
                                        )
                                        - pd.Timestamp.now()
                                    ).total_seconds()
                                    / 1800
                                )
                            else:
                                factors.append(1)

                        factors = [f / sum(factors) for f in factors]

                        if round(cost_at_min_price, 1) < round(max_import_cost, 1):
                            for slot, factor in zip(window, factors):
                                slots.append(
                                    (
                                        slot,
                                        round(
                                            min(
                                                round_trip_energy_required
                                                * 2000
                                                * factor,
                                                self.inverter.charger_power
                                                - x["forced"].loc[slot],
                                                (
                                                    (100 - x["soc_end"].loc[slot])
                                                    / 100
                                                    * self.battery.capacity
                                                )
                                                * 2
                                                * factor,
                                            ),
                                            0,
                                        ),
                                    )
                                )

                            df = pd.concat(
                                [
                                    prices,
                                    consumption,
                                    self.flows(
                                        initial_soc, static_flows, slots=slots, **kwargs
                                    ),
                                ],
                                axis=1,
                            )
                            net_cost.append(round(contract.net_cost(df).sum(), 1))
                            slot_count.append(len(factors))
                            str_log += f"New SOC: {df.loc[start_window]['soc']:5.1f}%->{df.loc[start_window]['soc_end']:5.1f}% "
                            net_cost_opt = net_cost[-1]
                            str_log += f"Net: {net_cost_opt:6.1f}"
                            if log:
                                self.log(str_log)
                        else:
                            available[max_slot] = False
                else:
                    done = True
            else:
                done = True

        z = pd.DataFrame(data={"net_cost": net_cost, "slot_count": slot_count})
        z["slot_total"] = z["slot_count"].cumsum()
        z["delta"] = z["net_cost"].diff()
        max_delta = z["net_cost"].diff().iloc[1:].max()
        if log:
            self.log("")
            self.log(f"Maximum 1st pass slot delta is {max_delta:0.1f}p")
            self.log("")

        df = pd.concat(
            [
                prices,
                self.flows(initial_soc, static_flows, slots=slots, **kwargs),
            ],
            axis=1,
        )

        slots_added = 999
        j = 0

        while (slots_added > 0) and (j < max_iters):
            slots_added = 0
            j += 1
            # No need to iterate if this is charge only
            if not discharge:
                j += max_iters

            # Check how many slots which aren't full are at an import price less than any export price:
            max_export_price = df[df["forced"] <= 0]["export"].max()
            if log:
                self.log("")
                self.log("Low Cost Charging")
                self.log("------------------")
                self.log("")

            net_cost_pre = net_cost_opt
            slots_pre = copy(slots)

            if log:
                self.log(
                    f"Max export price when there is no forced charge: {max_export_price:0.2f}p/kWh."
                )
                # self.log(
                #     f">>> Charger power: {self.inverter.charger_power}. Inverter power: {self.inverter.inverter_power}"
                # )

            i = 0
            available = (
                (df["import"] < max_export_price)
                & (df["forced"] < self.inverter.charger_power)
                & (df["forced"] >= 0)
            )
            # self.log((df["import"]<max_export_price)
            a0 = available.sum()
            if log:
                self.log(
                    f"{available.sum()} slots have an import price less than the max export price"
                )
            done = available.sum() == 0

            while not done:
                x = df[available][df["import"] < max_export_price][
                    df["forced"] < self.inverter.charger_power
                ][df["forced"] >= 0].copy()
                i += 1
                done = i > a0

                min_price = x["import"].min()

                if len(x[x["import"] == min_price]) > 0:
                    start_window = x[x["import"] == min_price].index[0]
                    available.loc[start_window] = False
                    str_log = f"{available.sum():>2d} Min import price {min_price:5.2f}p/kWh at {start_window.strftime(TIME_FORMAT)} {x.loc[start_window]['forced']:4.0f}W "

                    if (pd.Timestamp.now() > start_window.tz_localize(None)) and (
                        pd.Timestamp.now()
                        < start_window.tz_localize(None) + pd.Timedelta(30, "minutes")
                    ):
                        str_log += "* "
                        factor = (
                            (
                                start_window.tz_localize(None)
                                + pd.Timedelta(30, "minutes")
                            )
                            - pd.Timestamp.now()
                        ).total_seconds() / 1800
                    else:
                        str_log += "  "
                        factor = 1

                    str_log += f"SOC: {x.loc[start_window]['soc']:5.1f}%->{x.loc[start_window]['soc_end']:5.1f}% "

                    forced_charge = min(
                        self.inverter.charger_power - x["forced"].loc[start_window],
                        (
                            (100 - x["soc_end"].loc[start_window])
                            / 100
                            * self.battery.capacity
                        )
                        * 2
                        * factor,
                    )

                    # self.log(f">>> {forced_charge} {factor}")
                    slot = (
                        start_window,
                        forced_charge,
                    )

                    slots.append(slot)

                    df = pd.concat(
                        [
                            prices,
                            self.flows(
                                initial_soc, static_flows, slots=slots, **kwargs
                            ),
                        ],
                        axis=1,
                    )

                    net_cost = contract.net_cost(df).sum()
                    str_log += f"Net: {net_cost:5.1f} "
                    if net_cost < net_cost_opt - self.host.get_config(
                        "slot_threshold_p"
                    ):
                        str_log += f"New SOC: {df.loc[start_window]['soc']:5.1f}%->{df.loc[start_window]['soc_end']:5.1f}% "
                        str_log += f"Max export: {-df['grid'].min():0.0f}W "
                        net_cost_opt = net_cost
                        slots_added += 1
                        if log:
                            self.log(str_log)
                    else:
                        # done = True
                        slots = slots[:-1]
                        df = pd.concat(
                            [
                                prices,
                                self.flows(
                                    initial_soc, static_flows, slots=slots, **kwargs
                                ),
                            ],
                            axis=1,
                        )

                    done = available.sum() == 0
                else:
                    done = True

            cost_delta = net_cost_opt - net_cost_pre
            str_log = f"Charge net cost delta:{(-cost_delta):5.1f}p"
            if cost_delta > -self.host.get_config("pass_threshold_p"):
                slots = slots_pre
                slots_added = 0
                net_cost_opt = net_cost_pre
                str_log += f": < threshold {self.host.get_config('pass_threshold_p')} => Excluded"
            else:
                str_log += f": > threshold {self.host.get_config('pass_threshold_p')} => Included"

            if log:
                self.log("")
                self.log(str_log)

            # -----------
            # Discharging
            # -----------
            if discharge:
                net_cost_pre = net_cost_opt
                slots_pre = copy(slots)
                slots_added_pre = slots_added
                net_cost_pre = net_cost_opt

                # Check how many slots which aren't full are at an export price less than any import price:
                min_import_price = df["import"].min()
                if log:
                    self.log("")
                    self.log("Forced Discharging")
                    self.log("------------------")
                    self.log("")

                i = 0
                available = (df["export"] > min_import_price) & (df["forced"] == 0)
                a0 = available.sum()
                if log:
                    self.log(
                        f"{available.sum()} slots have an export price greater than the min import price"
                    )
                done = available.sum() == 0

                while not done:
                    x = df[available].copy()
                    i += 1
                    done = i > a0
                    max_price = x["export"].max()

                    if len(x[x["export"] == max_price]) > 0:
                        start_window = x[x["export"] == max_price].index[0]
                        available.loc[start_window] = False
                        str_log = f"{available.sum():>2d} Max export price {max_price:5.2f}p/kWh at {start_window.strftime(TIME_FORMAT)} "

                        if (pd.Timestamp.now() > start_window.tz_localize(None)) and (
                            pd.Timestamp.now()
                            < start_window.tz_localize(None)
                            + pd.Timedelta(30, "minutes")
                        ):
                            str_log += "* "
                            factor = (
                                (
                                    start_window.tz_localize(None)
                                    + pd.Timedelta(30, "minutes")
                                )
                                - pd.Timestamp.now()
                            ).total_seconds() / 1800
                        else:
                            str_log += "  "
                            factor = 1

                        str_log += f"SOC: {x.loc[start_window]['soc']:5.1f}%->{x.loc[start_window]['soc_end']:5.1f}% "

                        slot = (
                            start_window,
                            -min(
                                self.inverter.inverter_power,
                                (
                                    (
                                        x["soc_end"].loc[start_window]
                                        - self.battery.max_dod
                                    )
                                    / 100
                                    * self.battery.capacity
                                )
                                * 2
                                * factor,
                            ),
                        )

                        slots.append(slot)

                        df = pd.concat(
                            [
                                prices,
                                self.flows(
                                    initial_soc, static_flows, slots=slots, **kwargs
                                ),
                            ],
                            axis=1,
                        )

                        net_cost = contract.net_cost(df).sum()
                        str_log += f"Net: {net_cost:5.1f} "
                        if net_cost < net_cost_opt - self.host.get_config(
                            "slot_threshold_p"
                        ):
                            str_log += f"New SOC: {df.loc[start_window]['soc']:5.1f}%->{df.loc[start_window]['soc_end']:5.1f}% "
                            str_log += f"Max export: {-df['grid'].min():0.0f}W "
                            net_cost_opt = net_cost
                            slots_added += 1
                            if log:
                                self.log(str_log)
                        else:
                            # done = True
                            slots = slots[:-1]
                            df = pd.concat(
                                [
                                    prices,
                                    self.flows(
                                        initial_soc, static_flows, slots=slots, **kwargs
                                    ),
                                ],
                                axis=1,
                            )
                            # if log:
                            #     self.log(str_log)
                    else:
                        done = True

                cost_delta = net_cost_opt - net_cost_pre
                str_log = f"Discharge net cost delta:{(-cost_delta):5.1f}p"
                if cost_delta > -self.host.get_config("pass_threshold_p"):
                    slots = slots_pre
                    slots_added = slots_added_pre
                    str_log += f": < threshold ({self.host.get_config('pass_threshold_p')}) => Excluded"
                    net_cost_opt = net_cost_pre
                else:
                    str_log += f": > threshold ({self.host.get_config('pass_threshold_p')}) => Included"

                if log:
                    self.log("")
                    self.log(str_log)

            if log:
                self.log(f"Iteration {j:2d}: Slots added: {slots_added:3d}")

        df.index = pd.to_datetime(df.index)

        if not self.host.get_config("allow_cyclic"):
            if log:
                self.log("")
                self.log("Removing cyclic charge/discharge")
            a = df["forced"][df["forced"] != 0].to_dict()
            new_slots = [(k, a[k]) for k in a]
            revised_slots = []
            skip_flag = False
            for slot, next_slot in zip(new_slots[:-1], new_slots[1:]):
                if (int(slot[1]) == self.inverter.charger_power) & (
                    int(-next_slot[1]) == self.inverter.inverter_power
                ):
                    skip_flag = True
                    if log:
                        self.log(
                            f"  Skipping slots at {slot[0].strftime(TIME_FORMAT)} ({slot[1]}W) and {next_slot[0].strftime(TIME_FORMAT)} ({next_slot[1]}W)"
                        )
                elif skip_flag:
                    skip_flag = False
                else:
                    revised_slots.append(slot)

            df = pd.concat(
                [
                    prices,
                    self.flows(
                        initial_soc, static_flows, slots=revised_slots, **kwargs
                    ),
                ],
                axis=1,
            )
            net_cost_opt_new = contract.net_cost(df).sum()
            if log:
                self.log(
                    f"  Net cost revised from {net_cost_opt:0.1f}p to {net_cost_opt_new:0.1f}p"
                )
            slots = revised_slots
            df.index = pd.to_datetime(df.index)
        return df


# %%

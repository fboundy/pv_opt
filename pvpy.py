# %%
import pandas as pd
import requests

# from scipy.stats import linregress
from datetime import datetime

OCTOPUS_PRODUCT_URL = r"https://api.octopus.energy/v1/products/"
TIME_FORMAT = "%d/%m %H:%M"


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
        eco7_start="01:00",  # UTC
        **kwargs,
    ) -> None:
        self.name = name
        self.export = export
        self.eco7 = eco7
        self.area = kwargs.get("area", None)
        if self.eco7:
            self.eco7_start = pd.Timestamp(eco7_start)
            if self.eco7_start.tzinfo is None:
                self.eco7_start.tz_localize("UTC")

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
            "page_size": 100,
            "order_by": "period",
        } | {
            k: self._oct_time(kwargs.get(k, None))
            for k in ["period_from", "period_to"]
            if kwargs.get(k, None) is not None
        }

        # print(params)

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

        else:
            url = f"{OCTOPUS_PRODUCT_URL}{product}/electricity-tariffs/{code}/standard-unit-rates/"
            self.unit = requests.get(url, params=params).json()["results"]

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

    def to_df(self, start=None, end=None):
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
            df = df.reindex(
                index=pd.date_range(
                    start,
                    end,
                    freq="30T",
                )
            ).fillna(method="ffill")
            mask = (df.index.time >= self.eco7_start.time()) & (
                df.index.time < (self.eco7_start + pd.Timedelta("7H")).time()
            )
            df.loc[mask, "value_inc_vat"] = df.loc[mask, "Night"]
            df = df["unit"]

        else:
            df = pd.DataFrame(self.unit).set_index("valid_from")["value_inc_vat"]
            df.index = pd.to_datetime(df.index)
            df = df.sort_index()
            newindex = pd.date_range(df.index[0], end, freq="30T")
            df = df.reindex(index=newindex).fillna(method="ffill").loc[start:]
            df.name = "unit"

        if not self.export:
            x = pd.DataFrame(self.fixed).set_index("valid_from")["value_inc_vat"]
            x.index = pd.to_datetime(x.index)
            newindex = pd.date_range(x.index[0], df.index[-1], freq="30T")
            x = (
                x.reindex(newindex)
                .sort_index()
                .fillna(method="ffill")
                .loc[df.index[0] :]
            )
            df = pd.concat([df, x], axis=1).set_axis(["unit", "fixed"], axis=1)

            mask = df.index.time != pd.Timestamp("00:00", tz="UTC").time()
            df.loc[mask, "fixed"] = 0

        return pd.DataFrame(df)


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
        base=None,
    ) -> None:
        self.name = name
        self.base = base
        if self.base:
            self.log = base.log
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
            self.log(f"INFO:  Connecting to {url}")
            try:
                r = requests.get(url, auth=(octopus_account.api_key, ""))
                r.raise_for_status()  # Raise an exception for unsuccessful HTTP status codes

            except requests.exceptions.RequestException as e:
                self.log("ERROR: An HTTP error occurred:", e)
                self.imp = e

            mpans = r.json()["properties"][0]["electricity_meter_points"]
            for mpan in mpans:
                self.log(f"INFO:  Getting details for MPAN {mpan}")
                df = pd.DataFrame(mpan["agreements"])
                df = df.set_index("valid_from")
                df.index = pd.to_datetime(df.index)
                df = df.sort_index()
                tariff_code = df["tariff_code"].iloc[-1]

                self.log(f"INFO:  Retrieved most recent tariff code {tariff_code}")
                if mpan["is_export"]:
                    self.exp = Tariff(tariff_code, export=True)
                else:
                    self.imp = Tariff(tariff_code)

            if self.imp is None:
                raise ValueError(
                    "Either a named import tariff or valid Octopus Account details much be provided"
                )

    def __str__(self):
        str = f"Contract: {self.name}\n"
        str += f'{"-"*(11 + len(self.name))}\n\n'
        for tariff in [self.imp, self.exp]:
            str += f"{tariff.__str__()}\n"
        return str

    def net_cost(self, grid_flow, grid_col="grid"):
        start = grid_flow.index[0]
        end = grid_flow.index[-1]
        if isinstance(grid_flow, pd.DataFrame):
            grid_flow = grid_flow[grid_col]
        grid_imp = grid_flow.clip(0)
        grid_exp = grid_flow.clip(upper=0)
        # if self.base is not None:
        #     self.base.log(f"Start: {start}")
        #     self.base.log(f"End: {end}")

        nc = self.imp.to_df(start, end)["fixed"]
        nc += self.imp.to_df(start, end)["unit"] * grid_imp / 2000
        nc += self.exp.to_df(start, end)["unit"] * grid_exp / 2000

        return nc


class PVsystemModel:
    def __init__(
        self, name: str, inverter: InverterModel, battery: BatteryModel, log=None
    ) -> None:
        self.name = name
        self.inverter = inverter
        self.battery = battery
        self.log = log

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
                timed_slot_flows.loc[t] += c

            chg_mask = timed_slot_flows != 0
            battery_flows[chg_mask] = timed_slot_flows[chg_mask]
            forced_charge[chg_mask] = timed_slot_flows[chg_mask]

        if soc_now is None:
            chg = [initial_soc / 100 * self.battery.capacity]
            freq = pd.infer_freq(static_flows.index) / pd.Timedelta("60T")

        else:
            chg = [soc_now[1] / 100 * self.battery.capacity]
            freq = (soc_now[0] - df.index[0]) / pd.Timedelta("60T")
        # freq = (pd.Timestamp.now().ceil("30T") - pd.Timestamp.now()) / pd.Timedelta("60T")

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
                freq = pd.infer_freq(static_flows.index) / pd.Timedelta("60T")

        if soc_now is not None:
            chg[0] = [initial_soc / 100 * self.battery.capacity]

        df["chg"] = chg[:-1]
        df["chg"].interpolate(method="ffill", inplace=True)
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
        df["soc_end"] = df["soc"].shift(-1)

        return df

    def optimised_force(self, initial_soc, static_flows, contract: Contract, **kwargs):
        cols = {k: kwargs.get(k, k) for k in ["consumption"]}
        consumption = static_flows[cols["consumption"]]
        consumption.name = "consumption"

        neg = kwargs.pop("neg", False)
        discharge = kwargs.pop("discharge", False)

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

        prices = prices.set_axis(["import", "export"], axis=1)
        df = pd.concat(
            [prices, consumption, self.flows(initial_soc, static_flows, **kwargs)],
            axis=1,
        )
        base_cost = contract.net_cost(df).sum()
        net_cost = []
        net_cost_opt = base_cost

        slots = []

        # Add any slots where the price is negative:
        if neg:
            neg_slots = df[df["import"] <= 0].sort_values(ascending=True).index
            if len(neg_slots) > 0:
                for idx in neg_slots:
                    slots.append((idx, self.inverter.charger_power))
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
                    net_cost.append(contract.net_cost(df).sum())

                net_cost_opt = min(net_cost)
                opt_neg_slots = net_cost.index(net_cost_opt)
                slots = slots[: opt_neg_slots + 1]

        # --------------------------------------------------------------------------------------------
        #                                    Charging
        # --------------------------------------------------------------------------------------------
        if self.log is not None:
            self.log("Optimising charge")
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
        while not done:
            i += 1
            done = i > 96
            import_cost = (df["import"] * df["grid"]).clip(0) / 2000
            if len(import_cost) > 0:
                max_import_cost = import_cost[df["forced"] == 0].max()
                max_slot = import_cost[import_cost == max_import_cost].index[0]
                max_slot_energy = df["grid"].loc[max_slot] / 2000  # kWh
                if round(max_slot_energy, 0) > 0:
                    round_trip_energy_required = (
                        max_slot_energy
                        / self.inverter.charger_efficiency
                        / self.inverter.inverter_efficiency
                    )

                    x = df.loc[:max_slot]
                    x = x[
                        x["soc_end"]
                        # < (100 - round_trip_energy_required) / self.battery.capacity * 100
                        < 100
                    ]
                    x = x[x["forced"] < self.inverter.charger_power]

                    search_window = x.index
                    str_log = f"{max_slot.strftime(TIME_FORMAT)} costs {max_import_cost:5.2f}p. "
                    str_log += f"Energy: {round_trip_energy_required:5.2f} kWh. "
                    if len(search_window) > 0:
                        str_log += f"Window: [{search_window[0].strftime(TIME_FORMAT)}-{search_window[-1].strftime(TIME_FORMAT)}] "
                    else:
                        str_log = "No available window."
                    if len(x) > 0:
                        min_price = x["import"].min()
                        start_window = x[x["import"] == min_price].index[0]

                        cost_at_min_price = round_trip_energy_required * min_price
                        str_log += f"Min price at {start_window.strftime(TIME_FORMAT)}: {min_price:5.2f}p/kWh costing {cost_at_min_price:5.2f} "
                        str_log += f"SOC: {x.loc[start_window]['soc']:5.1f}% ->  {x.loc[start_window]['soc_end']:5.1f}%"

                        if cost_at_min_price < max_import_cost:
                            slots.append(
                                (
                                    start_window,
                                    round(
                                        min(
                                            round_trip_energy_required * 2000,
                                            self.inverter.charger_power
                                            - x["forced"].loc[start_window],
                                            (
                                                (100 - x["soc_end"].loc[start_window])
                                                * self.battery.capacity
                                            )
                                            * 2,
                                        ),
                                        0,
                                    ),
                                )
                            )
                            # for slot in start_window:
                            #     slots.append(
                            #         (
                            #             slot,
                            #             round(
                            #                 min(
                            #                     min_price_energy
                            #                     * 2000
                            #                     / len(start_window),
                            #                     self.inverter.charger_power
                            #                     - x["forced"].loc[slot],
                            #                 ),
                            #                 0,
                            #             ),
                            #         )
                            #     )

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
                            str_log += f"Net: {net_cost_opt:5.1f}"

                            #                          if contract.net_cost(df).sum() < net_cost_opt:
                            net_cost_opt = contract.net_cost(df).sum()
                        #                          else:
                        #                              done = True
                        #                               slots = slots[:-1]
                        #                               df = pd.concat(
                        #                                   [
                        #                                       prices,
                        #                                      consumption,
                        #                                      self.flows(
                        #                                           initial_soc,
                        #                                          static_flows,
                        #                                           slots=slots,
                        #                                           **kwargs,
                        #                                       ),
                        #                                  ],
                        #                                  axis=1,
                        #                               )
                        else:
                            done = True
                    self.log(str_log)
            else:
                done = True

        df = pd.concat(
            [
                prices,
                self.flows(initial_soc, static_flows, slots=slots, **kwargs),
            ],
            axis=1,
        )
        if self.log is not None:
            self.log("INFO:  Optimal forced charge slots:")
            x = df[df["forced"] > 0]
            for t_start in x.index:
                t_end = t_start + pd.Timedelta("30T")
                self.log(
                    f"INFO:    {t_start.strftime('%d-%b %H:%M'):>13s} - {t_end.strftime('%d-%b %H:%M'):<13s} {x.loc[t_start]['forced']:8.0f} W   SOC: {x.loc[t_start]['soc']:0.0f}% -> {df.loc[t_end]['soc']:0.0f}%"
                )

        if discharge:
            # --------------------------------------------------------------------------------------------
            #                                    Discharging
            # --------------------------------------------------------------------------------------------

            done = False
            i = 0
            tested = pd.Series(index=df.index, data=0)

            while not done:
                i += 1
                done = i >= 20

                max_discharge = (
                    self.inverter.inverter_power + df["grid"].fillna(0).clip(upper=0)
                ) * 0.5  # Wh

                max_batt = (
                    self.battery.capacity
                    * (df["soc"] / 100 - self.battery.max_dod)
                    * self.inverter.inverter_efficiency
                    - df["consumption"] * 0.5
                )  # Wh

                df["export_pot"] = (
                    df["export"]
                    * pd.DataFrame([max_discharge, max_batt]).T.min(axis=1)
                    / 100
                    / 1000
                )  # p/kWh x Wh x £/p x kWh/Wh = £

                export_slots = df["export_pot"][(df["forced"] == 0) & (tested == 0)]
                # df["export_slots"] = 0
                # df.loc[export_slots, "export_slots"] = 1

                if len(export_slots) > 0:
                    max_export_pot = export_slots.max()
                    max_slot = export_slots.index[0]
                    max_slot_price = df["export"].loc[max_slot]
                    max_slot_energy = max_export_pot / max_slot_price * 1e5

                    tested.loc[max_slot] = 1
                    slots.append(
                        (
                            max_slot,
                            -max_slot_energy * 2,
                        )
                    )

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

                    if self.log is not None:
                        self.log(
                            f"Discharge loop {i:>2d}: Net cost: {net_cost:6.1f}  Opt: {net_cost_opt:6.1f}"
                        )

                    if net_cost > net_cost_opt:
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
                    else:
                        net_cost_opt = net_cost

                else:
                    done = True
        df.index = pd.to_datetime(df.index)
        return df

# %%
import requests
import pandas as pd
from scipy.stats import linregress

# %%
url = "https://www.nordpoolgroup.com/api/marketdata/page/325?currency=GBP"

try:
    r = requests.get(url)
    r.raise_for_status()  # Raise an exception for unsuccessful HTTP status codes

except requests.exceptions.RequestException as e:
    print(f"HTTP error occurred: {e}")

# %%
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
                        index.append(pd.Timestamp(i["Name"] + time))

price = pd.Series(index=index, data=data).sort_index()
price.index = price.index.tz_localize("CET")
price = price[~price.index.duplicated()]
price.plot()
price.name = "Day Ahead"
# %%
OCTOPUS_PRODUCT_URL = r"https://api.octopus.energy/v1/products/"
product = "AGILE-FLEX-22-11-25"
code = f"E-1R-{product}-G"
url = f"{OCTOPUS_PRODUCT_URL}{product}/electricity-tariffs/{code}/standard-unit-rates/"
parameters = {
    "period_from": price.index[0].tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
    "page_size": len(price) * 2,
}
try:
    r = requests.get(url, params=parameters)
    r.raise_for_status()  # Raise an exception for unsuccessful HTTP status codes

except requests.exceptions.RequestException as e:
    print(f"HTTP error occurred: {e}")

agile = pd.Series(
    index=[x["valid_from"] for x in r.json()["results"]],
    data=[x["value_inc_vat"] for x in r.json()["results"]],
)
agile.index = pd.to_datetime(agile.index)
agile.name = "Agile"
agile = agile.sort_index()
# %%
mask = (price.index.hour >= 16) & (price.index.hour < 19)


pred = (
    pd.concat(
        [
            price[mask] * 0.186 + 16.5,
            price[~mask] * 0.229 - 0.6,
        ]
    )
    .sort_index()
    .loc[agile.index[-1] :]
    .iloc[1:]
)


# %%
merge = pd.concat(
    [
        price.sort_index().loc[: agile.sort_index().index[-1]],
        agile.resample("1H").mean(),
    ],
    axis=1,
)

mask = (merge.index.hour >= 16) & (merge.index.hour < 19)
merge["Forecast"] = 0
merge.loc[mask, "Forecast"] = merge[mask]["Day Ahead"] * 0.186 + 16.5
merge.loc[~mask, "Forecast"] = merge[~mask]["Day Ahead"] * 0.229 - 0.6
ax = merge.plot()


ax = merge[mask].plot.scatter("Day Ahead", "Agile")
merge[~mask].plot.scatter("Day Ahead", "Agile", ax=ax, color="C1")

lr_peak = linregress(
    merge[mask]["Day Ahead"].to_numpy(), merge[mask]["Agile"].to_numpy()
)
print(lr_peak)
lr_off_peak = lr_peak = linregress(
    merge[~mask]["Day Ahead"].to_numpy(), merge[~mask]["Agile"].to_numpy()
)
print(lr_off_peak)
# %%

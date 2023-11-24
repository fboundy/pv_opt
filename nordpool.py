#%%
import requests
import pandas as pd
from pprint import pprint
import 

url="https://www.nordpoolgroup.com/api/marketdata/page/325?currency=GBP"

try:
    r=requests.get(url)
    r.raise_for_status()  # Raise an exception for unsuccessful HTTP status codes

except requests.exceptions.RequestException as e:
    print(f"HTTP error occurred: {e}")

# %%
index = []
data = []
for row in r.json()['data']['Rows']:
    str = ""
    # pprint.pprint(row)

    for column in row:
        if isinstance(row[column], list):
            for i in row[column]:
                if i['CombinedName']=="CET/CEST time":
                    if len(i['Value'])>10:
                        time = f"T{i['Value'][:2]}:00"
                        print(time)
                else:
                    if len(i['Name'])>8:
                        print(i['Name'])
                        data.append(float(i['Value'].replace(",",".")))
                        index.append(pd.Timestamp(i['Name'] + time))

price = pd.Series(index=index, data=data)
price.plot()
# %%
agile_code = 

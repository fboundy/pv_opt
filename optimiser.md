# PV Opt Optimiser - How it Works

For those who are interested this document gives a brief overview of the logic behind the algorythm that PV_Opt uses. It may help users determine if it is doing what is expected or to better tune the Optimiser.

<h2>Input Data<h2>

<h3>The PV Model</h3>

At the heart of the system is the model of the PV system. This comprises a number of classes defined in `pvpy.py`:

| Component | Class | Descriptions|
|:--|:--|:--|
| Battery   | BatteryModel | Describes the battery. Its two attributes are its capacity in kWh and the maxmimum permissible depth of discharge in % SOC.
| 

<h3>Forecast Period</h3>

All calculations are done over a 48 hour period starting at the most recent midnight (UTC). Resolution is 30 minutes since this is the standard pricing interval for all variable rate tariffs. The objective of the optimiser is to minimise the net cost at the end of this period.


<h3>Static Data</h3>

Static data are defined as the data that do not change during the optimisation process. These are the expected solar power profile and the expected load profile. These are defined at 30 minute intervals to the end of the following day (in UTC) from the selected Solcast forecast and the expected consumption respectively.

<h3>Prices</h3>

These are also static and are defined from the available Octopus API data. If Agile is required and is not available for the full duration it is predicted from published Day-Ahead wholesale pricing.

<h2>The Base Forecast</h2>

The Base Forecast simply predicts battery SOC and grid power (in and out) for every 30 minutes from now forward using the solar and load forecasts. It allows for conversion efficiencies and the limits of the inverter and charger as defined in the PV Model. The grid power flows are then combined with the import and export prices to generate a Base Net Cost for the 48 hour period.

<h2>Optimisation</h2>

There are three stages to the optimisation algorithm. Stage 1 is always run. Stages 2 and 3 are only relevant if there is an Export tariff.

<h3>Stage 1: High Cost Usage Swaps</h3>

The basic algorythm is as follows:

1. Find the 30 minute period with the highest cost in the Base Forecast (`max_cost_slot`)
2. Find the cheapest period where you could buy the same amount of energy (allowing for efficiencies) before `max_cost_slot` and after the last time the battery is full (`min_price_slot`) and when there is available forced charge capacity. If several slots have the same price then spread the charging equally over these slots.
3. Force the battery to charge by the necessary power during this slow.
4. Recalculate the Latest Forecast and find the new `max_cost_slot`. In practice this may well be the same slot as before. 
5. Repeat (2) - (4) until there are no slots left to buy cheaper.

An example of this phase is shown below. 

In this example teh algoryth 1st deals with the expensive slot at 18:30 on 25/02 which it is able to swap for slots at 14:00 - 15:00 on 24/02. Once enough charging has been added to keep the system sunning on battery at 18:30 on 25/02, the next high cost is at 08:30 on 25/02. This is dealt with by buying more power between 20:30 and 03:30.
```
10:10:00     INFO: High Cost Usage Swaps
10:10:00     INFO: ---------------------
10:10:00     INFO: 
10:10:00     INFO: 25/02 18:30:  1.07 kWh at  27.91p. <==> 24/02 14:30: 11.25p/kWh 12.01p  SOC:  61.1%-> 15.0% New SOC:  61.1%-> 65.9% Net:  522.2
10:10:00     INFO: 25/02 18:30:  1.07 kWh at  27.91p. <==> 24/02 14:30: 11.25p/kWh 12.01p  SOC:  61.1%-> 19.9% New SOC:  61.1%-> 70.8% Net:  517.8
10:10:00     INFO: 25/02 18:30:  1.07 kWh at  27.91p. <==> 24/02 14:30: 11.25p/kWh 12.01p  SOC:  61.1%-> 24.7% New SOC:  61.1%-> 74.7% Net:  511.0
10:10:00     INFO: 25/02 18:30:  1.07 kWh at  27.91p. <==> 24/02 14:00: 11.47p/kWh 12.25p  SOC:  63.5%-> 15.0% New SOC:  63.5%-> 68.4% Net:  501.8
10:10:00     INFO: 25/02 18:30:  1.07 kWh at  27.91p. <==> 24/02 14:00: 11.47p/kWh 12.25p  SOC:  63.5%-> 20.0% New SOC:  63.5%-> 73.2% Net:  495.1
10:10:00     INFO: 25/02 18:30:  1.07 kWh at  27.91p. <==> 24/02 14:00: 11.47p/kWh 12.25p  SOC:  63.5%-> 24.9% New SOC:  63.5%-> 77.2% Net:  487.9
10:10:00     INFO: 25/02 18:30:  1.07 kWh at  27.91p. <==> 24/02 15:00: 11.84p/kWh 12.65p  SOC:  90.8%-> 34.9% New SOC:  90.8%-> 92.0% Net:  469.8
10:10:00     INFO: 25/02 18:30:  0.80 kWh at  20.79p. <==> 24/02 15:00: 11.84p/kWh  9.43p  SOC:  90.8%-> 44.9% New SOC:  90.8%-> 92.9% Net:  467.3
10:10:00     INFO: 25/02 08:30:  1.53 kWh at  20.67p. <==> 24/02 15:00: 11.84p/kWh 18.07p  SOC:  90.8%-> 17.1% New SOC:  90.8%-> 94.0% Net:  467.8
10:10:00     INFO: 25/02 08:30:  1.53 kWh at  20.67p. <==> 24/02 15:00: 11.84p/kWh 18.07p  SOC:  90.8%-> 19.4% New SOC:  90.8%-> 94.9% Net:  467.8
10:10:00     INFO: 25/02 08:30:  1.53 kWh at  20.67p. <==> 24/02 20:30: 11.84p/kWh 18.07p  SOC:  40.8%-> 21.7% New SOC:  40.8%-> 51.0% Net:  467.6
10:10:00     INFO: 25/02 08:30:  1.53 kWh at  20.67p. <==> 24/02 20:30: 11.84p/kWh 18.07p  SOC:  40.8%-> 25.2% New SOC:  40.8%-> 54.5% Net:  468.6
10:10:00     INFO: 25/02 08:30:  1.53 kWh at  20.67p. <==> 25/02 03:30: 11.87p/kWh 18.10p  SOC:  15.0%-> 15.0% New SOC:  15.0%-> 21.9% Net:  467.2
10:10:00     INFO: 25/02 08:30:  1.53 kWh at  20.67p. <==> 25/02 03:30: 11.87p/kWh 18.10p  SOC:  15.0%-> 28.9% New SOC:  15.0%-> 28.6% Net:  465.3
10:10:00     INFO: 25/02 08:30:  1.53 kWh at  20.67p. <==> 25/02 02:00: 12.06p/kWh 18.40p  SOC:  26.5%-> 15.0% New SOC:  26.5%-> 31.2% Net:  459.4
10:10:00     INFO: 25/02 19:00:  1.06 kWh at  15.67p. <==> 25/02 15:00: 11.84p/kWh 12.55p  SOC:  42.4%-> 46.7% New SOC:  42.4%-> 49.4% Net:  449.5
10:10:00     INFO: 25/02 19:30:  0.79 kWh at  11.41p. <==> 25/02 15:00: 11.84p/kWh  9.39p  SOC:  42.4%-> 56.3% New SOC:  42.4%-> 53.0% Net:  447.3
10:10:00     INFO: 25/02 19:30:  0.60 kWh at   8.61p. <==> 25/02 15:00: 11.84p/kWh  7.08p  SOC:  42.4%-> 63.5% New SOC:  42.4%-> 55.7% Net:  445.7
10:10:00     INFO: 25/02 20:00:  0.64 kWh at   8.51p. <==> 25/02 15:00: 11.84p/kWh  7.58p  SOC:  42.4%-> 69.0% New SOC:  42.4%-> 56.1% Net:  445.6
10:10:00     INFO: 25/02 21:00:  0.65 kWh at   8.05p. <==> 25/02 20:30: 11.84p/kWh  7.70p  SOC:  15.0%-> 15.0% New SOC:  15.0%-> 20.9% Net:  445.3
10:10:00     INFO: 25/02 20:00:  0.56 kWh at   7.38p. <==> 25/02 13:30: 11.97p/kWh  6.64p  SOC:  16.0%-> 15.1% New SOC:  16.0%-> 21.0% Net:  444.5
10:10:00     INFO: 25/02 09:00:  0.31 kWh at   4.20p. <==> 25/02 02:00: 12.06p/kWh  3.72p  SOC:  26.5%-> 40.4% New SOC:  26.5%-> 32.1% Net:  444.0
10:10:00     INFO: 25/02 09:30:  0.22 kWh at   2.99p. <==> 25/02 02:00: 12.06p/kWh  2.64p  SOC:  26.5%-> 43.2% New SOC:  26.5%-> 32.8% Net:  443.7
```

Once this is done the Net Cost saving is checked against the "Pass Threshold". In this case the saving is 80p which is well above the theshold of 4p and so the slots are kept.


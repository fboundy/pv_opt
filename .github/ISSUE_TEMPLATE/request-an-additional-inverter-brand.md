---
name: Request an Additional Inverter Brand
about: Use this template if you want to request support for an additional brand or
  model of inverter
title: ''
labels: ''
assignees: ''

---

PV Opt can be updated to support additional models and brands of inverter. If you want to request this, please supply as much of the following information as possible:

<h2>Home Assistant Entities to Read</h2>
PV Opt reads data from a number of entities in Home Assistant. These will vary by inverter. Please document what your inverter provides. Examples are provided from the Solis Solax Modbus integration:

Battery maximum depth of discharge/minimum SOC: `number.solis_battery_minimum_soc`
Battery SOC: `sensor.solis_battery_soc`
Either:
    Load power: [`sensor.solis_house_load`, `sensor.solis_bypass_load`], or
    Load today: `sensor.solis_house_load_today`
Either:
    Grid import power: `sensor.solis_grid_import_power` and
    Grid export power: `sensor.solis_grid_export_power`
Or:
    Grid import today: `sensor.solis_grid_import_today` and
    Grid export today: `sensor.solis_grid_export_today`

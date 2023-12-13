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

    Battery minimum SOC: number.solis_battery_minimum_soc
    Battery SOC:         sensor.solis_battery_soc
    Either:
      Load power:        [sensor.solis_house_load, sensor.solis_bypass_load], or
      Load today:        sensor.solis_house_load_today
    Either:
      Grid import power: sensor.solis_grid_import_power and
      Grid export power: sensor.solis_grid_export_power
    Or:
      Grid import today: sensor.solis_grid_import_today and
      Grid export today: sensor.solis_grid_export_today

<h2>Inverter Control</h2>
PV Opt also needs to control your inverter. How this is done and what can be done varies hugely by brand, by model and by the integration you use with Home Assistant. Please provide as much detail under each heading. Examples are provided for the Solis inverter using the both the Solax Modbus Integration and the HA Core Modbus functionality. Please add your details below:

<h3>Examples</h3>

| | Solis Solax Modbus | Solis Core HA Modbus |
|:--|:--:|:--:|
| How do you enable forced charging? | Only done via timed charge | Only done via timed charge |
| How do you enable forced discharging? | Only done via timed discharge | Only done via distimed charge |
| Are forced charge and discharge controlled using Power or Current?| Current | Current |
| Does your inverter support timed charging slots? | Yes | Yes |      
| Does your inverter support timed discharging slots? | Yes | Yes |   
| How do you enabled timed charge? | Set the following: `number.timed_charge_start_hour`, `number.timed_charge_start_minute`, `number.timed_charge_end_hour`, `number.timed_charge_start_minute`. Then press '`button.solis_update_charge_discharge_times`. Set the required current to `number.solis_timed_charge_current`. Ensure `select.solis_energy_storage_control_switch` has Timed Grid Charging enabled. | Use the `modbus\write_register` service to write start and end hours and minutes to the correct registers. Ensure the `energy_storage_control_switch` has Bits 2 and 5 enabled. Set the required current using the `modbus\write_register` service |      
| How do you enabled timed charge? | As for charging but all entities are `discharge` rather than `charge`| As for charging but registers are different. |
| Can you set a target SOC for a timed charge period? | No | No |
| Can you set a target SOC for a timed discharge period? | No | No |
| What modes does you inverter have and how are they controlled?| One register on the inverter `Energy Control Switch` which controls mode in a bit-wise sense. Only some modes can be selected vai the entity `select.solis_energy_storage_control_switch` | One register on the inverter `Energy Control Switch` which controls mode in a bit-wise sense. The required number is set using the `modbus\write_register` service |      

<h3>Your Setup</h3>

<h4>What is the inverter brand?</h4>
Answer

<h4>What is the inverter model?</h4>
Answer

<h4>What integration do you use in Home Assistant</h4>
Answer
<h4>How do you enable forced charging?</h4>
Answer 

<h4>How do you enable forced discharging?</h4>
Answer 

<h4>Are forced charge and discharge controlled using Power or Current?<h4>
Answer

<h4> Does your inverter support timed charging slots?</h4>
Answer

<h4> Does your inverter support timed discharging slots?</h4>
Answer

<h4>How do you enabled timed charge?</h4>
Answer

<h4>How do you enabled timed discharge?</h4>
Answer

<h4>Can you set a target SOC for a timed charge period?</h4>
Answer

<h4>Can you set a target SOC for a timed discharge period?</h4>
Answer

<h4>What modes does you inverter have and how are they controlled?</h4>
Answer

<h4>Any other useful information</h4>
Answer

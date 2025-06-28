<p align="center">
  <img src="https://zendure.com/cdn/shop/files/zendure-logo-infinity-charge_240x.png?v=1717728038" alt="Logo">
</p>

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=FireSon&repository=Zendure-HA&category=integration)

# Zendure Home Assistant Integration
This Home Assistant integration connects your Zendure devices to Home Assistant, making all reported parameters available as entities. You can track battery levels, power input/output, manage charging settings, and integrate your Zendure devices into your home automation routines. The integration also provides a power manager feature that can help balance energy usage across multiple devices without requiring a seperate Shelly or P1 meter.

The integration connects to the Zendure cloud API using your Zendure account credentials. After authentication, it automatically discovers all Zendure devices linked to your account and makes them available in Home Assistant. The integration uses MQTT to get notifications from the devices when a parameter changes, and updates the corresponding entity in Home assistant. The Integration can connect to the Zendure cloud Mqtt server, or a local Mqtt server. It is recommended to start with the Zendure Cloud Mqtt server, since local Mqtt requires more configuration and requires a working Home Assistant Bluetooth connection to the device(s). If you want to try out local Local mqtt please make sure you follow the [instructions](https://github.com/FireSon/Zendure-HA/wiki/Local-Mqtt)

## Installation
Preferable way to install this custom integration is to use [HACS](https://www.hacs.xyz/), learn how to install HACS [here](https://www.hacs.xyz/docs/use/download/download). After you have successfully installed and configured HACS you can search for `Zendure Home Assistant Integration` and install the Integration. 

There are a few tutorials for installation:
- [Domotica & IoT 🇺🇸](https://iotdomotica.nl/tutorial/install-zendure-home-assistant-integration-tutorial)
- [twoenter blog 🇺🇸](https://www.twoenter.nl/blog/en/smarthome-en/zendure-home-battery-home-assistant-integration/) or [twoenter blog 🇳🇱](https://www.twoenter.nl/blog/home-assistant-nl/zendure-thuisaccu-integratie-met-home-assistant/)

## 📌 Compatible Devices

This document currently supports the following products:

| Product Name      | Notes |
| ----------------- | ----- |
| Hyper 2000     |        |
| Hub 1200     |       |
| Hub 1200     |       |
| ACE 1500 | |
| AIO 2400 | |
| SolarFlow 800 | No device sharing, use primary account |
| SolarFlow 2400 AC| No device sharing, use primary account |
| SolarFlow 800 Pro| No device sharing, use primary account |

## **🚀 Key Features**

### ZendureManager
The ZendureManager, can be used to manage all Zendure devices.Except for 'Off' all modes use the 'P1 Sensor for smart matching' (P1) to control all devices.
- There are five mode of operation available for the Zendure Manger in order to mange how it operates:
    1) Off; the Zendure Manger does nothing.
    2) Manual power; the 'Zendure Manual Power' number is used to set discharging (if negative) and charging if positive. 
    3) Smart matching; The P1 Sensor is used to keep zero on the meter.
    4) Smart discharge only; The P1 Sensor is used to discharge if necessary.
    5) Smart charge only; The P1 Sensor is used to discharge if possible.

In all of these modes (except off), the current is always distributed dynamicly, based on the 'actual soc' for charging and discharging.
The actual soc is calculated like this:
- chargecapacity = kwh * max(0, socSet - electricLevel)
- dischargecapacity = kwh * max(0, electricLevel - minSoc)

In this way the maximal availability for charging/discharging is achieved. This is also the reason why the AC mode can not be manipulated because it would break this feature.

### Clusters
At this moment the integration cannot handle the Zenlink cluster (will be added in the future).
However it is possible to create clusters of your own in the integration. For which you can use the information about clusters from the Zendure App for that as well. This option is only available if you have multiple devices.
![image](https://github.com/user-attachments/assets/dba74b54-e75f-481d-b35b-98a37f079fad)
In this example the Zen 05 behaves like a cluster with a maximum output of 800watt. At this moment there are three options available 800/1200 and 2400 watt. The Zen66 device is part of this cluster. The output per device of this cluster is dependant on the actual capacity of the devices. If the device is not in a cluster the ZendureManager will use it maximum input or output. Wherever the device cluster is not defined, the ZendureManager will not use the device! The configured values are persisted, and also after a reboot of HA they should stay the same.

### Smart Matching Sensor Configuration

For the smart matching feature to work properly, you need to configure a power sensor that:

- Reports values in Watts (W)
- Reports negative values when there is excess energy (e.g., from solar production)
- Reports positive values when the house is drawing power from the grid

If your existing power meter sensor doesn't meet these requirements, you can create a template sensor to convert the values appropriately (see below).

#### Example: Converting DSMR Integration Values

If you're using the DSMR integration which reports values in kilowatts (kW) as separate "delivered" and "returned" sensors, you can create a template to combine and convert them to the required format:

```yaml
{{ (states("sensor.dsmr_reading_electricity_currently_delivered") | float - states("sensor.dsmr_reading_electricity_currently_returned") | float) * 1000 }}
```

This template:
1. Takes the currently delivered electricity value (positive when consuming from grid)
2. Subtracts the currently returned electricity value (positive when sending to grid)
3. Multiplies by 1000 to convert from kW to W

#### Setting Up a Template Sensor

You can set this up as a Helper in Home Assistant:

1. Go to Settings → Devices & Services → Helpers
2. Click "Add Helper" and select "Template"
3. Choose "Sensor" as the template type
4. Enter the template code above
5. Configure the name, icon, and unit of measurement (W)
6. Save the helper

For more information on template sensors, see the [Home Assistant Template documentation](https://www.home-assistant.io/integrations/template/).

## Home assistant Energy Dashboard

The Zendure integration reports power values in watts (W), which represent instantaneous power flow. However, the Home Assistant Energy Dashboard requires energy values in watt-hours (Wh) or kilowatt-hours (kWh), which represent accumulated energy over time.

To integrate your Zendure devices with the Energy Dashboard, you'll need to create additional sensors that convert the power readings into energy measurements. You can use the (Riemann sum) Integral sensor to accumulate power readings into energy values.

To do this go to Devices & Services > Helpers and add an Integral sensor for both the power flowing into the battery (eg: `sensor.hyper_2000_grid_input_power`) as well as the power feeding back to the grid/house (eg: `sensor.hyper_2000_energy_power`)

Once you have the integral sensors set up:

1. Go to Settings → Dashboards → Energy
2. In the "Grid" section, add your grid consumption/return sensors
3. In the "Battery" section:
   - Add your Zendure battery
   - Select the integral sensor for energy going into the battery
   - Select the integral sensor for energy coming from the battery
4. Save your configuration & wait to the next hour before the summarized data starts to show up.

For more information, see the [Home Assistant Energy documentation](https://www.home-assistant.io/docs/energy/).

## License

MIT License

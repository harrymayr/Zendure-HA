# Zendure Integration
![image](https://github.com/user-attachments/assets/393fec2b-af03-4876-a2d3-3bb3111de1d0)

This Home Assistant Integration is for Zendure devices.
Currently the Hyper2000 and the Solarflow 800 are supported.

## Telemetry
All the properties which the devices are reporting, are automatically added to HA.

## Power Manager
The ZendureManager, can be used as a cluster manager.
- For each phase the maximum output can be configured'
- There are three mode of operation available for the Zendure Manger in order to mange how it operates:
    1) Off; the Zendure Manger does nothing.
    2) Manual power; the 'Zendure Manual Power' number is used to set discharging (if negative) and charging if positive.
    3) Smart matching; The 'P1 Sensor for smart matching' sensor is used to keep zero on the meter.

In all of these modes, the current is always distributed dynamicly, based on the 'actual soc' for charging and discharging.
The actual soc is calculated like this:
- chargecapacity = packNum * max(0, socSet - electricLevel)
- dischargecapacity = packNum * max(0, electricLevel - socMin)


In this way the maximal availability for charging/discharging is achieved. This is also the reason why the AC mode can not be manipulated because it would break this feature.


### Installation using HACS

Preferable way to install this custom integration is to use [HACS](https://www.hacs.xyz/). Learn how to install HACS [here](https://www.hacs.xyz/docs/use/download/download).
After you have successfully installed and configured HACS you can simply press this button to add this repository to HACS and proceed to `Zendure Home Assistant Integration` installation.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=FireSon&repository=Zendure-HA&category=integration)

## Configuration options

![image](https://github.com/user-attachments/assets/a92daa42-99aa-41fa-880a-d7acd19185da)

## License

MIT License

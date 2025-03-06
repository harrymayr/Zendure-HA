# Zendure Integration

This Home Assistant Integration is for the Zendure Hyper2000.
All the properties which the Hyper2000 reports, are automatically added to HA.

I have added a PowerManager which distribution of the available current over the different phases and in proportion to the number of batteries. Giving the best overall availabilty for charging and descharging. In order to mange this there is a ZendureManager device added to HA where you can select the operating mode of the integration. In order to use these modes, you have to configure a few HA sensors which the integration will use for the different modes.
Currently the are 3 modes:
1) Off; which is obvious.
2) Manual power mode; the 'power' sensor is used to set discharging (if negative) and charging if positive.
3) Smart power matching; The sensor Consumption/Production are used to keep zero on the meter.

The integration will re-evaluate the distribution of current each 2 minutes.

## Features

- Get telemetry data from your Hyper 2000
- Home assistant smart mode, based on P1 meter sensor name

### 1.0.10 (2025-03-06) ALPHA

- Add PowerManager + smart distribution of the available current over the different phases and in proportion to the number of batteries
- The current distribution is revaluated each 2 minutes, based upon the status of all hypers

### 1.0.9 (2025-03-04) ALPHA

- Update the AC Mode
- Started with a smartmode based on number input (Values are only calculated and not written to the hypers)
- Tried to add SolarFlow 800.

### 1.0.8 (2025-03-03) ALPHA

- Changed the name of the repository (again) to better reflect the purpose (more than just h2k)
- Changed the domain of the integration to zendure-ha
- Updated a number of sensors with the correct type/uom.
- Renamed HyperManager to ZendureManager,since other devices should be added in the future
- Refacter the class structure to be able to add other devices (Added Hyper 800) without testing
- Added additional logging on connecting to Zendure

### 1.0.7 (2025-03-02) ALPHA

- Updated a number of sensors with the correct type/uom.
- Added the HyperManager as a device in order to be able to select the operation status
- Updated the smart mode for charging discharging.
    All Hyper2000's are switching to smart matching mode
    Below 400 watts, only one Hyper2000 is used for charging/discharging. Above 400 watts, the load it is devided over all Hyper2000's which are either not full or empty. Clusters I have not tested yet, so please be carefull if you test this to not overload your system if multiple hypers are on one phase!!!

### 1.0.6 (2025-02-27) ALPHA

- First try to adjust battery output based upon home assistant sensor (for example P1 meter).

### 1.0.5 (2025-02-24) ALPHA

- The values are read from the Hyper 2000 and displayed in Home Assistant. Each 90 seconds the values are updated, or sooner when they are changing.
- You need to specify your Zendure username + password during the configuration of the integration. All your hyper2000 devices are found in the cloud. If you want to see the details enable the debug logging for the integration.
- Not all the sensors have the correct unit of measurement. This will be fixed in a later version.

## License

MIT License

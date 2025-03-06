# Zendure Integration

This Home Assistant Integration is for the Zendure Hyper2000.
It is possible to set the actual charge and discarge values, the Hyper2000 works in 'smart mode'.
It is all in the early stages of develpment, so please be patient.

## Features

- Get telemetry data from your Hyper 2000
- Home assistant smart mode, based on P1 meter sensor name

### 1.0.10 (2025-03-06) ALPHA

- Add PowerManager + smart distribution of the available current over the different phases and in proportion to the number of batteries
- Manual mode
- Tried to add SolarFlow 800.

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

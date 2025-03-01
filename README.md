# Zendure Integration

This Home Assistant Integration is for the Zendure Hyper2000.
It is possible to set the actual charge and discarge values, the Hyper2000 works in 'smart mode'. 
It is all in the early stages of develpment, so please be patient.

## Features

- Get telemetry data from your Hyper 2000
- Set the charge and discharge values

### 1.0.6 (2025-02-27) ALPHA

- First try to adjust battery output based upon home assistant sensor (for example P1 meter).

### 1.0.5 (2025-02-24) ALPHA

- The values are read from the Hyper 2000 and displayed in Home Assistant. Each 90 seconds the values are updated, or sooner when they are changing.
- You need to specify your Zendure username + password during the configuration of the integration. All your hyper2000 devices are found in the cloud. If you want to see the details enable the debug logging for the integration.
- Not all the sensors have the correct unit of measurement. This will be fixed in a later version.

## License

MIT License

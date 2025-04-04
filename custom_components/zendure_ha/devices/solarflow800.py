"""Module for SolarFlow800 integration."""

import logging
from typing import Any

from homeassistant.components.number import NumberMode
from homeassistant.core import HomeAssistant

from custom_components.zendure_ha.binary_sensor import ZendureBinarySensor
from custom_components.zendure_ha.number import ZendureNumber
from custom_components.zendure_ha.sensor import ZendureSensor
from custom_components.zendure_ha.switch import ZendureSwitch
from custom_components.zendure_ha.zenduredevice import ZendureDevice

_LOGGER = logging.getLogger(__name__)


class SolarFlow800(ZendureDevice):
    def __init__(self, hass: HomeAssistant, h_id: str, data: Any) -> None:
        """Initialise SolarFlow800."""
        super().__init__(hass, h_id, data["productKey"], data["deviceName"], "SolarFlow 800")
        self.chargemax = 1200
        self.dischargemax = 800

    def sensorsCreate(self) -> None:
        binairies = [
            self.binary("masterSwitch", None, "switch"),
            self.binary("buzzerSwitch", None, "switch"),
            self.binary("wifiState", None, "switch"),
            self.binary("heatState", None, "switch"),
            self.binary("reverseState", None, "switch"),
        ]
        ZendureBinarySensor.addBinarySensors(binairies)

        numbers = [
            self.number("outputLimit", None, "W", "power", 0, 800, NumberMode.SLIDER),
            self.number("inputLimit", None, "W", "power", 0, 1200, NumberMode.SLIDER),
            self.number("socSet", "{{ value | int / 10 }}", "%", None, 5, 100, NumberMode.SLIDER),
            self.number("minSoc", "{{ value | int / 10 }}", "%", None, 5, 100, NumberMode.SLIDER),
        ]
        ZendureNumber.addNumbers(numbers)

        switches = [
            self.switch("lampSwitch", None, "switch"),
        ]
        ZendureSwitch.addSwitches(switches)

        sensors = [
            self.sensor("chargingMode"),
            self.sensor("hubState"),
            self.sensor("solarInputPower", None, "W", "power"),
            self.sensor("packInputPower", None, "W", "power"),
            self.sensor("outputPackPower", None, "W", "power"),
            self.sensor("outputHomePower", None, "W", "power"),
            self.sensor("remainOutTime", None, "min", "duration"),
            self.sensor("remainInputTime", None, "min", "duration"),
            self.sensor("packNum", None),
            self.sensor("electricLevel", None, "%", "battery"),
            self.sensor("inverseMaxPower", None, "W"),
            self.sensor("solarPower1", None, "W", "power"),
            self.sensor("solarPower2", None, "W", "power"),
            self.sensor("gridInputPower", None, "W", "power"),
            self.sensor("pass"),
            self.sensor("strength"),
            self.sensor("hyperTmp", "{{ (value | float/10 - 273.15) | round(2) }}", "°C", "temperature"),
        ]
        ZendureSensor.addSensors(sensors)

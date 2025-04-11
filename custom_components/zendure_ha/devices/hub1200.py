"""Module for the Hyper2000 device integration in Home Assistant."""

import logging
from typing import Any

from homeassistant.components.number import NumberMode
from homeassistant.core import HomeAssistant

from custom_components.zendure_ha.binary_sensor import ZendureBinarySensor
from custom_components.zendure_ha.number import ZendureNumber
from custom_components.zendure_ha.select import ZendureSelect
from custom_components.zendure_ha.sensor import ZendureSensor
from custom_components.zendure_ha.zenduredevice import AcMode, ZendureDevice

_LOGGER = logging.getLogger(__name__)


class Hub1200(ZendureDevice):
    def __init__(self, hass: HomeAssistant, h_id: str, data: Any) -> None:
        """Initialise Hub1200."""
        super().__init__(hass, h_id, data["productKey"], data["deviceName"], "Hub 1200")
        self.powerMin = -1000
        self.powerMax = 800
        self.numbers: list[ZendureNumber] = []

    def sensorsCreate(self) -> None:
        super().sensorsCreate()

        binairies = [
            self.binary("masterSwitch", None, "switch"),
            self.binary("buzzerSwitch", None, "switch"),
            self.binary("wifiState", None, "switch"),
            self.binary("heatState", None, "switch"),
            self.binary("reverseState", None, "switch"),
        ]
        ZendureBinarySensor.addBinarySensors(binairies)

        self.numbers = [
            self.number("inputLimit", None, "W", "power", 0, 1200, NumberMode.SLIDER),
            self.number("outputLimit", None, "W", "power", 0, 200, NumberMode.SLIDER),
            self.number("socSet", "{{ value | int / 10 }}", "%", None, 5, 100, NumberMode.SLIDER),
            self.number("minSoc", "{{ value | int / 10 }}", "%", None, 5, 100, NumberMode.SLIDER),
        ]
        ZendureNumber.addNumbers(self.numbers)

        sensors = [
            self.sensor("hubState"),
            self.sensor("solarInputPower", None, "W", "power", 1),
            self.sensor("batVolt", None, "V", "voltage", 1),
            self.sensor("packInputPower", None, "W", "power", 1),
            self.sensor("outputPackPower", None, "W", "power", 1),
            self.sensor("outputHomePower", None, "W", "power", 1),
            self.sensor("remainOutTime", "{{ (value / 60) }}", "h", "duration"),
            self.sensor("remainInputTime", "{{ (value / 60) }}", "h", "duration"),
            self.sensor("packNum", None),
            self.sensor("electricLevel", None, "%", "battery", 1),
            self.sensor("energyPower", None, "W"),
            self.sensor("inverseMaxPower", None, "W"),
            self.sensor("solarPower1", None, "W", "power", 1),
            self.sensor("solarPower2", None, "W", "power", 1),
            self.sensor("gridInputPower", None, "W", "power", 1),
            self.sensor("packInputPowerCycle", None, "W", "power"),
            self.sensor("outputHomePowerCycle", None, "W", "power"),
            self.sensor("pass", None),
            self.sensor("strength", None),
        ]
        ZendureSensor.addSensors(sensors)

    def updateProperty(self, key: Any, value: Any) -> None:
        if key == "inverseMaxPower":
            self.powerMax = int(value)
            self.numbers[1].update_range(0, value)

        # Call the base class updateProperty method
        super().updateProperty(key, value)

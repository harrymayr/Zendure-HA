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
        self.powerMin = -1200
        self.powerMax = 800
        self.numbers: list[ZendureNumber] = []

    def sensorsCreate(self) -> None:
        super().sensorsCreate()

        binairies = [
            self.binary("heatState", None, "switch"),
            self.binary("reverseState", None, "switch"),
        ]
        ZendureBinarySensor.addBinarySensors(binairies)

        self.numbers = [
            self.number("outputLimit", None, "W", "power", 0, 800, NumberMode.SLIDER),
            self.number("inputLimit", None, "W", "power", 0, 1200, NumberMode.SLIDER),
            self.number("socSet", "{{ value | int / 10 }}", "%", None, 5, 100, NumberMode.SLIDER),
            self.number("minSoc", "{{ value | int / 10 }}", "%", None, 5, 100, NumberMode.SLIDER),
        ]
        ZendureNumber.addNumbers(self.numbers)

        switches = [
            self.switch("lampSwitch", None, "switch"),
        ]
        ZendureSwitch.addSwitches(switches)

        sensors = [
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
        ]
        ZendureSensor.addSensors(sensors)

    def updateProperty(self, key: Any, value: Any) -> bool:
        # Call the base class updateProperty method
        if not super().updateProperty(key, value):
            return False
        match key:
            case "inverseMaxPower":
                self.powerMax = value
                self.numbers[1].update_range(0, value)

            case "localState":
                _LOGGER.info(f"Hyper {self.name} set local state: {value}")
        return True

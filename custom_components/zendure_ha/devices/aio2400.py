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


class AIO2400(ZendureDevice):
    def __init__(self, hass: HomeAssistant, h_id: str, data: Any) -> None:
        """Initialise AIO2400."""
        super().__init__(hass, h_id, data["productKey"], data["deviceName"], "AIO 2400")
        self.powerMin = -1000
        self.powerMax = 800
        self.numbers: list[ZendureNumber] = []

    def sensorsCreate(self) -> None:
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

        selects = [
            self.select(
                "acMode",
                {1: "input", 2: "output"},
                self.update_ac_mode,
            ),
        ]
        ZendureSelect.addSelects(selects)
        sensors = [
            self.sensor("chargingMode", "Charging Mode"),
            self.sensor("hubState", "Hub State"),
            self.sensor("solarInputPower", "Solar Input Power", None, "W", "power"),
            self.sensor("packInputPower", "Pack Input Power", None, "W", "power"),
            self.sensor("outputPackPower", "Output Pack Power", None, "W", "power"),
            self.sensor("outputHomePower", "Output Home Power", None, "W", "power"),
            self.sensor("remainOutTime", "Remain Out Time", None, "min", "duration"),
            self.sensor("remainInputTime", "Remain Input Time", None, "min", "duration"),
            self.sensor("packNum", "Pack Num", None),
            self.sensor("electricLevel", "Electric Level", None, "%", "battery"),
            self.sensor("inverseMaxPower", "Inverse Max Power", None, "W"),
            self.sensor("gridInputPower", "grid Input Power", None, "W", "power"),
            self.sensor("pass", "Pass Mode", None),
            self.sensor("strength", "WiFi strength", None),
            self.sensor("autoModel"),
            self.sensor("packState"),
        ]
        ZendureSensor.addSensors(sensors)

    def update_ac_mode(self, mode: int) -> None:
        if mode == AcMode.INPUT:
            self.writeProperties({"acMode": mode, "inputLimit": self.entities["inputLimit"].state})
        elif mode == AcMode.OUTPUT:
            self.writeProperties({"acMode": mode, "outputLimit": self.entities["outputLimit"].state})

    def updateProperty(self, key: Any, value: Any) -> None:
        if key == "inverseMaxPower":
            self.powerMax = int(value)
            self.numbers[1].update_range(0, value)

        # Call the base class updateProperty method
        super().updateProperty(key, value)

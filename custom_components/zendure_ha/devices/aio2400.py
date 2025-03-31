"""Module for the Hyper2000 device integration in Home Assistant."""

import logging
from typing import Any

from homeassistant.components.number import NumberMode
from homeassistant.core import HomeAssistant

from custom_components.zendure_ha.select import ZendureSelect

from ..binary_sensor import ZendureBinarySensor
from ..number import ZendureNumber
from ..sensor import ZendureSensor
from ..switch import ZendureSwitch
from ..zenduredevice import ZendureDevice

_LOGGER = logging.getLogger(__name__)


class AIO2400(ZendureDevice):
    def __init__(self, hass: HomeAssistant, h_id: str, h_prod: str, name: str) -> None:
        """Initialise AIO2400."""
        super().__init__(hass, h_id, h_prod, name, "AIO 2400")
        self.chargemax = 1200
        self.dischargemax = 800
        self.numbers: list[ZendureNumber] = []

    def sensorsCreate(self) -> None:
        binairies = [
            self.binary("masterSwitch", "Master Switch", None, None, "switch"),
            self.binary("buzzerSwitch", "Buzzer Switch", None, None, "switch"),
            self.binary("wifiState", "WiFi State", None, None, "switch"),
            self.binary("heatState", "Heat State", None, None, "switch"),
            self.binary("reverseState", "Reverse State", None, None, "switch"),
        ]
        ZendureBinarySensor.addBinarySensors(binairies)

        self.numbers = [
            self.number("inputLimit", "Limit Input", None, "W", "power", 0, 1200, NumberMode.SLIDER),
            self.number("outputLimit", "Limit Output", None, "W", "power", 0, 200, NumberMode.SLIDER),
            self.number("socSet", "Soc maximum", "{{ value | int / 10 }}", "%", None, 5, 100, NumberMode.SLIDER),
            self.number("minSoc", "Soc minimum", "{{ value | int / 10 }}", "%", None, 5, 100, NumberMode.SLIDER),
        ]
        ZendureNumber.addNumbers(self.numbers)

        selects = [
            ZendureSelect(
                self.attr_device_info,
                f"{self.name} acMode",
                f"{self.name} AC Mode",
                self.update_ac_mode,
                options=["None", "AC input mode", "AC output mode"],
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
            self.sensor(
                "autoModel",
                "Auto Model",
                """{% set u = (value | int) %}
                {% set d = {
                0: 'Nothing',
                6: 'Battery priority mode',
                7: 'Appointment mode',
                8: 'Smart Matching Mode',
                9: 'Smart CT Mode',
                10: 'Electricity Price' } %}
                {{ d[u] if u in d else '???' }}""",
            ),
            self.sensor(
                "packState",
                "Pack State",
                """{% set u = (value | int) %}
                {% set d = {
                0: 'Sleeping',
                1: 'Charging',
                2: 'Discharging' } %}
                {{ d[u] if u in d else '???' }}""",
            ),
        ]
        ZendureSensor.addSensors(sensors)

    def update_ac_mode(self, mode: int) -> None:
        if mode == 1:
            self.writeProperties({"acMode": mode, "inputLimit": self.entities["inputLimit"].state})
        elif mode == 2:
            self.writeProperties({"acMode": mode, "outputLimit": self.entities["outputLimit"].state})
        else:
            self.writeProperties({"acMode": mode})

    def updateProperty(self, key: Any, value: Any) -> None:
        if key == "inverseMaxPower":
            self.dischargemax = int(value)
            self.numbers[1].update_range(0, value)

        # Call the base class updateProperty method
        super().updateProperty(key, value)

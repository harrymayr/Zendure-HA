"""Module for the Hyper2000 device integration in Home Assistant."""

import json
import logging
import socket
from datetime import datetime
from typing import Any

from homeassistant.components.number import NumberMode
from homeassistant.core import HomeAssistant

from custom_components.zendure_ha.binary_sensor import ZendureBinarySensor
from custom_components.zendure_ha.number import ZendureNumber
from custom_components.zendure_ha.select import ZendureSelect
from custom_components.zendure_ha.sensor import ZendureSensor
from custom_components.zendure_ha.switch import ZendureSwitch
from custom_components.zendure_ha.zenduredevice import ZendureDevice

_LOGGER = logging.getLogger(__name__)


class Hyper2000(ZendureDevice):
    def __init__(self, hass: HomeAssistant, h_id: str, data: Any) -> None:
        """Initialise Hyper2000."""
        super().__init__(hass, h_id, data["productKey"], data["deviceName"], "Hyper 2000")
        self.chargemax = 1200
        self.dischargemax = 800
        self.ipaddress = data["ip"]
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)  # UDP
        self.numbers: list[ZendureNumber] = []
        self.shelly = -1

    def sensorsCreate(self) -> None:
        selects = [
            self.select(
                "acMode",
                {1: "input", 2: "output"},
                self.update_ac_mode,
            ),
        ]
        ZendureSelect.addSelects(selects)

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

        switches = [
            self.switch("lampSwitch", None, "switch"),
        ]
        ZendureSwitch.addSwitches(switches)

        sensors = [
            # self.sensor("chargingMode"),
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
            self.sensor("hyperTmp", "{{ (value | float/10 - 273.15) | round(2) }}", "°C", "temperature"),
        ]
        ZendureSensor.addSensors(sensors)

    def update_ac_mode(self, mode: int) -> None:
        if mode == 1:
            self.writeProperties({"acMode": mode, "inputLimit": self.entities["inputLimit"].state})
        elif mode == 2:
            self.writeProperties({"acMode": mode, "outputLimit": self.entities["outputLimit"].state})

    def updateProperty(self, key: Any, value: Any) -> None:
        if key == "inverseMaxPower":
            self.dischargemax = value
            self.numbers[1].update_range(0, value)

        # Call the base class updateProperty method
        super().updateProperty(key, value)

    def init_shelly(self, chargeType: int) -> None:
        if self.shelly != chargeType:
            self.shelly = chargeType
            self.function_invoke({
                "timestamp": int(datetime.now().timestamp()),
                "messageId": self._messageid,
                "deviceKey": self.hid,
                "method": "invoke",
                "function": "deviceAutomation",
                "arguments": [{"autoModelValue": {"localSrc": "34987a6720f4", "lineSelect": 1}}],
            })
            self.function_invoke({
                "arguments": [
                    {
                        "autoModelProgram": 2,
                        "autoModelValue": {
                            "chargingType": chargeType,
                            "chargingPower": self.dischargemax if chargeType == 0 else 0,
                            "freq": 0,
                            "lineSelect": 1,
                            "outPower": 0,
                        },
                        "msgType": 1,
                        "autoModel": 9,
                    }
                ],
                "deviceKey": self.hid,
                "function": "deviceAutomation",
                "messageId": self._messageid,
                "timestamp": int(datetime.now().timestamp()),
            })

    def power_charge(self, power: int) -> None:
        pwr = power - self.asInt("outputPackPower")

        if self.shelly != 3:
            self.init_shelly(3)

        payload = json.dumps(
            {
                "src": "shellypro3em-34987a6720f4",
                "dst": "*",
                "method": "NotifyStatus",
                "params": {
                    "ts": round(datetime.now().timestamp(), 2),
                    "em:0": {"id": 0, "a_act_power": -pwr, "b_act_power": 0, "c_act_power": 0},
                },
            },
            default=lambda o: o.__dict__,
            separators=(",", ":"),
        )
        _LOGGER.info(f"power charge: {self.name} [{self.ipaddress}] set: {power} from {self.power} => {payload}")
        self.sock.sendto(bytes(payload, "utf-8"), (self.ipaddress, 8006))
        self.sock.sendto(bytes(payload, "utf-8"), ("192.168.2.14", 1010))

    def power_discharge(self, power: int) -> None:
        actual = self.asInt("packInputPower")
        pwr = power - actual
        if self.shelly != 0:
            self.init_shelly(0)

        payload = json.dumps(
            {
                "src": "shellypro3em-34987a6720f4",
                "dst": "*",
                "method": "NotifyStatus",
                "params": {
                    "ts": round(datetime.now().timestamp(), 2),
                    "em:0": {"id": 0, "a_act_power": pwr},
                },
            },
            default=lambda o: o.__dict__,
            separators=(",", ":"),
        )
        _LOGGER.info(f"power discharge: {self.name} [{self.ipaddress}] set: {power} from {actual} => {payload}")
        self.sock.sendto(bytes(payload, "utf-8"), (self.ipaddress, 8006))
        self.sock.sendto(bytes(payload, "utf-8"), ("192.168.2.143", 1010))

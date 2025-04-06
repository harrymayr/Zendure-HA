"""Module for the Hyper2000 device integration in Home Assistant."""

from __future__ import annotations

from calendar import c
import json
import logging
import socket
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.number import NumberMode
from homeassistant.core import HomeAssistant

from custom_components.zendure_ha.binary_sensor import ZendureBinarySensor
from custom_components.zendure_ha.number import ZendureNumber
from custom_components.zendure_ha.select import ZendureSelect
from custom_components.zendure_ha.sensor import ZendureSensor
from custom_components.zendure_ha.switch import ZendureSwitch
from custom_components.zendure_ha.zenduredevice import AcMode, BatteryState, ZendureDevice

_LOGGER = logging.getLogger(__name__)


class Hyper2000(ZendureDevice):
    def __init__(self, hass: HomeAssistant, h_id: str, data: Any) -> None:
        """Initialise Hyper2000."""
        super().__init__(hass, h_id, data["productKey"], data["deviceName"], "Hyper 2000")
        self.chargemax = 1200
        self.dischargemax = 800
        self.ipaddress = data["ip"]
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.numbers: list[ZendureNumber] = []
        self.idle = datetime.min

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
        if mode == AcMode.INPUT:
            self.writeProperties({"acMode": mode, "inputLimit": self.entities["inputLimit"].state})
        elif mode == AcMode.OUTPUT:
            self.writeProperties({"acMode": mode, "outputLimit": self.entities["outputLimit"].state})

    def updateProperty(self, key: Any, value: Any) -> bool:
        # Call the base class updateProperty method
        if not super().updateProperty(key, value):
            return False
        match key:
            case "inverseMaxPower":
                self.dischargemax = value
                self.numbers[1].update_range(0, value)

            case "localState":
                _LOGGER.info(f"Hyper {self.name} set local state: {value}")

            case "packInputPower":
                self.power = int(value)

            case "outputPackPower":
                self.power = -int(value)
        return True

    def updateSetpoint(self, setpoint: int | None = None) -> None:
        """Update setpoint."""
        if setpoint and setpoint != self.setpoint:
            _LOGGER.info(f"Hyper {self.name} setpoint: {setpoint} old:{self.setpoint}")
            self.setpoint = setpoint

        # if self.power == 0:
        #     if self.idle < datetime.now():
        #         # self.power_off()
        #     else:
        #         _LOGGER.info(f"Hyper {self.name} power off in {self.idle - datetime.now()}")
        #         # and not self.isEqual("acMode", 0)
        #         # if self.power > 0:
        #         #     self.idle = datetime.max
        #         # elif self.idle == datetime.max:
        #         #     self.idle = datetime.now() + timedelta(seconds=30)

        _LOGGER.info(f"Hyper {self.name} update setpoint: {self.setpoint}")
        if not self.isEqual("autoModel", 9) or not self.isEqual("packState", self.batteryState):
            chargeType = 0 if ZendureDevice.batteryState == BatteryState.DISCHARGING else 3
            _LOGGER.info(
                f"Hyper {self.name} {ZendureDevice.batteryState} CT mode: {chargeType} autoModel: {self.asInt('autoModel')} packState: {self.asInt('packState')}"
            )
            self.function_invoke({
                "arguments": [
                    {
                        "autoModelProgram": 2,
                        "autoModelValue": {
                            "chargingType": chargeType,
                            "chargingPower": 0 if ZendureDevice.batteryState == BatteryState.DISCHARGING else 800,
                            "freq": 0,
                            "lineSelect": 1,
                            # "outPower": 1,
                        },
                        "msgType": 10,
                        "autoModel": 9,
                    }
                ],
                "deviceKey": self.hid,
                "function": "deviceAutomation",
                "messageId": self._messageid,
                "timestamp": int(datetime.now().timestamp()),
            })

        if not self.isEqual("localState", 1):
            _LOGGER.info(f"Hyper {self.name} set local mode")
            self.function_invoke({
                "timestamp": int(datetime.now().timestamp()),
                "messageId": self._messageid,
                "deviceKey": self.hid,
                "method": "invoke",
                "function": "deviceAutomation",
                "arguments": [{"autoModelValue": {"localSrc": "34987a6720f4", "lineSelect": 1}}],
            })

        payload = json.dumps(
            {
                "src": "shellypro3em-34987a6720f4",
                "dst": "*",
                "method": "NotifyStatus",
                "params": {
                    "ts": round(datetime.now().timestamp(), 2),
                    "em:0": {"id": 0, "a_act_power": self.setpoint, "b_act_power": 0, "c_act_power": 0},
                },
            },
            default=lambda o: o.__dict__,
            separators=(",", ":"),
        )
        self.sock.sendto(bytes(payload, "utf-8"), (self.ipaddress, 8006))
        _LOGGER.info(f"Update power: {self.name} [{self.ipaddress}] set: {self.setpoint}")

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
                            # "outPower": 0,
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
        self.power = self.asInt("outputPackPower")
        pwr = power - self.power

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
                    "em:0": {"id": 0, "a_act_power": pwr, "b_act_power": 0, "c_act_power": 0},
                },
            },
            default=lambda o: o.__dict__,
            separators=(",", ":"),
        )
        _LOGGER.info(f"power discharge: {self.name} [{self.ipaddress}] set: {power} from {actual} => {payload}")
        self.sock.sendto(bytes(payload, "utf-8"), (self.ipaddress, 8006))

"""Zendure Integration device."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from homeassistant.components.number import NumberMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.template import Template
from paho.mqtt import client as mqtt_client

from .binary_sensor import ZendureBinarySensor
from .const import DOMAIN
from .number import ZendureNumber
from .sensor import ZendureSensor
from .switch import ZendureSwitch
from .zendurecharge import ZendureCharge

_LOGGER = logging.getLogger(__name__)


class ZendureDevice(ZendureCharge):
    """A Zendure Device."""

    _messageid = 0

    def __init__(self, hass: HomeAssistant, h_id: str, h_prod: str, name: str, model: str) -> None:
        """Initialize ZendureDevice."""
        super().__init__()
        self._hass = hass
        self.hid = h_id
        self.prodkey = h_prod
        self.name = name
        self.unique = "".join(name.split())
        self.attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self.name)},
            name=self.name,
            manufacturer="Zendure",
            model=model,
        )

        self._topic_read = f"iot/{self.prodkey}/{self.hid}/properties/read"
        self._topic_write = f"iot/{self.prodkey}/{self.hid}/properties/write"
        self.topic_function = f"iot/{self.prodkey}/{self.hid}/function/invoke"
        self.mqtt: mqtt_client.Client
        self.entities: dict[str, Any] = {}
        self.phase: Any | None = None

    def handleTopic(self, topic: str, payload: str) -> None:
        _LOGGER.info(f"Received topic: {self.hid} {topic} {payload}")

    def sensorsCreate(self) -> None:
        return

    def sendRefresh(self) -> None:
        self.mqtt.publish(self._topic_read, '{"properties": ["getAll"]}')

    def writeProperty(self, entity: Entity, value: Any) -> None:
        _LOGGER.info(f"Writing property {self.name} {entity.name} => {value}")
        ZendureDevice._messageid += 1
        if entity.unique_id is None:
            _LOGGER.error(f"Entity {entity.name} has no unique_id.")
            return

        property_name = entity.unique_id[(len(self.name) + 1) :]
        if property_name in {"minSoc", "socSet"}:
            value = int(value * 10)

        self.writeProperties({property_name: value})

    def writeProperties(self, props: dict[str, Any]) -> None:
        ZendureDevice._messageid += 1
        payload = json.dumps(
            {
                "deviceId": self.hid,
                "messageId": ZendureDevice._messageid,
                "timestamp": int(datetime.now().timestamp()),
                "properties": props,
            },
            default=lambda o: o.__dict__,
        )
        self.mqtt.publish(self._topic_write, payload)

    def sensorAdd(self, propertyname: str, value: Any | None = None) -> None:
        try:
            _LOGGER.info(f"{self.hid} {self.name}new sensor: {propertyname}")
            sensor = ZendureSensor(self.attr_device_info, f"{self.hid} {propertyname}", f"{self.name} {propertyname}")
            self.entities[propertyname] = sensor
            ZendureSensor.addSensors([sensor])
            if value:
                sensor.update_value(value)
        except Exception as err:
            _LOGGER.error(err)

    def updateProperty(self, key: Any, value: Any) -> None:
        if sensor := self.entities.get(key, None):
            sensor.update_value(value)
        elif isinstance(value, (int | float)):
            self._hass.loop.call_soon_threadsafe(self.sensorAdd, key, value)
        else:
            _LOGGER.info(f"Found unknown state value:  {self.hid} {key} => {value}")

    def updateBattery(self, _data: str) -> None:
        # _LOGGER.info(f"update_battery: {self.hid} => {data}")
        return

    def update_power_delta(self, power: int) -> None:
        _LOGGER.info(f"update power: {self.name} set: {power} from {self.currentpower}")
        ZendureDevice._messageid += 1

        if power >= 0:
            if (outPower := power - self.currentpower) == 0:
                return
            _LOGGER.info(f"update power; discharging : {self.name} with {power} delta:{outPower}")
            payload = json.dumps(
                {
                    "arguments": [
                        {
                            "autoModelProgram": 2,
                            "autoModelValue": {"chargingType": 2, "outPower": outPower},
                            "msgType": 1,
                            "autoModel": 9,
                        }
                    ],
                    "deviceKey": self.hid,
                    "function": "deviceAutomation",
                    "messageId": ZendureDevice._messageid,
                    "timestamp": int(datetime.now().timestamp()),
                },
                default=lambda o: o.__dict__,
            )
        else:
            if (outPower := (power - self.currentpower)) == 0:
                return
            if outPower != 0:
                outPower -= 50  # 50W for the inverter
            _LOGGER.info(f"update power; charging : {self.name} with {power} delta:{outPower}")
            payload = json.dumps(
                {
                    "arguments": [
                        {
                            "autoModelProgram": 2,
                            "autoModelValue": {"chargingType": 3, "chargingPower": self.data[1].max, "outPower": outPower},
                            "msgType": 1,
                            "autoModel": 9,
                        }
                    ],
                    "deviceKey": self.hid,
                    "function": "deviceAutomation",
                    "messageId": ZendureDevice._messageid,
                    "timestamp": int(datetime.now().timestamp()),
                },
                default=lambda o: o.__dict__,
            )

        self.mqtt.publish(self.topic_function, payload)

    def update_power(self, power: int) -> None:
        _LOGGER.info(f"update_power: {self.name} {power}")
        ZendureDevice._messageid += 1

        autoModel = 8 if power != 0 else 0
        chargetype = 1 if power < 0 else 0
        program = 1 if power < 0 else 0
        chargepower = max(0, -power)
        outpower = max(0, power)
        payload = json.dumps(
            {
                "arguments": [
                    {
                        "autoModelProgram": program,
                        "autoModelValue": {"chargingType": chargetype, "chargingPower": chargepower, "outPower": outpower},
                        "msgType": 1,
                        "autoModel": autoModel,
                    }
                ],
                "deviceKey": self.hid,
                "function": "deviceAutomation",
                "messageId": ZendureDevice._messageid,
                "timestamp": int(datetime.now().timestamp()),
            },
            default=lambda o: o.__dict__,
        )
        self.mqtt.publish(self.topic_function, payload)

    def update_power_test(self, power: int) -> None:
        _LOGGER.info(f"update_power: {self.name} {power}")
        ZendureDevice._messageid += 1

        payload = json.dumps(
            {
                "arguments": [
                    {
                        "autoModelProgram": 2,
                        "autoModelValue": {
                            "chargingType": 2,
                            "chargingPower": 800,
                            "outPower": power,
                        },
                        "msgType": 1,
                        "autoModel": 9,
                    }
                ],
                "deviceKey": self.hid,
                "function": "deviceAutomation",
                "messageId": ZendureDevice._messageid,
                "timestamp": int(datetime.now().timestamp()),
            },
            default=lambda o: o.__dict__,
        )
        self.mqtt.publish(self.topic_function, payload)

    def binary(
        self,
        uniqueid: str,
        name: str,
        template: str | None = None,
        uom: str | None = None,
        deviceclass: Any | None = None,
    ) -> ZendureBinarySensor:
        tmpl = Template(template, self._hass) if template else None
        s = ZendureBinarySensor(self.attr_device_info, f"{self.name} {uniqueid}", f"{self.name} {name}", tmpl, uom, deviceclass)
        self.entities[uniqueid] = s
        return s

    def number(
        self,
        uniqueid: str,
        name: str,
        template: str | None = None,
        uom: str | None = None,
        deviceclass: Any | None = None,
        minimum: int = 0,
        maximum: int = 2000,
        mode: NumberMode = NumberMode.AUTO,
    ) -> ZendureNumber:
        def _write_property(entity: Entity, value: Any) -> None:
            self.writeProperty(entity, value)

        tmpl = Template(template, self._hass) if template else None
        s = ZendureNumber(
            self.attr_device_info,
            f"{self.name} {uniqueid}",
            f"{self.name} {name}",
            _write_property,
            tmpl,
            uom,
            deviceclass,
            maximum,
            minimum,
            mode,
        )
        self.entities[uniqueid] = s
        return s

    def sensor(
        self,
        uniqueid: str,
        name: str,
        template: str | None = None,
        uom: str | None = None,
        deviceclass: Any | None = None,
    ) -> ZendureSensor:
        tmpl = Template(template, self._hass) if template else None
        s = ZendureSensor(self.attr_device_info, f"{self.name} {uniqueid}", f"{self.name} {name}", tmpl, uom, deviceclass)
        self.entities[uniqueid] = s
        return s

    def switch(
        self,
        uniqueid: str,
        name: str,
        template: str | None = None,
        uom: str | None = None,
        deviceclass: Any | None = None,
    ) -> ZendureSwitch:
        def _write_property(entity: Entity, value: Any) -> None:
            self.writeProperty(entity, value)

        tmpl = Template(template, self._hass) if template else None
        s = ZendureSwitch(self.attr_device_info, f"{self.name} {uniqueid}", f"{self.name} {name}", _write_property, tmpl, uom, deviceclass)
        self.entities[uniqueid] = s
        return s

    def asInt(self, name: str) -> int:
        if (sensor := self.entities.get(name, None)) and sensor.state:
            return int(sensor.state)
        return 0

    def isInt(self, name: str) -> int | None:
        if (sensor := self.entities.get(name, None)) and sensor.state:
            return int(sensor.state)
        return None

    def asFloat(self, name: str) -> float:
        if (sensor := self.entities.get(name, None)) and sensor.state:
            return float(sensor.state)
        return 0

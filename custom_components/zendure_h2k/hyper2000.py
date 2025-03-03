from __future__ import annotations
import logging
import json
from datetime import datetime
from typing import Any
from paho.mqtt import client as mqtt_client
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.template import Template
from homeassistant.components.sensor import SensorEntity
from homeassistant.components.binary_sensor import BinarySensorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class Hyper2000:
    addBinarySensors: AddEntitiesCallback
    addSelects: AddEntitiesCallback
    addSensors: AddEntitiesCallback
    addSwitches: AddEntitiesCallback

    def __init__(self, hass: HomeAssistant, h_id, h_prod, name, device: dict) -> None:
        """Initialise."""
        self._hass = hass
        self.hid = h_id
        self.prodkey = h_prod
        self.name = name
        self.unique = "".join(name.split())
        self.properties: dict[str, Any] = {}
        self.sensors: dict[str, Any] = {}
        # for key, value in device.items():
        #     self.properties[key] = value
        self._topic_read = f"iot/{self.prodkey}/{self.hid}/properties/read"
        self._topic_write = f"iot/{self.prodkey}/{self.hid}/properties/write"
        self.topic_function = f"iot/{self.prodkey}/{self.hid}/function/invoke"
        self.attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self.name)},
            name=self.name,
            manufacturer="Zendure",
            model="Hyper2000",
        )
        self._messageid = 0

    def create_sensors(self) -> None:
        def binary(
            uniqueid: str,
            name: str,
            template: str = None,
            uom: str = None,
            deviceclass: str = None,
        ) -> Hyper2000BinarySensor:
            if template:
                s = Hyper2000BinarySensor(self, uniqueid, name, Template(template, self._hass), uom, deviceclass)
            else:
                s = Hyper2000BinarySensor(self, uniqueid, name, None, uom, deviceclass)
            self.sensors[uniqueid] = s
            return s

        def sensor(
            uniqueid: str,
            name: str,
            template: str = None,
            uom: str = None,
            deviceclass: str = None,
        ) -> Hyper2000Sensor:
            if template:
                s = Hyper2000Sensor(
                    self,
                    uniqueid,
                    name,
                    Template(template, self._hass),
                    uom,
                    deviceclass,
                )
            else:
                s = Hyper2000Sensor(self, uniqueid, name, None, uom, deviceclass)
            self.sensors[uniqueid] = s
            return s

        binairies = [
            binary("masterSwitch", "Master Switch", "{{ value | default() }}", None, "switch"),
            binary("buzzerSwitch", "Buzzer Switch", "{{ value | default() }}", None, "switch"),
            binary("wifiState", "WiFi State", "{{ value | bool() }}", None, "switch"),
            binary("heatState", "Heat State", "{{ value | bool() }}", None, "switch"),
            binary("reverseState", "Reverse State", "{{ value | bool() }}", None, "switch"),
        ]
        Hyper2000.addBinarySensors(binairies)

        sensors = [
            sensor(
                "acMode",
                "AC Mode",
                """{% set u = (value | int) %}
                {% set d = {
                0: 'None',
                1: 'Charging',
                2: 'Standby',
                3: 'Bypass',
                4: 'Discharging' } %}
                {{ d[u] if u in d else '???' }}""",
            ),
            sensor(
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
            sensor(
                "chargingMode",
                "Charging Mode",
                """{% set u = (value | int) %}
                {% set d = {
                0: 'None',
                1: 'Standby',
                2: 'Charging' } %}
                {{ d[u] if u in d else '???' }}""",
            ),
            sensor("hubState", "Hub State"),
            sensor("solarInputPower", "Solar Input Power", None, "W", "power"),
            sensor("packInputPower", "Pack Input Power", None, "W", "power"),
            sensor("outputPackPower", "Output Pack Power", None, "W", "power"),
            sensor("outputHomePower", "Output Home Power", None, "W", "power"),
            sensor("outputLimit", "Output Limit", None, "W"),
            sensor("inputLimit", "Input Limit", None, "W"),
            sensor("remainOutTime", "Remain Out Time", None, "min", "duration"),
            sensor("remainInputTime", "Remain Input Time", None, "min", "duration"),
            sensor("packState", "Pack State", None),
            sensor("packNum", "Pack Num", None),
            sensor("electricLevel", "Electric Level", None, "%", "battery"),
            sensor("socSet", "socSet", "{{ value | int / 10 }}", "%"),
            sensor("minSoc", "minSOC", "{{ value | int / 10 }}", "%"),
            sensor("inverseMaxPower", "Inverse Max Power", None, "W"),
            sensor("solarPower1", "Solar Power 1", None, "W", "power"),
            sensor("solarPower2", "Solar Power 2", None, "W", "power"),
            sensor("gridInputPower", "grid Input Power", None, "W", "power"),
            sensor("pass", "Pass Mode", None),
            sensor("strength", "WiFi strength", None),
            sensor("hyperTmp", "Hyper Temperature", "{{ (value | float/10 - 273.15) | round(2) }}", "°C", "temperature"),
        ]
        Hyper2000.addSensors(sensors)

    def add_sensor(self, propertyname: str, value=None) -> None:
        try:
            _LOGGER.info(f"{self.hid} new sensor: {propertyname}")
            sensor = Hyper2000Sensor(self, propertyname, propertyname)
            self.sensors[propertyname] = sensor
            if value:
                sensor.update_value(value)
            Hyper2000.addSensors([sensor])
        except Exception as err:
            _LOGGER.exception(err)

    def update_battery(self, data) -> None:
        _LOGGER.info(f"update_battery: {self.hid} => {data}")

    def update_power(self, client: mqtt_client.Client, chargetype: int, chargepower: int, outpower: int) -> None:
        _LOGGER.info(f"update_power: {self.hid} {chargetype} {chargepower} {outpower}")
        self._messageid += 1
        program = 1 if chargetype > 0 else 0
        power = json.dumps(
            {
                "arguments": [
                    {
                        "autoModelProgram": program,
                        "autoModelValue": {"chargingType": chargetype, "chargingPower": chargepower, "outPower": outpower},
                        "msgType": 1,
                        "autoModel": 8,
                    }
                ],
                "deviceKey": self.hid,
                "function": "deviceAutomation",
                "messageId": self._messageid,
                "timestamp": int(datetime.now().timestamp()),
            },
            default=lambda o: o.__dict__,
        )
        client.publish(self.topic_function, power)


class Hyper2000Sensor(SensorEntity):
    def __init__(
        self,
        hyper: Hyper2000,
        uniqueid: str,
        name: str,
        template: Template | None = None,
        uom: str = None,
        deviceclass: str = None,
    ) -> None:
        """Initialize a Hyper2000 entity."""
        self._attr_available = True
        self._attr_device_info = hyper.attr_device_info
        self.hyper = hyper
        self._attr_name = f"{hyper.name} {name}"
        self._attr_unique_id = f"{hyper.unique}-{uniqueid}"
        self._attr_should_poll = False
        self._attr_native_unit_of_measurement = uom
        self._value_template: Template | None = template
        self._attr_device_class = deviceclass

    def update_value(self, value):
        try:
            if self._value_template is not None:
                self._attr_native_value = self._value_template.async_render_with_possible_json_value(value, None)
                if self.hass:
                    self.schedule_update_ha_state()
            elif isinstance(value, (int, float)):
                self._attr_native_value = int(value)
                if self.hass:
                    self.schedule_update_ha_state()
        except Exception as err:
            _LOGGER.exception(f"Error {err} setting state: {self._attr_unique_id} => {value}")


class Hyper2000BinarySensor(BinarySensorEntity):
    def __init__(
        self,
        hyper: Hyper2000,
        uniqueid: str,
        name: str,
        template: Template | None = None,
        uom: str = None,
        deviceclass: str = None,
    ) -> None:
        """Initialize a Hyper2000 entity."""
        self._attr_available = True
        self._attr_device_info = hyper.attr_device_info
        self.hyper = hyper
        self._attr_name = f"{hyper.name} {name}"
        self._attr_unique_id = f"{hyper.unique}-{uniqueid}"
        self._attr_should_poll = False
        self._attr_native_unit_of_measurement = uom
        self._value_template: Template | None = template
        self._attr_device_class = deviceclass

    def update_value(self, value):
        try:
            _LOGGER.info(f"Update binary sensor: {self._attr_unique_id} => {value}")
            if self._value_template is not None:
                self._attr_is_on = self._value_template.async_render_with_possible_json_value(value, None)
                self.schedule_update_ha_state()
            elif isinstance(value, (int, float)):
                self._attr_is_on = int(value) != 0
                self.schedule_update_ha_state()
            elif isinstance(value, (bool)):
                self._attr_is_on = bool(value)
                self.schedule_update_ha_state()
        except Exception as err:
            _LOGGER.error(f"Error {err} setting state: {self._attr_unique_id} => {value}")

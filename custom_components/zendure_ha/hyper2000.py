import logging
import json
from datetime import datetime
from typing import Any
from paho.mqtt import client as mqtt_client
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.template import Template

from .sensor import ZendureSensor
from .binary_sensor import ZendureBinarySensor
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class Hyper2000:
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
            model="Hyper 2000",
        )
        self._messageid = 0
        self.busy = False

    def create_sensors(self) -> None:
        def binary(
            uniqueid: str,
            name: str,
            template: str = None,
            uom: str = None,
            deviceclass: str = None,
        ) -> ZendureBinarySensor:
            if template:
                s = ZendureBinarySensor(
                    self.attr_device_info, f"{self.hid} {uniqueid}", f"{self.name} {name}", Template(template, self._hass), uom, deviceclass
                )
            else:
                s = ZendureBinarySensor(self.attr_device_info, f"{self.hid} {uniqueid}", f"{self.name} {name}", None, uom, deviceclass)
            self.sensors[uniqueid] = s
            return s

        def sensor(
            uniqueid: str,
            name: str,
            template: str = None,
            uom: str = None,
            deviceclass: str = None,
        ) -> ZendureSensor:
            if template:
                s = ZendureSensor(
                    self.attr_device_info, f"{self.hid} {uniqueid}", f"{self.name} {name}", Template(template, self._hass), uom, deviceclass
                )
            else:
                s = ZendureSensor(self.attr_device_info, f"{self.hid} {uniqueid}", f"{self.name} {name}", None, uom, deviceclass)
            self.sensors[uniqueid] = s
            return s

        binairies = [
            binary("masterSwitch", "Master Switch", "{{ value | default() }}", None, "switch"),
            binary("buzzerSwitch", "Buzzer Switch", "{{ value | default() }}", None, "switch"),
            binary("lampSwitch", "Lamp Switch", "{{ value | default() }}", None, "switch"),
            binary("wifiState", "WiFi State", "{{ value | bool() }}", None, "switch"),
            binary("heatState", "Heat State", "{{ value | bool() }}", None, "switch"),
            binary("reverseState", "Reverse State", "{{ value | bool() }}", None, "switch"),
        ]
        ZendureBinarySensor.addBinarySensors(binairies)

        sensors = [
            sensor("chargingMode", "Charging Mode"),
            sensor("hubState", "Hub State"),
            sensor("solarInputPower", "Solar Input Power", None, "W", "power"),
            sensor("packInputPower", "Pack Input Power", None, "W", "power"),
            sensor("outputPackPower", "Output Pack Power", None, "W", "power"),
            sensor("outputHomePower", "Output Home Power", None, "W", "power"),
            sensor("outputLimit", "Output Limit", None, "W"),
            sensor("inputLimit", "Input Limit", None, "W"),
            sensor("remainOutTime", "Remain Out Time", None, "min", "duration"),
            sensor("remainInputTime", "Remain Input Time", None, "min", "duration"),
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
            sensor(
                "acMode",
                "AC Mode",
                """{% set u = (value | int) %}
                {% set d = {
                0: 'None',
                1: "AC input mode",
                2: "AC output mode" } %}
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

    def add_sensor(self, propertyname: str, value=None) -> None:
        try:
            _LOGGER.info(f"{self.hid} new sensor: {propertyname}")
            sensor = ZendureSensor(self.attr_device_info, f"{self.hid} {propertyname}", f"{self.name} {propertyname}")
            self.sensors[propertyname] = sensor
            if value:
                sensor.update_value(value)
            ZendureSensor.addSensors([sensor])
        except Exception as err:
            _LOGGER.exception(err)

    def update_battery(self, data) -> None:
        # _LOGGER.info(f"update_battery: {self.hid} => {data}")
        return

    def update_power(self, client: mqtt_client.Client, chargetype: int, chargepower: int, outpower: int) -> None:
        if self.busy:
            _LOGGER.info(f"update_power error busy: {self.hid} {chargetype} {chargepower} {outpower}")
            return
        self.busy = True
        _LOGGER.info(f"update_power: {self.hid} {chargetype} {chargepower} {outpower}")
        self._messageid += 1
        program = 1 if chargetype > 0 else 0
        autoModel = 8 if chargetype > 0 or (outpower != 0) else 0
        power = json.dumps(
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
                "messageId": self._messageid,
                "timestamp": int(datetime.now().timestamp()),
            },
            default=lambda o: o.__dict__,
        )
        client.publish(self.topic_function, power)

    def handle_message(self, topic: Any, payload: Any) -> None:
        def handle_properties(properties: Any) -> None:
            for key, value in properties.items():
                handle_property(key, value)

        def handle_property(key: Any, value: Any) -> None:
            if sensor := self.sensors.get(key, None):
                sensor.update_value(value)
            elif isinstance(value, (int | float)):
                self._hass.loop.call_soon_threadsafe(self.add_sensor, key, value)
            else:
                _LOGGER.info(f"Found unknown state value:  {self.hid} {key} => {value}")

        topics = topic.split("/")
        parameter = topics[-1]
        if parameter == "report":
            if properties := payload.get("properties", None):
                handle_properties(properties)
            elif properties := payload.get("cluster", None):
                handle_property("clusterId", properties["clusterId"])
                handle_property("Phase", properties["phaseCheck"])
            else:
                _LOGGER.info(f"Found unknown topic: {self.hid} {topic} {payload}")
        elif parameter == "reply" and topics[-3] == "function":
            # battery information
            self.busy = False
        elif parameter == "log" and payload["logType"] == 2:
            # battery information
            self.update_battery(payload["log"]["params"])
        else:
            _LOGGER.info(f"Receive: {self.hid} {topic} => {payload}")

"""Zendure Integration device."""

from __future__ import annotations

import asyncio
import json
import logging
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from homeassistant.components.number import NumberMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.template import Template
from homeassistant.util import dt as dt_util
from paho.mqtt import client as mqtt_client

from custom_components.zendure_ha.binary_sensor import ZendureBinarySensor
from custom_components.zendure_ha.const import DOMAIN
from custom_components.zendure_ha.number import ZendureNumber
from custom_components.zendure_ha.select import ZendureRestoreSelect, ZendureSelect
from custom_components.zendure_ha.sensor import ZendureRestoreSensor, ZendureSensor
from custom_components.zendure_ha.switch import ZendureSwitch

_LOGGER = logging.getLogger(__name__)

SF_COMMAND_CHAR = "0000c304-0000-1000-8000-00805f9b34fb"


class ZendureDevice:
    """A Zendure Device."""

    devicedict: dict[str, ZendureDevice] = {}
    devices: list[ZendureDevice] = []
    clusters: list[ZendureDevice] = []
    logMqtt: bool = False
    _messageid = 0

    def __init__(self, hass: HomeAssistant, h_id: str, definition: ZendureDeviceDefinition, model: str) -> None:
        """Initialize ZendureDevice."""
        self._hass = hass
        self.hid = h_id
        self.prodkey = definition.productKey
        self.name = definition.deviceName
        self.unique = "".join(self.name.split())
        self.attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self.name)},
            name=self.name,
            manufacturer="Zendure",
            model=model,
            serial_number=definition.snNumber,
        )
        self._topic_read = f"iot/{self.prodkey}/{self.hid}/properties/read"
        self._topic_write = f"iot/{self.prodkey}/{self.hid}/properties/write"
        self.topic_function = f"iot/{self.prodkey}/{self.hid}/function/invoke"
        self.mqtt: mqtt_client.Client | None = None
        self.entities: dict[str, Entity | None] = {}
        self.batteries: list[str] = []
        self.devices.append(self)

        self.lastUpdate = datetime.now()
        self.bleDevice: BLEDevice | None = None

        self.powerMax = 0
        self.powerMin = 0
        self.powerAct = 0
        self.capacity = 0
        self.clusterType: Any = 0
        self.clusterdevices: list[ZendureDevice] = []
        self.powerSensors: list[ZendureSensor] = []

    def initMqtt(self, mqtt: mqtt_client.Client) -> None:
        self.mqtt = mqtt
        if self.mqtt:
            self.mqtt.subscribe(f"/{self.prodkey}/{self.hid}/#")
            self.mqtt.subscribe(f"iot/{self.prodkey}/{self.hid}/#")
        self.sendRefresh()

    def sensorsCreate(self) -> None:
        if len(self.devices) > 1:
            clusters: dict[Any, str] = {0: "clusterunknown", 1: "clusterowncircuit", 2: "cluster800", 3: "cluster1200", 4: "cluster2400"}
            for d in self.devices:
                if d != self:
                    clusters[d.hid] = f"Part of {d.name} cluster"

            ZendureSelect.addSelects([
                self.select(
                    "cluster",
                    clusters,
                    self.update_cluster,
                    True,
                )
            ])

        self.powerSensors = [
            self.sensor("aggrChargeDaykWh", None, "kWh", "energy", "total", 2, True),
            self.sensor("aggrDischargeDaykWh", None, "kWh", "energy", "total", 2, True),
        ]
        ZendureSensor.addSensors(self.powerSensors)

    def sensorsBatteryCreate(self, data: list[str]) -> None:
        if self.logMqtt:
            _LOGGER.info(f"update_battery: {self.name} => {data}")
        self.batteries = data
        for i in range(len(data)):
            idx = i + 1
            sensors = [
                self.sensor(f"battery {idx} totalVol", "{{ (value / 100) }}", "V", "voltage", "measurement"),
                self.sensor(f"battery {idx} maxVol", "{{ (value / 100) }}", "V", "voltage", "measurement"),
                self.sensor(f"battery {idx} minVol", "{{ (value / 100) }}", "V", "voltage", "measurement"),
                self.sensor(f"battery {idx} batcur", "{{ (value / 10) }}", "A", "current", "measurement"),
                self.sensor(f"battery {idx} state"),
                self.sensor(f"battery {idx} power", None, "W", "power", "measurement"),
                self.sensor(f"battery {idx} socLevel", None, "%", "battery", "measurement"),
                self.sensor(f"battery {idx} maxTemp", "{{ (value | float/10 - 273.15) | round(2) }}", "°C", "temperature", "measurement"),
                self.sensor(f"battery {idx} softVersion"),
            ]
            ZendureSensor.addSensors(sensors)

    def sensorAdd(self, entity: Entity, value: Any) -> None:
        try:
            _LOGGER.info(f"Add sensor: {entity.unique_id}")
            ZendureSensor.addSensors([entity])
            entity.update_value(value)

        except Exception as err:
            _LOGGER.error(err)
            _LOGGER.error(traceback.format_exc())

    def message(self, topic: str, payload: Any) -> None:
        try:
            self.lastUpdate = datetime.now() + timedelta(seconds=30)
            topics = topic.split("/")
            parameter = topics[-1]

            if self.logMqtt:
                _LOGGER.info(f"Topic: {topic} => {payload.replace(self.hid, self.name)}")
            match parameter:
                case "report":
                    if properties := payload.get("properties", None):
                        for key, value in properties.items():
                            self.updateProperty(key, value)

                    if batprops := payload.get("packData", None):
                        # get the battery serial numbers
                        if properties and (cnt := properties.get("packNum", None)):
                            if cnt != len(self.batteries):
                                self.batteries = ["" for x in range(len(batprops))]
                                self._hass.loop.call_soon_threadsafe(self.sensorsBatteryCreate, [bat["sn"] for bat in batprops if "sn" in bat])
                            elif self.batteries:
                                self.batteries = [bat["sn"] for bat in batprops if "sn" in bat]

                        # update the battery properties
                        for bat in batprops:
                            sn = bat.pop("sn")
                            if sn in self.batteries:
                                idx = list.index(self.batteries, sn) + 1
                                for key, value in bat.items():
                                    self.updateProperty(f"battery {idx} {key}", value)

                case "reply":
                    if topics[-3] == "function":
                        _LOGGER.info(f"Receive: {self.name} => ready!")
                    return

        except Exception as err:
            _LOGGER.error(err)
            _LOGGER.error(traceback.format_exc())

    def updateProperty(self, key: Any, value: Any) -> bool:
        if (entity := self.entities.get(key, None)) is None:
            if key.endswith("Switch"):
                entity = self.binary(key, None, "switch")
            elif key.endswith("power"):
                entity = self.sensor(key, None, "w", "power", "measurement")
            elif key.endswith(("Temperature", "Temp")):
                entity = self.sensor(key, "{{ (value | float/10 - 273.15) | round(2) }}", "°C", "temperature", "measurement")
            elif key.endswith("PowerCycle"):
                entity = None
            else:
                entity = ZendureSensor(self.attr_device_info, key)

            # set current entity to None in order to prevent error during async initialization
            self.entities[key] = entity
            if entity is not None:
                self._hass.loop.call_soon_threadsafe(self.sensorAdd, entity, value)
            return False

        # update energy sensors
        if value is not None:
            match key:
                case "outputPackPower":
                    self.powerAct = int(value)
                    self.update_aggr([int(value), 0])
                case "packInputPower":
                    self.powerAct = -int(value)
                    self.update_aggr([0, int(value)])

        # update entity state
        if entity is not None and entity.platform and entity.state != value:
            entity.update_value(value)
            return True
        return False

    def update_aggr(self, values: list[int]) -> None:
        try:
            time = dt_util.now()
            for i in range(len(values)):
                s = self.powerSensors[i]
                if isinstance(s, ZendureRestoreSensor):
                    s.aggregate(time, values[i])
        except Exception as err:
            _LOGGER.error(err)

    def update_ac_mode(self, mode: int) -> None:
        if mode == AcMode.INPUT:
            self.writeProperties({"acMode": mode, "inputLimit": self.asInt("inputLimit")})
        elif mode == AcMode.OUTPUT:
            self.writeProperties({"acMode": mode, "outputLimit": self.asInt("outputLimit")})

    def update_cluster(self, cluster: Any) -> None:
        try:
            _LOGGER.info(f"Update cluster: {self.name} => {cluster}")
            self.clusterType = cluster

            for d in self.devices:
                if self in d.clusterdevices:
                    if d.hid != cluster:
                        _LOGGER.info(f"Remove {self.name} from cluster {d.name}")
                        if self in d.clusterdevices:
                            d.clusterdevices.remove(self)
                elif d.hid == cluster:
                    _LOGGER.info(f"Add {self.name} to cluster {d.name}")
                    if self not in d.clusterdevices:
                        d.clusterdevices.append(self)

            if cluster in [1, 2, 3, 4] and self not in self.clusters:
                self.clusters.append(self)
                if self not in self.clusterdevices:
                    self.clusterdevices.append(self)

        except Exception as err:
            _LOGGER.error(err)
            _LOGGER.error(traceback.format_exc())

    def sendRefresh(self) -> None:
        if self.mqtt:
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
        if self.mqtt:
            self.mqtt.publish(self._topic_write, payload)

    def writePower(self, power: int, inprogram: bool) -> None:
        _LOGGER.info(f"Update power {self.name} => {power} capacity {self.capacity} [program {inprogram}]")

    async def bleMqttReset(self, mqttserverlocal: str, mqttserver: str, wifissid: str, wifipsw: str) -> None:
        if self.bleDevice is None:
            return
        async with BleakClient(self.bleDevice) as bt_client:
            try:
                _LOGGER.info(f"Reset mqtt {self.name}")
                await self.bleMqtt(bt_client, mqttserverlocal, wifissid, wifipsw)
                await asyncio.sleep(1)
                await self.bleMqtt(bt_client, mqttserver, wifissid, wifipsw)
            except Exception as err:
                _LOGGER.error(f"BLE error: {err}")
                _LOGGER.error(traceback.format_exc())

    async def bleMqtt(self, client: BleakClient, mqttserver: str, wifissid: str, wifipsw: str) -> None:
        await self.bleCommand(
            client,
            {
                "messageId": self._messageid,
                "method": "token",
                "iotUrl": mqttserver,
                "ssid": wifissid,
                "password": wifipsw,
                "timeZone": "GMT+01:00",
                "token": "abcdefgh",
            },
        )

        await self.bleCommand(
            client,
            {
                "messageId": self._messageid,
                "method": "station",
            },
        )

    async def bleCommand(self, client: BleakClient, command: object):
        try:
            self._messageid += 1
            b = bytearray()
            b.extend(map(ord, json.dumps(command)))
            _LOGGER.error(f"BLE command: {command}")
            await client.write_gatt_char(SF_COMMAND_CHAR, b, response=False)
        except Exception as err:
            _LOGGER.error(f"BLE error: {err}")

    def function_invoke(self, command: Any) -> None:
        ZendureDevice._messageid += 1
        payload = json.dumps(
            command,
            default=lambda o: o.__dict__,
        )

        if self.mqtt:
            if self.logMqtt:
                _LOGGER.info(f"Invoke function {self.name} => {payload.replace(self.hid, self.name)}")
            self.mqtt.publish(self.topic_function, payload)

    def binary(
        self,
        uniqueid: str,
        template: str | None = None,
        deviceclass: Any | None = None,
    ) -> ZendureBinarySensor:
        tmpl = Template(template, self._hass) if template else None
        s = ZendureBinarySensor(self.attr_device_info, uniqueid, tmpl, deviceclass)
        self.entities[uniqueid] = s
        return s

    def number(
        self,
        uniqueid: str,
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
            uniqueid,
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

    def select(self, uniqueid: str, options: dict[int, str], onwrite: Callable | None = None, persistent: bool = False) -> ZendureSelect:
        def _write_property(value: Any) -> None:
            self.writeProperties({uniqueid: value})

        if onwrite is None:
            onwrite = _write_property

        if persistent:
            s = ZendureRestoreSelect(self.attr_device_info, uniqueid, options, onwrite)
        else:
            s = ZendureSelect(self.attr_device_info, uniqueid, options, onwrite)
        self.entities[uniqueid] = s
        return s

    def sensor(
        self,
        uniqueid: str,
        template: str | None = None,
        uom: str | None = None,
        deviceclass: Any | None = None,
        stateclass: Any | None = None,
        precision: int | None = None,
        persistent: bool = False,
    ) -> ZendureSensor:
        tmpl = Template(template, self._hass) if template else None
        if persistent:
            s = ZendureRestoreSensor(self.attr_device_info, uniqueid, tmpl, uom, deviceclass, stateclass, precision)
        else:
            s = ZendureSensor(self.attr_device_info, uniqueid, tmpl, uom, deviceclass, stateclass, precision)
        self.entities[uniqueid] = s
        return s

    def switch(
        self,
        uniqueid: str,
        template: str | None = None,
        deviceclass: Any | None = None,
    ) -> ZendureSwitch:
        def _write_property(entity: Entity, value: Any) -> None:
            self.writeProperty(entity, value)

        tmpl = Template(template, self._hass) if template else None
        s = ZendureSwitch(self.attr_device_info, uniqueid, _write_property, tmpl, deviceclass)
        self.entities[uniqueid] = s
        return s

    def asInt(self, name: str) -> int:
        if sensor := self.entities.get(name, None):
            if isinstance(sensor.state, int):
                return sensor.state
            if isinstance(sensor.state, float):
                return int(sensor.state)
        return 0

    def asFloat(self, name: str) -> float:
        if (sensor := self.entities.get(name, None)) and isinstance(sensor.state, (int, float)):
            return sensor.state
        return 0

    def isEqual(self, name: str, value: Any) -> bool:
        if (sensor := self.entities.get(name, None)) and sensor.state:
            return sensor.state == value
        return False

    @property
    def clustercapacity(self) -> int:
        """Get the capacity of the cluster."""
        if self.clusterType == 0:
            return 0
        return sum(d.capacity for d in self.clusterdevices)

    @property
    def clusterMax(self) -> int:
        """Get the maximum power of the cluster."""
        cmax = sum(d.powerMax for d in self.clusterdevices)
        match self.clusterType:
            case 1:
                cmax = min(cmax, 3600)
            case 2:
                cmax = min(cmax, 800)
            case 3:
                cmax = min(cmax, 1200)
            case 4:
                cmax = min(cmax, 2400)
            case _:
                return 0
        return cmax

    @property
    def clusterMin(self) -> int:
        """Get the minimum power of the cluster."""
        cmin = sum(d.powerMin for d in self.clusterdevices)
        match self.clusterType:
            case 1:
                cmin = min(cmin, -3600)
            case 2:
                cmin = min(cmin, -2400)
            case 3:
                cmin = min(cmin, -2400)
            case 4:
                cmin = min(cmin, -3600)
            case _:
                return 0
        return cmin


class AcMode:
    INPUT = 1
    OUTPUT = 2


@dataclass
class ZendureDeviceDefinition:
    """Class to hold zendure device properties."""

    productKey: str
    deviceName: str
    productName: str
    snNumber: str
    ip_address: str | None

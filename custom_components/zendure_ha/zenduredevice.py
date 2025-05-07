"""Zendure Integration device."""

from __future__ import annotations

import json
import logging
import traceback
from datetime import datetime, timedelta
from typing import Any

from bleak import BleakClient
from bleak.exc import BleakError
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.util import dt as dt_util
from paho.mqtt import client as mqtt_client

from .const import AcMode
from .select import ZendureSelect
from .sensor import ZendureRestoreSensor, ZendureSensor
from .switch import ZendureSwitch
from .zendurebase import ZendureBase
from .zendurebattery import ZendureBattery

_LOGGER = logging.getLogger(__name__)

SF_COMMAND_CHAR = "0000c304-0000-1000-8000-00805f9b34fb"


class ZendureDevice(ZendureBase):
    """A Zendure Device."""

    devicedict: dict[str, ZendureDevice] = {}
    devices: list[ZendureDevice] = []
    clusters: list[ZendureDevice] = []
    mqttCloud = mqtt_client.Client()
    mqttCloudUrl = ""
    mqttIsLocal: bool = False
    mqttLocal = mqtt_client.Client()
    mqttLocalUrl = ""
    mqttLog: bool = False
    wifissid: str | None = None
    wifipsw: str | None = None
    _messageid = 1000

    def __init__(self, hass: HomeAssistant, deviceId: str, prodName: str, definition: Any, parent: str | None = None) -> None:
        """Initialize ZendureDevice."""
        self.deviceId = deviceId
        self.snNumber = definition["snNumber"]
        self.prodkey = definition["productKey"]
        super().__init__(hass, definition["name"], prodName, self.snNumber, parent)
        self._topic_read = f"iot/{self.prodkey}/{self.deviceId}/properties/read"
        self._topic_write = f"iot/{self.prodkey}/{self.deviceId}/properties/write"
        self.topic_function = f"iot/{self.prodkey}/{self.deviceId}/function/invoke"
        self.lastmessage = datetime.min
        self.mqtt = self.mqttCloud
        self.mqttDevice = self.mqttCloud

        self.devicedict[deviceId] = self
        self.devices.append(self)
        self.lastUpdate = datetime.min
        self.service_info: bluetooth.BluetoothServiceInfoBleak | None = None

        self.powerMax = 0
        self.powerMin = 0
        self.powerAct = 0
        self.capacity = 0
        self.kwh = 0
        self.clusterType: Any = 0
        self.clusterdevices: list[ZendureDevice] = []
        self.powerSensors: list[ZendureSensor] = []

    def deviceMqttClient(self, mqttUrl: str, mqttPsw: str) -> None:
        """Initialize MQTT client for device."""
        self.mqttDevice = mqtt_client.Client(client_id=self.deviceId, clean_session=False, userdata=mqttUrl)
        self.mqttDevice.username_pw_set(username=self.deviceId, password=mqttPsw)
        self.mqttDevice.on_connect = self.deviceConnect
        self.mqttDevice.on_disconnect = self.deviceDisconnect
        self.mqttDevice.on_message = self.deviceMessage
        self.mqttDevice.suppress_exceptions = True
        # self.mqttDevice.connect(mqttUrl, 1883)
        # self._cloud.loop_start()

    def deviceConnect(self, client: mqtt_client.Client, _userdata: Any, _flags: Any, rc: Any) -> None:
        """Handle MQTT connection for device."""
        _LOGGER.info(f"Device {self.name} Mqtt Client has been connected, return code: {rc}")
        client.subscribe(f"/{self.prodkey}/{self.deviceId}/#")
        client.subscribe(f"iot/{self.prodkey}/{self.deviceId}/#")

    def deviceDisconnect(self, _client: Any, _userdata: Any, rc: Any) -> None:
        _LOGGER.info(f"Device {self.name} disconnected from MQTT broker with return code {rc}")

    def deviceMessage(self, _client: Any, _userdata: Any, msg: Any) -> None:
        """Handle MQTT message for device."""
        # skip report messages
        if msg.topic.endswith("report"):
            return
        # keep sending updates for two minutes
        self.lastmessage = datetime.now() + timedelta(seconds=120)
        self.mqttLocal.publish(msg.topic, msg.payload)

    def entitiesCreate(self) -> None:
        super().entitiesCreate()
        if len(self.devices) > 1:
            clusters: dict[Any, str] = {0: "clusterunknown", 1: "clusterowncircuit", 2: "cluster800", 3: "cluster1200", 4: "cluster2400"}
            for d in self.devices:
                if d != self:
                    clusters[d.deviceId] = f"Part of {d.name} cluster"

            ZendureSelect.addSelects([
                self.select(
                    "cluster",
                    clusters,
                    self.clusterUpdate,
                    True,
                )
            ])

        self.powerSensors = [
            self.sensor("aggrChargeDaykWh", None, "kWh", "energy", "total", 2, True),
            self.sensor("aggrDischargeDaykWh", None, "kWh", "energy", "total", 2, True),
        ]
        ZendureSensor.addSensors(self.powerSensors)

        if self.mqttLocal:
            ZendureSwitch.addSwitches([
                self.switch("MqttLocal", None, "switch", self.mqttSwitchMqtt, False),
            ])

    def entitiesBattery(self, _battery: ZendureBattery, _sensors: list[ZendureSensor]) -> None:
        return

    def entityChanged(self, key: str, _entity: Entity, value: Any) -> None:
        match key:
            case "outputPackPower":
                self.powerAct = int(value)
                self.update_aggr([int(value), 0])
            case "packInputPower":
                self.powerAct = -int(value)
                self.update_aggr([0, int(value)])

    def entityWrite(self, entity: Entity, value: Any) -> None:
        _LOGGER.info(f"Writing property {self.name} {entity.name} => {value}")
        if entity.unique_id is None:
            _LOGGER.error(f"Entity {entity.name} has no unique_id.")
            return

        property_name = entity.unique_id[(len(self.name) + 1) :]
        if property_name in {"minSoc", "socSet"}:
            value = int(value * 10)

        self.writeProperties({property_name: value})

    def mqttSwitchMqtt(self, _entity: ZendureSwitch, value: Any) -> None:
        if self.service_info is None:
            _LOGGER.info(f"Unable to set mqtt {self.name} => no bluetooth device")
            return
        self._hass.async_create_task(self.bleMqtt(value == 1))

    def mqttPublish(self, topic: str, payload: Any) -> None:
        _LOGGER.debug(f"Publish to {topic}: {payload}")
        if self.mqtt:
            self.mqtt.publish(topic, payload)

    def mqttInvoke(self, command: Any) -> None:
        if self.mqtt:
            self._messageid += 1
            command["messageId"] = self._messageid
            command["deviceId"] = self.deviceId
            payload = json.dumps(command, default=lambda o: o.__dict__)
            # if self.mqttLog:
            #     _LOGGER.info(f"Invoke function {self.name} => {payload}")
            self.mqtt.publish(self.topic_function, payload)

    def mqttMessage(self, topics: list[str], payload: Any) -> None:
        try:
            parameter = topics[-1]

            match parameter:
                case "report":
                    self.lastUpdate = datetime.now() + timedelta(seconds=30)
                    if properties := payload.get("properties", None):
                        for key, value in properties.items():
                            self.entityUpdate(key, value)

                    # update the battery properties
                    if batprops := payload.get("packData", None):
                        for b in batprops:
                            sn = b.pop("sn")
                            if (bat := ZendureBattery.batterydict.get(sn, None)) is None:
                                match sn[0]:
                                    case "A":
                                        bat = ZendureBattery(sn, "AB1000", sn, self.name, 1)
                                    case "C":
                                        bat = ZendureBattery(sn, "AB2000" + ("S" if sn[3] == "F" else ""), sn, self.name, 2)
                                    case "F":
                                        bat = ZendureBattery(sn, "AB3000", sn, self.name, 3)
                                    case _:
                                        bat = ZendureBattery(sn, "AB????", sn, self.name, 3)
                                self.kwh += bat.kwh
                                self._hass.loop.call_soon_threadsafe(bat.entitiesCreate, self.entitiesBattery)

                            if bat.entities:
                                for key, value in b.items():
                                    bat.entityUpdate(key, value)

                case "reply":
                    if self.mqttLog and topics[-3] == "function":
                        _LOGGER.info(f"Receive: {self.name} => ready!")
                    return

        except Exception as err:
            _LOGGER.error(err)
            _LOGGER.error(traceback.format_exc())

    def mqttRefresh(self) -> None:
        if self.mqtt:
            self.mqtt.publish(self._topic_read, '{"properties": ["getAll"]}')

    def update_aggr(self, values: list[int]) -> None:
        try:
            time = dt_util.now()
            for i in range(len(values)):
                s = self.powerSensors[i]
                if isinstance(s, ZendureRestoreSensor):
                    s.aggregate(time, values[i])
        except Exception as err:
            _LOGGER.error(err)

    def update_ac_mode(self, _entity: ZendureSelect, mode: int) -> None:
        if mode == AcMode.INPUT:
            self.writeProperties({"acMode": mode, "inputLimit": self.asInt("inputLimit")})
        elif mode == AcMode.OUTPUT:
            self.writeProperties({"acMode": mode, "outputLimit": self.asInt("outputLimit")})

    def writeProperties(self, props: dict[str, Any]) -> None:
        if self.mqtt:
            ZendureDevice._messageid += 1
            payload = json.dumps(
                {
                    "deviceId": self.deviceId,
                    "messageId": ZendureDevice._messageid,
                    "timestamp": int(datetime.now().timestamp()),
                    "properties": props,
                },
                default=lambda o: o.__dict__,
            )
            self.mqtt.publish(self._topic_write, payload)

    def writePower(self, power: int, inprogram: bool) -> None:
        _LOGGER.info(f"Update power {self.name} => {power} capacity {self.capacity} [program {inprogram}]")

    async def bleMqtt(self, local: bool) -> None:
        if self.service_info is None:
            return
        # get the bluetooth device
        if self.service_info.connectable:
            device = self.service_info.device
        elif connectable_device := bluetooth.async_ble_device_from_address(self._hass, self.service_info.device.address, True):
            device = connectable_device
        else:
            return

        try:
            server = self.mqttLocalUrl if local else self.mqttCloudUrl
            _LOGGER.info(f"Set mqtt {self.name} to {server}")

            async with BleakClient(device) as client:
                await self.bleCommand(
                    client,
                    {
                        "iotUrl": server,
                        "messageId": str(self._messageid),
                        "method": "token",
                        "password": self.wifipsw,
                        "ssid": self.wifissid,
                        "timeZone": "GMT+01:00",
                        "token": "abcdefgh",
                    },
                )

                await self.bleCommand(
                    client,
                    {
                        "messageId": str(self._messageid),
                        "method": "station",
                    },
                )
                # set the mqtt client
                self.mqtt = self.mqttLocal if local else self.mqttCloud
                self.entities["MqttLocal"].update_value(local)

        except TimeoutError:
            _LOGGER.debug(f"Timeout when trying to connect to {self.name} {self.service_info.name}")
        except (AttributeError, BleakError) as err:
            _LOGGER.debug(f"Could not connect to {self.name}: {err}")
        except Exception as err:
            _LOGGER.error(f"BLE error: {err}")
            _LOGGER.error(traceback.format_exc())

    async def bleCommand(self, client: BleakClient, command: Any) -> None:
        try:
            self._messageid += 1
            payload = json.dumps(command, default=lambda o: o.__dict__)
            b = bytearray()
            b.extend(map(ord, payload))
            _LOGGER.info(f"BLE command: {self.name} => {payload}")
            await client.write_gatt_char(SF_COMMAND_CHAR, b, response=False)
        except Exception as err:
            _LOGGER.error(f"BLE error: {err}")

    def clusterUpdate(self, _entity: ZendureSelect, cluster: Any) -> None:
        try:
            _LOGGER.info(f"Update cluster: {self.name} => {cluster}")
            self.clusterType = cluster

            for d in self.devices:
                if self in d.clusterdevices:
                    if d.deviceId != cluster:
                        _LOGGER.info(f"Remove {self.name} from cluster {d.name}")
                        if self in d.clusterdevices:
                            d.clusterdevices.remove(self)
                elif d.deviceId == cluster:
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

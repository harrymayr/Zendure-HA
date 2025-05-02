"""Zendure Integration manager using DataUpdateCoordinator."""

from __future__ import annotations

import json
import logging
import traceback
from base64 import b64decode
from datetime import datetime, timedelta
from typing import Any

from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from homeassistant.components import bluetooth
from homeassistant.components.number import NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from paho.mqtt import client as mqtt_client

from .api import Api
from .const import (
    CONF_MQTTLOCAL,
    CONF_MQTTLOG,
    CONF_MQTTPORT,
    CONF_MQTTPSW,
    CONF_MQTTSERVER,
    CONF_MQTTUSER,
    CONF_P1METER,
    CONF_WIFIPSW,
    CONF_WIFISSID,
    DOMAIN,
    ManagerState,
    SmartMode,
)
from .devices.ace1500 import ACE1500
from .devices.aio2400 import AIO2400
from .devices.hub1200 import Hub1200
from .devices.hub2000 import Hub2000
from .devices.hyper2000 import Hyper2000
from .devices.solarflow800 import SolarFlow800
from .devices.solarflow2400ac import SolarFlow2400AC
from .number import ZendureNumber
from .select import ZendureSelect
from .zendurebase import ZendureBase
from .zenduredevice import ZendureDevice

_LOGGER = logging.getLogger(__name__)


class ZendureManager(DataUpdateCoordinator[int], ZendureBase):
    """The Zendure manager."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize ZendureManager."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} ({config_entry.unique_id})",
            update_interval=timedelta(seconds=90),
            always_update=True,
        )
        ZendureBase.__init__(self, hass, "Zendure Manager", "Zendure Manager", "1.0.41")

        self.p1meter = config_entry.data.get(CONF_P1METER)
        self._mqttcloud: mqtt_client.Client | None = None
        self._mqttlocal: mqtt_client.Client | None = None

        # get the local settings
        if config_entry.data.get(CONF_MQTTLOCAL, False):
            self._mqttlocal = mqtt_client.Client(client_id=config_entry.data.get(CONF_MQTTUSER, None), clean_session=False, userdata=True)
            self._mqttlocal.username_pw_set(username=config_entry.data.get(CONF_MQTTUSER, None), password=config_entry.data.get(CONF_MQTTPSW, None))

        self.mqttserver: str = config_entry.data.get(CONF_MQTTSERVER, None)
        self.mqttport: str = config_entry.data.get(CONF_MQTTPORT, 1883)
        self.wifissid: str = config_entry.data.get(CONF_WIFISSID, None)
        self.wifipsw: str = config_entry.data.get(CONF_WIFIPSW, None)
        self.mqttlocal = config_entry.data.get(CONF_MQTTLOCAL, False) and self.wifissid and self.wifipsw
        ZendureDevice.logMqtt = config_entry.data.get(CONF_MQTTLOG, False)

        self.operation = 0
        self.setpoint = 0
        self.zero_idle = datetime.max
        self.zero_next = datetime.min
        self.zero_fast = datetime.min
        self.active: list[ZendureDevice] = []
        self.store: Store | None = None
        self.next_scan = datetime.now() + timedelta(seconds=30)

        # Create the api
        self.api = Api(self._hass, dict(config_entry.data))

    async def load(self) -> bool:
        """Initialize the manager."""
        try:
            if not await self.api.connect():
                _LOGGER.error("Unable to connect to Zendure API")
                return False

            # create and initialize the devices
            await self.createDevices()
            _LOGGER.info(f"Found: {len(ZendureDevice.devicedict)} devices")

            # Add ZendureManager sensors
            _LOGGER.info(f"Adding sensors {self.name}")
            selects = [
                self.select("Operation", {0: "off", 1: "manual", 2: "smart"}, self.update_operation, True),
            ]
            ZendureSelect.addSelects(selects)

            numbers = [
                self.number("manual_power", None, "W", "power", -10000, 10000, NumberMode.BOX, self._update_manual_energy),
            ]
            ZendureNumber.addNumbers(numbers)

            # Set sensors from values entered in config flow setup
            if self.p1meter:
                _LOGGER.info(f"Energy sensors: {self.p1meter} to _update_smart_energyp1")
                async_track_state_change_event(self._hass, [self.p1meter], self._update_smart_energyp1)

            # create the zendure cloud mqtt client
            _LOGGER.info("Create mqtt client")
            self._mqttcloud = mqtt_client.Client(client_id=self.api.token, clean_session=False, userdata=True)
            self._mqttcloud.username_pw_set(username="zenApp", password=b64decode(self.api.mqttinfo.encode()).decode("latin-1"))
            self._mqttcloud.on_connect = self.mqttConnect
            self._mqttcloud.on_disconnect = self.mqttDisconnect
            self._mqttcloud.on_message = self.mqttMessage
            self._mqttcloud.connect(self.api.mqttUrl, 1883)
            self._mqttcloud.suppress_exceptions = True
            self._mqttcloud.loop_start()

            if self._mqttlocal:
                self._mqttlocal.on_connect = self.mqttConnect
                self._mqttlocal.on_disconnect = self.mqttDisconnect
                self._mqttlocal.on_message = self.mqttMessage
                self._mqttlocal.suppress_exceptions = True
                # self._mqttlocal.connect(self.mqttserver, self.mqttport)
                # self._mqttlocal.loop_start()
            _LOGGER.info("Zendure Manager initialized")

        except Exception as err:
            _LOGGER.error(err)
            _LOGGER.error(traceback.format_exc())
            return False
        return True

    async def unload(self) -> None:
        """Unload the manager."""
        if self._mqttcloud:
            for device in ZendureDevice.devices:
                self._mqttcloud.unsubscribe(f"/{device.prodkey}/{device.hid}/#")
                self._mqttcloud.unsubscribe(f"iot/{device.prodkey}/{device.hid}/#")
            self._mqttcloud.loop_stop()
            self._mqttcloud.disconnect()

        ZendureDevice.devicedict.clear()
        ZendureDevice.devices.clear()
        ZendureDevice.clusters.clear()

    async def createDevices(self) -> None:
        # Create the devices
        deviceInfo = await self.api.getDevices()
        for dev in deviceInfo:
            if (deviceId := dev["deviceKey"]) is None or (prodName := dev["productName"]) is None:
                continue
            _LOGGER.info(f"Adding device: {deviceId} {prodName}")
            _LOGGER.info(f"Data: {dev}")

            try:
                match prodName.lower():
                    case "hyper 2000":
                        device = Hyper2000(self._hass, deviceId, prodName, dev)
                    case "solarflow 800":
                        device = SolarFlow800(self._hass, deviceId, prodName, dev)
                    case "solarflow2.0":
                        device = Hub1200(self._hass, deviceId, prodName, dev)
                    case "solarflow hub 2000":
                        device = Hub2000(self._hass, deviceId, prodName, dev)
                        if (packList := dev.get("packList", None)) is not None:
                            for pack in packList:
                                if pack.get("productName", None) == "Ace 1500":
                                    _LOGGER.info(f"{device.name} Adding Ace 1500 from packList")
                                    ace = ACE1500(self._hass, pack["deviceId"], pack["productName"], pack, device.name)
                                    ZendureDevice.devicedict[deviceId] = ace

                    case "solarflow aio zy":
                        device = AIO2400(self._hass, deviceId, prodName, dev)
                    case "ace 1500":
                        device = ACE1500(self._hass, deviceId, prodName, dev)
                    case "solarflow 2400 ac":
                        device = SolarFlow2400AC(self._hass, deviceId, prodName, dev)
                    case _:
                        _LOGGER.info(f"Device {prodName} is not supported!")
                        continue
                ZendureDevice.devicedict[deviceId] = device

            except Exception as err:
                _LOGGER.error(err)
                _LOGGER.error(traceback.format_exc())

        # create the sensors
        for device in ZendureDevice.devicedict.values():
            device.entitiesCreate()

    def update_operation(self, _entity: ZendureSelect, operation: int) -> None:
        _LOGGER.info(f"Update operation: {operation} from: {self.operation}")

        if operation == self.operation:
            return

        self.operation = operation
        if self.operation != SmartMode.MATCHING:
            for d in ZendureDevice.devices:
                d.writePower(0, self.operation == SmartMode.MANUAL)

        # One device always has it's own phase
        if len(ZendureDevice.devices) == 1 and not ZendureDevice.devices[0].clusterdevices:
            ZendureDevice.devices[0].clusterType = 1
            ZendureDevice.devices[0].clusterdevices = [ZendureDevice.devices[0]]
            ZendureDevice.clusters = [ZendureDevice.devices[0]]

    async def _async_update_data(self) -> int:
        """Refresh the data of all devices's."""
        _LOGGER.info("refresh devices")
        try:
            doscan = self.mqttlocal and self.next_scan < datetime.now()
            if doscan:
                self.next_scan = datetime.now() - timedelta(seconds=300)
                reset: list[ZendureDevice] = []

            for device in ZendureDevice.devices:
                device.mqttRefresh()
                if doscan and device.lastUpdate < self.next_scan:
                    reset.append(device)

            if doscan:
                self.next_scan = datetime.now() + timedelta(seconds=300)
                if reset:
                    for si in bluetooth.async_discovered_service_info(self.hass, False):
                        _LOGGER.info(f"Service info: {si}")
                        if si.name.startswith("Zen") and (bts := si.manufacturer_data.get(17733, None)) is not None:
                            sn = bts.decode("utf8")[:-1]
                            if zd := next((d for d in reset if d.snNumber.endswith(sn)), None):
                                zd.service_info = si
                                self.hass.async_create_task(zd.bleMqttReset(self.mqttserver, self.wifissid, self.wifipsw))

        except Exception as err:
            _LOGGER.error(err)
            _LOGGER.error(traceback.format_exc())

        if self.hass and self.hass.loop.is_running():
            self._schedule_refresh()
        return 0

    def mqttConnect(self, _client: Any, _userdata: Any, _flags: Any, rc: Any) -> None:
        _LOGGER.info(f"Client has been connected, return code: {rc}")
        if rc == 0 and self._mqttcloud:
            for device in ZendureDevice.devices:
                device.mqttInit(self._mqttcloud)

    def mqttDisconnect(self, _client: Any, _userdata: Any, rc: Any) -> None:
        _LOGGER.info(f"Client disconnected from MQTT broker with return code {rc}")

    def mqttMessage(self, _client: Any, _userdata: Any, msg: Any) -> None:
        try:
            # check for valid device in payload
            topics = msg.topic.split("/")
            deviceId = topics[2]
            if (device := ZendureDevice.devicedict.get(deviceId, None)) is not None:
                topics[2] = device.name
                payload = json.loads(msg.payload.decode())
                payload.pop("deviceId", None)
                if ZendureDevice.logMqtt:
                    _LOGGER.info(f"Topic: {self.name} {msg.topic.replace(deviceId, device.name)} => {payload}")
                device.mqttMessage(topics, payload)
            else:
                _LOGGER.info(f"Unknown device: {deviceId} => {msg.topic} => {msg.payload.decode()}")

        except:  # noqa: E722
            return

    def _update_manual_energy(self, _number: Any, power: float) -> None:
        try:
            if self.operation == SmartMode.MANUAL:
                self.setpoint = int(power)
                self.updateSetpoint(self.setpoint, ManagerState.DISCHARGING if power >= 0 else ManagerState.CHARGING)

        except Exception as err:
            _LOGGER.error(err)
            _LOGGER.error(traceback.format_exc())

    @callback
    def _update_smart_energyp1(self, event: Event[EventStateChangedData]) -> None:
        try:
            # exit if there is nothing to do
            if (new_state := event.data["new_state"]) is None or self.operation == SmartMode.NONE:
                return

            # convert the state to a float
            try:
                p1 = int(float(new_state.state))
            except ValueError:
                return

            # check minimal time between updates
            time = datetime.now()
            if time < self.zero_next or (time < self.zero_fast and abs(p1) < SmartMode.FAST_UPDATE):
                return

            # get the current power, exit if a device is waiting
            powerActual = 0
            for d in ZendureDevice.devices:
                d.powerAct = d.asInt("packInputPower") - (d.asInt("outputPackPower") - d.asInt("solarInputPower"))
                powerActual += d.powerAct

            _LOGGER.info(f"Update p1: {p1} power: {powerActual} operation: {self.operation}")
            # update the manual setpoint
            if self.operation == SmartMode.MANUAL:
                self.updateSetpoint(self.setpoint, ManagerState.DISCHARGING if self.setpoint >= 0 else ManagerState.CHARGING)

            # update when we are charging
            elif powerActual < 0:
                self.updateSetpoint(min(0, powerActual + p1), ManagerState.CHARGING)

            # update when we are discharging
            elif powerActual > 0:
                self.updateSetpoint(max(0, powerActual + p1), ManagerState.DISCHARGING)

            # check if it is the first time we are idle
            elif self.zero_idle == datetime.max:
                _LOGGER.info(f"Wait 10 sec for state change p1: {p1}")
                self.zero_idle = time + timedelta(seconds=SmartMode.TIMEIDLE)

            # update when we are idle for more than SmartMode.TIMEIDLE seconds
            elif self.zero_idle < time:
                if p1 < -SmartMode.MIN_POWER:
                    _LOGGER.info(f"Start charging with p1: {p1}")
                    self.updateSetpoint(p1, ManagerState.CHARGING)
                    self.zero_idle = datetime.max
                elif p1 >= 0:
                    _LOGGER.info(f"Start discharging with p1: {p1}")
                    self.updateSetpoint(p1, ManagerState.DISCHARGING)
                    self.zero_idle = datetime.max
                else:
                    _LOGGER.info(f"Unable to charge/discharge p1: {p1}")

            self.zero_next = time + timedelta(seconds=SmartMode.TIMEZERO)
            self.zero_fast = time + timedelta(seconds=SmartMode.TIMEFAST)

        except Exception as err:
            _LOGGER.error(err)
            _LOGGER.error(traceback.format_exc())

    def updateSetpoint(self, power: int, state: ManagerState) -> None:
        """Update the setpoint for all devices."""
        totalCapacity = 0
        totalPower = 0
        for d in ZendureDevice.devices:
            if state == ManagerState.DISCHARGING:
                d.capacity = max(0, d.kwh * (d.asInt("electricLevel") - d.asInt("minSoc")))
                _LOGGER.info(f"Update capacity: {d.name} {d.capacity} = {d.kwh} * ({d.asInt('electricLevel')} - {d.asInt('minSoc')})")
                totalPower += d.powerMax
            else:
                d.capacity = max(0, d.kwh * (d.asInt("socSet") - d.asInt("electricLevel")))
                _LOGGER.info(f"Update capacity: {d.name} {d.capacity} = {d.kwh} * ({d.asInt('socSet')} - {d.asInt('electricLevel')})")
                totalPower += abs(d.powerMin)
            if d.clusterType == 0:
                d.capacity = 0
            totalCapacity += d.capacity

        _LOGGER.info(f"Update setpoint: {power} state{state} capacity: {totalCapacity} max: {totalPower}")

        # redistribute the power on clusters
        isreverse = bool(abs(power) > totalPower / 2)
        active = sorted(ZendureDevice.clusters, key=lambda d: d.clustercapacity, reverse=isreverse)
        for c in active:
            clusterCapacity = c.clustercapacity
            clusterPower = int(power * clusterCapacity / totalCapacity) if totalCapacity > 0 else 0
            clusterPower = max(0, min(c.clusterMax, clusterPower)) if state == ManagerState.DISCHARGING else min(0, max(c.clusterMin, clusterPower))
            totalCapacity -= clusterCapacity

            if totalCapacity == 0:
                clusterPower = max(0, min(c.clusterMax, power)) if state == ManagerState.DISCHARGING else min(0, max(c.clusterMin, power))
            elif abs(clusterPower) > 0 and (abs(clusterPower) < SmartMode.MIN_POWER or (abs(clusterPower) < SmartMode.START_POWER and c.powerAct == 0)):
                clusterPower = 0

            for d in sorted(c.clusterdevices, key=lambda d: d.capacity, reverse=isreverse):
                if d.capacity == 0:
                    continue
                pwr = int(clusterPower * d.capacity / clusterCapacity) if clusterCapacity > 0 else 0
                clusterCapacity -= d.capacity
                pwr = max(0, min(d.powerMax, pwr)) if state == ManagerState.DISCHARGING else min(0, max(d.powerMin, pwr))
                if abs(pwr) > 0:
                    if clusterCapacity == 0:
                        pwr = max(0, min(d.powerMax, clusterPower)) if state == ManagerState.DISCHARGING else min(0, max(d.powerMin, clusterPower))
                    elif abs(pwr) > SmartMode.START_POWER or (abs(pwr) > SmartMode.MIN_POWER and d.powerAct != 0):
                        clusterPower -= pwr
                    else:
                        pwr = 0
                power -= pwr

                # update the device
                d.writePower(pwr, True)

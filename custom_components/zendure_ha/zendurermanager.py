"""Zendure Integration manager using DataUpdateCoordinator."""

from __future__ import annotations

import json
import logging
import traceback
from datetime import datetime, timedelta
from typing import Any

from paho.mqtt import client as mqtt_client

from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from homeassistant.components import bluetooth
from homeassistant.components.number import NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import (
    DOMAIN,
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
)
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from custom_components.zendure_ha.api import Api
from custom_components.zendure_ha.number import ZendureNumber, ZendureRestoreNumber
from custom_components.zendure_ha.select import ZendureRestoreSelect, ZendureSelect
from custom_components.zendure_ha.zenduredevice import ZendureDevice

from .const import (
    CONF_BROKER,
    CONF_BROKERPSW,
    CONF_BROKERUSER,
    CONF_P1METER,
    CONF_WIFIPSW,
    CONF_WIFISSID,
    ManagerState,
    SmartMode,
)

_LOGGER = logging.getLogger(__name__)


class ZendureManager(DataUpdateCoordinator[int]):
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

        self._hass = hass
        self._mqtt: mqtt_client.Client | None = None
        self.p1meter = config_entry.data.get(CONF_P1METER)
        self._attr_device_info = self.attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "ZendureManager")},
            model="Zendure Manager",
            name="Zendure Manager",
            manufacturer="Fireson",
        )

        # get the local settings
        self.broker = config_entry.data.get(CONF_BROKER, None)
        self.brokeruser = config_entry.data.get(CONF_BROKERUSER, None)
        self.brokerpsw = config_entry.data.get(CONF_BROKERPSW, None)
        self.wifissid = config_entry.data.get(CONF_WIFISSID, None)
        self.wifipsw = config_entry.data.get(CONF_WIFIPSW, None)
        self.uselocal = self.broker and self.brokeruser and self.brokerpsw and self.wifissid and self.wifipsw

        self.operation = 0
        self.setpoint = 0
        self.zero_idle = datetime.max
        self.zero_next = datetime.min
        self.zero_fast = datetime.min
        self.active: list[ZendureDevice] = []

        # Set sensors from values entered in config flow setup
        if self.p1meter:
            _LOGGER.info(f"Energy sensors: {self.p1meter} to _update_smart_energyp1")
            async_track_state_change_event(self._hass, [self.p1meter], self._update_smart_energyp1)

        # Create the api
        self.api = Api(self._hass, dict(config_entry.data))

        if "items" in config_entry.data:
            _LOGGER.info(f"Runtime data: {config_entry.as_dict()['items']}")

    async def initialize(self) -> bool:
        """Initialize the manager."""
        try:
            if not await self.api.connect():
                return False
            ZendureDevice.devicedict = await self.api.getDevices(self._hass)
            self._mqtt = self.api.get_mqtt(self.on_message)

            try:
                for d in ZendureDevice.devicedict.values():
                    d.mqtt = self._mqtt
                    self._mqtt.subscribe(f"/{d.prodkey}/{d.hid}/#")
                    self._mqtt.subscribe(f"iot/{d.prodkey}/{d.hid}/#")
                    d.sensorsCreate()
                    d.sendRefresh()

                if self.uselocal:
                    _LOGGER.info("Check for bluetooth devices ...")
                    bleak_scanner = bluetooth.async_get_scanner(self._hass)
                    bleak_scanner.register_detection_callback(self._device_detected)

            except Exception as err:
                _LOGGER.error(err)

            _LOGGER.info(f"Found: {len(ZendureDevice.devicedict)} devices")

            # Add ZendureManager sensors
            _LOGGER.info(f"Adding sensors {self.name}")
            selects = [
                ZendureRestoreSelect(
                    self._attr_device_info,
                    "Operation",
                    {0: "off", 1: "manual", 2: "smart"},
                    self.update_operation,
                    0,
                ),
            ]
            ZendureSelect.addSelects(selects)

            numbers = [
                ZendureRestoreNumber(
                    self.attr_device_info,
                    "manual_power",
                    self._update_manual_energy,
                    None,
                    "W",
                    "power",
                    10000,
                    -10000,
                    NumberMode.BOX,
                ),
            ]
            ZendureNumber.addNumbers(numbers)

        except Exception as err:
            _LOGGER.error(err)
            return False
        return True

    def _device_detected(self, device: BLEDevice, advertisement_data: AdvertisementData) -> None:
        """Handle a detected device."""
        if advertisement_data.local_name and advertisement_data.local_name.startswith("Zen"):
            _LOGGER.info(f"Found Zendure BLE device: {device.name} => {advertisement_data}")

        # id = advertisement_data.manufacturer_data.get(0x004C, None)

    def update_operation(self, operation: int) -> None:
        _LOGGER.info(f"Update operation: {operation} from: {self.operation}")

        if operation == self.operation:
            return

        self.operation = operation
        if self.operation != SmartMode.MATCHING:
            for d in ZendureDevice.devices:
                d.powerSet(0, self.operation == SmartMode.MANUAL)

        # One device always has it's own phase
        if len(ZendureDevice.devices) == 1 and not ZendureDevice.devices[0].clusterdevices:
            ZendureDevice.devices[0].clusterType = 1
            ZendureDevice.devices[0].clusterdevices = [ZendureDevice.devices[0]]
            ZendureDevice.clusters = [ZendureDevice.devices[0]]

    async def _async_update_data(self) -> int:
        """Refresh the data of all devices's."""
        _LOGGER.info("refresh devices")
        try:
            if self._mqtt:
                for d in ZendureDevice.devices:
                    d.sendRefresh()
        except Exception as err:
            _LOGGER.error(err)
        if self.hass and self.hass.loop.is_running():
            self._schedule_refresh()
        return 0

    def on_message(self, _client: Any, _userdata: Any, msg: Any) -> None:
        try:
            # check for valid device in payload
            payload = json.loads(msg.payload.decode())
            if not (deviceid := payload.get("deviceId", None)) or not (device := ZendureDevice.devicedict.get(deviceid, None)):
                # _LOGGER.info(f"Unknown topic: {msg.topic} => {payload}")
                return
            device.lastUpdate = datetime.now() + timedelta(seconds=30)

            topics = msg.topic.split("/")
            parameter = topics[-1]

            # _LOGGER.info(f"Topic: {msg.topic} => {payload}")
            match parameter:
                case "report":
                    if properties := payload.get("properties", None):
                        for key, value in properties.items():
                            device.updateProperty(key, value)

                    if batprops := payload.get("packData", None):
                        # get the battery serial numbers
                        if properties and (cnt := properties.get("packNum", None)):
                            if cnt != len(device.batteries):
                                device.batteries = ["" for x in range(len(batprops))]
                                self._hass.loop.call_soon_threadsafe(device.sensorsBatteryCreate, [bat["sn"] for bat in batprops if "sn" in bat])
                            elif device.batteries:
                                device.batteries = [bat["sn"] for bat in batprops if "sn" in bat]

                        # update the battery properties
                        for bat in batprops:
                            sn = bat.pop("sn")
                            if sn in device.batteries:
                                idx = list.index(device.batteries, sn) + 1
                                for key, value in bat.items():
                                    device.updateProperty(f"battery {idx} {key}", value)

                case "config":
                    # _LOGGER.info(f"Receive: {device.hid} => event: {payload}")
                    return

                case "device":
                    # if topics[-2] == "event":
                    #     _LOGGER.info(f"Receive: {device.hid} => event: {payload}")
                    return

                case "error":
                    # if topics[-2] == "event":
                    #     _LOGGER.info(f"Receive: {device.hid} => error: {payload}")
                    return

                case "reply":
                    # if topics[-3] == "function":
                    _LOGGER.info(f"Receive: {device.hid} => ready!")
                    return

                # case _:
                #     _LOGGER.info(f"Unknown topic {msg.topic} => {payload}")

        except Exception as err:
            _LOGGER.error(err)
            _LOGGER.error(traceback.format_exc())

    @callback
    def _update_manual_energy(self, _number: Any, power: float) -> None:
        try:
            if self.operation == SmartMode.MANUAL:
                self.setpoint = int(power)
                self.updateSetpoint(self.setpoint, datetime.now(), ManagerState.DISCHARGING if power >= 0 else ManagerState.CHARGING)

        except Exception as err:
            _LOGGER.error(err)
            _LOGGER.error(traceback.format_exc())

    @callback
    def _update_smart_energyp1(self, event: Event[EventStateChangedData]) -> None:
        try:
            # exit if there is nothing to do
            if (new_state := event.data["new_state"]) is None or self.operation == SmartMode.NONE:
                return

            # check minimal time between updates
            time = datetime.now()
            p1 = int(float(new_state.state))
            if time < self.zero_next or (time < self.zero_fast and abs(p1) < SmartMode.FAST_UPDATE):
                return

            # get the current power, exit if a device is waiting
            powerActual = 0
            for d in ZendureDevice.devices:
                d.powerAct = d.asInt("packInputPower") - d.asInt("outputPackPower")
                powerActual += d.powerAct

            _LOGGER.info(f"Update p1: {p1} power: {powerActual} operation: {self.operation}")
            # update the setpoint
            if self.operation == SmartMode.MANUAL:
                self.updateSetpoint(self.setpoint, time, ManagerState.DISCHARGING if self.setpoint >= 0 else ManagerState.CHARGING)
            elif powerActual < 0:
                self.updateSetpoint(powerActual + p1 + 50, time, ManagerState.CHARGING)
            elif powerActual > 0:
                self.updateSetpoint(powerActual + p1, time, ManagerState.DISCHARGING)
            elif self.zero_idle == datetime.max:
                _LOGGER.info(f"Wait 10 sec for state change p1: {p1}")
                self.zero_idle = time + timedelta(seconds=SmartMode.TIMEIDLE)
            elif self.zero_idle < time:
                _LOGGER.info(f"Update state: p1: {p1}")
                self.updateSetpoint(p1, time, ManagerState.DISCHARGING if p1 >= 0 else ManagerState.CHARGING)

            self.zero_next = time + timedelta(seconds=SmartMode.TIMEZERO)
            self.zero_fast = time + timedelta(seconds=SmartMode.TIMEFAST)

        except Exception as err:
            _LOGGER.error(err)
            _LOGGER.error(traceback.format_exc())

    def updateSetpoint(self, power: int, time: datetime, state: ManagerState) -> None:
        """Update the setpoint for all devices."""
        capacity = 0
        maxTotal = 0
        for d in ZendureDevice.devices:
            if state == ManagerState.DISCHARGING:
                d.capacity = max(0, d.asInt("packNum") * (d.asInt("electricLevel") - d.asInt("minSoc")))
                _LOGGER.info(f"Update capacity: {d.name} {d.capacity} = {d.asInt('packNum')} * ({d.asInt('electricLevel')} - {d.asInt('minSoc')})")
                maxTotal += d.powerMax
            else:
                d.capacity = max(0, d.asInt("packNum") * (d.asInt("socSet") - d.asInt("electricLevel")))
                _LOGGER.info(f"Update capacity: {d.name} {d.capacity} = {d.asInt('packNum')} * ({d.asInt('socSet')} - {d.asInt('electricLevel')})")
                maxTotal += abs(d.powerMin)
            capacity += d.capacity

        _LOGGER.info(f"Update setpoint: {power} state{state} capacity: {capacity} max: {maxTotal}")

        # redistribute the power on clusters
        isreverse = bool(power > maxTotal / 2)
        active = sorted(ZendureDevice.clusters, key=lambda d: d.clustercapacity, reverse=isreverse)
        for d in active:
            pwr = int(power * d.clustercapacity / capacity) if capacity > 0 else 0
            pwr = max(0, min(d.clusterMax, pwr)) if state == ManagerState.DISCHARGING else min(0, max(d.clusterMin, pwr))
            capacity -= d.clustercapacity

            if capacity == 0:
                pwr = max(0, min(d.clusterMax, power)) if state == ManagerState.DISCHARGING else min(0, max(d.clusterMin, power))
            elif abs(pwr) > 0:
                if abs(pwr) > SmartMode.START_POWER or (abs(pwr) > SmartMode.MIN_POWER and d.powerAct != 0):
                    power -= pwr
                else:
                    pwr = 0

            # update the cluster
            d.clusterSet(state, pwr)

"""Zendure Integration manager using DataUpdateCoordinator."""

from __future__ import annotations

import json
import logging
import traceback
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.number import NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import DOMAIN, Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from paho.mqtt import client as mqtt_client

from .api import Api
from .const import CONF_P1METER, CONF_PHASE1, CONF_PHASE2, CONF_PHASE3, DEFAULT_SCAN_INTERVAL, LOGTYPE_BATTERY
from .number import ZendureNumber
from .select import ZendureSelect
from .zenduredevice import BatteryState, ZendureDevice
from .zendurephase import ZendurePhase

_LOGGER = logging.getLogger(__name__)


class ZendureManager(DataUpdateCoordinator[int]):
    """The Zendure manager."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize ZendureManager."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} ({config_entry.unique_id})",
            update_method=config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            update_interval=timedelta(seconds=config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
            always_update=True,
        )

        self._hass = hass
        self.devices: dict[str, ZendureDevice] = {}
        ZendurePhase.phases = [
            ZendurePhase("1", config_entry.data.get(CONF_PHASE1, None)),
            ZendurePhase("2", config_entry.data.get(CONF_PHASE2, None)),
            ZendurePhase("3", config_entry.data.get(CONF_PHASE3, None)),
        ]
        self._mqtt: mqtt_client.Client | None = None
        self.p1meter = config_entry.data.get(CONF_P1METER)
        self._attr_device_info = self.attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "ZendureManager")},
            name="Zendure Manager",
            manufacturer="Fireson",
        )
        self.operation = 0
        self.currentPower = 0

        # Set sensors from values entered in config flow setup
        if self.p1meter:
            _LOGGER.info(f"Energy sensors: {self.p1meter} to _update_smart_energyp1")
            async_track_state_change_event(self._hass, [self.p1meter], self._update_smart_energyp1)

        # Create the api
        self.api = Api(self._hass, config_entry.data)

    async def initialize(self) -> bool:
        """Initialize the manager."""
        try:
            if not await self.api.connect():
                return False
            self.devices = await self.api.getDevices(self._hass)
            self._mqtt = self.api.get_mqtt(self.on_message)

            try:
                for h in self.devices.values():
                    h.mqtt = self._mqtt
                    h.sensorsCreate()
                    self._mqtt.subscribe(f"/{h.prodkey}/{h.hid}/#")
                    self._mqtt.subscribe(f"iot/{h.prodkey}/{h.hid}/#")

            except Exception as err:
                _LOGGER.error(err)

            _LOGGER.info(f"Found: {len(self.devices)} hypers")

            # Add ZendureManager sensors
            _LOGGER.info(f"Adding sensors {self.name}")
            selects = [
                ZendureSelect(
                    self._attr_device_info,
                    "Operation",
                    {0: "off", 1: "manual", 2: "smart"},
                    self.update_operation,
                    0,
                ),
            ]
            ZendureSelect.addSelects(selects)

            numbers = [
                ZendureNumber(
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

    def update_operation(self, operation: int) -> None:
        self.operation = operation
        self.currentPower = 0
        if self.operation != SmartMode.MATCHING:
            for d in self.devices.values():
                d.power_off()
        else:
            # reevalueate the power distribution
            ZendureDevice.batteryState = BatteryState.OFF

    async def _async_update_data(self) -> int:
        """Refresh the data of all hyper2000's."""
        _LOGGER.info("refresh hypers")
        try:
            if self._mqtt:
                for d in self.devices.values():
                    d.sendRefresh()
        except Exception as err:
            _LOGGER.error(err)
        self._schedule_refresh()
        return 0

    def on_message(self, _client: Any, _userdata: Any, msg: Any) -> None:
        try:
            # check for valid device in payload
            payload = json.loads(msg.payload.decode())
            if not (deviceid := payload.get("deviceId", None)) or not (device := self.devices.get(deviceid, None)):
                # _LOGGER.info(f"Unknown topic: {msg.topic} => {payload}")
                return

            topics = msg.topic.split("/")
            parameter = topics[-1]

            match parameter:
                case "report":
                    if properties := payload.get("properties", None):
                        for key, value in properties.items():
                            device.updateProperty(key, value)

                    if properties := payload.get("cluster", None):
                        device.updateProperty("clusterId", properties["clusterId"])
                        if (phase := properties.get("phaseCheck", None)) is not None:
                            device.updateProperty("Phase", phase)
                            if not device.phase or device.phase != ZendurePhase.phases[phase]:
                                device.phase = ZendurePhase.phases[phase]

                    # if properties := payload.get("packData", None):
                    #     for bat in properties:
                    #         sn = bat.pop("sn")
                    #         _LOGGER.info(f"Batdata: {bat}")
                    #         for key, value in bat.items():
                    #             device.updateProperty(f"battery:{sn} {key}", value)

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
                    #     _LOGGER.info(f"Receive: {device.hid} => ready!")
                    return

                case "log":
                    if payload["logType"] == LOGTYPE_BATTERY:
                        device.updateBattery(payload["log"]["params"])

                # case _:
                #     _LOGGER.info(f"Unknown topic {msg.topic} => {payload}")

        except Exception as err:
            _LOGGER.error(err)
            _LOGGER.error(traceback.format_exc())

    @callback
    def _update_manual_energy(self, _number: Any, power: float) -> None:
        try:
            if self.operation == SmartMode.MANUAL:
                self.currentPower = int(power)
                power = self.currentPower - sum(d.power for d in self.devices.values())
                ZendureDevice.batteryState = BatteryState.OFF if power == 0 else BatteryState.DISCHARGING if power > 0 else BatteryState.CHARGING
                ZendureDevice.updateDistribution(power)

        except Exception as err:
            _LOGGER.error(err)
            _LOGGER.error(traceback.format_exc())

    @callback
    def _update_smart_energyp1(self, event: Event[EventStateChangedData]) -> None:
        try:
            _LOGGER.info("Update P1")
            # exit if there is nothing to do
            if (new_state := event.data["new_state"]) is None or self.operation == SmartMode.NONE:
                return

            # update the power distribution of all devices
            if self.operation == SmartMode.MATCHING:
                power = int(new_state.state)
                if ZendureDevice.batteryState == BatteryState.OFF and power != 0:
                    ZendureDevice.batteryState = BatteryState.DISCHARGING if power > 0 else BatteryState.CHARGING
                _LOGGER.info(f"Update smart: {power} {self.currentPower}")
                ZendureDevice.updateDistribution(power, True)
            else:
                power = sum(d.power for d in self.devices.values())
                _LOGGER.info(f"Update manual Power: {power} {self.currentPower}")
                ZendureDevice.updateDistribution(self.currentPower - power)

        except Exception as err:
            _LOGGER.error(err)
            _LOGGER.error(traceback.format_exc())


class SmartMode:
    NONE = 0
    MANUAL = 1
    MATCHING = 2

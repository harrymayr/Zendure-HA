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
from .sensor import ZendureSensor
from .switch import ZendureSwitch
from .zendurecharge import ZendureCharge
from .zenduredevice import ZendureDevice
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
        self.phases: list[ZendurePhase] = [
            ZendurePhase("1", config_entry.data.get(CONF_PHASE1, None)),
            ZendurePhase("2", config_entry.data.get(CONF_PHASE2, None)),
            ZendurePhase("3", config_entry.data.get(CONF_PHASE3, None)),
        ]
        self._mqtt: mqtt_client.Client | None = None
        self.charge: ZendureCharge = ZendureCharge()
        self.p1meter = config_entry.data.get(CONF_P1METER)
        self._attr_device_info = self.attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "ZendureManager")},
            model="Zendure Manager",
            manufacturer="Fireson",
        )
        self.sensors: list[ZendureSensor] = []
        self.switches: list[ZendureSwitch] = []
        self.operation = 0
        self.bypass = False
        self.update_power = 0
        self.update_count = 0
        self.update_normal = datetime.now()

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
            _LOGGER.info(f"Adding sensors Hyper2000 {self.name}")
            selects = [
                ZendureSelect(
                    self._attr_device_info,
                    "zendure_manager_operation",
                    "Zendure Manager Operation",
                    self.update_operation,
                    options=["off", "manual power", "smart matching"],
                ),
            ]
            ZendureSelect.addSelects(selects)

            numbers = [
                ZendureNumber(
                    self.attr_device_info,
                    "zendure_manager_manual_power",
                    "Zendure Manual Power",
                    self._update_manual_energy,
                    None,
                    "W",
                    "power",
                    3600,
                    -3600,
                    NumberMode.BOX,
                ),
            ]
            ZendureNumber.addNumbers(numbers)

            self.sensors = [
                ZendureSensor(self.attr_device_info, "zendure_manager_current_power", "Zendure Current Power", None, "W", "power"),
                ZendureSensor(self.attr_device_info, "zendure_manager_current_delta", "Zendure Current Delta", None, "W", "power"),
            ]
            ZendureSensor.addSensors(self.sensors)

            self.switches = [
                ZendureSwitch(self.attr_device_info, "zendure_manager_use_bypass", "Zendure Bypass to Grid", self._update_bypass, None, "W", "power"),
            ]
            ZendureSensor.addSensors(self.sensors)

        except Exception as err:
            _LOGGER.error(err)
            return False
        return True

    def update_operation(self, operation: int) -> None:
        self.operation = operation
        if self.operation < SmartMode.MATCHING:
            for h in self.devices.values():
                h.update_power(0)

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
                _LOGGER.info(f"Unknown topic: {msg.topic} => {payload}")
                return

            topics = msg.topic.split("/")
            parameter = topics[-1]

            if parameter == "report":
                if properties := payload.get("properties", None):
                    for key, value in properties.items():
                        device.updateProperty(key, value)
                elif properties := payload.get("cluster", None):
                    device.updateProperty("clusterId", properties["clusterId"])
                    if (phase := properties.get("phaseCheck", None)) is not None:
                        device.updateProperty("Phase", phase)
                        if not device.phase:
                            device.phase = self.phases[phase]
                            self.phases[phase].addDevice(device)
                else:
                    device.handleTopic(msg.topic, payload)

            elif parameter == "reply" and topics[-3] == "function":
                # battery information
                _LOGGER.info(f"Receive: {device.hid} => ready!")
                self.busy = 0

            elif parameter == "log" and payload["logType"] == LOGTYPE_BATTERY:
                # battery information
                device.updateBattery(payload["log"]["params"])

            else:
                device.handleTopic(msg.topic, payload)

        except Exception as err:
            _LOGGER.error(err)

    @callback
    def _update_bypass(self, _switch: Any, value: int) -> None:
        try:
            self.bypass = value != 0
        except Exception as err:
            _LOGGER.error(err)
            _LOGGER.error(traceback.format_exc())

    @callback
    def _update_manual_energy(self, _number: Any, power: float) -> None:
        try:
            if self.operation == SmartMode.MANUAL:
                self._update_power(int(power), isdelta=False)

        except Exception as err:
            _LOGGER.error(err)
            _LOGGER.error(traceback.format_exc())

    @callback
    def _update_smart_energyp1(self, event: Event[EventStateChangedData]) -> None:
        try:
            if self.operation != SmartMode.MATCHING or (new_state := event.data["new_state"]) is None:
                return

            delta = int(float(new_state.state))

            # check for next update
            time = datetime.now()
            self.update_power += delta
            self.update_count += 1
            delta = int(self.update_power / self.update_count)
            self.sensors[1].update_value(delta)

            # only update each 5 seconds
            if not (self.update_normal < time):
                return

            # update the power distribution of all devices
            self._update_power(delta, True)

            # reset the update counters
            self.update_normal = time + timedelta(seconds=5)
            self.update_power = 0
            self.update_count = 0

        except Exception as err:
            _LOGGER.error(err)
            _LOGGER.error(traceback.format_exc())

    def _update_power(self, power: int, isdelta: bool) -> None:
        _LOGGER.info("")
        _LOGGER.info("")
        _LOGGER.info(f"_update_power: {power} isdelta: {isdelta}")

        # update the current power & capacity
        self.charge.reset()
        for p in self.phases:
            p.updateCharge(self.charge)

        self.sensors[0].update_value(self.charge.currentpower)
        if isdelta:
            self.sensors[1].update_value(power)

        # determine the phase distribution
        self.charge.power = (self.charge.currentpower + power) if isdelta else power
        if self.charge.power > -50 and self.charge.power < 0:
            _LOGGER.info(f"update power; clip charging : {self.charge.power}")
            self.charge.power = 0

        _LOGGER.info(f"_update_power: total: {self.charge.currentpower} power: {power} sel.power: {self.charge.power}")
        self.charge.distribute(self.name, self.phases)

        # determine the power distribution per phase
        for p in self.phases:
            p.distribute(p.name, p.devices)

        # update the power per device
        for p in self.phases:
            for d in p.devices:
                # set the bypass if necessary
                d.update_power_delta(d.power)


class SmartMode:
    NONE = 0
    MANUAL = 1
    MATCHING = 2

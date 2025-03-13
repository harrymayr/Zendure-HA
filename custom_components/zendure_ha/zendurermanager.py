"""Zendure Integration manager using DataUpdateCoordinator."""

from __future__ import annotations
from ast import List
from datetime import timedelta, datetime
import logging
import json
import traceback
from typing import Any
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import DOMAIN, HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.core import Event, EventStateChangedData, callback
from paho.mqtt import client as mqtt_client
from sqlalchemy import false
from .api import Api
from .const import DEFAULT_SCAN_INTERVAL, CONF_CONSUMED, CONF_PRODUCED, CONF_MANUALPOWER
from .select import ZendureSelect
from .sensor import ZendureSensor
from .zendurecharge import ZendureCharge
from .zendurephase import ZendurePhase
from .zenduredevice import ZendureDevice

_LOGGER = logging.getLogger(__name__)


class ZendureManager(DataUpdateCoordinator[int]):
    """The Zendure manager."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize ZendureManager."""
        self._hass = hass
        self.devices: dict[str, ZendureDevice] = {}
        self.phases: list[ZendurePhase] = [ZendurePhase("1"), ZendurePhase("2"), ZendurePhase("3")]
        self._mqtt: mqtt_client.Client | None = None
        self.poll_interval = config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        self.charge: ZendureCharge = ZendureCharge()
        self.consumed: str = config_entry.data[CONF_CONSUMED]
        self.produced: str = config_entry.data[CONF_PRODUCED]
        self.manualpower = config_entry.data.get(CONF_MANUALPOWER, None)
        self._attr_device_info = self.attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "ZendureManager")},
            model="Zendure Manager",
            manufacturer="Fireson",
        )
        self.sensors: list[ZendureSensor] = []
        self.operation = 0
        self.update_power = 0
        self.update_count = 0
        self.update_normal = datetime.now()
        self.update_fast = datetime.now()

        # Initialise DataUpdateCoordinator
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} ({config_entry.unique_id})",
            update_method=self._refresh_data,
            update_interval=timedelta(seconds=self.poll_interval),
            always_update=True,
        )

        # Set sensors from values entered in config flow setup
        if self.consumed and self.produced:
            _LOGGER.info(f"Energy sensors: {self.consumed} - {self.produced} to _update_smart_energy")
            async_track_state_change_event(self._hass, [self.consumed, self.produced], self._update_smart_energy)

        if self.manualpower:
            _LOGGER.info(f"Energy sensors: {self.manualpower} to _update_manual_energy")
            async_track_state_change_event(self._hass, [self.manualpower], self._update_manual_energy)
        else:
            _LOGGER.info("Energy sensors: nothing to _update_manual_energy")

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
                    "zendure_manager_status",
                    "Zendure Manager Status",
                    self.update_operation,
                    options=[
                        "off",
                        "manual power operation",
                        "smart power matching single sensor",
                        "smart power matching consumed/produced sensors",
                    ],
                ),
            ]
            ZendureSelect.addSelects(selects)

            self.sensors = [
                ZendureSensor(self.attr_device_info, "zendure_manager_current_power", "Current Power", None, "W", "power"),
                ZendureSensor(self.attr_device_info, "zendure_manager_current_delta", "Current Delta", None, "W", "power"),
            ]
            ZendureSensor.addSensors(self.sensors)

        except Exception as err:
            _LOGGER.exception(err)
            return False
        return True

    def update_operation(self, operation: int) -> None:
        self.operation = operation
        if self.operation < SmartMode.SMART_SINGLE:
            for h in self.devices.values():
                h.update_power(0)

    async def _refresh_data(self) -> None:
        """Refresh the data of all hyper2000's."""
        _LOGGER.info("refresh hypers")
        try:
            if self._mqtt:
                for d in self.devices.values():
                    d.sendRefresh()
        except Exception as err:
            _LOGGER.error(err)
        self._schedule_refresh()

    def on_message(self, client, userdata, msg) -> None:
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

            elif parameter == "log" and payload["logType"] == 2:
                # battery information
                device.updateBattery(payload["log"]["params"])

            else:
                device.handleTopic(msg.topic, payload)

        except Exception as err:
            _LOGGER.error(err)

    @callback
    def _update_manual_energy(self, event: Event[EventStateChangedData]) -> None:
        try:
            # get the new power value
            power = int(float(event.data["new_state"].state))
            _LOGGER.info(f"update_manual {power}")

            if self.operation == SmartMode.MANUAL:
                self._update_power(power, isdelta=False)
            elif self.operation == SmartMode.SMART_SINGLE:
                self._update_matching(power)

        except Exception as err:
            _LOGGER.error(err)
            _LOGGER.error(traceback.format_exc())

    @callback
    def _update_smart_energy(self, event: Event[EventStateChangedData]) -> None:
        """Update the battery input/output."""
        if self.operation != SmartMode.SMART_MATCHING:
            self.sensors[1].update_value(0)
            return
        delta = int(float(event.data["new_state"].state)) * (1 if event.data["entity_id"] == self.consumed else -1)
        self._update_matching(delta)

    def _update_matching(self, delta: int) -> None:
        """Update the battery input/output."""
        try:
            # check for next update
            time = datetime.now()
            self.update_power += delta
            self.update_count += 1
            delta = int(self.update_power / self.update_count)
            self.sensors[1].update_value(delta)

            # react quicker to a sudden rise of power
            if not (self.update_normal < time or (self.update_fast > time and abs(delta) > 250)):
                return

            # update the power distribution of all devices
            self._update_power(delta, True)

            # reset the update counters
            self.update_normal = time + timedelta(seconds=5)
            self.update_fast = time + (timedelta(seconds=2) if abs(delta) < 250 else timedelta(seconds=5))
            self.update_power = 0
            self.update_count = 0

        except Exception as err:
            _LOGGER.error(err)
            _LOGGER.error(traceback.format_exc())

    def _update_power(self, power: int, isdelta: bool) -> None:
        _LOGGER.info(f"_update_power: {power} isdelta: {isdelta}")

        # update the current power & capacity
        self.charge.reset()
        for p in self.phases:
            p.updateCharge(self.charge)

        _LOGGER.info(f"_update_power: total: {self.charge.currentpower} charge: {self.charge.data[0].capacity} discharge: {self.charge.data[1].capacity}")

        self.sensors[0].update_value(self.charge.currentpower)
        if isdelta:
            self.sensors[1].update_value(power)

        # determine the phase distribution
        self.charge.power = self.charge.currentpower + power if isdelta else power

        # switch between charge and discharge
        self.charge.distribute(self.name, self.phases)
        _LOGGER.info("")
        _LOGGER.info("")

        # determine the power distribution per phase
        for p in self.phases:
            p.distribute(p.name, p.devices)

        # update the power per device
        for p in self.phases:
            for d in p.devices:
                d.update_power(d.power)


class SmartMode:
    NONE = 0
    MANUAL = 1
    SMART_SINGLE = 2
    SMART_MATCHING = 3

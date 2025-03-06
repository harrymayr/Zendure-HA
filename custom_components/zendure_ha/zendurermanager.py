"""Zendure Integration manager using DataUpdateCoordinator."""

from __future__ import annotations
from dataclasses import dataclass
from datetime import timedelta, datetime
import logging
import json
from operator import le
from typing import Any
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import DOMAIN, HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.core import Event, EventStateChangedData, callback
from paho.mqtt import client as mqtt_client
from .api import Api
from .const import DEFAULT_SCAN_INTERVAL, CONF_CONSUMED, CONF_PRODUCED, CONF_MANUALPOWER
from .select import ZendureSelect
from .powermanager import PowerManager
from .hyper2000 import Hyper2000

_LOGGER = logging.getLogger(__name__)


class ZendureManager(DataUpdateCoordinator[int]):
    """The Zendure manager."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize ZendureManager."""
        self._hass = hass
        self.hypers: dict[str, Hyper2000] = {}
        self._mqtt: mqtt_client.Client = None
        self.poll_interval = config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        self.consumed: str = config_entry.data[CONF_CONSUMED]
        self.produced: str = config_entry.data[CONF_PRODUCED]
        if CONF_MANUALPOWER in config_entry.data:
            self.manualpower = config_entry.data[CONF_MANUALPOWER]
        else:
            self.manualpower = None
        self.operation = 0
        self._max_charge: int = 0
        self._max_discharge: int = 0
        self._attr_device_info = self.attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "ZendureManager")},
            model="Zendure Manager",
            manufacturer="Fireson",
        )
        self.power_manager = PowerManager()

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
            self.hypers = await self.api.get_hypers(self._hass)
            self._mqtt = self.api.get_mqtt(self.on_message)
            self.power_manager.hypers = list(self.hypers.values())

            try:
                for h in self.hypers.values():
                    h.create_sensors()
                    self._mqtt.subscribe(f"/{h.prodkey}/{h.hid}/#")
                    self._mqtt.subscribe(f"iot/{h.prodkey}/{h.hid}/#")

            except Exception as err:
                _LOGGER.exception(err)

            _LOGGER.info(f"Found: {len(self.hypers)} hypers")

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

        except Exception as err:
            _LOGGER.exception(err)
            return False
        return True

    def update_operation(self, operation: int) -> None:
        self.operation = operation
        if self.operation != SmartMode.SMART_MATCHING:
            for h in self.hypers.values():
                h.update_power(self._mqtt, 0, 0, 0)

    async def _refresh_data(self) -> None:
        """Refresh the data of all hyper2000's."""
        _LOGGER.info("refresh hypers")
        try:
            if self.operation == SmartMode.MANUAL:
                self.power_manager.update_manual(self._mqtt, self.power_manager.manual_power)

            if self._mqtt:
                for h in self.hypers.values():
                    self._mqtt.publish(h._topic_read, '{"properties": ["getAll"]}')
        except Exception as err:
            _LOGGER.error(err)
        self._schedule_refresh()

    @callback
    def _update_manual_energy(self, event: Event[EventStateChangedData]) -> None:
        try:
            # get the new power value
            power = int(float(event.data["new_state"].state))
            _LOGGER.info(f"update _update_manual_energy {power}")

            if self.operation == SmartMode.MANUAL:
                self.power_manager.update_manual(self._mqtt, power)
            elif self.operation == SmartMode.SMART_MATCHING:
                self.power_manager.update_matching(self._mqtt, power)

        except Exception as err:
            _LOGGER.error(err)
            _LOGGER.error(traceback.format_exc())

    @callback
    def _update_smart_energy(self, event: Event[EventStateChangedData]) -> None:
        """Update the battery input/output."""
        try:
            # get the new power value
            power = int(float(event.data["new_state"].state))
            _LOGGER.info(f"update _update_smart_energy {power}")
            if self.operation == SmartMode.SMART_MATCHING and power != 0:
                self.power_manager.update_matching(self._mqtt, power * (1 if event.data["entity_id"] == self.consumed else -1))

        except Exception as err:
            _LOGGER.error(err)
            _LOGGER.error(traceback.format_exc())

    def on_message(self, client, userdata, msg) -> None:
        try:
            # check for valid device in payload
            payload = json.loads(msg.payload.decode())
            if not (deviceid := payload.get("deviceId", None)) or not (hyper := self.hypers.get(deviceid, None)):
                return

            hyper.handle_message(msg.topic, payload)
        except Exception as err:
            _LOGGER.error(err)


class SmartMode:
    NONE = 0
    MANUAL = 1
    SMART_SINGLE = 2
    SMART_MATCHING = 3

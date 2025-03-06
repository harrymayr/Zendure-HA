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
            _LOGGER.info(f"Energy sensors: nothing to _update_manual_energy")

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
                        "smart power matching",
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

    def _update_hypers(self) -> None:
        """Update the hypers each 5 minutes."""
        if self.next_update < datetime.now():
            self.next_update = datetime.now() + timedelta(minutes=5)

            self._max_charge = 0
            self._max_discharge = 0
            total_charge_capacity = 0
            total_discharge_capacity = 0
            phases = [PhaseData([], 0, 0), PhaseData([], 0, 0), PhaseData([], 0, 0)]
            for h in self.hypers.values():
                # get device settings
                level = int(h.sensors["electricLevel"].state)
                levelmin = float(h.sensors["minSoc"].state)
                levelmax = float(h.sensors["socSet"].state)
                batcount = int(h.sensors["packNum"].state)
                phase_id = h.sensors["Phase"].state
                phase = phases[int(phase_id) if phase_id else 0]
                phase.hypers.append(h)

                # get discharge settings
                h.discharge_max = 800 if level > levelmin else 0
                if h.discharge_max > 0 and phase.max_discharge == 0:
                    phase.max_discharge = h.discharge_max
                    self._max_discharge += h.discharge_max
                h.discharge_capacity = int(batcount * max(0, level - levelmin))
                total_discharge_capacity += h.discharge_capacity

                # get charge settings
                h.charge_max = 1200 if level < levelmax else 0
                h.charge_capacity = int(batcount * max(0, levelmax - level))
                if h.charge_max > 0 and phase.max_charge == 0:
                    phase.max_charge = h.charge_max
                    self._max_charge += h.charge_max
                total_charge_capacity += h.charge_capacity

            # update the charge/discharge per phase
            for p in phases:
                if p.hypers:
                    for h in p.hypers:
                        h.charge_max = int(h.charge_max / len(p.hypers))
                        h.charge_fb = h.charge_max / self._max_charge
                        h.discharge_max = int(h.discharge_max / len(p.hypers))
                        h.discharge_fb = h.discharge_max / self._max_discharge

            # update the charge/discharge devices
            _LOGGER.info(f"Valid charging: {self._max_charge}")
            _LOGGER.info(f"Valid discharging: {self._max_discharge}")

    @callback
    def _update_manual_energy(self, event: Event[EventStateChangedData]) -> None:
        try:
            # get the new power value
            power = int(float(event.data["new_state"].state))
            _LOGGER.info(f"update _update_manual_energy {power}")
            if self.operation != SmartMode.MANUAL:
                return

            self.power_manager.update_manual(self._mqtt, power)
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
            if self.operation != SmartMode.SMART_MATCHING:
                return

            if power == 0:
                return

            self._update_hypers()
            if (discharge := sum(h.sensors["outputHomePower"].state for h in self._discharge_devices)) > 0:
                self.upd_discharging(discharge + power * (1 if event.data["entity_id"] == self.consumed else -1))
            elif (charge := sum(h.sensors["gridInputPower"].state for h in self._charge_devices)) > 0:
                self.upd_charging(charge + power * (-1 if event.data["entity_id"] == self.consumed else 1))
            elif event.data["entity_id"] == self.produced:
                self.upd_charging(power)
            else:
                self.upd_discharging(power)

        except Exception as err:
            _LOGGER.error(err)
            _LOGGER.error(traceback.format_exc())

    def upd_charging(self, charge: int) -> None:
        """Update the battery input/output."""
        _LOGGER.info(f"update energy Charging: {charge}")

        if charge >= self._max_charge:
            for h in self.hypers.values():
                h.update_power(self._mqtt, 1, h.charge_max, 0)
        else:
            for h in self.hypers.values():
                h.update_power(self._mqtt, 1, int(charge * h.charge_fb), 0)

        # if charge < 400:
        #     self._charge_devices[0].update_power(self._mqtt, 1, charge, 0)
        #     if len(self._charge_devices) > 1:
        #         for h in self._charge_devices[1:]:
        #             h.update_power(self._mqtt, 0, 0, 0)
        # else:
        #     for h in self._charge_devices:
        #         h.update_power(self._mqtt, 1, int(charge / len(self._charge_devices)), 0)

    def upd_discharging(self, discharge: int) -> None:
        """Update the battery input/output."""
        _LOGGER.info(f"update energy Discharging: {discharge} {self._max_charge}")
        if discharge >= self._max_discharge:
            for h in self.hypers.values():
                h.update_power(self._mqtt, 0, 0, h.discharge_max)
        else:
            for h in self.hypers.values():
                h.update_power(self._mqtt, 0, 0, int(discharge * h.discharge_fb))

        # if not self._discharge_devices:
        #     return

        # if discharge < 400:
        #     self._discharge_devices[0].update_power(self._mqtt, 0, 0, discharge)
        #     if len(self._discharge_devices) > 1:
        #         for h in self._discharge_devices[1:]:
        #             h.update_power(self._mqtt, 0, 0, 0)
        # else:
        #     for h in self._discharge_devices:
        #         h.update_power(self._mqtt, 0, 0, int(discharge / len(self._discharge_devices)))

    def on_message(self, client, userdata, msg) -> None:
        try:
            # check for valid device in payload
            payload = json.loads(msg.payload.decode())
            if not (deviceid := payload.get("deviceId", None)) or not (hyper := self.hypers.get(deviceid, None)):
                return

            hyper.handle_message(msg.topic, payload)
        except Exception as err:
            _LOGGER.error(err)


@dataclass
class PhaseData:
    """Class to hold phase totals."""

    hypers: list[Hyper2000]
    max_charge: int
    max_discharge: int


class SmartMode:
    NONE = 0
    MANUAL = 1
    SMART_MATCHING = 2

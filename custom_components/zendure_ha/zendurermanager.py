"""Zendure Integration manager using DataUpdateCoordinator."""

from __future__ import annotations

import json
import logging
from math import e
import traceback
from datetime import datetime, timedelta
from typing import Any, OrderedDict

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
        self.p1meter = config_entry.data.get(CONF_P1METER)
        self._attr_device_info = self.attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "ZendureManager")},
            model="Zendure Manager",
            manufacturer="Fireson",
        )
        self.operation = 0
        self.nom_count = 0
        self.nom_timer = datetime.now()

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

        except Exception as err:
            _LOGGER.error(err)
            return False
        return True

    def update_operation(self, operation: int) -> None:
        self.operation = operation
        if self.operation < SmartMode.MATCHING:
            for h in self.devices.values():
                h.power_off()

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

            match parameter:
                case "report":
                    if properties := payload.get("properties", None):
                        for key, value in properties.items():
                            device.updateProperty(key, value)
                            if device.waiting and key in ("packInputPower", "outputPackPower"):
                                self.nom_count -= 1
                                _LOGGER.info(f"Reset waiting: {device.name} count: {self.nom_count}")
                                device.waiting = False
                                if self.nom_count == 0:
                                    _LOGGER.info("Reset NOM timer!")
                                    self.nom_timer = datetime.now() + timedelta(seconds=1)

                    if properties := payload.get("cluster", None):
                        device.updateProperty("clusterId", properties["clusterId"])
                        if (phase := properties.get("phaseCheck", None)) is not None:
                            device.updateProperty("Phase", phase)
                            if not device.phase:
                                device.phase = self.phases[phase]
                                device.phase.devices.append(device)
                            elif device.phase != self.phases[phase]:
                                device.phase.devices.remove(device)
                                device.phase = self.phases[phase]
                                device.phase.devices.append(device)

                    # if properties := payload.get("packData", None):
                    #     for bat in properties:
                    #         sn = bat.pop("sn")
                    #         _LOGGER.info(f"Batdata: {bat}")
                    #         for key, value in bat.items():
                    #             device.updateProperty(f"battery:{sn} {key}", value)

                case "config":
                    _LOGGER.info(f"Receive: {device.hid} => event: {payload}")

                case "device":
                    if topics[-2] == "event":
                        _LOGGER.info(f"Receive: {device.hid} => event: {payload}")

                case "error":
                    if topics[-2] == "event":
                        _LOGGER.info(f"Receive: {device.hid} => error: {payload}")

                case "reply":
                    if topics[-3] == "function":
                        _LOGGER.info(f"Receive: {device.hid} => ready!")

                case "log":
                    if payload["logType"] == LOGTYPE_BATTERY:
                        device.updateBattery(payload["log"]["params"])

                case _:
                    _LOGGER.info(f"Unknown topic {msg.topic} => {payload}")

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
            if not (self.nom_timer < time):
                return

            # update the power distribution of all devices
            self._update_power(delta, True)

            # reset the update counters
            self.nom_timer = time + timedelta(seconds=(10 if self.nom_count > 0 else 2))
            # self.update_power = 0
            # self.update_count = 0

        except Exception as err:
            _LOGGER.error(err)
            _LOGGER.error(traceback.format_exc())

    def _update_power(self, pwr: int, isdelta: bool) -> None:
        _LOGGER.info("")
        _LOGGER.info("")

        # get the current power
        actualPower = sum(d.asInt("packInputPower") - d.asInt("outputPackPower") for d in self.devices.values())
        power = (actualPower + pwr) if isdelta else pwr
        _LOGGER.info(f"Update power: {power} from {actualPower} delta: {pwr if isdelta else ''}")
        if actualPower == 0:
            actualPower = power

        # Do the power distribution
        totalCapacity = 0
        activePhases = 0
        self.nom_count = 0
        if power == 0:
            for d in self.devices.values():
                d.power_off()

        elif power < 0:
            power = abs(power)
            for p in self.phases:
                if p.devices:
                    totalCapacity += p.charge_update()
                    activePhases += 1

            for p in sorted(self.phases, key=lambda p: p.capacity, reverse=True):
                if p.devices:
                    power -= p.charge(power, activePhases, totalCapacity)
                    totalCapacity -= p.capacity
                    activePhases -= 1
                    self.nom_count += p.activeDevices
                    _LOGGER.info(f"Discharging phase:  {p.name} capacity: {p.capacity} total:{totalCapacity}")

        else:
            for p in self.phases:
                if p.devices:
                    activePhases += 1
                    totalCapacity += p.discharge_update()

            for p in sorted(self.phases, key=lambda p: p.capacity, reverse=True):
                if p.devices:
                    power -= p.discharge(power, activePhases, totalCapacity)
                    totalCapacity -= p.capacity
                    activePhases -= 1
                    self.nom_count += p.activeDevices
                    _LOGGER.info(f"Discharging phase:  {p.name} capacity: {p.capacity} total:{totalCapacity}")


class SmartMode:
    NONE = 0
    MANUAL = 1
    MATCHING = 2

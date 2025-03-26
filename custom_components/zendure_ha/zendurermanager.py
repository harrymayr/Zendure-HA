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

            match parameter:
                case "report":
                    if properties := payload.get("properties", None):
                        for key, value in properties.items():
                            device.updateProperty(key, value)

                    if properties := payload.get("cluster", None):
                        device.updateProperty("clusterId", properties["clusterId"])
                        if (phase := properties.get("phaseCheck", None)) is not None:
                            device.updateProperty("Phase", phase)
                            if not device.phase:
                                device.phase = self.phases[phase]
                                self.phases[phase].addDevice(device)

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
                        device.busy = 5

                case "log":
                    if payload["logType"] == LOGTYPE_BATTERY:
                        device.updateBattery(payload["log"]["params"])

                case _:
                    _LOGGER.info(f"Unknown topic {msg.topic} => {payload}")

        except Exception as err:
            _LOGGER.error(err)
            _LOGGER.error(traceback.format_exc())

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
            self.update_normal = time + timedelta(seconds=2)
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
        totalPower = 0
        totalCapacity = 0
        totalMax = 0
        lead = self.phases[0]
        for p in self.phases:
            p.capacity = 0
            p.max = 0
            p.power = 0
            if not p.devices:
                continue
            p.lead = p.devices[0]
            for d in p.devices:
                d.power = d.asInt("packInputPower") - d.asInt("outputPackPower")
                p.power += d.power
                d.capacity = int(
                    d.asInt("packNum") * d.asFloat("socSet") - d.asInt("electricLevel") if power > 0 else d.asInt("electricLevel") - d.asFloat("socMin")
                )
                p.capacity += d.capacity
                if d.capacity > 0:
                    p.max += d.asInt("inverseMaxPower") if power > 0 else 1200
                if d.capacity > p.lead.capacity:
                    p.lead = d

            if p.capacity > lead.capacity:
                lead = p
            p.max = max(p.max, p.dischargemax if power > 0 else p.chargemax)
            totalPower += p.power
            totalCapacity += p.capacity
            totalMax += p.max

        _LOGGER.info(f"Total power: {totalPower} Total capacity: {totalCapacity} Total max: {totalMax}")

        # clip the total power
        power = min(totalMax, (totalPower + power) if isdelta else power)

        # update the power distribution of all phases
        ready = False
        while not ready:
            ready = True
            for p in self.phases:
                pwr = power * p.capacity / totalCapacity
                if pwr != 0 and not (p == lead or (abs(pwr) > 0.1 * p.max and p.power > 0) or (abs(pwr) > 0.125 * p.max and p.power == 0)):
                    totalCapacity -= p.capacity
                    p.capacity = 0
                    ready = False
                    break

        _LOGGER.info(f"Lead: {lead.name} phase1: {self.phases[0].capacity} phase2: {self.phases[1].capacity} phase3: {self.phases[2].capacity}")

        # update the power distribution per phases
        for p in self.phases:
            if not p.devices:
                continue
            pwr = power * p.capacity / totalCapacity
            _LOGGER.info(f"Phase: {p.name} power: {pwr} capacity: {p.capacity} max: {p.max}")
            if pwr == 0:
                for d in p.devices:
                    d.update_power_delta(0)
            else:
                ready = False
                while not ready:
                    ready = True
                    for d in p.devices:
                        dpwr = pwr * d.capacity / p.capacity
                        if dpwr != 0 and not (d == p.lead or (abs(dpwr) > 60 and d.power > 0) or (abs(dpwr) > 120 and d.power == 0)):
                            p.capacity -= d.capacity
                            d.capacity = 0
                            ready = False
                            break
                for d in p.devices:
                    d.update_power_delta(int(pwr * d.capacity / p.capacity))


class SmartMode:
    NONE = 0
    MANUAL = 1
    MATCHING = 2

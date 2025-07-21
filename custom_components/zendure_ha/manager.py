"""Zendure Integration manager using DataUpdateCoordinator."""

from __future__ import annotations

import asyncio
import json
import logging
import traceback
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import sqrt
from pathlib import Path
from typing import Any

from homeassistant.components import bluetooth
from homeassistant.components.number import NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import Api, ApiOld
from .const import CONF_BETA, CONF_P1METER, DOMAIN, ManagerState, SmartMode
from .device import Device, ZendureDevice
from .number import ZendureRestoreNumber
from .select import ZendureRestoreSelect, ZendureSelect

_LOGGER = logging.getLogger(__name__)


class Manager(DataUpdateCoordinator[int], Device):
    """The Zendure manager."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize Manager."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} ({config_entry.unique_id})",
            update_interval=timedelta(seconds=90),
            always_update=True,
        )

        Device.__init__(self, hass, "manager", "Zendure Manager", "Zendure Manager")

        data = config_entry.data
        # self.api = Api(hass, data)  # type: ignore[call-arg]
        self.api = Api(self.hass, data) if data.get(CONF_BETA) else ApiOld(self.hass, data)  # type: ignore[call-arg]

        self.p1meter = data.get(CONF_P1METER)
        self.operation = 0
        self.setpoint = 0
        self.zero_idle = datetime.max
        self.zero_next = datetime.min
        self.zero_fast = datetime.min
        self.check_reset = datetime.min
        self.zorder: deque[int] = deque([25, -25], maxlen=8)
        self.cluster: dict[str, ClusterGroup] = {}

    async def load(self) -> bool:
        """Initialize the manager."""
        try:
            manifest = Path(f"custom_components/{DOMAIN}/manifest.json")
            if manifest.exists():
                manifest_data = await asyncio.to_thread(manifest.read_text)
                self.attr_device_info["serial_number"] = json.loads(manifest_data)["version"]

            # create and initialize the devices
            await self.api.load(True)
            _LOGGER.info(f"Found: {len(self.api.devices)} devices")

            def updateCluster(_entity: ZendureRestoreSelect, _value: Any) -> None:
                self.update_clusters()

            for device in self.api.devices.values():
                device.cluster.onchanged = updateCluster
            self.update_clusters()

            # Add Manager sensors
            _LOGGER.info(f"Adding sensors {self.name}")
            self.operationmode = (
                ZendureRestoreSelect(
                    self, "Operation", {0: "off", 1: "manual", 2: "smart", 3: "smart_discharging", 4: "smart_charging"}, self.update_operation
                ),
            )
            self.manualpower = ZendureRestoreNumber(self, "manual_power", self._update_manual_energy, None, "W", "power", 10000, -10000, NumberMode.BOX)

            # Set sensors from values entered in config flow setup
            if self.p1meter:
                _LOGGER.info(f"Energy sensors: {self.p1meter} to _update_smart_energyp1")
                self.p1meterEvent = async_track_state_change_event(self.hass, [self.p1meter], self._p1_update)

            _LOGGER.info("Zendure Manager initialized")

        except Exception as err:
            _LOGGER.error(err)
            _LOGGER.error(traceback.format_exc())
            return False
        return True

    async def unload(self) -> None:
        """Unload the manager."""
        if self.p1meterEvent:
            self.p1meterEvent()
        await self.api.unload()
        self.cluster.clear()

    async def _async_update_data(self) -> int:
        """Refresh the data of all devices's."""
        _LOGGER.info("refresh devices")
        try:
            for device in self.api.devices.values():
                _LOGGER.debug(f"Update device: {device.name} ({device.deviceId})")

                # check for bluetooth device
                if device.bleMac is None:
                    for si in bluetooth.async_discovered_service_info(self.hass, False):
                        if si.name.startswith("Zen") and any(device.snNumber.endswith(e.decode("utf8")[:-1]) for e in si.manufacturer_data.values()):
                            _LOGGER.info(f"Found Zendure Bluetooth device: {si}")
                            device.bleMac = si.address
                            break

                #     if device.bleMac is not None:
                #         device.mqttStatus()

                # if device.mqttZenApp < time:
                #     device.mqttZenApp = datetime.min

        except Exception as err:
            _LOGGER.error(err)
            _LOGGER.error(traceback.format_exc())

        if self.hass and self.hass.loop.is_running():
            self._schedule_refresh()
        return 0

    def update_clusters(self) -> None:
        _LOGGER.info("Update clusters")

        self.cluster.clear()
        for device in self.api.devices.values():
            match device.cluster.state:
                case "clusterowncircuit", "cluster3600":
                    cluster = ClusterGroup(device, [], 3600, -3600)
                case "cluster800":
                    cluster = ClusterGroup(device, [], 800, -1200)
                case "cluster1200":
                    cluster = ClusterGroup(device, [], 1200, -1800)
                case "cluster2400":
                    cluster = ClusterGroup(device, [], 2400, -3600)
                case _:
                    continue
            cluster.devices.append(device)
            self.cluster[device.deviceId] = cluster

        # Update the clusters and select optins for each device
        for device in self.api.devices.values():
            clusters: dict[Any, str] = {0: "unused", 1: "clusterowncircuit", 2: "cluster800", 3: "cluster1200", 4: "cluster2400", 5: "cluster3600"}
            for c in self.cluster.values():
                if c.device.deviceId != device.deviceId:
                    clusters[c.device.deviceId] = f"Part of {c.device.name} cluster"
            device.cluster.setOptions(clusters)

        # Add devices to clusters
        for device in self.api.devices.values():
            if clstr := self.cluster.get(device.cluster.value):
                clstr.devices.append(device)

    def update_operation(self, entity: ZendureSelect, _operation: Any) -> None:
        operation = int(entity.value)
        _LOGGER.info(f"Update operation: {operation} from: {self.operation}")
        if operation == self.operation:
            return

        self.operation = operation
        if self.operation != SmartMode.MATCHING:
            for d in self.api.devices.values():
                d.power_set(ManagerState.IDLE, 0)

    def _update_manual_energy(self, _number: Any, power: float) -> None:
        try:
            if self.operation == SmartMode.MANUAL:
                self.setpoint = int(power)
                self.update_power(self.setpoint, ManagerState.DISCHARGING if power >= 0 else ManagerState.CHARGING)

        except Exception as err:
            _LOGGER.error(err)
            _LOGGER.error(traceback.format_exc())

    @callback
    def _p1_update(self, event: Event[EventStateChangedData]) -> None:
        try:
            # exit if there is nothing to do
            if not self.hass.is_running or not self.hass.is_running or (new_state := event.data["new_state"]) is None or self.operation == SmartMode.NONE:
                return

            # convert the state to a float
            try:
                p1 = int(float(new_state.state))
            except ValueError:
                return

            # calculate the standard deviation
            avg = sum(self.zorder) / len(self.zorder) if len(self.zorder) > 1 else 0
            stddev = min(50, sqrt(sum([pow(i - avg, 2) for i in self.zorder]) / len(self.zorder)))
            if isFast := abs(p1 - avg) > SmartMode.Threshold * stddev:
                self.zorder.clear()
            self.zorder.append(p1)

            # check minimal time between updates
            time = datetime.now()
            if time < self.zero_next or (time < self.zero_fast and not isFast):
                return

            # get the current power
            powerActual = 0
            for d in self.api.devices.values():
                d.powerAct = d.power_get()
                powerActual += d.powerAct

            _LOGGER.info(f"Update p1: {p1} power: {powerActual} operation: {self.operation} delta:{p1 - avg} stddev: {stddev} fast: {isFast}")
            match self.operation:
                case SmartMode.MATCHING:
                    # update when we are charging
                    if powerActual < 0:
                        self.update_power(min(0, powerActual + p1), ManagerState.CHARGING)

                    # update when we are discharging
                    elif powerActual > 0:
                        self.update_power(max(0, powerActual + p1), ManagerState.DISCHARGING)

                    # check if it is the first time we are idle
                    elif self.zero_idle == datetime.max:
                        _LOGGER.info(f"Wait {SmartMode.TIMEIDLE} sec for state change p1: {p1}")
                        self.zero_idle = time + timedelta(seconds=SmartMode.TIMEIDLE)

                    # update when we are idle for more than SmartMode.TIMEIDLE seconds
                    elif self.zero_idle < time:
                        if p1 < -SmartMode.MIN_POWER:
                            _LOGGER.info(f"Start charging with p1: {p1}")
                            self.update_power(p1, ManagerState.CHARGING)
                            self.zero_idle = datetime.max
                        elif p1 >= 0:
                            _LOGGER.info(f"Start discharging with p1: {p1}")
                            self.update_power(p1, ManagerState.DISCHARGING)
                            self.zero_idle = datetime.max
                        else:
                            _LOGGER.info(f"Unable to charge/discharge p1: {p1}")

                case SmartMode.MATCHING_DISCHARGE:
                    self.update_power(max(0, powerActual + p1), ManagerState.DISCHARGING)

                case SmartMode.MATCHING_CHARGE:
                    pwr = powerActual + p1 if powerActual < 0 else p1 if p1 < -SmartMode.MIN_POWER else 0
                    self.update_power(min(0, pwr), ManagerState.CHARGING)

                case SmartMode.MANUAL:
                    self.update_power(self.setpoint, ManagerState.DISCHARGING if self.setpoint >= 0 else ManagerState.CHARGING)

            self.zero_next = time + timedelta(seconds=SmartMode.TIMEZERO)
            self.zero_fast = time + timedelta(seconds=SmartMode.TIMEFAST)

        except Exception as err:
            _LOGGER.error(err)
            _LOGGER.error(traceback.format_exc())

    def update_power(self, power: int, state: ManagerState) -> None:
        """Update the setpoint for all devices."""
        totalCapacity = 0
        totalPower = 0

        # get the total capacity of all clusters
        for c in self.cluster.values():
            totalCapacity += c.capacity_get(state)
            totalPower += c.maxpower if state == ManagerState.DISCHARGING else abs(c.minpower)

        _LOGGER.info(f"Update setpoint: {power} state{state} capacity: {totalCapacity} max: {totalPower}")

        # redistribute the power on clusters
        isreverse = bool(abs(power) > totalPower / 2)
        clusters = sorted(self.cluster.values(), key=lambda d: d.capacity, reverse=isreverse)
        for c in clusters:
            _LOGGER.debug(f"Cluster: {c.device.name} capacity: {c.capacity} power: {power}")
            clusterPower = int(power * c.capacity / totalCapacity) if totalCapacity > 0 else 0
            clusterPower = max(0, min(c.maxpower, clusterPower)) if state == ManagerState.DISCHARGING else min(0, max(c.minpower, clusterPower))
            totalCapacity -= c.capacity
            clusterCapacity = c.capacity
            for d in sorted(c.devices, key=lambda d: d.capacity, reverse=isreverse):
                if d.capacity == 0:
                    d.power_set(state, 0)
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
                d.power_set(state, pwr)


@dataclass
class ClusterGroup:
    """ClusterGroup data."""

    device: ZendureDevice
    devices: list[ZendureDevice]
    maxpower: int = 0
    minpower: int = 0
    capacity: float = 0.0

    def capacity_get(self, state: ManagerState) -> float:
        """Get the cluster capacity for state."""
        self.capacity = sum(c.power_capacity(state) for c in self.devices)
        return self.capacity

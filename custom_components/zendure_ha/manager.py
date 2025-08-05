"""Coordinator for Zendure integration."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import traceback
from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta
from math import sqrt
from pathlib import Path
from typing import Any

from homeassistant.auth.const import GROUP_ID_USER
from homeassistant.auth.providers import homeassistant as auth_ha
from homeassistant.components import bluetooth
from homeassistant.components.number import NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import Api
from .const import CONF_P1METER, DOMAIN, ManagerState, SmartMode
from .device import ZendureDevice
from .entity import EntityDevice
from .fusegroup import FuseGroup
from .number import ZendureRestoreNumber
from .select import ZendureRestoreSelect, ZendureSelect

SCAN_INTERVAL = timedelta(seconds=90)

_LOGGER = logging.getLogger(__name__)

type ZendureConfigEntry = ConfigEntry[ZendureManager]


class ZendureManager(DataUpdateCoordinator[None], EntityDevice):
    """Class to regular update devices."""

    devices: list[ZendureDevice] = []
    fuseGroups: dict[str, FuseGroup] = {}

    def __init__(self, hass: HomeAssistant, entry: ZendureConfigEntry) -> None:
        """Initialize Zendure Manager."""
        super().__init__(hass, _LOGGER, name="Zendure Manager", update_interval=SCAN_INTERVAL, config_entry=entry)
        EntityDevice.__init__(self, hass, "manager", "Zendure Manager", "Zendure Manager")
        self.operation = 0
        self.setpoint = 0
        self.zero_idle = datetime.max
        self.zero_next = datetime.min
        self.zero_fast = datetime.min
        self.check_reset = datetime.min
        self.zorder: deque[int] = deque([25, -25], maxlen=8)
        self.fuseGroup: dict[str, FuseGroup] = {}
        self.p1meterEvent: Callable[[], None] | None = None
        self.update_p1meter(entry.data.get(CONF_P1METER, "sensor.power_actual"))
        self.api = Api()
        self.update_count = 0

    async def loadDevices(self) -> None:
        if self.config_entry is None or (data := await Api.Connect(self.hass, dict(self.config_entry.data))) is None:
            return

        # read version number from manifest
        manifest = Path(f"custom_components/{DOMAIN}/manifest.json")
        if manifest.exists():
            manifest_data = await asyncio.to_thread(manifest.read_text)
            props = json.loads(manifest_data)
            self.attr_device_info["sw_version"] = props.get("version", "unknown")
            _LOGGER.info(f"Zendure Manager version: {self.attr_device_info['sw_version']}")

        self.operationmode = (
            ZendureRestoreSelect(self, "Operation", {0: "off", 1: "manual", 2: "smart", 3: "smart_discharging", 4: "smart_charging"}, self.update_operation),
        )
        self.manualpower = ZendureRestoreNumber(self, "manual_power", self._update_manual_energy, None, "W", "power", 10000, -10000, NumberMode.BOX)

        # updateFuseGroup callback
        def updateFuseGroup(_entity: ZendureRestoreSelect, _value: Any) -> None:
            self.update_fusegroups()

        # load devices
        device_registry = dr.async_get(self.hass)
        for dev in data["deviceList"]:
            try:
                if (deviceId := dev["deviceKey"]) is None or (prodModel := dev["productModel"]) is None:
                    continue
                _LOGGER.info(f"Adding device: {deviceId} {prodModel} => {dev}")

                init = Api.createdevice.get(prodModel.lower(), None)
                if init is None:
                    _LOGGER.info(f"Device {prodModel} is not supported!")
                    continue

                # create the device and mqtt server
                device = init(self.hass, deviceId, prodModel, dev)
                if di := device_registry.async_get_device(identifiers={(DOMAIN, device.name)}):
                    device.attr_device_info["connections"] = di.connections

                self.devices.append(device)
                Api.devices[deviceId] = device
                device.fuseGroup.onchanged = updateFuseGroup

                if Api.localServer is not None and Api.localServer != "":
                    try:
                        psw = hashlib.md5(deviceId.encode()).hexdigest().upper()[8:24]  # noqa: S324
                        provider: auth_ha.HassAuthProvider = auth_ha.async_get_provider(self.hass)
                        credentials = await provider.async_get_or_create_credentials({"username": deviceId.lower()})
                        user = await self.hass.auth.async_get_user_by_credentials(credentials)
                        if user is None:
                            user = await self.hass.auth.async_create_user(deviceId, group_ids=[GROUP_ID_USER], local_only=False)
                            await provider.async_add_auth(deviceId.lower(), psw)
                            await self.hass.auth.async_link_user(user, credentials)
                        else:
                            await provider.async_change_password(deviceId.lower(), psw)

                        _LOGGER.info(f"Created MQTT user: {deviceId} with password: {psw}")

                    except Exception as err:
                        _LOGGER.error(err)

            except Exception as e:
                _LOGGER.error(f"Unable to create device {e}!")
                _LOGGER.error(traceback.format_exc())

        _LOGGER.info(f"Loaded {len(self.devices)} devices")
        self.update_fusegroups()

        # initialize the api
        self.api.Init(self.config_entry.data, data["mqtt"])

    async def _async_update_data(self) -> None:
        _LOGGER.debug("Updating Zendure data")

        def isBleDevice(device: ZendureDevice, si: bluetooth.BluetoothServiceInfoBleak) -> bool:
            for d in si.manufacturer_data.values():
                try:
                    if d is None or len(d) <= 1:
                        continue
                    sn = d.decode("utf8")[:-1]
                    if device.snNumber.endswith(sn):
                        _LOGGER.info(f"Found Zendure Bluetooth device: {si}")
                        device.attr_device_info["connections"] = {("bluetooth", str(si.address))}
                        return True
                except Exception:  # noqa: S112
                    continue
            return False

        for device in self.devices:
            if self.attr_device_info.get("connections", None) is None:
                for si in bluetooth.async_discovered_service_info(self.hass, False):
                    if isBleDevice(device, si):
                        break

            _LOGGER.debug(f"Update device: {device.name} ({device.deviceId})")
            await device.dataRefresh(self.update_count)
        self.update_count += 1

        # Manually update the timer
        if self.hass and self.hass.loop.is_running():
            self._schedule_refresh()

    def update_p1meter(self, p1meter: str | None) -> None:
        """Update the P1 meter sensor."""
        _LOGGER.debug("Updating P1 meter to: %s", p1meter)
        if self.p1meterEvent:
            self.p1meterEvent()
        if p1meter:
            self.p1meterEvent = async_track_state_change_event(self.hass, [p1meter], self._p1_changed)
        else:
            self.p1meterEvent = None

    @callback
    async def _p1_changed(self, event: Event[EventStateChangedData]) -> None:
        try:
            # exit if there is nothing to do
            if not self.hass.is_running or not self.hass.is_running or (new_state := event.data["new_state"]) is None:
                return

            try:  # convert the state to a float
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
            for d in self.devices:
                d.powerAct = await d.power_get()
                powerActual += d.powerAct

            _LOGGER.info(f"Update p1: {p1} power: {powerActual} operation: {self.operation} delta:{p1 - avg} stddev: {stddev} fast: {isFast}")
            match self.operation:
                case SmartMode.NONE:
                    return
                case SmartMode.MATCHING:
                    if powerActual < 0:  # update when we are charging
                        self.update_power(min(0, powerActual + p1), ManagerState.CHARGING)
                    elif powerActual > 0:  # update when we are discharging
                        self.update_power(max(0, powerActual + p1), ManagerState.DISCHARGING)
                    elif self.zero_idle == datetime.max:  # check if it is the first time we are idle
                        _LOGGER.info(f"Wait {SmartMode.TIMEIDLE} sec for state change p1: {p1}")
                        self.zero_idle = time + timedelta(seconds=SmartMode.TIMEIDLE)
                    elif self.zero_idle < time:  # update when we are idle for more than SmartMode.TIMEIDLE seconds
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
        """Update the power for all devices."""
        devices: list[tuple[ZendureDevice, FuseGroup, int, bool]] = []
        totalAvail = 0
        for c in self.fuseGroup.values():
            c.powerAvail = 0
            for d in c.devices:
                # do nothing if device is offline
                d.powerAvail = 0
                if not d.online or d.electricLevel.state is None or d.socSet.state is None or d.minSoc.state is None or d.socStatus.state is None:
                    continue

                # calculate the electric level based on the socLimit and calibration state
                if d.socStatus.state == SmartMode.SOC_CALIBRATE:
                    kwh = int(d.electricLevel.state / 50 * d.kWh)  # step 0.5 kWh
                    devices.append((d, c, kwh, True))
                elif (d.socLimit.state == SmartMode.SOC_DISCHARGED and state == ManagerState.DISCHARGING) or (
                    d.socLimit.state == SmartMode.SOC_CHARGED and state == ManagerState.CHARGING
                ):
                    devices.append((d, c, 0, True))
                    continue
                else:  # calc relative level, adjust socMin
                    kwh = int((d.electricLevel.state - d.minSoc.state) / 50 * d.kWh)  # step 0.5 kWh
                    devices.append((d, c, kwh, False))

                # add device
                d.powerAvail = d.powerMin if state == ManagerState.CHARGING else d.powerMax
                c.powerAvail += d.powerAvail

            # limit the power to the fusegroup
            c.powerAvail = max(c.powerAvail, c.minpower) if state == ManagerState.CHARGING else min(c.powerAvail, c.maxpower)
            totalAvail += c.powerAvail

        def distribute_power(pwr: int, clipMin: Callable[[ZendureDevice, int], int], clipMax: Callable[[ZendureDevice, int], int]) -> None:
            # Clip the maximum device power
            maxload = min(0.85, max(1, pwr / totalAvail if totalAvail != 0 else 1))
            needed = 0
            for d, c, _kwh, rdy in devices:
                d.powerAvail = 0 if rdy else clipMin(d, c.powerAvail)
                if d.powerAvail == 0:
                    continue
                if d.online and abs(needed * maxload) < abs(pwr):
                    needed += d.powerAvail
                else:
                    d.powerAvail = 0
                c.powerAvail = clipMax(d, c.powerAvail)

            for d, _c, _kwh, _rdy in devices:
                if d.powerAvail == 0 or needed == 0:
                    d.power_set(state, 0)
                else:
                    pwr -= d.power_set(state, int(d.powerAvail * pwr / needed))
                    needed -= d.powerAvail

        if state == ManagerState.CHARGING:
            # charge emptiest devices first
            devices.sort(key=lambda x: x[2], reverse=False)
            distribute_power(max(totalAvail, power), lambda d, a: max(a, d.powerMin), lambda d, a: min(0, a - d.powerAvail))

        else:
            # discharge larger devices first
            devices.sort(key=lambda x: x[2], reverse=True)
            distribute_power(min(totalAvail, power), lambda d, a: min(a, d.powerMax), lambda d, a: min(0, a - d.powerAvail))

        # self.powerKwh = (
        #     self.kWh
        #     * (self.socSet.state - self.minSoc.state)
        #     / 1000
        #     * ((self.electricLevel.state - self.minSoc.state) * 100 / (self.socSet.state - self.minSoc.state))
        # )

        # if state == ManagerState.CHARGING:
        #     self.capacity = 0 if self.socLimit.state == SmartMode.SOC_CHARGED else self.kWh * max(0, self.socSet.value - self.electricLevel.value)
        # else:
        #     self.capacity = 0 if self.socLimit.state == SmartMode.SOC_DISCHARGED else self.kWh * max(0, self.electricLevel.value - self.minSoc.value)

        # return self.capacity if self.powerAct == 0 else self.capacity * 1.02

        # # get the total capacity of all fusegroups
        # availPower = sum(c.initFuseGroup(state) for c in self.fusegroup.values())
        # _LOGGER.info(f"Update setpoint: {power} state{state} max power: {availPower}")

        # # distribute the power over fusegroups
        # fusegroups = sorted(self.fusegroup.values(), key=lambda d: d.capacity, reverse=False)
        # for c in fusegroups:
        #     fusegroupPower = c.fusegroupPower(power, availPower)
        #     fusegroupDevices = sorted(c.devices, key=lambda d: d.capacity, reverse=False)

        #     # set the device power
        #     for d in fusegroupDevices:
        #         pwr = c.devicePower(fusegroupPower, c.powerTotal, d)
        #         _LOGGER.debug(f"Set power for device: {d.name} ({d.capacity}) to {pwr}W")
        #         pwr = d.power_set(state, pwr)
        #         availPower -= d.powerAvail
        #         c.powerTotal -= d.powerAvail
        #         fusegroupPower -= pwr
        #         power -= pwr

    def update_fusegroups(self) -> None:
        _LOGGER.info("Update fusegroups")

        self.fuseGroup.clear()
        for device in self.devices:
            try:
                match device.fuseGroup.state:
                    case "owncircuit" | "group3600":
                        fusegroup = FuseGroup(device, [], 3600, -3600)
                    case "group800":
                        fusegroup = FuseGroup(device, [], 800, -1200)
                    case "group1200":
                        fusegroup = FuseGroup(device, [], 1200, -1800)
                    case "group2400":
                        fusegroup = FuseGroup(device, [], 2400, -3600)
                    case _:
                        continue
                fusegroup.devices.append(device)
                self.fuseGroup[device.deviceId] = fusegroup
            except:  # noqa: E722
                _LOGGER.error(f"Unable to create fusegroup for device: {device.name} ({device.deviceId})")

        # Update the fusegroups and select optins for each device
        for device in self.devices:
            try:
                fusegroups: dict[Any, str] = {
                    0: "unused",
                    1: "owncircuit",
                    2: "group800",
                    3: "group1200",
                    4: "group2400",
                    5: "group3600",
                }
                for c in self.fuseGroup.values():
                    if c.device.deviceId != device.deviceId:
                        fusegroups[c.device.deviceId] = f"Part of {c.device.name} fusegroup"
                device.fuseGroup.setDict(fusegroups)
            except:  # noqa: E722
                _LOGGER.error(f"Unable to create fusegroup for device: {device.name} ({device.deviceId})")

        # Add devices to fusegroups
        for device in self.devices:
            if clstr := self.fuseGroup.get(device.fuseGroup.value):
                clstr.devices.append(device)
            device.setStatus()

    def update_operation(self, entity: ZendureSelect, _operation: Any) -> None:
        operation = int(entity.value)
        _LOGGER.info(f"Update operation: {operation} from: {self.operation}")
        self.operation = operation
        if self.operation != SmartMode.MATCHING and len(self.devices) > 0:
            for d in self.devices:
                d.power_set(ManagerState.IDLE, 0)

    def _update_manual_energy(self, _number: Any, power: float) -> None:
        try:
            if self.operation == SmartMode.MANUAL:
                self.setpoint = int(power)
                self.update_power(self.setpoint, ManagerState.DISCHARGING if power >= 0 else ManagerState.CHARGING)

        except Exception as err:
            _LOGGER.error(err)
            _LOGGER.error(traceback.format_exc())

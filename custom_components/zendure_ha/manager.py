"""Coordinator for Zendure integration."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import traceback
import random
from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta
from math import sqrt
from pathlib import Path
from typing import Any

from homeassistant.auth.const import GROUP_ID_USER
from homeassistant.auth.providers import homeassistant as auth_ha
from homeassistant.components import bluetooth, persistent_notification
from homeassistant.components.number import NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, EventStateChangedData, HomeAssistant
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.loader import async_get_integration

from .api import Api
from .const import (
    CONF_AUTO_MQTT_USER,
    CONF_P1METER,
    DOMAIN,
    DeviceState,
    ManagerMode,
    ManagerState,
    SmartMode,
)
from .device import DeviceSettings, ZendureDevice, ZendureLegacy
from .entity import EntityDevice
from .fusegroup import FuseGroup
from .number import ZendureRestoreNumber
from .select import ZendureRestoreSelect, ZendureSelect
from .sensor import ZendureSensor

SCAN_INTERVAL = timedelta(seconds=60)

_LOGGER = logging.getLogger(__name__)

type ZendureConfigEntry = ConfigEntry[ZendureManager]


class ZendureManager(DataUpdateCoordinator[None], EntityDevice):
    """Class to regular update devices."""

    devices: list[ZendureDevice] = []
    fuseGroups: list[FuseGroup] = []
    simulation: bool = False

    def __init__(self, hass: HomeAssistant, entry: ZendureConfigEntry) -> None:
        """Initialize Zendure Manager."""
        super().__init__(hass, _LOGGER, name="Zendure Manager", update_interval=SCAN_INTERVAL, config_entry=entry)
        EntityDevice.__init__(self, hass, "Zendure Manager", "Zendure Manager")
        self.api = Api()
        self.operation: ManagerMode = ManagerMode.OFF
        self.zero_next = datetime.min
        self.zero_fast = datetime.min
        self.check_reset = datetime.min
        self.p1meterEvent: Callable[[], None] | None = None
        self.p1_history: deque[int] = deque([25, -25], maxlen=8)
        self.p1_factor = 1
        self.update_count = 0

        self.charge: list[ZendureDevice] = []
        self.charge_limit = 0
        self.charge_optimal = 0
        self.charge_time = datetime.max
        self.charge_last = datetime.min
        self.charge_weight = 0

        self.discharge: list[ZendureDevice] = []
        self.discharge_bypass = 0
        self.discharge_produced = 0
        self.discharge_limit = 0
        self.discharge_optimal = 0
        self.discharge_weight = 0

        self.idle: list[ZendureDevice] = []
        self.idle_lvlmax = 0
        self.idle_lvlmin = 0
        self.produced = 0
        self.pwr_low = 0

    async def loadDevices(self) -> None:
        if self.config_entry is None or (data := await Api.Connect(self.hass, dict(self.config_entry.data), True)) is None:
            return
        if (mqtt := data.get("mqtt")) is None:
            return

        # get version number from integration
        integration = await async_get_integration(self.hass, DOMAIN)
        if integration is None:
            _LOGGER.error("Integration not found for domain: %s", DOMAIN)
            return
        self.attr_device_info["sw_version"] = integration.manifest.get("version", "unknown")

        self.operationmode = (
            ZendureRestoreSelect(self, "Operation", {0: "off", 1: "manual", 2: "smart", 3: "smart_discharging", 4: "smart_charging", 5: "store_solar"}, self.update_operation),
        )
        self.operationstate = ZendureSensor(self, "operation_state")
        self.manualpower = ZendureRestoreNumber(self, "manual_power", None, None, "W", "power", 12000, -12000, NumberMode.BOX, True)
        self.availableKwh = ZendureSensor(self, "available_kwh", None, "kWh", "energy_storage", None, 1)
        self.totalKwh = ZendureSensor(self, "total_kwh", None, "kWh", "energy_storage", "measurement", 2)
        self.power = ZendureSensor(self, "power", None, "W", "power", "measurement", 0)

        # load devices
        for dev in data["deviceList"]:
            try:
                if (deviceId := dev["deviceKey"]) is None or (prodModel := dev["productModel"]) is None:
                    continue
                _LOGGER.info("Adding device: %s %s => %s", deviceId, prodModel, dev)

                init = Api.createdevice.get(prodModel.lower().strip(), None)
                if init is None:
                    _LOGGER.info("Device %s is not supported!", prodModel)
                    continue

                # create the device and mqtt server
                device = init(self.hass, deviceId, dev.get("deviceName", prodModel), dev)
                device.discharge_start = device.discharge_limit // 10
                device.discharge_optimal = device.discharge_limit // 2.5
                Api.devices[deviceId] = device

                # Check if we should automatically manage MQTT users (opt-in)
                auto_mqtt = self.config_entry.data.get(CONF_AUTO_MQTT_USER, False)
                if auto_mqtt and Api.localServer is not None and Api.localServer != "":
                    try:
                        psw = hashlib.md5(deviceId.encode()).hexdigest().upper()[8:24]  # noqa: S324
                        provider: auth_ha.HassAuthProvider = auth_ha.async_get_provider(self.hass)
                        credentials = await provider.async_get_or_create_credentials({"username": deviceId.lower()})
                        user = await self.hass.auth.async_get_user_by_credentials(credentials)
                        if user is None:
                            # Enforce local_only=True for technical MQTT accounts
                            user = await self.hass.auth.async_create_user(deviceId, group_ids=[GROUP_ID_USER], local_only=True)
                            await provider.async_add_auth(deviceId.lower(), psw)
                            await self.hass.auth.async_link_user(user, credentials)
                        else:
                            await provider.async_change_password(deviceId.lower(), psw)

                        _LOGGER.info("Managed MQTT user for device: %s", deviceId)

                    except Exception as err:
                        _LOGGER.error("Failed to manage MQTT user for %s: %s", deviceId, err)
                elif auto_mqtt:
                    _LOGGER.debug("Skipping auto MQTT user creation for %s: Local server not configured.", deviceId)

            except Exception as e:
                _LOGGER.error("Unable to create device %s!", e)
                _LOGGER.error(traceback.format_exc())

        self.devices = list(Api.devices.values())
        _LOGGER.info("Loaded %s devices", len(self.devices))

        # initialize the api & p1 meter
        self.api.Init(self.config_entry.data, mqtt)
        await self.update_fusegroups()
        self.update_p1meter(self.config_entry.data.get(CONF_P1METER, "sensor.power_actual"))
        await asyncio.sleep(1)  # allow other tasks to run

    async def update_fusegroups(self) -> None:
        _LOGGER.info("Update fusegroups")

        # updateFuseGroup callback
        async def updateFuseGroup(_entity: ZendureRestoreSelect, _value: Any) -> None:
            await self.update_fusegroups()

        fuseGroups: dict[str, FuseGroup] = {}
        for device in self.devices:
            try:
                if device.fuseGroup.onchanged is None:
                    device.fuseGroup.onchanged = updateFuseGroup

                fg: FuseGroup | None = None
                match device.fuseGroup.state:
                    case "owncircuit" | "group3600":
                        fg = FuseGroup(device.name, 3600, -3600)
                    case "group800":
                        fg = FuseGroup(device.name, 800, -1200)
                    case "group800_2400":
                        fg = FuseGroup(device.name, 800, -2400)
                    case "group1200":
                        fg = FuseGroup(device.name, 1200, -1200)
                    case "group2000":
                        fg = FuseGroup(device.name, 2000, -2000)
                    case "group2400":
                        fg = FuseGroup(device.name, 2400, -2400)
                    case "unused":
                        # only switch off, if Manager is used
                        if self.operation != ManagerMode.OFF:
                            await device.power_off()
                        continue
                    case _:
                        _LOGGER.debug("Device %s has unsupported fuseGroup state: %s", device.name, device.fuseGroup.state)
                        continue

                if fg is not None:
                    fg.devices.append(device)
                    fuseGroups[device.deviceId] = fg
            except AttributeError as err:
                _LOGGER.error("Device %s missing fuseGroup attribute: %s", device.name, err)
            except Exception as err:
                _LOGGER.error("Unable to create fusegroup for device %s (%s): %s", device.name, device.deviceId, err, exc_info=True)

        # Update the fusegroups and select optins for each device
        for device in self.devices:
            try:
                fusegroups: dict[Any, str] = {
                    0: "unused",
                    1: "owncircuit",
                    2: "group800",
                    3: "group800_2400",
                    4: "group1200",
                    5: "group2000",
                    6: "group2400",
                    7: "group3600",
                }
                for deviceId, fg in fuseGroups.items():
                    if deviceId != device.deviceId:
                        fusegroups[deviceId] = f"Part of {fg.name} fusegroup"
                device.fuseGroup.setDict(fusegroups)
            except AttributeError as err:
                _LOGGER.error("Device %s missing fuseGroup attribute: %s", device.name, err)
            except Exception as err:
                _LOGGER.error("Unable to update fusegroup options for device %s (%s): %s", device.name, device.deviceId, err, exc_info=True)

        # Add devices to fusegroups
        for device in self.devices:
            if fg := fuseGroups.get(device.fuseGroup.value):
                device.fuseGrp = fg
                fg.devices.append(device)
            device.setStatus()

        # check if we can split fuse groups
        self.fuseGroups.clear()
        for fg in fuseGroups.values():
            if len(fg.devices) > 1 and fg.maxpower >= sum(d.discharge_limit for d in fg.devices) and fg.minpower <= sum(d.charge_limit for d in fg.devices):
                for d in fg.devices:
                    self.fuseGroups.append(FuseGroup(d.name, d.discharge_limit, d.charge_limit, [d]))
            else:
                for d in fg.devices:
                    d.fuseGrp = fg
                self.fuseGroups.append(fg)

    async def update_operation(self, entity: ZendureSelect, _operation: Any) -> None:
        operation = ManagerMode(entity.value)
        _LOGGER.info("Update operation: %s from: %s", operation, self.operation)

        self.operation = operation
        if self.p1meterEvent is not None:
            if operation != ManagerMode.OFF and (len(self.devices) == 0 or all(not d.online for d in self.devices)):
                _LOGGER.warning("No devices online, not possible to start the operation")
                persistent_notification.async_create(self.hass, "No devices online, not possible to start the operation", "Zendure", "zendure_ha")
                return

            match self.operation:
                case ManagerMode.OFF:
                    if len(self.devices) > 0:
                        for d in self.devices:
                            await d.power_off()

    async def _async_update_data(self) -> None:

        def isBleDevice(device: ZendureDevice, si: bluetooth.BluetoothServiceInfoBleak) -> bool:
            for d in si.manufacturer_data.values():
                try:
                    if d is None or len(d) <= 1:
                        continue
                    sn = d.decode("utf8")[:-1]
                    if device.snNumber.endswith(sn):
                        _LOGGER.info("Found Zendure Bluetooth device: %s", si)
                        device.attr_device_info["connections"] = {("bluetooth", str(si.address))}
                        return True
                except Exception:  # noqa: S112
                    continue
            return False

        time = datetime.now()
        kwh = 0
        for device in self.devices:
            kwh += device.kWh
            if isinstance(device, ZendureLegacy) and device.bleMac is None:
                for si in bluetooth.async_discovered_service_info(self.hass, False):
                    if isBleDevice(device, si):
                        break

            _LOGGER.debug("Update device: %s (%s)", device.name, device.deviceId)
            await device.dataRefresh(self.update_count)
            if device.hemsState.is_on and (time - device.hemsStateUpdated).total_seconds() > SmartMode.HEMSOFF_TIMEOUT:
                device.hemsState.update_value(0)
            device.setStatus()
        self.update_count += 1
        self.totalKwh.update_value(kwh)

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
            if (entity := self.hass.states.get(p1meter)) is not None and entity.attributes.get("unit_of_measurement", "W") in ("kW", "kilowatt", "kilowatts"):
                self.p1_factor = 1000
        else:
            self.p1meterEvent = None

    def writeSimulation(self, time: datetime, p1: int) -> None:
        if Path("simulation.csv").exists() is False:
            with Path("simulation.csv").open("w") as f:
                f.write(
                    "Time;P1;Operation;Battery;Solar;Home;SetPoint;--;"
                    + ";".join(
                        [
                            f"bat;Prod;Home;{
                                json.dumps(
                                    DeviceSettings(
                                        d.name,
                                        d.fuseGrp.name,
                                        d.charge_limit,
                                        d.discharge_limit,
                                        d.maxSolar,
                                        d.kWh,
                                        d.socSet.asNumber,
                                        d.minSoc.asNumber,
                                    ),
                                    default=vars,
                                )
                            }"
                            for d in self.devices
                        ]
                    )
                    + "\n"
                )

        with Path("simulation.csv").open("a") as f:
            data = ""
            tbattery = 0
            tsolar = 0
            thome = 0

            for d in self.devices:
                tbattery += (pwr_battery := d.batteryOutput.asInt - d.batteryInput.asInt)
                tsolar += (pwr_solar := d.solarInput.asInt)
                thome += (pwr_home := d.homeOutput.asInt - d.homeInput.asInt)
                data += f";{pwr_battery};{pwr_solar};{pwr_home};{d.electricLevel.asInt}"

            f.write(f"{time};{p1};{self.operation};{tbattery};{tsolar};{thome};{self.manualpower.asNumber};" + data + "\n")

    async def _p1_changed(self, event: Event[EventStateChangedData]) -> None:
        # exit if there is nothing to do
        if not self.hass.is_running or not self.hass.is_running or (new_state := event.data["new_state"]) is None:
            return

        try:  # convert the state to a float
            p1 = int(self.p1_factor * float(new_state.state))
        except ValueError:
            return

        # Get time & update simulation
        time = datetime.now()
        if ZendureManager.simulation:
            self.writeSimulation(time, p1)

        # Check for fast delay
        if time < self.zero_fast:
            self.p1_history.append(p1)
            return

        # calculate the standard deviation
        if len(self.p1_history) > 1:
            avg = int(sum(self.p1_history) / len(self.p1_history))
            stddev = SmartMode.P1_STDDEV_FACTOR * max(SmartMode.P1_STDDEV_MIN, sqrt(sum([pow(i - avg, 2) for i in self.p1_history]) / len(self.p1_history)))
            if isFast := abs(p1 - avg) > stddev or abs(p1 - self.p1_history[0]) > stddev:
                self.p1_history.clear()
        else:
            isFast = False
        self.p1_history.append(p1)

        # check minimal time between updates
        if isFast or time > self.zero_next:
            try:
                # prevent updates during power distribution changes
                self.zero_fast = datetime.max
                self.charge.clear()
                self.charge_limit = 0
                self.charge_optimal = 0
                self.charge_weight = 0
                self.discharge.clear()
                self.discharge_bypass = 0
                self.discharge_limit = 0
                self.discharge_optimal = 0
                self.discharge_produced = 0
                self.discharge_weight = 0
                self.idle.clear()
                self.idle_lvlmax = 0
                self.idle_lvlmin = 100
                self.produced = 0
                self.discharge_lvlmax = 100
                self.charge_lvlmax = 0

                for fg in self.fuseGroups:
                    fg.initCPower = True
                    fg.initDPower = True

                await self.powerChanged(p1, isFast, time)
            except Exception as err:
                _LOGGER.error(err)
                _LOGGER.error(traceback.format_exc())

            time = datetime.now()
            self.zero_next = time + timedelta(seconds=SmartMode.TIMEZERO)
            self.zero_fast = time + timedelta(seconds=SmartMode.TIMEFAST)

    async def powerChanged(self, p1: int, isFast: bool, time: datetime) -> None:
        """Return the distribution setpoint."""
        availableKwh = 0
        setpoint = p1
        power = 0

        _LOGGER.info("Distribution setpoint calculation for %s devices with setpoint %sW", len(self.devices), setpoint)
        for d in sorted(self.devices, key=lambda d: (d.solarInput.asInt, d.pwr_offgrid), reverse=True):
            if await d.power_get():
                # get power production
                d.pwr_produced = min(0, d.batteryOutput.asInt + d.homeInput.asInt - d.batteryInput.asInt - d.homeOutput.asInt)
                self.produced -= d.pwr_produced
                # SF 2400 AC show higher offGridpower as sum of all inputpower. SF 800 pro and newer devices have offGrid and PV-input sockets 
                _pwr_offgrid = min(max(0,d.pwr_offgrid), d.batteryOutput.asInt + d.homeInput.asInt + d.solarInput.asInt)
                # charging from the view of the homegrid is power from the homegrid and some power into the batterie
                if d.homeInput.asInt > 0 and d.batteryInput.asInt > 0:
                    setpoint -= d.homeInput.asInt + _pwr_offgrid
                    _LOGGER.info("homeInput:%s batteryInput:%s, setpoint:%sW Charge", d.homeInput.asInt, d.batteryInput.asInt, setpoint)
                    self.charge.append(d)
                    self.charge_limit += d.fuseGrp.charge_limit(d)
                    self.charge_optimal += d.charge_optimal
                    self.charge_weight += d.pwr_max * (100 - d.electricLevel.asInt) * max(d.kWh, 1.0)
                    self.charge_lvlmax = max(self.charge_lvlmax, d.electricLevel.asInt)
                # discharge from the view of the homegrid is power to the homegrid or offGrid socket and some power from the batterie
                elif (d.homeOutput.asInt > 0 or _pwr_offgrid > SmartMode.POWER_START):
                    # if there is a offGrid power. device needs to be charged, but it can use for that a max power of charge_limt 
                    setpoint += d.homeOutput.asInt + min(abs(d.charge_limit),_pwr_offgrid - (d.homeInput.asInt if _pwr_offgrid > 0 else 0))
                    _LOGGER.info("homeInput:%s, homeOutput:%s, batteryOutput:%s, setpoint:%sW Discharge", d.homeInput.asInt, d.homeOutput.asInt, d.batteryOutput.asInt, setpoint)
                    self.discharge.append(d)
                    self.discharge_bypass -= d.pwr_produced if d.state == DeviceState.SOCFULL else 0
                    self.discharge_limit += d.fuseGrp.discharge_limit(d)
                    self.discharge_optimal += d.discharge_optimal
                    self.discharge_produced -= d.pwr_produced
                    self.discharge_weight += d.pwr_max * d.electricLevel.asInt * max(d.kWh, 1.0)
                    self.discharge_lvlmax = min(self.discharge_lvlmax, d.electricLevel.asInt if d.state != DeviceState.SOCFULL else 100)

                # special case: gridOff device with SoC empty get the power from the grid. But if homeOutput is still > 0, this information was
                # not yet pushed in the MQTT stream. So add the offGrid Power to the setpoint and stop discharging
                elif (home := d.homeOutput.asInt) > 0 and d.state == DeviceState.SOCEMPTY and _pwr_offgrid > 0:
                    setpoint += _pwr_offgrid
                    await d.power_discharge(0)

                else:
                    self.idle.append(d)
                    setpoint += _pwr_offgrid
                    _LOGGER.info("setpoint:%sW Idle", setpoint)
                    # don't care on SoC for discharge, if there are other devices with production
                    self.idle_lvlmax = max(self.idle_lvlmax, 0 if ((d.pwr_produced == 0 and self.produced > 0) or d.fuseGrp.maxpower == 0) else d.electricLevel.asInt)
                    self.idle_lvlmin = min(self.idle_lvlmin, d.electricLevel.asInt if d.state != DeviceState.SOCFULL else 100)

                availableKwh += d.actualKwh
                setpoint -= _pwr_offgrid if setpoint < 0 else 0
                home = d.homeOutput.asInt - d.homeInput.asInt
                power += home + d.pwr_produced + _pwr_offgrid
                _LOGGER.info("Device: %s\t home: %sW\tprod: %sW\t SoC: %s\toffGridPower: %s\tstate: %s\tbatOut: %s\thomeIn: %s \tbatIn: %s \thomeOut: %s \tpwr_max: %s \tsetpoint: %s", d.name, home, d.pwr_produced, d.electricLevel.asInt, d.pwr_offgrid, d.state.name, d.batteryOutput.asInt, d.homeInput.asInt, d.batteryInput.asInt, d.homeOutput.asInt, d.pwr_max, setpoint)

        # Update the power entities
        self.power.update_value(power)
        self.availableKwh.update_value(availableKwh)
        if self.discharge_bypass > setpoint:
            setpoint -= self.discharge_bypass

        # Update power distribution.
        _LOGGER.info("P1 ======> p1:%s isFast:%s, setpoint:%sW stored:%sW", p1, isFast, setpoint, self.produced)
        match self.operation:
            case ManagerMode.MATCHING:
                if setpoint < 0:
                    await self.power_charge(setpoint, time)
                else:
                    await self.power_discharge(setpoint)

            case ManagerMode.MATCHING_DISCHARGE:
                # Only discharge, do nothing if setpoint is negative
                await self.power_discharge(max(0, setpoint))

            case ManagerMode.MATCHING_CHARGE | ManagerMode.STORE_SOLAR:
                # Allow discharge of produced power in MATCHING_CHARGE-Mode, otherwise only charge
                # d.pwr_produced is negative, but self.produced is positive
                if setpoint > 0 and self.produced > SmartMode.POWER_START and self.operation == ManagerMode.MATCHING_CHARGE:
                    await self.power_discharge(min(self.produced, setpoint))
                # send device into idle-mode
                elif setpoint > 0:
                    await self.power_discharge(0)
                else:
                    # Only charge, do nothing if setpoint is positive
                    await self.power_charge(min(0, setpoint), time)

            case ManagerMode.MANUAL:
                # Manual power into or from home
                if (setpoint := int(self.manualpower.asNumber)) > 0:
                    await self.power_discharge(setpoint)
                else:
                    await self.power_charge(setpoint, time)

            case ManagerMode.OFF:
                self.operationstate.update_value(ManagerState.OFF.value)

    async def power_charge(self, setpoint: int, time: datetime) -> None:
        """Charge devices."""
        _LOGGER.info("Charge => setpoint %sW", setpoint)

        # stop discharging devices
        for d in self.discharge:
            # avoid stopping fully charged devices to discharge
            # if gridOff device is discharging, use solarpower to cover the offGrid need
            # the next round it will be considered as charging
            if max(0,d.pwr_offgrid) == 0:
                if d.byPass.asInt > 0:
                    continue            
                await d.power_discharge(0)
            else:
                setpoint -= await d.power_charge(max(setpoint, -max(0,d.pwr_offgrid)-SmartMode.POWER_START))

        # prevent hysteria
        if self.charge_time > time:
            if self.charge_time == datetime.max:
                self.charge_time = time + timedelta(seconds=2 if (time - self.charge_last).total_seconds() > 300 else 60)
                self.charge_last = self.charge_time
                self.pwr_low = 0
            setpoint = 0
        self.operationstate.update_value(ManagerState.CHARGE.value if setpoint < 0 else ManagerState.IDLE.value)

        # distribute charging devices
        # take offGrid power into account on deciding to start more devices
        # use discharge_optimal from next device to start on deciding to start more devices (necessary for devices with different charge-limits)
        nextChargeOptimal = 0
        if len(self.charge) > 0 and len(self.idle) > 0:
            self.idle.sort(key=lambda d: d.electricLevel.asInt, reverse=False)
            fd = self.idle[0] # next device to start
            # if next device has larger charge-limit use self_charge_optimal
            nextChargeOptimal = min(self.charge_optimal, fd.charge_optimal * (1 if fd.state != DeviceState.SOCFULL else 4))
        dev_start = min(0, setpoint - (self.charge_optimal + nextChargeOptimal) + (sum(max(0,d.pwr_offgrid) for d in self.devices) if len(self.charge) > 0 else 0)) if setpoint < -SmartMode.POWER_START else 0
        # if gridOff device will be added, reduce power for the other devices
        if (dev_start < 0 and len(self.idle) > 0):
            sum_idle_pwr = sum(max(0,di.pwr_offgrid if di.state != DeviceState.SOCFULL else 0) for di in self.idle)
            setpoint -= dev_start
        else:
            sum_idle_pwr = 0
           
        limit = self.charge_limit
#        setpoint = max(limit, setpoint)
        for i, d in enumerate(sorted(self.charge, key=lambda d: (max(50,d.limitInput.asNumber+d.batInOut.asInt), max(100,d.pwr_offgrid), 100-d.electricLevel.asInt), reverse=True)):
            pwr = int(setpoint * ((d.pwr_max * (100 - d.electricLevel.asInt)* max(d.kWh, 1.0)) / self.charge_weight) if self.charge_weight != 0 else 0)
            self.charge_weight -= d.pwr_max * (100 - d.electricLevel.asInt) * max(d.kWh, 1.0)

            # adjust the limit, make sure we have 'enough' power to charge
            limit -= d.pwr_max
            pwr = max(pwr, setpoint, d.pwr_max)
            if limit > setpoint - pwr:
                pwr = max(setpoint - limit, setpoint, d.pwr_max)

            # make sure we have devices in optimal working range
            if len(self.charge) > 1 and i == 0:
                self.pwr_low = 0 if (delta := d.charge_start * 1.5 - pwr) >= 0 else self.pwr_low + int(-delta)
                pwr = 0 if self.pwr_low < d.charge_optimal else pwr

            setpoint -= await d.power_charge(pwr)
            dev_start += -1 if pwr != 0 and d.electricLevel.asInt > self.idle_lvlmin + 3 else 0
            if len(self.charge) > 1 and d.state != DeviceState.SOCFULL and ((setpoint / (len(self.charge)-i)) > d.charge_optimal) and dev_start >= 0 and d.charge_limit <= setpoint:
                _LOGGER.info("pwr: %s, setpoint: %s, charge_optimal: %s", pwr, setpoint, d.charge_optimal)
                # if remaining setpoint < discharge_optimal, use remaining setpoint, this will stop following devices
                pwr = setpoint

            _LOGGER.info("power: %s, pwr_max: %s, sum_idle_pwr: %s, charge_limit: %s, charge_weight: %s, charge_lvlmax: %s, i: %s, len(self.discharge) %s", pwr, d.pwr_max, sum_idle_pwr, d.charge_limit, self.charge_weight, self.charge_lvlmax, i, len(self.discharge))
            if (len(self.discharge) == 0) and (i < len(self.charge)-1) and (d.electricLevel.asInt < self.charge_lvlmax):
                pwr = max(d.charge_limit, setpoint)
                if dev_start == 0: 
                    sum_idle_pwr = 0
            # SF 2400 feed all negative offGridPower into homegrid, if power set to 0
            # SF 2400 let us control only battery out vs. homeOutput on other devices
            setpoint -= await d.power_charge(min(0, max(d.pwr_max,pwr + (sum_idle_pwr if dev_start < 0 else 0) - max(0,d.pwr_offgrid))))
            _LOGGER.info("remaining setpoint: %s", setpoint)

        _LOGGER.info("dev_start: %s, idle: %s, charge: %s, produced: %s, setpoint: %s", dev_start, len(self.idle), len(self.charge), self.produced, setpoint)
        # start idle device if needed
        if (dev_start < 0 and len(self.idle) > 0) or (len(self.charge)==0 and self.produced == 0 and setpoint <= -SmartMode.POWER_START) or (setpoint <= -SmartMode.POWER_START and len(self.idle) > 0):
            self.idle.sort(key=lambda d: d.electricLevel.asInt, reverse=False)
            for d in self.idle:
                # offGrid device need to be started with at least their offgrid power, otherwise they will not be recognized as charging
                # but should not be started with more than pwr_offgrid if they are full
                # if a offGrid device need to be started, the output power is set to 0 and it take all offGrid power from grid
                # also, do not start any devices that are not AC chargeable.
                _LOGGER.info("charge limit %s => %s", d.name, d.charge_limit)
                if d.charge_limit < 0:
                    startpower = -(SmartMode.POWER_START  + random.randint(0, 10)) if dev_start > -SmartMode.POWER_START else max(d.charge_limit, max(dev_start, d.charge_optimal * 2 if dev_start - d.charge_optimal * 2 < -SmartMode.POWER_START else dev_start)) 
                    setpoint = await d.power_charge(startpower - max(0,d.pwr_offgrid) if d.state != DeviceState.SOCFULL else -max(0,d.pwr_offgrid) if d.batteryOutput.asInt > -dev_start else 0)
                    if (dev_start := dev_start - setpoint) >= 0:
                        break
            self.pwr_low: int = 0

    async def power_discharge(self, setpoint: int) -> None:
        """Discharge devices."""
        _LOGGER.info("Discharge => setpoint %sW", setpoint)
        self.operationstate.update_value(ManagerState.DISCHARGE.value if setpoint > 0 and self.discharge else ManagerState.IDLE.value)

        # reset hysteria time
        if self.charge_time != datetime.max:
            self.charge_time = datetime.max
            self.pwr_low = 0

        # stop charging devices
        for d in self.charge:
            # SF 2400 may show more gridInputPower than offGridPower and will be recognized as charging, 
            await d.power_discharge(0)
            
        # distribute discharging devices, use produced power first, before adding another device
        dev_start = max(0, setpoint - self.discharge_optimal * 2 - self.discharge_produced) if setpoint > SmartMode.POWER_START else 0
        # if gridOff device will be added, reduce power for the other devices
        if (dev_start > 0 and len(self.idle) > 0):
            sum_idle_pwr = sum(max(0, di.pwr_offgrid) if di.state != DeviceState.SOCEMPTY else 0 for di in self.idle)
            sum_fgrp_pwr = sum(max(0, di.fuseGrp.maxpower) if di.state != DeviceState.SOCEMPTY else 0 for di in self.idle)
            if sum_fgrp_pwr > 0:
                setpoint -= dev_start
        else:
            sum_idle_pwr = 0        
        solaronly = self.produced >= setpoint
        limit = self.produced if solaronly else self.discharge_limit
        setpoint = min(limit, setpoint)
        # first discharge devices with highest solar input and highest SoC
        _LOGGER.info("dev_start: %s, idle: %s, charge: %s, discharge: %s, produced: %s, setpoint: %s, limit: %s", dev_start, len(self.idle), len(self.charge), len(self.discharge), self.produced, setpoint, limit)
        for i, d in enumerate(sorted(self.discharge, key=lambda d: (d.solarInput.asInt - min(0,d.pwr_offgrid), -max(100,d.pwr_offgrid), d.electricLevel.asInt), reverse=True)):
            # calculate power to discharge
            if (pwr := (int(setpoint * (d.pwr_max * d.electricLevel.asInt * max(d.kWh, 1.0)) / self.discharge_weight)) if self.discharge_weight > 0 else 0) < -d.pwr_produced and d.state == DeviceState.SOCFULL:
                pwr = -d.pwr_produced
            self.discharge_weight -= d.pwr_max * d.electricLevel.asInt * max(d.kWh, 1.0)

            # adjust the limit, make sure we have 'enough' power to discharge
            limit -= -d.pwr_produced if solaronly else d.pwr_max
            if limit < setpoint - pwr:
                pwr = max(setpoint - limit, 0 if d.state != DeviceState.SOCFULL else -d.pwr_produced)
            pwr = min(pwr, setpoint, d.pwr_max)
            _LOGGER.info("power: %s, discharge_limit: %s, discharge_weight: %s, discharge_lvlmax: %s, i: %s, len(self.charge)+len(self.idle) %s", pwr, d.discharge_limit, self.discharge_weight, self.discharge_lvlmax, i, len(self.charge)+len(self.idle))
            if (len(self.charge) == 0) and (len(self.idle) == 0) and (i < len(self.discharge)-1) and (d.electricLevel.asInt > self.discharge_lvlmax):
                pwr = min(d.discharge_limit, setpoint)

            # check if we need to start a devices with higher SoC
            dev_start += 1 if (pwr != 0 and d.electricLevel.asInt + 3 < self.idle_lvlmax) else 0
            # make sure we have devices in optimal working range
            if len(self.discharge) > 1 and ((setpoint / (len(self.discharge)-1)) <= d.discharge_optimal * 1.5) and dev_start == 0:
                # if remaining setpoint < discharge_optimal, use remaining setpoint, this will stop following devices
                pwr = setpoint

            if solaronly:
                pwr = min(pwr, -d.pwr_produced)

            _LOGGER.info("power: %s, setpoint: %s", pwr, setpoint)

            setpoint -= await d.power_discharge(-max(0,d.pwr_offgrid) + pwr)
            setpoint = max(0, setpoint)


        _LOGGER.info("dev_start: %s, idle: %s, charge: %s, discharge: %s, idle_lvlmax: %s", dev_start, len(self.idle), len(self.charge), len(self.discharge), self.idle_lvlmax)
        # start idle device if needed (also if setpoint wasn't reached due to solaronly constraints)
        if (dev_start > 0 or setpoint > SmartMode.POWER_START * 2) and len(self.idle) > 0:
            # start devices with highest solar input and highest SoC first
            self.idle.sort(key=lambda d:(d.solarInput.asInt - min(0,d.pwr_offgrid), max(0,d.pwr_offgrid), d.electricLevel.asInt), reverse=True)
            for d in self.idle:             
                # switch OFF device, if empty
                _LOGGER.info("fuseGrp maxpower %s => %s", d.name, d.fuseGrp.maxpower)
                if d.state != DeviceState.SOCEMPTY and d.fuseGrp.maxpower > 0:
                    startpower = (SmartMode.POWER_START  + random.randint(0, 10)) if dev_start < SmartMode.POWER_START else min(d.discharge_limit, min(dev_start, d.discharge_optimal * 2 if dev_start - d.discharge_optimal * 2 > SmartMode.POWER_START else dev_start)) 
                    dev_start -= await d.power_discharge(-startpower if max(0,d.pwr_offgrid) > 0 and startpower > SmartMode.POWER_START else startpower)                   
                    _LOGGER.info("remaining dev_start: %s, startpower: %s", dev_start, startpower)
                    if dev_start <= SmartMode.POWER_START:
                        break
                else:
                    await d.power_discharge(0)
            self.pwr_low: int = 0

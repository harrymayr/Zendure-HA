"""Base class for Zendure entities."""

from __future__ import annotations

import logging

from .const import SmartMode
from .device import ZendureDevice
from .distribution import PowerDistribution, PowerState

_LOGGER = logging.getLogger(__name__)


class FuseGroup(PowerDistribution):
    """Zendure Fuse Group."""

    def __init__(self, name: str, maxpower: int, minpower: int, maxDischarge: int, maxCharge: int) -> None:
        """Initialize the fuse group."""
        self.name: str = name
        self.maxpower = maxpower
        self.minpower = minpower

        self.maxCharge = maxCharge
        self.maxDischarge = maxDischarge
        self.startCharge = minpower // 8
        self.startDischarge = maxpower // 8
        self.devices: list[ZendureDevice] = []

    def power_actual(self, isCharging: bool) -> float:
        """Return the kWh for this fuse group."""
        self.state = PowerState.NOPOWER
        self.actualKwh = 0.0
        self.actualWatt = 0
        for d in self.devices:
            d.actualKwh = 0.0
            if d.online:
                if isCharging and (d.socLimit.asInt == SmartMode.SOCFULL or d.electricLevel.asInt >= d.socSet.asNumber):
                    d.state = PowerState.NOPOWER
                    continue
                if not isCharging and (d.socLimit.asInt == SmartMode.SOCEMPTY or d.electricLevel.asInt <= d.minSoc.asNumber):
                    d.state = PowerState.NOPOWER
                    continue

                d.actualKwh = d.availableKwh.asNumber
                d.actualWatt = d.gridInputPower.asInt - d.packInputPower.asInt
                d.state = PowerState.INACTIVE

                self.state = PowerState.INACTIVE
                self.actualKwh += d.actualKwh
                self.actualWatt += d.actualWatt
            else:
                d.state = PowerState.NOPOWER

        return self.actualKwh

    def power_charge(self, power: int) -> int:
        """Set charge power."""
        match self.state:
            case PowerState.ACTIVE:
                power -= PowerDistribution.charge(self.devices, max(power, self.minpower))
            case PowerState.STARTING:
                for i in sorted(self.devices, key=lambda i: i.power_actual(False)):
                    i.power_charge(power)
                    power = 0
            case PowerState.INACTIVE:
                PowerDistribution.setzero(self.devices)
        return power

    def power_discharge(self, power: int) -> int:
        """Set discharge power."""
        match self.state:
            case PowerState.ACTIVE:
                power -= PowerDistribution.discharge(self.devices, min(power, self.maxpower))
            case PowerState.STARTING:
                for i in sorted(self.devices, key=lambda i: i.power_actual(False), reverse=True):
                    i.power_discharge(power)
                    power = 0
            case PowerState.INACTIVE:
                PowerDistribution.setzero(self.devices)
        return power

"""Fusegroup for Zendure devices."""

from __future__ import annotations

import logging

from .const import DeviceState
from .device import ZendureDevice

_LOGGER = logging.getLogger(__name__)


class FuseGroup:
    """Zendure Fuse Group."""

    def __init__(self, name: str, maxpower: int, minpower: int, devices: list[ZendureDevice] | None = None) -> None:
        """Initialize the fuse group."""
        self.name: str = name
        self.maxpower = maxpower
        self.minpower = minpower
        self.pwr_update = 0
        self.devices: list[ZendureDevice] = devices if devices is not None else []
        for d in self.devices:
            d.fuseGrp = self

    def chargePower(self, device: ZendureDevice, pwr_update: int) -> int:
        """Return the charge power for a device."""
        if len(self.devices) == 1:
            return max(self.minpower, device.limitCharge)

        # return maxPower if it is already calculated
        if pwr_update != self.pwr_update:
            self.pwr_update = pwr_update
            total = 0
            for d in self.devices:
                if d.homeOutput.asInt > 0 or d.batteryInput.asInt > 0:
                    d.maxPower = d.limitCharge + max(d.maxSolar - d.limitCharge, d.pwr_produced)
                    total += d.maxPower * (100 - d.electricLevel.asInt) / 100

            for d in self.devices:
                d.maxPower = int(d.maxPower * d.maxPower * (100 - d.electricLevel.asInt) / 100 / total)
        return device.maxPower

    def dischargePower(self, device: ZendureDevice, pwr_update: int) -> int:
        """Return the discharge power for a device."""
        if len(self.devices) == 1:
            return max(self.maxpower, device.limitDischarge)

        # return maxPower if it is already calculated
        if pwr_update != self.pwr_update:
            self.pwr_update = pwr_update
            total = 0
            for d in self.devices:
                if d.homeOutput.asInt > 0:
                    d.maxPower = d.limitDischarge
                    total += d.maxPower * d.electricLevel.asInt / 100

            for d in self.devices:
                d.maxPower = int(d.maxPower * d.maxPower * d.electricLevel.asInt / 100 / total)
        return device.maxPower

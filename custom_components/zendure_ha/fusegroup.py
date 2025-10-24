"""Fusegroup for Zendure devices."""

from __future__ import annotations

import logging

from custom_components.zendure_ha.const import DeviceState

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
            device.maxPower = max(self.minpower, device.limitCharge)
        elif pwr_update != self.pwr_update:
            # calculate maxPower for all devices in the group
            self.pwr_update = pwr_update
            total = 0
            for d in self.devices:
                if (d.homeOutput.asInt > 0 or d.batteryInput.asInt > 0) and d.state != DeviceState.SOCFULL:
                    d.maxPower = d.limitCharge + max(d.maxSolar - d.limitCharge, d.pwr_produced)
                    total += d.maxPower * (100 - d.electricLevel.asInt)

            for d in self.devices:
                if (d.homeOutput.asInt > 0 or d.batteryInput.asInt > 0) and d.state != DeviceState.SOCFULL:
                    d.maxPower = int(self.minpower * d.maxPower * (100 - d.electricLevel.asInt) / total)
                else:
                    d.maxPower = 0
        return device.maxPower

    def dischargePower(self, device: ZendureDevice, pwr_update: int) -> int:
        """Return the discharge power for a device."""
        if len(self.devices) == 1:
            device.maxPower = min(self.maxpower, device.limitDischarge)
        elif pwr_update != self.pwr_update:
            # calculate maxPower for all devices in the group
            self.pwr_update = pwr_update
            total = 0
            for d in self.devices:
                if d.homeOutput.asInt > 0:
                    d.maxPower = d.limitDischarge
                    total += d.maxPower * d.electricLevel.asInt

            for d in self.devices:
                if d.homeOutput.asInt > 0:
                    d.maxPower = int(self.maxpower * d.maxPower * d.electricLevel.asInt / total)
                else:
                    d.maxPower = 0
        return device.maxPower

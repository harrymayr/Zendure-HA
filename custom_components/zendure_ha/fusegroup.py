"""Fusegroup for Zendure devices."""

from __future__ import annotations

import logging

from .device import ZendureDevice

_LOGGER = logging.getLogger(__name__)


class FuseGroup:
    """Zendure Fuse Group."""

    def __init__(self, name: str, maxpower: int, minpower: int, devices: list[ZendureDevice] | None = None) -> None:
        """Initialize the fuse group."""
        self.name: str = name
        self.maxpower = maxpower
        self.minpower = minpower
        self.initPower = True
        self.devices: list[ZendureDevice] = devices if devices is not None else []
        for d in self.devices:
            d.fuseGrp = self

    def charge_limit(self, d: ZendureDevice) -> int:
        """Return the limit discharge power for a device."""
        if self.initPower:
            self.initPower = False
            if len(self.devices) == 1:
                d.pwr_max = max(self.minpower, d.charge_limit)
            else:
                used = 0
                weight = 0
                for fd in self.devices:
                    if fd.homeInput.asInt > 0:
                        used += fd.charge_start
                        weight += (100 - fd.electricLevel.asInt) * fd.actualKwh
                used = min(0, self.minpower - used)
                for fd in self.devices:
                    if fd.homeInput.asInt > 0:
                        fd.pwr_max = fd.charge_start + int(used * ((100 - fd.electricLevel.asInt) * fd.actualKwh) / weight) if weight > 0 else fd.charge_start

        return d.pwr_max

    def discharge_limit(self, d: ZendureDevice) -> int:
        """Return the limit discharge power for a device."""
        if self.initPower:
            self.initPower = False
            if len(self.devices) == 1:
                d.pwr_max = min(self.maxpower, d.discharge_limit)
            else:
                used = 0
                weight = 0
                for fd in self.devices:
                    if fd.homeOutput.asInt > 0 and fd.state != DeviceState.SOCEMPTY:
                        used += fd.discharge_start
                        weight += fd.electricLevel.asInt * fd.actualKwh
                used = max(0, self.maxpower - used)
                for fd in self.devices:
                    if fd.homeOutput.asInt > 0 and fd.state != DeviceState.SOCEMPTY:
                        fd.pwr_max = fd.discharge_start + int(used * (fd.electricLevel.asInt * fd.actualKwh) / weight) if weight > 0 else fd.discharge_start

        return d.pwr_max

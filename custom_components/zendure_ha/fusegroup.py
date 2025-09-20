"""Base class for Zendure entities."""

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
        self.actualPower = 0
        self.devices: list[ZendureDevice] = devices if devices is not None else []
        for d in self.devices:
            d.fuseGrp = self

    def maxCharge(self) -> int:
        """Return the maximum charge for a device."""
        if len(self.devices) == 1:
            return max(self.devices[0].limitCharge, self.minpower)

        count = 0
        total = 0
        for d in self.devices:
            if d.state not in {DeviceState.OFFLINE, DeviceState.SOCFULL}:
                total += d.limitCharge
                count += 1
        return max(self.minpower, total // count if count > 0 else 0)

    def maxDischarge(self) -> int:
        """Return the maximum discharge for a device."""
        if len(self.devices) == 1:
            return max(self.devices[0].limitDischarge, self.maxpower)

        count = 0
        total = 0
        for d in self.devices:
            if d.state not in {DeviceState.OFFLINE, DeviceState.SOCEMPTY}:
                total += d.limitDischarge
                count += 1
        return max(self.minpower, total // count if count > 0 else 0)

    def distribute(self, _device: ZendureDevice, isCharging: bool) -> int:
        if len(self.devices) == 1:
            d = self.devices[0]
            d.pwr_max = max(d.limitCharge, self.minpower) if isCharging else min(d.limitDischarge, self.maxpower)
            return d.pwr_max

        """Distribute available power over devices."""
        active = []
        kWh = 0.0
        maxWatt = 0
        for d in self.devices:
            if d.state == DeviceState.ACTIVE:
                active.append(d)
                kWh += d.actualKwh
                maxWatt += d.limitCharge if isCharging else d.limitDischarge

        if len(active) == 0 or kWh == 0:
            return d.pwr_max

        if isCharging:
            maxWatt = max(maxWatt, self.minpower)
            for d in sorted(active, key=lambda d: d.actualKwh, reverse=False):
                d.maxCharge = max(d.limitCharge, int(maxWatt * d.actualKwh / kWh))
                maxWatt -= d.maxCharge
                kWh -= d.actualKwh
        else:
            maxWatt = min(maxWatt, self.maxpower)
            for d in sorted(active, key=lambda d: d.actualKwh, reverse=True):
                d.maxDischarge = min(d.limitDischarge, int(maxWatt * d.actualKwh / kWh))
                maxWatt -= d.maxDischarge
                kWh -= d.actualKwh
        return d.pwr_max

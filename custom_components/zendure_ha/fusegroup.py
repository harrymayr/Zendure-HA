"""Base class for Zendure entities."""

from __future__ import annotations

import logging

from .const import SmartMode, DeviceState
from .device import ZendureDevice

_LOGGER = logging.getLogger(__name__)


class FuseGroup:
    """Zendure Fuse Group."""

    def __init__(self, name: str, maxpower: int, minpower: int, maxDischarge: int, maxCharge: int) -> None:
        """Initialize the fuse group."""
        self.name: str = name
        self.maxpower = maxpower
        self.minpower = minpower
        self.devices: list[ZendureDevice] = []

    def distribute(self, isCharging: bool) -> None:
        if len(self.devices) == 1:
            d = self.devices[0]
            d.maxCharge = max(d.limitCharge, self.minpower)
            d.maxDischarge = min(d.limitDischarge, self.maxpower)
            return

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
            return

        if isCharging:
            maxWatt = max(maxWatt, self.minpower)
            for d in sorted(active, key=lambda d: d.actualKwh, reverse=False):
                d.maxCharge = max(d.limitCharge, int(d.limitCharge * d.actualKwh / kWh))
                maxWatt -= d.maxCharge
                kWh -= d.actualKwh
        else:
            maxWatt = min(maxWatt, self.maxpower)
            for d in sorted(active, key=lambda d: d.actualKwh, reverse=True):
                d.maxDischarge = max(d.limitDischarge, int(d.limitDischarge * d.actualKwh / kWh))
                maxWatt -= d.maxDischarge
                kWh -= d.actualKwh

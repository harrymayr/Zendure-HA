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
            d.fuseCharge = self.fuseCharge
            d.fuseDischarge = self.fuseDischarge

    def fuseCharge(self, device: ZendureDevice) -> bool:
        # power needed to start charging
        power = device.startCharge + device.minCharge
        isFirst = len(self.devices) == 1 or not any(d.state == DeviceState.ACTIVE for d in self.devices)
        if isFirst:
            # limit the power to minpower for all devices
            device.maxCharge = max(device.limitCharge, self.minpower)
            self.actualPower = power

            # adjust for solar power, will still deliver the same amount of power
            device.maxCharge = max(device.maxCharge, device.maxSolar - device.actualSolar)
            return True

        # there needs to be at least power to start charging
        if self.minpower > power + self.actualPower:
            return False

        # limit the power to minpower for all devices
        self.actualPower += power
        for d in self.devices:
            if d.state == DeviceState.ACTIVE or d == device:
                # limit the power to minpower for all devices
                d.maxCharge = max(d.limitCharge, int(self.minpower * (d.startCharge + d.minCharge) / self.actualPower))
                # adjust for solar power, will still deliver the same amount of power
                d.maxCharge = max(d.maxCharge, d.maxSolar - d.actualSolar)
        return True

    def fuseDischarge(self, device: ZendureDevice) -> bool:
        # power needed to start discharging
        power = device.startDischarge + device.minDischarge

        isFirst = len(self.devices) == 1 or not any(d.state == DeviceState.ACTIVE for d in self.devices)
        if isFirst:
            # limit the power to minpower for all devices
            device.maxDischarge = min(device.limitDischarge, self.maxpower)
            self.actualPower = power

            # adjust for solar power, will still deliver the same amount of power
            device.maxDischarge = device.maxDischarge - device.actualSolar
            return True

        # there needs to be at least power to start charging
        if power + self.actualPower > self.maxpower:
            return False

        # limit the power to minpower for all devices
        self.actualPower += power
        for d in self.devices:
            if d.state == DeviceState.ACTIVE or d == device:
                # limit the power to minpower for all devices
                d.maxDischarge = min(d.limitDischarge, int(self.maxpower * (d.startDischarge + d.minDischarge) / self.actualPower))
                # adjust for solar power, will still deliver the same amount of power
                d.maxDischarge = d.maxDischarge - d.actualSolar
        return True

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
                d.maxCharge = max(d.limitCharge, int(maxWatt * d.actualKwh / kWh))
                maxWatt -= d.maxCharge
                kWh -= d.actualKwh
        else:
            maxWatt = min(maxWatt, self.maxpower)
            for d in sorted(active, key=lambda d: d.actualKwh, reverse=True):
                d.maxDischarge = min(d.limitDischarge, int(maxWatt * d.actualKwh / kWh))
                maxWatt -= d.maxDischarge
                kWh -= d.actualKwh

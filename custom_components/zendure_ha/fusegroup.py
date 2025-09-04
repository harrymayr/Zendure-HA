"""Base class for Zendure entities."""

from dataclasses import dataclass

import av


@dataclass
class FuseGroup:
    """Zendure Fuse Group."""

    name: str = ""
    deviceId: str = ""
    maxpower: int = 0
    minpower: int = 0
    powerAvail: int = 0
    powerTotal: int = 0
    kWh: float = 0.0

    def getPower(self, isCharging: bool, deviceMax: int) -> int:
        """Get the maximum power for a device in this fuse group."""
        if self.powerAvail == 0:
            return 0
        pwr = max(self.powerAvail, deviceMax) if isCharging else min(self.powerAvail, deviceMax)
        self.powerAvail -= pwr
        return pwr

    def getMaxPower(self, isCharging: bool, deviceMax: int, availableKwh: float) -> int:
        """Get the maximum power for a device in this fuse group."""
        if self.powerTotal >= self.minpower if isCharging else self.powerTotal <= self.maxpower:
            return deviceMax

        pwr = availableKwh / self.kWh * self.maxpower if isCharging else self.minpower
        return pwr

    def updatePower(self, power: int, powerMax: int, kWh: float) -> None:
        """Update the kWh for this fuse group."""
        self.powerAvail -= power
        self.powerTotal += powerMax
        self.kWh += kWh

"""Base class for Zendure entities."""

from dataclasses import dataclass

from .const import ManagerState
from .device import ZendureDevice


@dataclass
class FuseGroup:
    """Zendure Fuse Group."""

    device: ZendureDevice
    devices: list[ZendureDevice]
    maxpower: int = 0
    minpower: int = 0
    powerAvail: int = 0
    powerAct: int = 0
    capacity: float = 0.0

    def initGroup(self, state: ManagerState) -> int:
        """Get the group capacity."""
        self.capacity = 0.0
        self.powerAvail = 0
        self.powerTotal = 0
        self.powerAct = 0
        self.activeDevices = 0
        self.availableDevices = 0
        # for d in self.devices:
        #     if (capacity := d.power_capacity(state)) > 0:
        #         self.capacity += capacity
        #         d.powerAvail = d.powerMin if state != ManagerState.DISCHARGING else d.powerMax
        #         d.powerAct += d.powerAct
        #         self.powerTotal += d.powerAvail
        #     else:
        #         d.powerAvail = 0

        self.powerAvail = max(self.powerTotal, self.minpower) if state != ManagerState.DISCHARGING else min(self.powerTotal, self.maxpower)
        return self.powerAvail

    def GroupPower(self, power: int, availablePower: int) -> int:
        if self.powerAvail == 0:
            return 0

        remain = availablePower - self.powerAvail
        if abs(remain) > abs(power):
            return 0
        return power - (availablePower - self.powerAvail)

    def devicePower(self, power: int, availablePower: int, device: ZendureDevice) -> int:
        if device.powerAvail == 0 or power == 0:
            return 0

        remain = availablePower - device.powerAvail
        if abs(remain) > abs(power):
            return 0
        return power - (availablePower - device.powerAvail)

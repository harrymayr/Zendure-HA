"""Base class for Zendure entities."""

from dataclasses import dataclass

from .const import ManagerState
from .device import ZendureDevice


@dataclass
class Cluster:
    """Zendure Device Cluster."""

    device: ZendureDevice
    devices: list[ZendureDevice]
    maxpower: int = 0
    minpower: int = 0
    capacity: float = 0.0

    def capacity_get(self, state: ManagerState) -> float:
        """Get the cluster capacity for state."""
        self.capacity = sum(c.power_capacity(state) for c in self.devices)
        return self.capacity

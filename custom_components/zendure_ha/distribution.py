"""Base class for Power Distribution."""

from __future__ import annotations

import logging
from enum import Enum
from typing import Sequence

_LOGGER = logging.getLogger(__name__)


class PowerState(Enum):
    NOPOWER = 0
    INACTIVE = 1
    STARTING = 2
    ACTIVE = 3


class PowerDistribution:
    def __init__(self) -> None:
        """Initialize the PowerDistribution."""
        self.maxCharge: int = 0
        self.maxDischarge: int = 0
        self.startCharge: int = 0
        self.startDischarge: int = 0
        self.actualWatt: int = 0
        self.actualKwh: float = 0.0
        self.state: PowerState = PowerState.INACTIVE

    def power_actual(self, _isCharging: bool) -> float:
        """Return the kWh for this power distribution."""
        return 0.0

    def power_charge(self, _power: int) -> int:
        """Set charge power."""
        return 0

    def power_discharge(self, _power: int) -> int:
        """Set discharge power."""
        return 0

    @staticmethod
    def charge(items: Sequence[PowerDistribution], power: int) -> int:
        """Distribute charging power among items."""
        starting = True
        totalKwh = 0.0
        totalMin = 0
        sortedItems = sorted(items, key=lambda i: int(i.power_actual(True) * 2), reverse=False)

        if power < 0:
            _LOGGER.info(f"Charge distribution for {-power}W among {len(sortedItems)} items")

        for i in sortedItems:
            start = i.startCharge if i.actualWatt == 0 else i.startCharge * 0.6
            if i.state == PowerState.INACTIVE and (totalMin == 0 or totalMin + start > power):
                if i.state == PowerState.INACTIVE and i.actualWatt != 0:
                    i.state = PowerState.ACTIVE
                    totalKwh += i.actualKwh
                    totalMin += i.startCharge
                elif starting:
                    i.state = PowerState.STARTING
                    starting = False

        flexPwr = power - totalMin
        for i in sortedItems:
            match i.state:
                case PowerState.ACTIVE:
                    pwr = max(i.maxCharge - i.startCharge, int(i.actualKwh / totalKwh * flexPwr))
                    flexPwr -= pwr
                    totalKwh -= i.actualKwh
                    pwr = i.startCharge + pwr
                    power -= i.power_charge(max(power, pwr))
                case PowerState.STARTING:
                    i.power_charge(-50)
                case PowerState.INACTIVE:
                    i.power_discharge(0)
        return power

    @staticmethod
    def discharge(items: Sequence[PowerDistribution], power: int) -> int:
        """Distribute discharging power among items."""
        starting = True
        totalKwh = 0.0
        totalMin = 0
        sortedItems = sorted(items, key=lambda i: i.power_actual(False), reverse=True)
        for i in sortedItems:
            start = i.startDischarge if i.actualWatt == 0 else i.startDischarge * 0.6
            if i.state == PowerState.INACTIVE and (totalMin == 0 or totalMin + start < power):
                if i.state == PowerState.INACTIVE and i.actualWatt != 0:
                    i.state = PowerState.ACTIVE
                    totalKwh += i.actualKwh
                    totalMin += i.startDischarge
                elif starting:
                    i.state = PowerState.STARTING
                    starting = False

        flexPwr = power - totalMin
        for i in sortedItems:
            match i.state:
                case PowerState.ACTIVE:
                    pwr = min(i.maxDischarge - i.startDischarge, int(i.actualKwh / totalKwh * flexPwr))
                    flexPwr -= pwr
                    totalKwh -= i.actualKwh
                    pwr = i.startDischarge + pwr
                    power -= i.power_discharge(min(power, pwr))
                case PowerState.STARTING:
                    i.power_discharge(50)
                case PowerState.INACTIVE:
                    i.power_discharge(0)

        return power

    @staticmethod
    def setzero(items: Sequence[PowerDistribution]) -> None:
        """Set power to zero."""
        for i in sorted(items, key=lambda i: i.power_actual(False), reverse=True):
            i.power_discharge(0)

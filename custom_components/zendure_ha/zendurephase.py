"""Zendure Integration device."""

from __future__ import annotations

import logging
from typing import ClassVar

_LOGGER = logging.getLogger(__name__)


class ZendurePhase:
    """A Zendure Phase."""

    phases: list[ZendurePhase]

    options: ClassVar[list[str]] = [
        "800 watt output",
        "1200 watt output, possible circuit overload, use at your own risk!!",
        "2400 watt output, possible circuit overload, use at your own risk!!",
        "3000 watt output, possible circuit overload, use at your own risk!!",
    ]

    def __init__(self, name: str, option: str) -> None:
        """Initialize ZendurePhase."""
        self.name = name
        self.chargemax = 2400
        self.dischargemax = 800
        if option == ZendurePhase.options[1]:
            self.chargemax = 2400
            self.dischargemax = 1200
        elif option == ZendurePhase.options[2]:
            self.chargemax = 3600
            self.dischargemax = 2400
        elif option == ZendurePhase.options[3]:
            self.chargemax = 3600
            self.dischargemax = 3000
        _LOGGER.info(f"Create phase {self.name} with {self.chargemax} watt output and {self.dischargemax} watt input {option}")
        self.max = 0
        self.capacity = 0

    def charge_update(self) -> int:
        """Update charge capacity."""
        self.capacity = 0
        self.max = 0
        self.power = 0
        self.activeDevices = 0
        for d in self.devices:
            d.capacity = max(0, int(d.asInt("packNum") * (d.asInt("socSet") - d.asInt("electricLevel"))))
            d.power = d.asInt("outputPackPower")
            self.power += d.power

            if d.capacity > 0:
                self.capacity += d.capacity
                self.max += d.chargemax
                if d.power > 0:
                    self.activeDevices += 1
            else:
                d.power_off()

        return self.capacity

    def charge(self, totalPower: int, activePhases: int, totalCapacity: int) -> int:
        """Update charge."""
        power = (
            0
            if totalCapacity <= 0
            else totalPower
            if abs(totalPower) < 120 or (activePhases <= 1 and abs(totalPower) < 250)
            else int(totalPower * self.capacity / totalCapacity)
        )

        power = max(0, min(power, self.chargemax))
        if power == 0:
            _LOGGER.info(f"Charging phase: {self.name} off")
            for d in self.devices:
                d.power_off()
            return 0

        _LOGGER.info(f"Charging: {self.name}=>{power} of {totalPower} active:{self.activeDevices} max: {self.chargemax} capacity:{self.capacity}")
        totalPower = 0
        active = 0
        capacity = self.capacity
        for d in sorted(self.devices, key=lambda d: d.capacity, reverse=True):
            pwr = 0 if capacity <= 0 else power if power < 120 or (self.activeDevices <= 1 and power < 250) else int(power * d.capacity / capacity)
            pwr = min(d.chargemax, pwr)
            if pwr > 0:
                d.power_charge(pwr)
                active += 1
            else:
                d.power_off()
            totalPower += pwr
            power -= pwr
            capacity -= d.capacity

        self.activeDevices = active
        _LOGGER.info(f"Charging phase: {self.name} total:{totalPower} {active} active devices")
        return totalPower

    def discharge_update(self) -> int:
        """Update discharge capacity."""
        self.capacity = 0
        self.max = 0
        self.activeDevices = 0
        for d in self.devices:
            d.capacity = max(0, int((d.asInt("packNum") * (d.asInt("electricLevel") - d.asInt("socMin"))) / 2))
            d.power = d.asInt("packInputPower")

            if d.capacity > 0:
                self.capacity += d.capacity
                self.max += d.dischargemax
                if d.power != 0:
                    self.activeDevices += 1
            else:
                d.power_off()
        return self.capacity

    def discharge(self, totalPower: int, activePhases: int, totalCapacity: int) -> int:
        """Update discharge."""
        power = (
            0
            if totalCapacity <= 0
            else totalPower
            if abs(totalPower) < 100 or (activePhases <= 1 and abs(totalPower) < 160)
            else int(totalPower * self.capacity / totalCapacity)
        )

        power = max(0, min(power, self.dischargemax))
        if power == 0:
            _LOGGER.info(f"Charging phase: {self.name} off")
            for d in self.devices:
                d.power_off()
            return 0

        _LOGGER.info(f"Discharging: {self.name} with {power} of total:{totalPower} active:{self.activeDevices} capacity: {self.capacity} total:{totalCapacity}")
        totalPower = 0
        active = 0
        capacity = self.capacity
        for d in sorted(self.devices, key=lambda d: d.capacity, reverse=True):
            pwr = 0 if self.capacity <= 0 else power if power < 100 or (self.activeDevices <= 1 and power < 200) else int(power * d.capacity / capacity)
            pwr = min(d.chargemax, pwr)
            if pwr > 0:
                d.power_discharge(pwr)
                active += 1
            else:
                d.power_off()
            totalPower += pwr
            power -= pwr
            capacity -= d.capacity

        self.activeDevices = active
        _LOGGER.info(f"Discharging phase: {self.name} total:{totalPower} {active} active devices")
        return totalPower

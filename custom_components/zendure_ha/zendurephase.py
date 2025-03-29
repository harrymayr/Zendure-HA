"""Zendure Integration device."""

import logging
from typing import ClassVar

from .zenduredevice import ZendureDevice

_LOGGER = logging.getLogger(__name__)


class ZendurePhase:
    """A Zendure Phase."""

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
        self.activeDevices = 0
        self.devices: list[ZendureDevice] = []

    def charge_update(self) -> int:
        """Update charge capacity."""
        self.capacity = 0
        self.max = 0
        self.power = 0
        self.activeDevices = 0
        for d in self.devices:
            d.capacity = max(0, int((d.asInt("packNum") * (d.asInt("socSet") - d.asInt("electricLevel"))) / 2))
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

    def charge(self, totalPower: int, activePhases: int, totalcapacity: int) -> int:
        """Update charge."""
        power = (
            0
            if totalcapacity <= 0
            else totalPower
            if totalPower < 120 or (activePhases == 1 and totalPower < 250)
            else int(totalPower * self.capacity / totalcapacity)
        )

        power = max(0, min(power, self.chargemax))
        if power == 0:
            _LOGGER.info(f"Charging phase: {self.name} off")
            for d in self.devices:
                d.power_off()
            return 0

        _LOGGER.info(f"Charging phase: {self.name} with {power} watt of total:{totalPower} active:{self.activeDevices}")
        totalPower = 0
        for d in self.devices:
            pwr = 0 if self.capacity <= 0 else power if power < 120 or (self.activeDevices <= 1 and power < 250) else int(power * d.capacity / self.capacity)
            pwr = min(d.chargemax, pwr)
            if pwr > 0:
                d.power_charge(pwr)
            else:
                d.power_off()
            totalPower += pwr
            power -= pwr
            self.capacity -= d.capacity

        _LOGGER.info(f"Charging phase: {self.name} total:{totalPower}")
        return totalPower

    def discharge_update(self) -> int:
        """Update discharge capacity."""
        self.capacity = 0
        self.max = 0
        for d in self.devices:
            d.capacity = max(0, int((d.asInt("packNum") * (d.asInt("electricLevel") - d.asInt("socMin"))) / 2))
            d.power = d.asInt("packInputPower")
            _LOGGER.info(f"Device: {d.name} capacity: {d.capacity} power: {d.power} phase: {self.name}")

            if d.capacity > 0:
                self.capacity += d.capacity
                self.max += d.dischargemax
            else:
                d.power_off()
        return self.capacity

    def discharge(self, totalPower: int, activePhases: int, totalcapacity: int) -> int:
        """Update discharge."""
        power = (
            0
            if totalcapacity <= 0
            else totalPower
            if totalPower < 120 or (activePhases == 1 and totalPower < 250)
            else int(totalPower * self.capacity / totalcapacity)
        )

        power = max(0, min(power, self.dischargemax))
        if power == 0:
            _LOGGER.info(f"Charging phase: {self.name} off")
            for d in self.devices:
                d.power_off()
            return 0

        _LOGGER.info(f"Discharging phase: {self.name} with {power} watt of total:{totalPower} active:{self.activeDevices}")
        totalPower = 0
        for d in self.devices:
            pwr = 0 if self.capacity <= 0 else power if power < 120 or (self.activeDevices <= 1 and power < 250) else int(power * d.capacity / self.capacity)
            pwr = min(d.chargemax, pwr)
            if pwr > 0:
                d.power_discharge(pwr)
            else:
                d.power_off()
            totalPower += pwr
            power -= pwr
            self.capacity -= d.capacity

        _LOGGER.info(f"Discharging phase: {self.name} total:{totalPower}")
        return totalPower

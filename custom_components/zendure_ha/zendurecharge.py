"""Zendure Integration charge data."""

from __future__ import annotations
import logging
from dataclasses import dataclass
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


@dataclass
class ZendureChargeData:
    """Class to hold charging data."""

    max: int = 0
    capacity: int = 0
    avail: bool = False
    lead: ZendureCharge | None = None


class ZendureCharge:
    """Class to hold charging data."""

    def __init__(self) -> None:
        """Initialize ZendurePhase."""
        self.data: list[ZendureChargeData] = [ZendureChargeData(800), ZendureChargeData(800)]
        self.currentpower: int = 0
        self.power: int = 0
        self.avail: bool = False

    def reset(self) -> None:
        self.power = 0
        self.currentpower = 0
        self.data[0].capacity = 0
        self.data[0].avail = False
        self.data[0].lead = None
        self.data[1].capacity = 0
        self.data[1].avail = False
        self.data[1].lead = None

    def distribute(self, name: str, items: list) -> None:
        """Update data information."""
        idx = 0 if self.power < 0 else 1
        power = min(self.power, self.data[idx].max) if idx == 0 else max(self.power, -self.data[idx].max)
        _LOGGER.info(f"distribute: {name} power: {power} over {len(items)} items")
        ready = False
        while not ready:
            ready = True
            lead = self.data[idx].lead
            for p in items:
                if not p.data[idx].avail:
                    _LOGGER.info(f"distribute power => {p.name}: not avaliable")
                    continue
                percent = p.data[idx].capacity / self.data[idx].capacity
                p.power = int(power * percent)
                _LOGGER.info(f"distribute power => {p.name}: {p.power} {p.currentpower} ({percent * 100})")

                if p != lead and ((p.currentpower == 0 and abs(p.power) < 100) or abs(p.power) < 40):
                    self.data[idx].capacity -= p.data[idx].capacity
                    p.power = 0
                    p.data[idx].avail = ready = False

                elif abs(p.power) > p.data[idx].max:
                    _LOGGER.info(f"distribute clip => {p.name}: {p.power}")
                    self.data[idx].capacity -= p.data[idx].capacity
                    p.power = p.data[idx].max * (-1 if idx == 0 else 1)
                    p.data[idx].avail = ready = False
                    power -= p.power

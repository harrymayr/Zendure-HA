"""Zendure Integration device."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Callable

_LOGGER = logging.getLogger(__name__)


class PowerSupply:
    """A Power Supply."""

    def __init__(self, powerclip: bool, onupdate: Callable) -> None:
        """Initialize PowerSupply."""
        self.powerclip = powerclip
        self.actual = 0
        self.percent = 0.0
        self.capacity = 0
        self.last_update = datetime.now()
        self.onupdate = onupdate
        self.children: list[PowerSupply] = []

    def redistribute(self, parent: PowerSupply | None) -> None:
        """Redistribute power to devices."""
        total = 0
        self.powermax = 0
        self.powermin = 0
        for child in self.children:
            child.redistribute(self)
            total += child.capacity
            self.powermax += child.powermax
            self.powermin += child.powermin

        if total == 0:
            for child in self.children:
                child.percent = child.capacity / total

    def update_minmax(self, powermax: int, powermin: int, percent: float) -> None:
        """Initialize min-max of PowerSupply."""
        self.powermax = powermax
        self.powermin = powermin
        self.percent = percent

    def setpoint(self, setpoint: int) -> int:
        """Set the setpoint of the power supply."""
        if self.powerclip:
            if setpoint > 0 and setpoint > self.powermax:
                setpoint = self.powermax
            elif setpoint < 0 and setpoint < self.powermin:
                setpoint = self.powermin

        delta = setpoint - self.actual
        return self._set_actual(delta)

    def delta(self, delta: int) -> int:
        """Set the delta of the power supply."""
        if self.powerclip:
            if self.actual + delta > self.powermax:
                delta = self.powermax - self.actual
            elif self.actual + delta < self.powermin:
                delta = self.powermin - self.actual

        if abs(delta) > 2 or self.last_update < datetime.now():
            return self._set_actual(delta)
        return 0

    def _set_actual(self, delta: int) -> int:
        self.onupdate(delta)
        self.actual += delta
        self.last_update = datetime.now() + timedelta(seconds=8)
        return delta

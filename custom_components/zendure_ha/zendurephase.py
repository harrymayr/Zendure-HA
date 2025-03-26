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
        self.power = 0
        self.currentpower = 0
        self.chargemax = 1200
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
        self.devices: list[ZendureDevice] = []
        self.capacity = 0
        self.max = 0
        self.power = 0
        self.lead: ZendureDevice

    def addDevice(self, device: ZendureDevice) -> None:
        """Add a device to the phase."""
        _LOGGER.info(f"Adding device {device.name} to phase {self.name}")
        self.devices.append(device)

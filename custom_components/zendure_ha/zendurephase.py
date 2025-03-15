"""Zendure Integration device."""

import logging
from typing import ClassVar

from .zendurecharge import ZendureCharge
from .zenduredevice import ZendureDevice

_LOGGER = logging.getLogger(__name__)


class ZendurePhase(ZendureCharge):
    """A Zendure Phase."""

    options: ClassVar[list[str]] = [
        "800 watt output",
        "1200 watt output, possible circuit overload, use at your own risk!!",
        "2400 watt output, possible circuit overload, use at your own risk!!",
    ]

    def __init__(self, name: str, option: str) -> None:
        """Initialize ZendurePhase."""
        super().__init__()
        self.name = name
        self.power = 0
        self.currentpower = 0
        self.data[0].max = 1200
        self.data[1].max = 800
        if option == ZendurePhase.options[1]:
            self.data[0].max = 2400
            self.data[1].max = 1200
        elif option == ZendurePhase.options[2]:
            self.data[0].max = 2400
            self.data[1].max = 2400
        _LOGGER.info(f"Create phase {self.name} with {self.data[0].max} watt output and {self.data[1].max} watt input {option}")
        self.devices: list[ZendureDevice] = []

    def addDevice(self, device: ZendureDevice) -> None:
        """Add a device to the phase."""
        _LOGGER.info(f"Adding device {device.name} to phase {self.name}")
        self.devices.append(device)

    def updateCharge(self, total: ZendureCharge) -> None:
        """Update charge information."""
        self.currentpower = 0
        self.reset()

        for d in self.devices:
            d.power = 0
            d.currentpower = d.asInt("packInputPower") - d.asInt("outputPackPower")
            d.data[0].capacity = int(d.asInt("packNum") * max(0, (d.asFloat("socSet") - d.asInt("electricLevel"))))
            d.data[1].capacity = int(d.asInt("packNum") * max(0, (d.asInt("electricLevel") - d.asFloat("socMin"))))
            self.currentpower += d.currentpower

            for i in range(2):
                self.data[i].capacity += d.data[i].capacity
                d.data[i].avail = d.data[i].capacity > 0
                if d.data[i].avail and (self.data[i].lead is None or self.data[i].lead.data[i].capacity < d.data[i].capacity):
                    self.data[i].lead = d

            _LOGGER.info(f"Update dev: {d.name}: charge max {self.data[0].max} discharge max: {self.data[1].max}")

        total.currentpower += self.currentpower
        for i in range(2):
            total.data[i].capacity += self.data[i].capacity
            self.data[i].avail = self.data[i].capacity > 0
            if self.data[i].avail and (total.data[i].lead is None or total.data[i].lead.data[i].capacity < self.data[i].capacity):
                total.data[i].lead = self

        _LOGGER.info(f"Update phase: {self.name}: charge lead {self.data[0].lead} discharge: {self.data[1].lead}")
        _LOGGER.info(f"Update phase: {self.name}: charge {self.data[0].capacity} discharge: {self.data[1].capacity}")

        _LOGGER.info(f"Update phase: total: charge lead {total.data[0].lead} discharge: {total.data[1].lead}")
        _LOGGER.info(f"Update phase: total: charge {total.data[0].capacity} discharge: {total.data[1].capacity}")

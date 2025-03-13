"""Zendure Integration device."""

import logging
from .const import DOMAIN
from .zendurecharge import ZendureCharge
from .zenduredevice import ZendureDevice

_LOGGER = logging.getLogger(__name__)


class ZendurePhase(ZendureCharge):
    """A Zendure Phase."""

    def __init__(self, name: str) -> None:
        """Initialize ZendurePhase."""
        super().__init__()
        self.name = name
        self.power = 0
        self.currentpower = 0
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
            d.currentpower = d.asInt("packInputPower") - d.asInt("outputPackPower")
            d.data[0].capacity = int(d.asInt("packNum") * max(0, (d.asFloat("socSet") - d.asInt("electricLevel"))))
            d.data[1].capacity = int(d.asInt("packNum") * max(0, (d.asInt("electricLevel") - d.asFloat("socMin"))))
            d.power = 0
            self.currentpower += d.currentpower

            for i in range(2):
                self.data[i].capacity += d.data[i].capacity
                d.data[i].avail = d.data[i].capacity > 0
                if d.data[i].avail and (not self.data[i].lead or self.data[i].lead.data[i].capacity < d.data[i].capacity):
                    self.data[i].lead = d
                    _LOGGER.info(f"Upd hyper lead: {d.name}")

            _LOGGER.info(f"Upd device: {d.name}: {d.data[0].capacity} ({d.data[1].capacity})")

        total.currentpower += self.currentpower
        for i in range(2):
            total.data[i].capacity += self.data[i].capacity
            self.data[i].avail = self.data[i].capacity > 0
            if self.data[i].avail and (not total.data[i].lead or total.data[i].lead.data[i].capacity < self.data[i].capacity):
                total.data[i].lead = self
                _LOGGER.info(f"Upd phase lead: {self.name}")

        _LOGGER.info(f"Upd phase: {self.name}: charge {self.data[0].capacity} discharge: {self.data[1].capacity}")

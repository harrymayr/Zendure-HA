"""Zendure Integration device."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant

from .devicebase import DeviceBase

_LOGGER = logging.getLogger(__name__)


class ZendureBattery(DeviceBase):
    """A Zendure Battery."""

    def __init__(self, hass: HomeAssistant, name: str, model: str, snNumber: str) -> None:
        """Initialize ZendureBattery."""
        super().__init__(hass, name, model, snNumber)

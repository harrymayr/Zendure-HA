"""Module for the Hub1200 device integration in Home Assistant."""

import logging
from typing import Any

from homeassistant.core import HomeAssistant

from custom_components.zendure_ha.device import ZendureBattery, ZendureLegacy

_LOGGER = logging.getLogger(__name__)


class Hub1200(ZendureLegacy):
    def __init__(self, hass: HomeAssistant, deviceId: str, prodName: str, definition: Any) -> None:
        """Initialise Hub1200."""
        super().__init__(hass, deviceId, prodName, definition["productModel"], definition)
        """Can control the ACE 1500 with max 900W AC inputPower"""
        self.setLimits(-900, 1200)
        self.maxSolar = -800

    def entityUpdate(self, key, value):
        changed = super().entityUpdate(key, value)

        if changed:
            match key:
                case "outputPackPower" | "solarInputPower":
                    self.homeInput.update_value(max(0, self.batteryInput.asInt - self.solarInput.asInt))

    def batteryUpdate(self, batteries: list[ZendureBattery]) -> None:
        # Check if any battery has kWh > 1
        if any(battery.kWh > 1 for battery in batteries):
            self.powerMin = -1200
            self.limitInput.update_range(0, abs(self.powerMin))

    async def charge(self, power: int) -> int:
        _LOGGER.info("AC Power charge %s not available => set power from %s to 0", self.name, power)
        # The HUB family does not have AC charging possibility (even with ACE 1500), so set it to idle

        self.mqttInvoke(
            {
                "arguments": [{"autoModelProgram": 0, "autoModelValue": 0, "msgType": 1, "autoModel": 0}],
                "function": "deviceAutomation",
            }
        )
        return 0

    async def discharge(self, power: int) -> int:
        _LOGGER.info("Power discharge %s => %s", self.name, power)
        self.mqttInvoke(
            {
                "arguments": [{"autoModelProgram": 2, "autoModelValue": power, "msgType": 1, "autoModel": 8}],
                "function": "deviceAutomation",
            }
        )
        return power

    async def power_off(self) -> None:
        """Set the power off."""
        self.mqttInvoke(
            {
                "arguments": [{"autoModelProgram": 0, "autoModelValue": 0, "msgType": 1, "autoModel": 0}],
                "function": "deviceAutomation",
            }
        )

"""Interfaces with the Zendure Integration switch."""

import logging
from collections.abc import Callable
from typing import Any

from homeassistant.components.switch import (SwitchEntity,
                                             SwitchEntityDescription)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.template import Template
from stringcase import snakecase

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(_hass: HomeAssistant, _config_entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up the Zendure switch."""
    ZendureSwitch.addSwitches = async_add_entities


class ZendureSwitch(SwitchEntity):
    addSwitches: AddEntitiesCallback

    def __init__(
        self,
        deviceinfo: DeviceInfo,
        uniqueid: str,
        onwrite: Callable,
        template: Template | None = None,
        deviceclass: Any | None = None,
    ) -> None:
        """Initialize a switch entity."""
        self._attr_has_entity_name = True
        self._attr_should_poll = False
        self.entity_description = SwitchEntityDescription(key=uniqueid, name=uniqueid, device_class=deviceclass)
        self._attr_device_info = deviceinfo
        self._attr_unique_id = f"{deviceinfo.get('name', None)}-{uniqueid}"
        self.entity_id = f"switch.{deviceinfo.get('name', None)}-{snakecase(uniqueid)}"
        self._attr_translation_key = snakecase(uniqueid)

        self._attr_available = True
        self._value_template: Template | None = template
        self._onwrite = onwrite

    def update_value(self, value: Any) -> None:
        try:
            is_on = bool(
                int(self._value_template.async_render_with_possible_json_value(value, None)) != 0 if self._value_template is not None else int(value) != 0
            )

            if self._attr_is_on == is_on:
                return

            _LOGGER.info(f"Update switch: {self._attr_unique_id} => {is_on}")

            self._attr_is_on = is_on
            if self.hass and self.hass.loop.is_running():
                self.schedule_update_ha_state()
        except Exception as err:
            _LOGGER.error(f"Error {err} setting state: {self._attr_unique_id} => {value}")

    async def async_turn_on(self, **_kwargs: Any) -> None:
        """Turn switch on."""
        self._onwrite(self, 1)

    async def async_turn_off(self, **_kwargs: Any) -> None:
        """Turn switch off."""
        self._onwrite(self, 0)

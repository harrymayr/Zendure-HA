"""Interfaces with the Zendure Integration."""

import logging
from collections.abc import Callable
from hmac import new
from typing import Any

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from stringcase import snakecase

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(_hass: HomeAssistant, _config_entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up the Zendure select."""
    ZendureSelect.addSelects = async_add_entities


class ZendureSelect(SelectEntity):
    """Representation of a Zendure select entity."""

    addSelects: AddEntitiesCallback

    def __init__(self, deviceinfo: DeviceInfo, uniqueid: str, options: dict[int, str], onchanged: Callable | None, current: int | None = None) -> None:
        """Initialize a select entity."""
        self._attr_has_entity_name = True
        self.entity_description = SelectEntityDescription(key=uniqueid, name=uniqueid)
        self._attr_unique_id = f"{deviceinfo.get('name', None)}-{uniqueid}"
        self.entity_id = f"select.{deviceinfo.get('name', None)}-{snakecase(uniqueid)}"
        self._attr_translation_key = snakecase(uniqueid)

        self._attr_device_info = deviceinfo
        self._attr_should_poll = False
        self._attr_options = list(options.values())
        self._options = options
        if current:
            self._attr_current_option = options[current]
        else:
            self._attr_current_option = self._attr_options[0]
        self._onchanged = onchanged

    def update_value(self, value: Any) -> None:
        try:
            new_value = int(value)
            if new_value not in self._options:
                return
            new_value = self._options[new_value]
            if new_value != self._attr_current_option:
                self._attr_current_option = new_value
                if self.hass:
                    _LOGGER.info(f"Update sensor state: {self._attr_unique_id} => {new_value}")
                    self.schedule_update_ha_state()

        except Exception as err:
            _LOGGER.error(f"Error {err} setting state: {self._attr_unique_id} => {value}")

    async def async_select_option(self, option: str) -> None:
        """Update the current selected option."""
        for key, value in self._options.items():
            if value == option:
                self._attr_current_option = option
                self.async_write_ha_state()
                self._onchanged(key)
                break

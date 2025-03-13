"""Interfaces with the Zendure Integration api sensors."""

from typing import Callable
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.components.select import SelectEntity


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    ZendureSelect.addSelects = async_add_entities


class ZendureSelect(SelectEntity):
    """Representation of a Zendure select entity."""

    addSelects: AddEntitiesCallback

    def __init__(
        self,
        deviceinfo: DeviceInfo,
        uniqueid: str,
        name: str,
        onchanged: Callable,
        options: list[str],
    ) -> None:
        """Initialize a ZendureManager select entity."""
        self.name = name
        self._attr_device_info = deviceinfo
        self._attr_unique_id = uniqueid
        self._attr_name = name
        self._attr_should_poll = False
        self._attr_options = options
        self._attr_current_option = options[0]
        self._attr_translation_key = uniqueid
        self._onchanged = onchanged

    async def async_select_option(self, option: str) -> None:
        """Update the current selected option."""
        self._attr_current_option = option
        self.async_write_ha_state()
        self._onchanged(self._attr_options.index(option))

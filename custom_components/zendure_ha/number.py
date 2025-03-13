"""Interfaces with the Zendure Integration number."""

import logging
from typing import Any, Callable
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.template import Template

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    ZendureNumber.addNumbers = async_add_entities


class ZendureNumber(NumberEntity):
    addNumbers: AddEntitiesCallback

    def __init__(
        self,
        deviceinfo: DeviceInfo,
        uniqueid: str,
        name: str,
        onwrite: Callable,
        template: Template | None = None,
        uom: str | None = None,
        deviceclass: str | None = None,
        maximum: int = 2000,
        minimum: int = 0,
        mode: NumberMode = NumberMode.AUTO,
    ) -> None:
        """Initialize a switch entity."""
        self._attr_available = True
        self._attr_device_info = deviceinfo
        self._attr_name = name
        self._attr_unique_id = uniqueid
        self._attr_should_poll = False
        self._attr_native_unit_of_measurement = uom
        self._value_template: Template | None = template
        self._attr_device_class = deviceclass
        self._onwrite = onwrite
        self._attr_native_max_value = maximum
        self._attr_native_min_value = minimum
        self._attr_mode = mode

    def update_value(self, value: Any) -> None:
        try:
            new_value = int(
                float(self._value_template.async_render_with_possible_json_value(value, None)) if self._value_template is not None else float(value)
            )

            if self._attr_native_value == new_value:
                return

            _LOGGER.info(f"Update number: {self._attr_name} => {new_value}")

            self._attr_native_value = new_value
            self.schedule_update_ha_state()
        except Exception as err:
            _LOGGER.exception(f"Error {err} setting state: {self._attr_unique_id} => {value}")

    async def async_set_native_value(self, value: float) -> None:
        """Set the value."""
        self._onwrite(self, value)

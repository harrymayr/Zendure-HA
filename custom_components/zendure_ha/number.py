"""Interfaces with the Zendure Integration number."""

import logging
from collections.abc import Callable
from typing import Any

from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.template import Template
from stringcase import snakecase

from .device import Device

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(_hass: HomeAssistant, _config_entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Set up the Zendure number."""
    ZendureNumber.add = async_add_entities


class ZendureNumber(NumberEntity):
    add: AddEntitiesCallback

    def __init__(
        self,
        device: Device,
        uniqueid: str,
        onwrite: Callable,
        template: Template | None = None,
        uom: str | None = None,
        deviceclass: Any | None = None,
        maximum: int = 2000,
        minimum: int = 0,
        mode: NumberMode = NumberMode.AUTO,
        factor: int = 1,
    ) -> None:
        """Initialize a number entity."""
        self._attr_has_entity_name = True
        self._attr_should_poll = False
        self._attr_available = True
        self.entity_description = NumberEntityDescription(
            key=uniqueid,
            name=uniqueid,
            native_unit_of_measurement=uom,
            device_class=deviceclass,
        )
        self._attr_device_info = device.attr_device_info
        self._attr_unique_id = f"{self._attr_device_info.get('name', None)}-{uniqueid}"
        self.entity_id = f"number.{self._attr_device_info.get('name', None)}-{snakecase(uniqueid)}"
        self._attr_translation_key = snakecase(uniqueid)

        self._value_template: Template | None = template
        self._onwrite = onwrite
        self._attr_native_max_value = maximum
        self._attr_native_min_value = minimum
        self._attr_mode = mode
        self.factor = factor
        device.entities[uniqueid] = self
        # Ensure add is called on the main thread/event loop
        if self.hass and self.hass.loop.is_running():
            self.hass.loop.call_soon_threadsafe(self.add, [self])
        else:
            device.call_threadsafe(self.add, [self])

    def update_value(self, value: Any) -> None:
        try:
            new_value = (
                int(float(self._value_template.async_render_with_possible_json_value(value, None)) if self._value_template is not None else float(value))
                / self.factor
            )

            if self._attr_native_value == new_value:
                return

            _LOGGER.info(f"Update number: {self._attr_unique_id} => {new_value}")

            self._attr_native_value = new_value
            if self.hass and self.hass.loop.is_running():
                self.schedule_update_ha_state()
        except Exception as err:
            _LOGGER.error(f"Error {err} setting state: {self._attr_unique_id} => {value}")

    async def async_set_native_value(self, value: float) -> None:
        """Set the value."""
        self._onwrite(self, int(self.factor * value))
        self._attr_native_value = value
        if self.hass and self.hass.loop.is_running():
            self.schedule_update_ha_state()

    def update_range(self, minimum: int, maximum: int) -> None:
        self._attr_native_min_value = minimum
        self._attr_native_max_value = maximum
        if self.hass and self.hass.loop.is_running():
            self.schedule_update_ha_state()


class ZendureRestoreNumber(ZendureNumber, RestoreEntity):
    """Representation of a Zendure number entity with restore."""

    def __init__(
        self,
        device: Device,
        uniqueid: str,
        onwrite: Callable,
        template: Template | None = None,
        uom: str | None = None,
        deviceclass: Any | None = None,
        maximum: int = 2000,
        minimum: int = 0,
        mode: NumberMode = NumberMode.AUTO,
    ) -> None:
        """Initialize a number entity."""
        super().__init__(device, uniqueid, onwrite, template, uom, deviceclass, maximum, minimum, mode)
        self._attr_native_value = 0

    async def async_added_to_hass(self) -> None:
        """Handle entity which will be added."""
        await super().async_added_to_hass()
        if state := await self.async_get_last_state():
            if state.state is None or state.state == "unknown":
                self._attr_native_value = 0
                return
            self._attr_native_value = int(float(state.state))
            self._onwrite(self, self._attr_native_value)

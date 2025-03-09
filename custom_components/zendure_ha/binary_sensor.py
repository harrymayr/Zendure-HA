"""Interfaces with the Zendure Integration binairy sensors."""

import logging
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.template import Template

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    ZendureBinarySensor.addBinarySensors = async_add_entities


class ZendureBinarySensor(BinarySensorEntity):
    addBinarySensors: AddEntitiesCallback

    def __init__(
        self,
        deviceinfo: DeviceInfo,
        uniqueid: str,
        name: str,
        template: Template | None = None,
        uom: str = None,
        deviceclass: str = None,
    ) -> None:
        """Initialize a Hyper2000 entity."""
        self._attr_available = True
        self._attr_device_info = deviceinfo
        self._attr_name = name
        self._attr_unique_id = uniqueid
        self._attr_should_poll = False
        self._attr_native_unit_of_measurement = uom
        self._value_template: Template | None = template
        self._attr_device_class = deviceclass

    def update_value(self, value):
        try:
            is_on = bool(
                int(self._value_template.async_render_with_possible_json_value(value, None)) != 0
                if self._value_template is not None
                else int(value) != 0
            )

            if self._attr_is_on == is_on:
                return

            _LOGGER.info(f"Update binairy_sensor: {self._attr_unique_id} => {is_on}")

            self._attr_is_on = is_on
            self.schedule_update_ha_state()
        except Exception as err:
            _LOGGER.error(f"Error {err} setting state: {self._attr_unique_id} => {value}")
